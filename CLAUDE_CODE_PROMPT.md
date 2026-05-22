# Prompt for Claude Code

Copy the text below into your first Claude Code message, and attach
`SPECIFICATION.md` to the same message (or place it at the repo root so the
agent reads it). Do not modify the spec; if you find issues during
implementation, surface them as questions rather than silently deviating.

---

You are implementing a project described in `SPECIFICATION.md`, attached as
context. That document is the single source of truth: every endpoint,
schema, state name, constant, and Slovak UI label is normative. Treat any
ambiguity as a question for me, not a free choice.

Work in strict **test-driven development** mode:

1. **Read the entire spec first.** Do not start writing code until you can
   restate, in your own words, the data model, the state machine, and the
   contracts for all 5 Claude calls. Ask me about anything unclear.

2. **Scaffold the repository.** Create the directory structure suggested in
   § 3 of the spec. Initialize `pyproject.toml` for the backend and
   `package.json` for the frontend. Add `.env.example` files. Add
   `.gitignore` entries for `output/`, `data/`, `.env`, `node_modules/`,
   `dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
   Set up linting and type-checking per § 11.5 of the spec: configure Ruff
   in `backend/pyproject.toml`; create `frontend/eslint.config.js` (flat
   config) and `frontend/tsconfig.json` per the spec's strictness rules;
   add `lint` and `type-check` scripts to `frontend/package.json`.

3. **Write the tests first.** Before any implementation code exists,
   implement the test suites described in § 11 — backend unit tests,
   backend integration tests, and frontend unit tests. Use the exact
   schemas, state names, event types, and Slovak labels from the spec.
   Mock Anthropic and RunPod at the HTTP layer (respx for Python, MSW or
   simple fetch stubs for the frontend). Mock `EventSource` in frontend
   tests.

4. **Confirm the tests fail.** Run both test suites and verify they fail
   (because there is no implementation yet). Report this state to me
   briefly before continuing.

5. **Implement the code.** Build out the backend and frontend to make the
   tests pass. Implement in small vertical slices when possible (e.g., DB
   models + repository + one endpoint + its test). Do not change tests to
   match the code; if a test seems wrong, ask me.

6. **All checks must pass.** Run the following commands in order. Every
   one of them must exit with zero failures and zero errors before you
   declare the work complete:

   Backend (in `backend/`):
   ```bash
   pytest
   ruff check .
   ruff format --check .
   ```

   Frontend (in `frontend/`):
   ```bash
   vitest run
   npm run lint
   npm run type-check
   ```

   Do not silence lint rules to make output clean — if a rule fights the
   spec or genuinely makes no sense in context, ask before disabling it.
   Do not skip `ruff format --check`; if it complains, run `ruff format .`
   and re-run the check. Same for `eslint --fix` on the frontend.

7. **Smoke run.** With dummy values in `.env` (so external calls would
   fail), start the backend (`uvicorn`) and frontend (`npm run dev`). Both
   should start without errors and the frontend should render the Home
   screen. Report this confirmation to me.

8. **Hand off.** Provide:
   - A short README at the repo root explaining how to install, configure,
     and run both services.
   - A summary of what was implemented, what tests cover, and any
     deviations from the spec (with justification).
   - The exact commands to run tests, start the backend, and start the
     frontend.

## Hard rules

- **Source of truth.** If the spec says state X is called `RENDERING`,
  it is `RENDERING` everywhere — DB enum, Python enum, TypeScript type,
  SSE payload field. No synonyms, no abbreviations.
- **Slovak only in user-visible UI text.** Code identifiers, log messages,
  exception messages, and code comments are in English. UI labels are
  exactly as specified in § 6 and § 9 of the spec.
- **No secrets in frontend.** `ANTHROPIC_API_KEY` and `RUNPOD_API_KEY` must
  never be referenced in any file under `frontend/`.
- **No real network calls in tests.** Anthropic and RunPod are mocked at
  the HTTP layer in every test.
- **Zero lint, format, and type-check errors before delivery.** All six
  commands in step 6 must exit cleanly. The lint setup is intentionally
  lightweight (see § 11.5 of the spec); do not relax it further to make
  output clean.
- **Async correctness.** All I/O in the backend is async. The orchestrator
  uses `asyncio.gather` (or equivalent) with a semaphore of
  `MAX_CONCURRENT_BRANCHES` to run branches in parallel. Cancellation is
  cooperative: each branch checks the cancellation flag at every state
  transition and at every ComfyUI poll cycle.
- **Strict Claude output parsing.** Every Claude response is parsed into a
  Pydantic model. On parse failure, retry up to `CLAUDE_JSON_RETRY` times
  with an additional system message instructing strict JSON; only then
  fail the call.
- **No invented features.** Do not add functionality that is not in the
  spec (e.g., do not add login, history listing UI, retry-single-illustration
  button). Anything in § 12 is explicitly out of scope.
- **Reasonable defaults for the unspecified.** Where the spec is silent on
  small choices (HTTP status code for a niche error, exact CSS values,
  shape of internal helpers), pick something reasonable and move on. Do
  not block on these.

## Anti-patterns to avoid

- Writing implementation before tests.
- Adding pseudocode comments instead of real tests.
- Skipping tests because a piece "looks too simple to test".
- Tweaking spec values (limits, model name, state names) to "make it nicer".
- Using a UI component library or styling framework.
- Inventing a Claude tool-use loop where the spec uses 5 distinct, single-turn calls.
- Holding any image data in memory beyond what is needed; persist to disk
  and reference by path.
- Logging secret values.

## Communication

- If you find a contradiction or ambiguity in the spec, stop and ask.
- If a test you wrote disagrees with the code you wrote, fix the side that
  is wrong; if you cannot tell which, ask.
- Surface, do not hide: if you had to make a non-obvious decision, mention
  it in the final summary.

When you are ready to begin, start by restating the spec in your own words
(data model, state machine, Claude contracts, SSE events) so we both
confirm we have the same understanding. Then proceed to step 2.
