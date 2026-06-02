"""Image storage abstraction (§ 8.7).

Two backends live behind a single ``ImageStore`` Protocol so the orchestrator,
the manual flow, the salvage promotion, and the API serializers all speak the
same language regardless of where the bytes physically live:

- ``LocalImageStore`` writes under ``settings.output_dir`` and returns
  root-relative ``/static/...`` URLs that the existing ``StaticFiles`` mount
  serves directly.
- ``R2ImageStore`` writes to Cloudflare R2 via its S3-compatible API and
  returns absolute URLs anchored at ``settings.r2_public_base``.

The DB columns (``illustrations.image_path``,
``illustration_attempt_history.image_path``,
``manual_illustration_sessions.last_manual_image_path``) only ever store a
*logical key* (e.g. ``runs/<run_id>/scene_0.png``); the backend prefixes /
URL-anchors that key at write time. Rows stay portable across backends; a
backend switch without a parallel byte-copy is a one-way break.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

import aioboto3
import aiofiles
from botocore.exceptions import ClientError

from app.config import Settings

logger = logging.getLogger(__name__)


# ── Errors ────────────────────────────────────────────────────────────────


class ConfigurationError(RuntimeError):
    """Raised at startup when the configured image-store backend can't be
    constructed from the supplied ``Settings``. Mirrors the fail-fast
    posture of the agent-prompt loader: refuse to boot rather than 5xx at
    first render."""


# ── Protocol ──────────────────────────────────────────────────────────────


class ImageStore(Protocol):
    """The minimal surface every backend must implement. Logical keys are
    always forward-slash separated and never carry a backend prefix.
    """

    async def save(self, key: str, png: bytes) -> str:
        """Persist ``png`` under ``key`` (overwriting any existing object)
        and return ``key`` unchanged so callers can drop it straight onto
        an ``image_path`` column."""
        ...

    async def copy(self, src_key: str, dst_key: str) -> str:
        """Copy bytes already stored under ``src_key`` to ``dst_key``.
        Returns ``dst_key``. Raises if the source does not exist."""
        ...

    async def exists(self, key: str) -> bool:
        """Return True if ``key`` currently resolves to stored bytes."""
        ...

    async def delete_prefix(self, key_prefix: str) -> None:
        """Best-effort cleanup of every object under ``key_prefix``.
        Failures MUST be logged and swallowed (never re-raised) — image
        cleanup is not allowed to surface as a 5xx to the user."""
        ...

    def url_for(self, key: str) -> str:
        """Build the public URL the frontend should fetch ``key`` from."""
        ...


# ── Local filesystem backend ──────────────────────────────────────────────


class LocalImageStore:
    """Writes under ``output_dir`` and serves via the FastAPI ``/static``
    mount. Identical to the pre-abstraction behaviour, just wrapped in the
    ``ImageStore`` shape."""

    def __init__(self, output_dir: str) -> None:
        self._output_dir = output_dir

    def _full(self, key: str) -> str:
        # ``os.path.join`` would silently drop ``self._output_dir`` if a
        # caller passed an absolute key. Keys are by contract relative;
        # assert it loudly so the bug surfaces in tests, not in prod.
        if key.startswith("/"):
            raise ValueError(f"image-store keys must be relative, got {key!r}")
        return os.path.join(self._output_dir, key)

    async def save(self, key: str, png: bytes) -> str:
        full = self._full(key)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        async with aiofiles.open(full, "wb") as f:
            await f.write(png)
        return key

    async def copy(self, src_key: str, dst_key: str) -> str:
        src_full = self._full(src_key)
        dst_full = self._full(dst_key)
        os.makedirs(os.path.dirname(dst_full), exist_ok=True)
        async with aiofiles.open(src_full, "rb") as src:
            data = await src.read()
        async with aiofiles.open(dst_full, "wb") as dst:
            await dst.write(data)
        return dst_key

    async def exists(self, key: str) -> bool:
        return os.path.exists(self._full(key))

    async def delete_prefix(self, key_prefix: str) -> None:
        if key_prefix.startswith("/"):
            raise ValueError(f"image-store key prefixes must be relative, got {key_prefix!r}")
        root = os.path.join(self._output_dir, key_prefix)
        if not os.path.isdir(root):
            return
        # os.walk is sync, but the trees we sweep are tiny (a handful of
        # PNGs per run). Wrap nothing; the cost is negligible.
        for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    os.remove(path)
                except OSError as e:  # pragma: no cover - logged + swallowed
                    logger.warning("delete_prefix: failed to remove %s: %s", path, e)
            try:
                os.rmdir(dirpath)
            except OSError as e:  # pragma: no cover - logged + swallowed
                logger.warning("delete_prefix: failed to rmdir %s: %s", dirpath, e)

    def url_for(self, key: str) -> str:
        # Match the legacy "/static/runs/<id>/scene_N.png" shape exactly.
        return f"/static/{key}"


# ── Cloudflare R2 backend ─────────────────────────────────────────────────


class R2ImageStore:
    """Cloudflare R2 implementation. Uses ``aioboto3`` against the bucket's
    S3-compatible endpoint. All keys are prefixed with ``self._prefix`` at
    the wire boundary so dev/prod can share a single bucket without
    colliding."""

    # PNGs are immutable once written under their canonical key — retries
    # overwrite the same key intentionally — so we tell intermediaries to
    # cache aggressively.
    _CACHE_CONTROL = "public, max-age=31536000, immutable"
    _CONTENT_TYPE = "image/png"

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base: str,
        prefix: str,
    ) -> None:
        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket
        # Normalise both ends so url_for never produces "//" or trailing "/".
        self._public_base = public_base.rstrip("/")
        self._prefix = prefix.strip("/")
        self._endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        # One Session per process is fine — clients are short-lived
        # context managers; the Session just holds credential metadata.
        self._session = aioboto3.Session()

    def _full_key(self, key: str) -> str:
        if key.startswith("/"):
            raise ValueError(f"image-store keys must be relative, got {key!r}")
        return f"{self._prefix}/{key}" if self._prefix else key

    def _client(self):
        # R2 ignores ``region_name`` but boto3 requires one to be set.
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name="auto",
        )

    async def save(self, key: str, png: bytes) -> str:
        full = self._full_key(key)
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=full,
                Body=png,
                ContentType=self._CONTENT_TYPE,
                CacheControl=self._CACHE_CONTROL,
            )
        return key

    async def copy(self, src_key: str, dst_key: str) -> str:
        async with self._client() as s3:
            await s3.copy_object(
                Bucket=self._bucket,
                Key=self._full_key(dst_key),
                CopySource={"Bucket": self._bucket, "Key": self._full_key(src_key)},
                MetadataDirective="COPY",
            )
        return dst_key

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=self._full_key(key))
                return True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                # 404 / NoSuchKey / NotFound depending on the API path —
                # treat them all as "absent" and let any other error
                # propagate.
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise

    async def delete_prefix(self, key_prefix: str) -> None:
        if key_prefix.startswith("/"):
            raise ValueError(f"image-store key prefixes must be relative, got {key_prefix!r}")
        full_prefix = self._full_key(key_prefix).rstrip("/") + "/"
        try:
            async with self._client() as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                    contents = page.get("Contents") or []
                    if not contents:
                        continue
                    objects = [{"Key": obj["Key"]} for obj in contents]
                    # delete_objects is bounded to 1000 keys per call;
                    # the paginator already chunks below that, so passing
                    # the page as-is is safe.
                    resp = await s3.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                    for err in resp.get("Errors") or []:
                        logger.warning(
                            "delete_prefix: R2 reported error for %s: %s",
                            err.get("Key"),
                            err.get("Message"),
                        )
        except Exception as e:  # noqa: BLE001 - best-effort sweep
            logger.warning(
                "delete_prefix: best-effort R2 sweep of %r failed: %s",
                full_prefix,
                e,
            )

    def url_for(self, key: str) -> str:
        return f"{self._public_base}/{self._full_key(key)}"


# ── Factory ───────────────────────────────────────────────────────────────


_R2_REQUIRED_FIELDS = (
    "r2_account_id",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket",
    "r2_public_base",
)


def get_image_store(settings: Settings) -> ImageStore:
    """Construct the configured backend. Validates the R2 credential block
    eagerly so a misconfigured deploy fails on startup, not at the first
    render."""
    backend = settings.image_store_backend
    if backend == "local":
        return LocalImageStore(output_dir=settings.output_dir)
    if backend == "r2":
        missing = [name for name in _R2_REQUIRED_FIELDS if not getattr(settings, name, "")]
        if missing:
            raise ConfigurationError(
                "IMAGE_STORE_BACKEND=r2 requires "
                + ", ".join(name.upper() for name in missing)
                + " to be set."
            )
        return R2ImageStore(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
            public_base=settings.r2_public_base,
            prefix=settings.r2_prefix,
        )
    raise ConfigurationError(f"Unknown IMAGE_STORE_BACKEND={backend!r}; expected 'local' or 'r2'.")
