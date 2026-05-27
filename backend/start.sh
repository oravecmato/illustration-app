#!/bin/bash
set -e

echo "📦 Running database migrations..."
.venv/bin/alembic upgrade head

echo "🚀 Starting uvicorn server..."
.venv/bin/uvicorn app.main:app --reload
