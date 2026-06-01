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

### Scope: what belongs in the negative

The negative prompt is strictly for things that must be **absent** from
the rendered image. Two common abuses cancel themselves out and bloat
the negative budget:

1. **Composition/pose/framing/style control of a subject that IS in
   the image.** Tags like `bear in foreground`, `large bear`, `rearing
   bear`, `bear close-up`, `realistic bear` read as positive
   references to `bear` — they reinforce the noun while failing to
   move the composition. Composition, pose, distance, framing, and
   style of an in-frame subject belong in the POSITIVE prompt.
2. **Anti-anatomy tags with the species prepended.** Use the bare
   anti-anatomy vocabulary (`anthro, furry, humanoid, standing on two
   legs, wearing clothes`). Never write `anthro bear` or `humanoid
   cat` — the species token anchors and strengthens the unwanted
   concept. The bare tags are species-agnostic and effective.

The only legitimate references to an in-frame entity's species token
inside the negative prompt are:

- **Duplicate-count suppressors** (`2cats, multiple cats` when one cat
  is intended); and
- **Contradictory-colour or contradictory-attribute suppressors**
  (`white cat` in negative when the intended cat is black; `short
  tail` in negative when the intended fox has a long bushy tail).

If you cannot express your intent under these rules, revise the
positive prompt — do not invent a creative negative.

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
- **`muzzle`** is a hard homonym: it means BOTH "an animal's snout"
  AND "a strap/cage restraint worn over the snout (a dog/fox muzzle
  device)". On Illustrious the device sense wins frequently enough
  that the tag is unsafe for describing animal anatomy. Never use
  `muzzle` to describe an animal's face. For the snout, use
  `snout`, `vulpine face`, `canine face`, `small black nose`,
  `pointed snout`, or species-specific descriptors. If the
  restraint device must be excluded explicitly, add `muzzle
  (object), restraint, leash, harness, collar` to the negative.

## Quadruped animal anatomy

Illustrious / SDXL anime checkpoints render quadrupeds passably but
have known weak spots:

- **Tails**: the most common anatomy failure for foxes, wolves,
  cats, and dogs is a malformed or double tail (extra tail
  attached at the wrong angle, tail merged into the back, missing
  tail). Always include a descriptive tail tag in the positive
  (`bushy fox tail, single tail, long tail curled around body`)
  and ALWAYS include `extra tail, two tails, multiple tails,
  malformed tail` in the negative for any tailed quadruped.
- **Paws**: similar to hand anatomy on humans. Add `paws` (or
  `four paws`) positively, and `extra paws, malformed paws,
  deformed paws, six toes` negatively.
- **Species fidelity for under-trained species**: the base
  Illustrious checkpoint has strong cat/dog/bird knowledge and
  noticeably weaker fox/wolf/stag knowledge. Foxes in particular
  drift toward cats (similar silhouette, much more training data).
  Stack species-specific tags: `red fox cub, vulpine, kit, orange
  fur, white belly, black socks, pointed ears, fluffy fox tail`,
  and put `cat, kitten, feline, tabby` in the negative.

## Style-LoRA caveat (MHA single-character LoRAs)

- The MHA character LoRAs are trained on humans. When a non-human
  entity is in the same frame, the LoRA's human bias bleeds into
  the entity unless anti-anatomy negatives are strong.
- The MHA style LoRA biases towards school-uniform outfits. Custom
  outfits need explicit tagging (`casual clothes, modern fashion`)
  in positive AND `school uniform` in negative.
