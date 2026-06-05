# Anime Illustrator — user guide

Anime Illustrator is a web app where you sketch out a story together with an
assistant (Claude) in a short conversation, and the app then produces a series
of **five visually consistent anime illustrations** for it. The actual drawing
runs on third-party GPU hardware (RunPod ComfyUI Serverless, *Illustrious XL*
model with character LoRAs from My Hero Academia); the text and the quality
control are handled by Claude.

The app is deployed as a **private demo** accessible only via an invite link
or an access key. It runs in the cloud (frontend on Cloudflare Pages, backend
on Fly.io); no installation is expected from you.

---

## Access

### Via an invite link

The easiest path: the operator sends you a link of the form
`https://anime-illustrator.pages.dev/?invite=<key>`. Open it and the app will
remember your key in the browser — from then on you work without entering the
key again.

### Via a manually entered key

If you only received the key as text, go to
`https://anime-illustrator.pages.dev/`, paste the key into the "Access key"
field on the welcome screen and confirm. The key is stored in the browser's
`localStorage`, so on your next visit you won't have to enter anything.

### Per-key limits

Every key has a pre-allocated number of **completed stories** it can produce
within the demo (typically 2–5). Once you exhaust it, the app tells you and
asks you to contact the operator. If a story fails because of a GPU outage or
another infrastructure problem (not because Claude gave up), the quota for
that story is **refunded automatically**.

A single chat is capped at **20 messages from you**. If you hit that, the app
sends you off to start a new story — the old ones remain available for
viewing via their direct URL.

---

## Creating a story — step by step

### Step 1 — pick a language

There's a language switcher in the top-right corner (flags **SK / CZ / GB**).
Language affects two things:
- the language of the interface (labels, buttons, messages),
- the language of the story itself — Claude will narrate and write in this
  language.

You can switch the language **mid-run** or on a finished story too — the text
is translated, the images stay the same. Translations are cached, so flipping
back and forth is instant after the first time.

### Step 2 — chat with the assistant

The landing screen shows a chat window. The assistant (Claude in a
"co-creator" role) asks you about the idea, characters, environment, mood.
The rules the MVP enforces, which the assistant handles for you automatically:

- **At most one boy / man** (in anime style, modeled after Izuku Midoriya,
  MHA).
- **At most one girl / woman** (in the style of Kyoka Jiro, MHA).
- A **mother** as an optional third character, but only if at least one of
  the two above is present.
- Optionally **one non-human character** (animal, robot, plushie…) and
  **important objects** that resonate in the story.
- **5 illustrations** spread across at most 5 environments, with the main
  character appearing at least twice.

When the assistant is happy with the brief, it summarises it and asks for
your **confirmation**. Just type "yes" (or suggest a tweak — that extends
the conversation). After confirmation, a second Claude agent kicks in under
the hood to write the actual story and lay out the 5 illustration scenes.
This takes roughly 20–40 seconds.

### Step 3 — watching the generation

After the brief is confirmed, the page switches to the story detail
(`/<lang>/runs/<id>`). At the top you see:

- The **story title** (a short topic first, then the final title).
- The **state** (Running / Done / Failed / Cancelled) and the **counter**
  "K of 5 done".
- The **"Cancel run"** button while the run is in flight.
- An optional **banner** explaining the failure if the run as a whole failed.

Below that the story itself is shown — text paragraphs alternate with
illustrations exactly the way they'll appear in the final book. While text
or an image is being prepared, a skeleton placeholder (a light-grey area in
the right shape) holds its spot, so the layout doesn't jump around.

Feel free to **refresh or close** the page and come back later via the same
URL — the run continues in the background. If you find on return that the
run has finished since you last opened it, you'll see the result directly;
if a server restart interrupted things, the app will automatically try to
reconnect to the running GPU jobs (more on this in the *Resilience*
section).

### Illustration states

Each of the five illustration cards goes through its own sequence of states.
The most common ones you'll see:

| Label                           | What's happening                                                                |
|---------------------------------|---------------------------------------------------------------------------------|
| Waiting                         | The card hasn't started yet (waiting for a free "slot")                         |
| Building prompts                | Claude is formulating what the GPU should render                                |
| **Queued on GPU**               | The job has been sent to RunPod and is waiting for a free worker                |
| Rendering image (attempt K/3)   | A worker is actively rendering                                                  |
| Evaluating                      | Claude is scoring the finished image against the brief                          |
| Revising prompts                | The image didn't match; Claude rewrites the prompts and tries again             |
| Rethinking concept              | After three failed attempts Claude reworks the scene from scratch               |
| Rethinking environment          | In rare cases even the environment is swapped — when Claude can't "feed" the renderer the scene |
| Reviewing earlier attempts      | Once the auto-budget is spent, Claude revisits history and picks the best prior attempt |
| Co-creating (manual)            | The auto-pipeline gave up; a chat with a "co-illustrator" opens                 |
| Done                            | Success, the image is displayed                                                 |
| Failed                          | Even the manual budget ran out                                                  |
| Cancelled                       | The run was cancelled                                                           |

**"Queued on GPU"** is an important distinction: it means the job is waiting
for free hardware (typical on demo deploys with 0–1 warm workers). It will
automatically transition into **Rendering image** as soon as a worker picks
the job up. If a job spends more than 30 minutes in the queue, that's
treated as a capacity outage and the card gives up with a notice — the
quota is refunded for such a failure.

### Step 4 — result and interaction

When a card reaches the **Done** state, it shows the image right inside the
story. Clicking opens it in full size. Every card has a **three-dot menu**
in the top-right with these actions (as long as you still have manual
budget):

- **"Generate again"** — opens a chat with the manual assistant; the
  original image is kept as a backup until you accept the new one.
- **"Show conversation"** — visible if the card already went through some
  manual interaction; shows the dialog stored so far and all attempts.

Inside each card a click on the concept popover (a small icon) reveals
**what Claude knows about the scene** — concept, character, environment and
any non-human entity in the scene. It's mainly there to help you understand
why an image looks the way it does.

### Step 5 — cancelling the run

The **"Cancel run"** button at the top stops all pending cards. Heads-up:
images that are **right now** on the GPU will finish — the app just won't
use the result afterwards (RunPod has no API to abort an in-flight job).
Cards that are already done stay as they are.

---

## Manual co-creation ("co-illustrator")

If the auto-pipeline (3 concepts × 3 images × an optional history salvage)
doesn't succeed, the card is **not flipped into failure** — instead a short
chat with a **"co-illustrator"** (Claude in a different role) opens in its
place. The goal is to land a usable image in dialog with you.

How it looks:

1. The assistant greets you and briefly asks what you want to see in the
   scene. The assistant **doesn't see images**, so describe every piece of
   feedback in words ("brighten the background", "add a smile", "remove the
   glasses").
2. Once you have a concrete concept together, click **"Confirm"**. The
   assistant builds the prompts and ships them off for a render.
3. After every render you see the image right in the panel and small
   buttons **"Accept"** or **"Iterate"**. Accepting ends the manual
   co-creation and the image becomes part of the story. Iterating adds
   another piece of feedback and advances to the next attempt.
4. The manual budget is **5 attempts** per card. If you spend it, the card
   flips to "Failed". Even then the **"Show conversation"** menu remains
   available, so you can come back to any of the 5 past attempts and accept
   it after the fact.

You can also start manual co-creation yourself on a **finished image** via
the three-dot menu → "Generate again". In that case the original image is
preserved as a backup and the manual budget is not reset (it is shared with
any prior automatic fallback on the same card).

---

## Resilience to outages

For a demo deploy, compactness and cost won over robustness, but the app
still has a handful of mechanisms that handle ordinary short outages
gracefully:

- **Server restart during a run** (deploy, brief OOM) — at startup all
  running runs are classified and the ones that had an in-flight GPU job
  **re-attach to the same RunPod job-id**. At worst you lose your position
  in the queue, not the whole budget.
- **Lost SSE connection** (WiFi switch, laptop sleep) — the browser
  reconnects automatically; on reconnect you receive the current snapshot
  and SSE picks up as if nothing happened.
- **Saturated GPU queue** — when a job spends over 30 min in the queue, the
  card gives up with a "GPU queue timed out" message; the quota is
  refunded.
- **Stuck worker** — when a GPU starts processing a job but doesn't deliver
  the result within 10 minutes, the app retries the job up to 2 more times
  with a fresh seed (on a different worker). Only then does the card give
  up.

---

## Frequently asked questions

**How much will this cost me?**
The demo has a built-in per-key quota — the operator pays for the
infrastructure. You don't worry about prices, only about the number of
stories you have left.

**Generation is slow / some cards are stuck on "Queued on GPU".**
On small demo deploys there usually aren't any GPU workers running
continuously — every new card first warms up a worker (~30–60 s) and only
then starts rendering. Five cards run in parallel, so you may legitimately
see all 5 in "Queued" at once. Hang on, it will move.

**Some cards fail even after manual — what do I do?**
The most common cause is that the requested scene is beyond what the
MHA-LoRA model can handle (too many characters, exotic poses, strong style
clashes). The manual **"Show conversation"** menu lets you accept any of
the 5 historical manual attempts; often one of them looks reasonable, the
assistant just judged it imperfect.

**Can I download my story?**
Not for now — both images and text live exclusively at the run URL
(`/<lang>/runs/<id>`). You can however bookmark that URL, open it any
time later and in any of the three languages.

**Does it work on mobile?**
The app is responsive and does work in a phone browser, but the 5-column
card grid is more comfortable on a tablet or computer.

**Are my inputs stored anywhere?**
Yes — the chat and the resulting story are persisted in the backend
database, so you can come back to the run. For the demo the data is
private at the URL level (whoever has the URL sees the run; we don't link
the URL publicly anywhere).

**I lost my access key.**
Contact the operator — keys are generated one-off, there is no
self-service recovery. If you still have an active browser session in
which the key was used, you can find it in `localStorage` under the
`accessKey` key.

---

## Limits (summary)

| Limit                                            | Value                                  |
|--------------------------------------------------|----------------------------------------|
| Illustrations per story                          | exactly 5                              |
| Attempts per concept                             | 3                                      |
| Concepts per illustration                        | 3                                      |
| Manual attempts per illustration                 | 5                                      |
| User messages per chat                           | 20                                     |
| Total messages (incl. assistant) per chat        | 60                                     |
| Wait in the GPU queue                            | 30 minutes (then failure)              |
| Wait for a finished image after worker pickup    | 10 minutes × 3 attempts with new seed  |
| Supported UI and story languages                 | SK, CZ, EN                             |

---

## Reporting problems

If you hit a bug that isn't described in this guide, message the operator
(the person who sent you the access key) together with the URL of the run
where the problem showed up — from the URL they can dig the detailed log
of that specific run out of the backend.
