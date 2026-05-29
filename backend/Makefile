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

SRC := app tests

.PHONY: help test test-unit test-integration lint fmt fmt-check check migrate revision

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
