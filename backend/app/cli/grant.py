"""Operator CLI for managing demo access keys (§ 8.11.5).

Subcommands:

    grant       --runs N [--label STR]   Issue a new key with N-run quota.
    grant-admin            [--label STR] Issue an admin key (unlimited).
    revoke      --key STR                Revoke an existing key.
    list                                  List every key with usage stats.

The CLI is invoked via Makefile shims in ``backend/Makefile`` (see
``make grant runs=...``, ``make grant-admin``, ``make revoke key=...``,
``make list-keys``) so the working directory and venv are pinned and
the allow-list stays small.

Generated keys are URL-safe (``secrets.token_urlsafe(24)``) which yields
~32 characters of base64 — long enough to resist enumeration without
becoming awkward to share via DM.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.config import get_settings
from app.db.migrations import upgrade_to_head_async
from app.db.models import AccessKey
from app.db.session import get_session_factory, init_db


def _generate_key() -> str:
    # 24 bytes → 32 base64 chars. Cryptographically secure.
    return secrets.token_urlsafe(24)


async def _ensure_db_ready() -> None:
    settings = get_settings()
    await upgrade_to_head_async(settings.database_url)
    init_db(settings.database_url)


async def _grant(*, runs_allowed: int | None, label: str) -> str:
    """Insert a fresh key row and return the generated key string."""
    await _ensure_db_ready()
    factory = get_session_factory()
    key = _generate_key()
    async with factory() as session:
        session.add(
            AccessKey(
                key=key,
                label=label,
                runs_allowed=runs_allowed,
                runs_used=0,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return key


async def _revoke(*, key: str) -> bool:
    """Mark a key as revoked. Returns True if a row was touched."""
    await _ensure_db_ready()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            update(AccessKey)
            .where(AccessKey.key == key, AccessKey.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
        return result.rowcount > 0


async def _list() -> list[AccessKey]:
    await _ensure_db_ready()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(AccessKey).order_by(AccessKey.created_at.desc()))
        return list(result.scalars().all())


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"


def _print_grant(key: str, runs_allowed: int | None, label: str) -> None:
    quota = "∞ (admin)" if runs_allowed is None else f"{runs_allowed} run(s)"
    print(f"Issued access key for {label!r}: quota = {quota}")
    print()
    print(f"  KEY:    {key}")
    print()
    print("Share via invite link:")
    print(f"  https://anime-illustrator.pages.dev/?invite={key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Anime Illustrator demo access keys.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grant", help="Issue a new key with a finite run quota.")
    g.add_argument("--runs", type=int, required=True, help="Run quota (positive integer).")
    g.add_argument("--label", default="demo", help="Human-readable label for `list`.")

    ga = sub.add_parser("grant-admin", help="Issue an unlimited admin key.")
    ga.add_argument("--label", default="admin", help="Human-readable label for `list`.")

    r = sub.add_parser("revoke", help="Revoke an existing key.")
    r.add_argument("--key", required=True, help="The full key string to revoke.")

    sub.add_parser("list", help="List every issued key.")

    args = parser.parse_args(argv)

    if args.cmd == "grant":
        if args.runs <= 0:
            print("error: --runs must be a positive integer", file=sys.stderr)
            return 2
        key = asyncio.run(_grant(runs_allowed=args.runs, label=args.label))
        _print_grant(key, args.runs, args.label)
        return 0

    if args.cmd == "grant-admin":
        key = asyncio.run(_grant(runs_allowed=None, label=args.label))
        _print_grant(key, None, args.label)
        return 0

    if args.cmd == "revoke":
        ok = asyncio.run(_revoke(key=args.key))
        if not ok:
            print(f"error: key not found or already revoked: {args.key!r}", file=sys.stderr)
            return 1
        print(f"Revoked: {args.key}")
        return 0

    if args.cmd == "list":
        rows = asyncio.run(_list())
        if not rows:
            print("(no access keys)")
            return 0
        # Compact tabular dump; small N means we don't need a real
        # tabulator dependency.
        print(
            f"{'KEY':<36}  {'LABEL':<24}  {'USED':>10}  {'CREATED':<16}  {'LAST USED':<16}  STATUS"
        )
        for row in rows:
            quota = "∞" if row.runs_allowed is None else str(row.runs_allowed)
            used = f"{row.runs_used}/{quota}"
            status = "REVOKED" if row.revoked_at is not None else "active"
            print(
                f"{row.key:<36}  {row.label[:24]:<24}  {used:>10}  "
                f"{_fmt_dt(row.created_at):<16}  {_fmt_dt(row.last_used_at):<16}  {status}"
            )
        return 0

    return 2  # pragma: no cover - argparse covers


if __name__ == "__main__":
    sys.exit(main())
