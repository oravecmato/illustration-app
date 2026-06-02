"""Unit tests for the image-store abstraction (§ 8.7).

Covers LocalImageStore behaviour end-to-end against ``tmp_path`` and the
``get_image_store`` factory's dispatch + fail-fast validation. R2 backend
network paths are out of scope for unit tests; their construction is
exercised by the factory tests below.
"""

import pytest

from app.config import Settings
from app.services.storage import (
    ConfigurationError,
    LocalImageStore,
    R2ImageStore,
    get_image_store,
)

# ── LocalImageStore ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_save_creates_file_and_returns_key(tmp_path):
    store = LocalImageStore(str(tmp_path))
    key = "runs/abc/scene_0.png"
    returned = await store.save(key, b"PNG")
    assert returned == key
    assert (tmp_path / "runs" / "abc" / "scene_0.png").read_bytes() == b"PNG"


@pytest.mark.asyncio
async def test_local_save_overwrites(tmp_path):
    store = LocalImageStore(str(tmp_path))
    key = "runs/abc/scene_0.png"
    await store.save(key, b"first")
    await store.save(key, b"second")
    assert (tmp_path / "runs" / "abc" / "scene_0.png").read_bytes() == b"second"


@pytest.mark.asyncio
async def test_local_copy(tmp_path):
    store = LocalImageStore(str(tmp_path))
    await store.save("runs/abc/manual_0_1.png", b"PNG")
    returned = await store.copy("runs/abc/manual_0_1.png", "runs/abc/scene_0.png")
    assert returned == "runs/abc/scene_0.png"
    assert (tmp_path / "runs" / "abc" / "scene_0.png").read_bytes() == b"PNG"


@pytest.mark.asyncio
async def test_local_exists(tmp_path):
    store = LocalImageStore(str(tmp_path))
    assert await store.exists("runs/abc/scene_0.png") is False
    await store.save("runs/abc/scene_0.png", b"PNG")
    assert await store.exists("runs/abc/scene_0.png") is True


def test_local_url_for(tmp_path):
    store = LocalImageStore(str(tmp_path))
    assert store.url_for("runs/abc/scene_0.png") == "/static/runs/abc/scene_0.png"


@pytest.mark.asyncio
async def test_local_delete_prefix_removes_run_tree(tmp_path):
    store = LocalImageStore(str(tmp_path))
    await store.save("runs/abc/scene_0.png", b"a")
    await store.save("runs/abc/history/x_0_0.png", b"b")
    await store.save("runs/other/scene_0.png", b"c")
    await store.delete_prefix("runs/abc")
    assert not (tmp_path / "runs" / "abc").exists()
    # Sibling run untouched.
    assert (tmp_path / "runs" / "other" / "scene_0.png").exists()


@pytest.mark.asyncio
async def test_local_delete_prefix_missing_dir_is_noop(tmp_path):
    store = LocalImageStore(str(tmp_path))
    # No raise.
    await store.delete_prefix("runs/never-existed")


@pytest.mark.asyncio
async def test_local_rejects_absolute_keys(tmp_path):
    store = LocalImageStore(str(tmp_path))
    with pytest.raises(ValueError):
        await store.save("/runs/abc/scene_0.png", b"PNG")
    with pytest.raises(ValueError):
        await store.delete_prefix("/runs/abc")


# ── Factory ───────────────────────────────────────────────────────────────


def _settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="x",
        runpod_api_key="x",
        runpod_endpoint_id="x",
    )
    base.update(overrides)
    # Settings reads env by default; bypass by setting via constructor only.
    # We don't pass an env_file, so any missing required field will fall
    # back to env vars, which is fine in test runs that have them set.
    return Settings(**base)


def test_factory_local(tmp_path):
    settings = _settings(image_store_backend="local", output_dir=str(tmp_path))
    store = get_image_store(settings)
    assert isinstance(store, LocalImageStore)


def test_factory_r2_constructs_when_all_fields_set():
    settings = _settings(
        image_store_backend="r2",
        r2_account_id="acct",
        r2_access_key_id="ak",
        r2_secret_access_key="sk",
        r2_bucket="bucket",
        r2_public_base="https://pub.r2.dev",
        r2_prefix="dev",
    )
    store = get_image_store(settings)
    assert isinstance(store, R2ImageStore)
    assert store.url_for("runs/abc/scene_0.png") == ("https://pub.r2.dev/dev/runs/abc/scene_0.png")


@pytest.mark.parametrize(
    "missing_field",
    [
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_bucket",
        "r2_public_base",
    ],
)
def test_factory_r2_fails_fast_on_missing_field(missing_field):
    fields = dict(
        r2_account_id="acct",
        r2_access_key_id="ak",
        r2_secret_access_key="sk",
        r2_bucket="bucket",
        r2_public_base="https://pub.r2.dev",
    )
    fields[missing_field] = ""
    settings = _settings(image_store_backend="r2", **fields)
    with pytest.raises(ConfigurationError) as exc:
        get_image_store(settings)
    assert missing_field.upper() in str(exc.value)


def test_factory_unknown_backend_raises():
    # Bypass the Literal validator by mutating the settings instance after
    # construction; the factory must still reject the unknown value.
    settings = _settings(image_store_backend="local")
    object.__setattr__(settings, "image_store_backend", "ftp")
    with pytest.raises(ConfigurationError):
        get_image_store(settings)


# ── R2ImageStore key handling (no network) ────────────────────────────────


def test_r2_prefix_normalisation():
    store = R2ImageStore(
        account_id="acct",
        access_key_id="ak",
        secret_access_key="sk",
        bucket="bucket",
        public_base="https://pub.r2.dev/",  # trailing slash
        prefix="/dev/",  # leading + trailing
    )
    # url_for should not produce "//" anywhere.
    url = store.url_for("runs/abc/scene_0.png")
    assert url == "https://pub.r2.dev/dev/runs/abc/scene_0.png"
    assert "//" not in url.replace("https://", "")


def test_r2_default_jurisdiction_endpoint():
    store = R2ImageStore(
        account_id="acct",
        access_key_id="ak",
        secret_access_key="sk",
        bucket="bucket",
        public_base="https://pub.r2.dev",
        prefix="dev",
    )
    assert store._endpoint == "https://acct.r2.cloudflarestorage.com"


def test_r2_eu_jurisdiction_endpoint():
    store = R2ImageStore(
        account_id="acct",
        access_key_id="ak",
        secret_access_key="sk",
        bucket="bucket",
        public_base="https://pub.r2.dev",
        prefix="dev",
        jurisdiction="eu",
    )
    assert store._endpoint == "https://acct.eu.r2.cloudflarestorage.com"


def test_r2_rejects_absolute_keys():
    store = R2ImageStore(
        account_id="acct",
        access_key_id="ak",
        secret_access_key="sk",
        bucket="bucket",
        public_base="https://pub.r2.dev",
        prefix="dev",
    )
    with pytest.raises(ValueError):
        store._full_key("/runs/abc/scene_0.png")
