# Backend dev tasks. Always invoke from this directory:
#   cd backend && make <target>
#
# These targets are the canonical entry points; Claude Code is
# instructed (via auto-memory) to use `make <target>` instead of
# raw `.venv/bin/...` invocations so the project's allowlist stays
# small and reviewable.

PY := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
ALEMBIC := .venv/bin/alembic
UVICORN := .venv/bin/uvicorn

SRC := app tests

UVICORN_PID := /tmp/claude/uvicorn.pid
UVICORN_LOG := /tmp/claude/uvicorn.log
UVICORN_APP := app.main:app

.PHONY: help test test-unit test-integration lint fmt fmt-check check migrate revision serve-bg restart-bg stop-bg

help:
	@echo "Backend targets:"
	@echo "  make test              - run full pytest suite (-q)"
	@echo "  make test-unit         - run unit tests only"
	@echo "  make test-integration  - run integration tests only"
	@echo "  make lint              - ruff check"
	@echo "  make fmt               - ruff format (writes changes)"
	@echo "  make fmt-check         - ruff format --check (no writes)"
	@echo "  make check             - lint + fmt-check + test"
	@echo "  make migrate           - alembic upgrade head"
	@echo "  make revision msg=\"...\" - alembic autogenerate revision"
	@echo "  make serve-bg          - start uvicorn in background (migrates first; logs $(UVICORN_LOG))"
	@echo "  make restart-bg        - stop running uvicorn (if any) and start fresh in background"
	@echo "  make stop-bg           - stop background uvicorn"

test:
	$(PYTEST) -q

test-unit:
	$(PYTEST) tests/unit -q

test-integration:
	$(PYTEST) tests/integration -q

lint:
	$(RUFF) check $(SRC)

fmt:
	$(RUFF) format $(SRC)

fmt-check:
	$(RUFF) format --check $(SRC)

check: lint fmt-check test

migrate:
	$(ALEMBIC) upgrade head

revision:
	@if [ -z "$(msg)" ]; then \
		echo "usage: make revision msg=\"short description\""; \
		exit 1; \
	fi
	$(ALEMBIC) revision --autogenerate -m "$(msg)"

serve-bg:
	@mkdir -p /tmp/claude
	@if [ -f $(UVICORN_PID) ] && kill -0 $$(cat $(UVICORN_PID)) 2>/dev/null; then \
		echo "uvicorn already running (PID $$(cat $(UVICORN_PID))). Use 'make restart-bg'."; \
		exit 1; \
	fi
	@if pgrep -f "$(UVICORN) $(UVICORN_APP)" >/dev/null 2>&1; then \
		echo "uvicorn process matching '$(UVICORN_APP)' already running (stale PID file?). Use 'make restart-bg'."; \
		exit 1; \
	fi
	@echo "Running migrations..."
	@$(ALEMBIC) upgrade head
	@echo "Starting uvicorn in background..."
	@nohup $(UVICORN) $(UVICORN_APP) --reload > $(UVICORN_LOG) 2>&1 & echo $$! > $(UVICORN_PID)
	@sleep 2
	@if kill -0 $$(cat $(UVICORN_PID)) 2>/dev/null; then \
		echo "uvicorn started (PID $$(cat $(UVICORN_PID))). Logs: $(UVICORN_LOG)"; \
	else \
		echo "uvicorn failed to start. Tail of $(UVICORN_LOG):"; \
		tail -n 40 $(UVICORN_LOG); \
		rm -f $(UVICORN_PID); \
		exit 1; \
	fi

stop-bg:
	@if [ -f $(UVICORN_PID) ] && kill -0 $$(cat $(UVICORN_PID)) 2>/dev/null; then \
		kill $$(cat $(UVICORN_PID)); \
		echo "Sent TERM to PID $$(cat $(UVICORN_PID))"; \
	fi
	@-pkill -f "$(UVICORN) $(UVICORN_APP)" 2>/dev/null || true
	@sleep 1
	@rm -f $(UVICORN_PID)
	@echo "uvicorn stopped."

restart-bg: stop-bg serve-bg
