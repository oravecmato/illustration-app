"""Guard test for the access-key gate (§ 8.11.6).

Every entry in :data:`app.constants.PAID_ENDPOINTS` MUST mount
:func:`app.api.auth.require_access_key` somewhere in its dependant
graph. If a new paid endpoint is added without the guard — or an
existing one regresses — this test fails at unit-test time so it
never reaches a deployable branch.

The check walks the FastAPI ``Dependant`` tree directly rather than
calling the route, which keeps the test cheap and avoids needing a
seeded DB.
"""

from __future__ import annotations

from fastapi.dependencies.models import Dependant

from app.api.auth import require_access_key
from app.constants import PAID_ENDPOINTS
from app.main import create_app


def _has_dep(dependant: Dependant, target) -> bool:
    """Recursively check whether ``target`` appears anywhere in the
    Dependant tree rooted at ``dependant``."""
    if dependant.call is target:
        return True
    for sub in dependant.dependencies:
        if _has_dep(sub, target):
            return True
    return False


def test_every_paid_endpoint_requires_access_key():
    app = create_app()

    # Build a fast lookup keyed by (method, path) → APIRoute.
    routes: dict[tuple[str, str], object] = {}
    for route in app.routes:
        # FastAPI APIRoute exposes .methods and .path.
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if not path:
            continue
        for m in methods:
            routes[(m, path)] = route

    missing: list[str] = []
    for method, path in PAID_ENDPOINTS:
        route = routes.get((method, path))
        if route is None:
            missing.append(f"{method} {path} (route not registered)")
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None or not _has_dep(dependant, require_access_key):
            missing.append(f"{method} {path} (require_access_key not wired)")

    assert not missing, "Paid endpoints missing access-key guard:\n  " + "\n  ".join(missing)
