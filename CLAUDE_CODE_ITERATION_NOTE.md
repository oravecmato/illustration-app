# Iteration Note for Claude Code

The specification has been updated. Re-read `CLAUDE_CODE_PROMPT.md` — it
remains the source of truth for how to proceed. Then re-read the full
`SPECIFICATION.md`. Below is a quick orientation on what changed in this
iteration so you know where to focus.

## What changed

**Project rebranding.** The app is no longer "Fairy Tale Illustrator" — it
is now "Anime Illustrator". Visual output is anime/manga style, rendered
via Illustrious XL + MHA-style LoRAs. Project root folder is
`anime-illustrator/`. Slovak UI labels updated accordingly (Screen A and
Screen B in § 9.1).

**New § 7.3 — Creative Brief.** This is the largest addition and is
normative for all five Claude agents. Eight subsections cover:

- Visual stack: Illustrious base, Danbooru-style tag prompting (not
  sentences), MHA-style character + style LoRAs.
- Hard character vocabulary mapping: `male` → Izuku Midoriya, `female` →
  Kyoka Jiro, `mother` → Inko Midoriya. This is the single source of
  truth for prompt construction in Agents 1 and 3.
- MVP single-character scene constraint (Agent 0 selects only scenes
  featuring exactly one of the three roles, acting alone).
- Mandatory specificity: every selected scene must have a concrete
  expression, gesture, or action — generic poses are unacceptable.
- Agent 2 evaluation checklist (seven concrete criteria).
- Negative prompt baseline (safety + anatomy + composition + quality
  defaults injected by Agents 1 and 3).
- `backend/app/character_config.json` — operator-filled file containing
  LoRA filenames and trigger tags per role. Loader must refuse to start
  on missing/malformed config.
- Style guide responsibilities (what Agent 0 produces globally vs. what
  Agents 1 and 3 produce per-illustration).

**Typed run-level errors.** The `runs` table now has an `error_code`
column alongside `error_message`. See § 8 → "Orchestrator failure
handling" for the three defined codes: `NO_SUITABLE_SCENES`,
`STEP0_FAILED`, `INTERNAL_ERROR`. The `run_failed` SSE event payload now
carries the code.

**Agent 0 (`analyze_story`) returning empty `illustrations: []` is
valid** — it signals "no suitable scenes" and the orchestrator treats it
as a typed terminal failure with `error_code = NO_SUITABLE_SCENES`. Do
not raise; do not invent scenes. See § 7.1 Call 0 and § 7.3.3.

**New `character_role` field.** Both the `illustrations` table and Call
0's output schema now include `character_role: "male" | "female" |
"mother"`. This drives which LoRA is loaded per illustration via
`character_config.json` at workflow substitution time. The
`CHARACTER_LORA` placeholder mapping changed accordingly (§ 7.3.7
overrides the original mapping in § 7.2).

**Frontend additions.**

- New "Run-level error banner" element on Screen B (§ 9.1, item #3).
- New § 9.4 maps each `error_code` to its Slovak UX message. The
  mapping lives in a dedicated TS module (`src/i18n/runErrors.ts`) and
  is unit-tested.
- New `RunErrorBanner` component (see § 11.3 for test cases).

**Tests.** § 11 has new cases covering: `character_config` loader (incl.
refusal to start on bad config), `character_role` schema validation, the
NO_SUITABLE_SCENES end-to-end integration flow, the `RunErrorBanner`
component, and the `runErrors.ts` i18n mapping. The existing tests stay.

**Acceptance criteria.** § 13 has a new criterion #7 for the
NO_SUITABLE_SCENES path.

## What to do now

If you have already started implementation, audit your work against the
updated spec — pay particular attention to the schema changes (new
columns, new fields in Call 0 output, new SSE payload), to the existence
of `character_config.json` as a startup dependency, and to the Slovak
labels that have changed.

If you have not yet started, proceed as per the original prompt: restate
the spec in your own words (now including the Creative Brief and the
typed error handling), then scaffold, tests-first, implement, run all
six check commands clean, smoke run, hand off.
