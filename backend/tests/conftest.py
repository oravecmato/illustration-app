"""Set dummy environment variables before any app modules are imported."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("RUNPOD_API_KEY", "test-runpod-key")
os.environ.setdefault("RUNPOD_ENDPOINT_ID", "test-endpoint-123")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test.db")
os.environ.setdefault("OUTPUT_DIR", "/tmp/test-output")
os.environ.setdefault("WORKFLOW_PATH", "./app/workflows/default.json")
os.environ.setdefault("ALLOWED_ORIGIN", "http://localhost:5173")
