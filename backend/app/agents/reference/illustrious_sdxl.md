# Illustrious XL / SDXL anime renderer — prompt engineering reference

This document is the **shared, stable domain knowledge** prepended to the
system prompt of the prompt-engineering agents (Agents 1, 3, 7). It is
intentionally conservative: only facts that hold across the Illustrious
XL family and standard Danbooru-tagged SDXL anime checkpoints are
recorded here. Per-illustration empirical lessons live elsewhere
(`prompting_notes` on the illustration row, curated by Agent 3 / Agent
6). Do not duplicate or contradict that empirical memo here — when the
memo and this doc disagree on a specific scene, the memo wins.

## Tag dialect

- Prompts are **Danbooru-style comma-separated tags**, not natural
  language sentences. The CLIP text encoder tokenises the input
  into the BPE vocabulary; multi-word tags should match Danbooru's
  canonical spelling (`looking at viewer`, not `looking_at_viewer` or
  `looking towards the viewer`).
- The positive prompt has roughly **75 useful tokens** (one CLIP
  chunk). Illustrious models pack additional chunks but the early
  tokens dominate. Put the central subject and most important
  expression/action tags FIRST.
- Order matters: **subject → expression → action → outfit → setting →
  style** is the canonical ordering. The renderer pays more attention
  to earlier tags.

## Attention-weight syntax

- `(tag:1.x)` raises a tag's weight; `(tag:0.y)` lowers it. Typical
  operating range is `1.1`–`1.4`. Weights above `1.5` distort.
- Use weights **strategically**, not as decoration. Raising one
  semantically central tag (the entity, the expression, the action)
  beats reweighting many tags at once — over-weighting many tags
  cancels them out.
- Escape Danbooru disambiguation parens: `bow \(weapon\)` to
  distinguish from `bow tie`. The backslash is required so the
  parens are not parsed as weight wrappers.

## Negative prompts

- The CLIP text encoder has **no native negation**. Natural-language
  negations (`no cats`, `without flowers`, `not blurry`) are parsed
  as positive references to the noun and can INCREASE its presence.
  Always use the bare Danbooru tag for the unwanted concept in the
  negative prompt.
- Negative prompt token budget is also ~75. Roughly **30–45 tags is
  the sweet spot**. Beyond ~60 tags, additions start cancelling each
  other out and the negative becomes diluted.
- Dedupe — listing the same anti-X concept three different ways
  (`cat, feline, kitten`) is fine for coverage of related concepts,
  but listing the literal same tag twice is wasted budget.

## Count tags and the `1other` rule

- The `1girl` / `1boy` / `1other` / `2girls` / `6+girls` family are
  Danbooru COUNT tags. They count visible humanoids, not species.
- `1other` is the count tag for a humanoid of **unknown / non-binary**
  gender (a non-human character that is still humanoid: a
  shapeshifter, a featureless mannequin, an ambiguous figure). It is
  NOT a generic "any creature" count tag.
- For animals, robots, plants, and other non-humanoid entities,
  there is **no per-species count tag** — `1cat`, `1dog`,
  `1stag`, `1robot` are real Danbooru tags but their effect is
  unreliable on Illustrious checkpoints. The species noun (`cat`,
  `dog`, `stag`, `robot`) carried as a regular positive tag plus
  description tags is the reliable encoding.
- When a scene has no human at all: use `no humans` (do NOT use
  `solo`, which is a human-count tag and is meaningless without a
  human). Pair with `animal focus` (for fauna), `object focus` (for
  objects), or `scenery` (for landscapes) so the renderer knows
  what the frame's subject is.

## Anti-anatomy negatives for non-human entities

The style LoRA biases toward humans; non-human characters frequently
render anthropomorphised unless explicitly suppressed.

- Mammals (cat, dog, fox, wolf, rabbit, deer, stag): `anthro, furry,
  humanoid, standing on two legs, wearing clothes`.
- Birds / owls / raptors: `anthro, humanoid, hands, wearing clothes`.
- Reptiles / dragons: `anthro, humanoid, wearing clothes, dragon
  girl, dragon boy`.
- Robots / mechanical: `humanoid robot, android, human face, wearing
  clothes`.
- Plants / objects: usually no anti-anatomy needed; objects don't
  suffer from anthropomorphism.

## Disambiguation

Some Danbooru tags collide with everyday meanings — disambiguate
explicitly:

- `bow (weapon)` (escaped: `bow \(weapon\)`) vs `bow tie` vs
  `ribbon bow`. For an archer's bow, write `bow \(weapon\), longbow,
  drawn bowstring, arrow`.
- `crown` (royal) vs `crown` (tooth) — pair with `royal regalia` or
  `princess` to disambiguate.
- `glasses` (eyewear) vs `glass` (material). Use `eyewear` or
  `eyeglasses` for clarity.

## Style-LoRA caveat (MHA single-character LoRAs)

- The MHA character LoRAs are trained on humans. When a non-human
  entity is in the same frame, the LoRA's human bias bleeds into
  the entity unless anti-anatomy negatives are strong.
- The MHA style LoRA biases towards school-uniform outfits. Custom
  outfits need explicit tagging (`casual clothes, modern fashion`)
  in positive AND `school uniform` in negative.
