# syntax=docker/dockerfile:1.7
#
# Production backend image for Anime Illustrator.
#
# Build context MUST be `backend/`:
#   docker build -t anime-illustrator-backend backend/
#
# Runtime expects /data to be a writable volume:
#   - SQLite DB at $DATABASE_URL (default: sqlite+aiosqlite:////data/app.db)
#   - Generated images at $OUTPUT_DIR (default: /data/output)
# On Fly.io, mount the named volume `data` at /data via fly.toml [mounts].
#
# Migrations run inside FastAPI lifespan (app/main.py), so CMD is just uvicorn.

ARG PYTHON_VERSION=3.11

# ── builder ───────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Copy only what `pip install .` needs to resolve the package metadata + source.
# setuptools.packages.find in pyproject.toml is scoped to `app*`.
COPY pyproject.toml ./
COPY app ./app

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATABASE_URL=sqlite+aiosqlite:////data/app.db \
    OUTPUT_DIR=/data/output

# Apply OS-level security patches at build time. python:3.11-slim is rebuilt
# infrequently, so without this Trivy flags HIGH/CRITICAL CVEs that already
# have a fix in Debian's security archive but haven't landed in the base.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user with home at /app.
RUN groupadd --system app \
 && useradd  --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Bring in the prepared virtualenv from builder stage.
COPY --from=builder /opt/venv /opt/venv

# Application source + Alembic migration scripts.
COPY app          ./app
COPY alembic.ini  ./alembic.ini
COPY alembic      ./alembic

# /data is the Fly volume mount point (SQLite + generated images).
# Created here so the image is also runnable without a mounted volume.
RUN mkdir -p /data \
 && chown -R app:app /app /data

USER app

EXPOSE 8000

# Liveness probe consumed by Fly's services.http_checks.
# Uses stdlib urllib so we don't need curl/wget in the runtime image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys;\
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)" \
  || exit 1

# --proxy-headers / --forwarded-allow-ips=* so client IPs and scheme come
# through Fly's proxy correctly. Single worker — the orchestrator keeps state
# in-process and isn't safe to fan out across workers.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", \
     "--workers", "1"]
