# Fairy Tale Illustrator

A locally-hosted web application that takes a children's fairy tale text as input,
identifies suitable scenes to illustrate, and produces up to 5 visually consistent
illustrations using Claude (Anthropic API) for reasoning and a RunPod Serverless
ComfyUI endpoint for image rendering.

---

## Requirements

- **Python 3.11+** (installed via `brew install python@3.11`)
- **Node.js 18+** and **npm**

---

## Installation

### Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install ruff
```

Copy the env example and fill in your API keys:

```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY, RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env  # already filled with http://localhost:8000
```

---

## Configuration

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `RUNPOD_API_KEY` | Your RunPod API key |
| `RUNPOD_ENDPOINT_ID` | Your RunPod Serverless endpoint ID |
| `DATABASE_URL` | SQLite URL (default: `sqlite+aiosqlite:///./data/app.db`) |
| `OUTPUT_DIR` | Directory for generated images (default: `./output`) |
| `WORKFLOW_PATH` | Path to ComfyUI workflow JSON (default: `./app/workflows/default.json`) |
| `ALLOWED_ORIGIN` | Frontend origin for CORS (default: `http://localhost:5173`) |

### Frontend (`frontend/.env`)

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE` | Backend base URL (default: `http://localhost:8000`) |

---

## Running

### Backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm run dev
```

Then open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Running Tests

### Backend

```bash
cd backend
source .venv/bin/activate
pytest
ruff check .
ruff format --check .
```

### Frontend

```bash
cd frontend
vitest run
npm run lint
npm run type-check
```

---

## Architecture

### Backend (`backend/app/`)

- **`main.py`** — FastAPI app, CORS, lifespan startup
- **`config.py`** — Settings via pydantic-settings (reads `.env`)
- **`constants.py`** — Numeric limits and model name
- **`db/`** — SQLAlchemy ORM models, async session factory, repository CRUD
- **`schemas/`** — Pydantic models for API and Claude I/O
- **`services/`** — Claude client (5 distinct calls), RunPod client, workflow placeholder replacement, image file I/O
- **`orchestrator/`** — Pipeline (top-level), Branch (per-illustration state machine), EventBus (SSE pub/sub)
- **`api/`** — FastAPI router: `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events` (SSE), `POST /api/runs/{id}/cancel`

### Frontend (`frontend/src/`)

- **`types/`** — Shared TypeScript types mirroring backend schemas
- **`services/api.ts`** — fetch wrappers and SSE EventSource
- **`stores/run.ts`** — Pinia store: run state, illustrations, SSE event handling
- **`views/HomeView.vue`** — Story input form
- **`views/RunView.vue`** — Live progress with illustration grid
- **`components/`** — `IllustrationCard`, `ProgressCounter`, `CancelButton`

### State machine (per illustration)

```
PENDING → GENERATING_PROMPTS → RENDERING → EVALUATING
  ↓ (verdict=concept)           ↓ (verdict=prompt)
RETHINKING_CONCEPT       REVISING_PROMPTS → RENDERING ...
  ↓
GENERATING_PROMPTS
  ↓ (max 3 concepts × 3 prompts = 9 jobs max)
COMPLETED | FAILED | CANCELLED
```

---

## What is tested

- **Unit tests (backend):** Workflow placeholder replacement, all 5 Claude response schemas (valid + invalid), branch state machine (happy path, prompt revision, concept restart, concept rejection, exhaustion, cancellation), pipeline orchestration (3/5/8 illustrations, mixed outcomes, step 0 failure), SSE event bus, RunPod client (success, polling, timeout, failure statuses)
- **Integration tests (backend):** End-to-end happy path with HTTP-mocked Anthropic and RunPod; input validation (empty/too-long story); 404 for unknown runs; 409 cancel of non-running run
- **Unit tests (frontend):** `IllustrationCard` — all 9 state Slovak labels, spinner visibility, attempt counters, image rendering, error display; `ProgressCounter` — count display, unknown count; `CancelButton` — visibility by status, inline confirmation flow; `runStore` — snapshot, state update, completion, cancellation, error tolerance

## Deviations from spec

- The spec says `POST /api/runs/{run_id}/cancel` may return 409 if the run is already in a terminal state. In MVP, RunPod jobs already dispatched are allowed to finish (not cancelled mid-flight); subsequent branches check the cancel flag cooperatively.
- The `_update_snapshot` helper in `pipeline.py` calls `event_bus.set_snapshot()` which is synchronous (no await needed); in unit tests using `AsyncMock` for event_bus this generates a harmless `RuntimeWarning` about an un-awaited coroutine.
