MAX_ILLUSTRATIONS = 5
MAX_PROMPT_ATTEMPTS_PER_CONCEPT = 3
MAX_CONCEPT_ATTEMPTS = 3
MAX_MANUAL_ATTEMPTS = 5
COMFYUI_POLL_TIMEOUT_S = 600
COMFYUI_POLL_INTERVAL_S = 3
MAX_CONCURRENT_BRANCHES = 5
CLAUDE_JSON_RETRY = 2
# Number of additional Agent 0b (build_story) attempts after the first
# fails server-side semantic validation (pool fidelity or distribution
# rules). Each retry passes the validator's plain-English feedback back
# to the agent so it can correct course. Total attempts = 1 + retry.
BUILD_STORY_VALIDATOR_RETRY = 2
# Number of additional render attempts after the first hits a RunPod
# timeout (``RunPodTimeoutError``). A fresh seed is used for each retry
# so the GPU pool gets a different prompt-hash on the next try. The
# concept/prompt attempt counters are NOT incremented across the retry —
# a timeout is infrastructure noise, not a prompt-engineering signal.
# Other ``RunPodError`` failures (FAILED/CANCELLED job status, malformed
# response) still fail immediately without retry.
RUNPOD_TIMEOUT_RETRY = 2
# Status-aware poll timeouts (§ infra resilience). The poll loop tracks
# how long the job has stayed in each RunPod status and applies the
# matching cap. IN_QUEUE timeouts are NOT retried (a fresh job would
# lose FIFO position behind every other tenant), so the cap is set
# generously to ride out throttle waves. IN_PROGRESS timeouts ARE
# retried with a fresh seed (the worker stalled, the workflow is fine),
# matching the original ``COMFYUI_POLL_TIMEOUT_S`` budget.
RUNPOD_POLL_TIMEOUT_IN_QUEUE_S = 1800  # 30 min
RUNPOD_POLL_TIMEOUT_IN_PROGRESS_S = 600  # 10 min (matches existing)
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# Error-code strings persisted on ``Illustration.error_code`` so
# diagnostics can distinguish infrastructure failures from
# prompt-engineering exhaustions.
ERROR_CODE_RENDER_TIMEOUT = "RENDER_TIMEOUT"
# Stamped when the GPU pool was fully throttled for the entire
# ``RUNPOD_POLL_TIMEOUT_IN_QUEUE_S`` budget — the job never moved out
# of IN_QUEUE. Distinguished from ``RENDER_TIMEOUT`` (which means the
# worker started but stalled) so refunds + dashboards can attribute
# capacity events separately. Same refund semantics as RENDER_TIMEOUT.
ERROR_CODE_RENDER_QUEUE_TIMEOUT = "RENDER_QUEUE_TIMEOUT"
ERROR_CODE_RENDER_FAILED = "RENDER_FAILED"
# Stamped on illustrations whose parent run is reaped by
# ``_reap_orphan_runs`` on startup (uvicorn died mid-flight, e.g. OOM
# kill). Same refund semantics as RENDER_TIMEOUT — infrastructure
# noise, not prompt-engineering exhaustion. (§ 8.11.4)
ERROR_CODE_OOM_REAPED = "OOM_REAPED"

# Access-gating error codes (§ 8.11). All are returned as the
# ``error_code`` field of a 4xx response body so the frontend
# ``AccessGate.vue`` component can branch on them deterministically.
ERROR_CODE_MISSING_ACCESS_KEY = "MISSING_ACCESS_KEY"
ERROR_CODE_ACCESS_KEY_REVOKED = "ACCESS_KEY_REVOKED"
ERROR_CODE_QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
ERROR_CODE_SESSION_USER_MESSAGE_LIMIT = "SESSION_USER_MESSAGE_LIMIT"

# Supported UI and story languages (§ 9.6, § 10)
SUPPORTED_LANGUAGES = ("sk", "cs", "en")

# Canonical confirmation acknowledgements per language, returned by Agent 0a
# on phase="confirmed". Server normalises any other prose to this value so
# the frontend can render a deterministic message and tests can assert against
# a constant. (§ 7.1 Call 0a, § 10 Constants.)
CONFIRMED_ACK: dict[str, str] = {
    "sk": "Skvelé, ide na to. Pripravujem príbeh a ilustrácie…",
    "cs": "Skvělé, jdu na to. Připravuji příběh a ilustrace…",
    "en": "Great, on it. Building your story and illustrations…",
}

# Welcome message rendered as the first assistant bubble of every manual
# illustration session (§ 6A.3, § 6A.7). Contains a single `#…#` bold marker
# so the frontend renders the second sentence in bold. Localised in the
# illustration's source language; English fallback for any non-supported
# locale slipping through.
MANUAL_WELCOME: dict[str, str] = {
    "sk": (
        "Niečo sa pri tejto ilustrácii zaseklo a automaticky to nešlo. "
        "#Skús mi povedať, na čo by si chcel/a aby som sa zameral/a a "
        "spolu to vyriešime.#"
    ),
    "cs": (
        "U této ilustrace se to zaseklo a automaticky to nešlo. "
        "#Zkus mi říct, na co bych se měl/a zaměřit a vyřešíme to "
        "společně.#"
    ),
    "en": (
        "Something got stuck on this illustration and the automatic "
        "attempt did not land. #Tell me what you would like me to "
        "focus on and we will sort it out together.#"
    ),
}

# Welcome bubble appended at the start of a manual regeneration (§ 6A.9).
# Fired when the user clicks "Regenerate image" on a COMPLETED illustration:
# the prior canonical image is kept as a fallback and a fresh concept design
# begins. Same `#…#` bold-marker convention as MANUAL_WELCOME.
MANUAL_WELCOME_REGENERATE: dict[str, str] = {
    "sk": (
        "Ideme znova. Predchádzajúci obrázok si zachováme ako zálohu. "
        "#Povedz mi, čo by si chcel/a inak alebo lepšie a vyrobíme novú "
        "verziu.#"
    ),
    "cs": (
        "Jdeme znovu. Předchozí obrázek si necháme jako zálohu. "
        "#Řekni mi, co chceš jinak nebo lépe a vyrobíme novou verzi.#"
    ),
    "en": (
        "Let's try again. We're keeping the previous image as a fallback. "
        "#Tell me what you'd like different or better and we'll make a new "
        "version.#"
    ),
}

# Localised review prompt sent right after a manual render lands (§ 6A.4
# step 3.8). The frontend can also localise client-side; this server-side
# copy is what's persisted in `manual_messages` so reloads reproduce the
# exact bubble order.
MANUAL_REVIEW_PROMPT: dict[str, str] = {
    "sk": (
        "Ja obrázok nevidím — si moje oči. #Povedz mi konkrétne, čo chceš "
        "zmeniť# (napr. „rozjasni pozadie“, „pridaj úsmev“, „odstráň "
        "okuliare“), alebo napíš #„hotovo“#, ak je to dobré."
    ),
    "cs": (
        "Já obrázek nevidím — jsi mé oči. #Řekni mi konkrétně, co chceš "
        "změnit# (např. „zesvětli pozadí“, „přidej úsměv“, „odeber "
        "brýle“), nebo napiš #„hotovo“#, pokud je to dobré."
    ),
    "en": (
        "I can't see the image — you're my eyes. #Tell me concretely what "
        "you'd like to change# (e.g. “brighten the background”, “add a "
        "smile”, “remove the glasses”), or say #“done”# if it looks "
        "right."
    ),
}

# Localised iterate prompt appended when the user clicks the "Iterate"
# button on a freshly rendered manual image (§ 6A.10). Replaces the
# canonical role of MANUAL_REVIEW_PROMPT: the prompt is no longer
# auto-emitted after every render; it is appended only when the user
# explicitly asks for another iteration via the UI.
MANUAL_ITERATE_PROMPT: dict[str, str] = {
    "sk": (
        "Popíš tak detailne ako vieš, čo je s obrázkom zle a v čom sa "
        "odlišuje od konceptu, na ktorom sme sa dohodli. Ja tento obrázok "
        "nevidím — si moje oči. Čím lepší bude tvoj popis, tým väčšia "
        "bude pravdepodobnosť, že sa spoločnými silami dopracujeme k "
        "jeho požadovanej podobe."
    ),
    "cs": (
        "Popiš tak detailně jak umíš, co je s obrázkem špatně a v čem se "
        "liší od konceptu, na kterém jsme se dohodli. Já tento obrázek "
        "nevidím — jsi mé oči. Čím lepší bude tvůj popis, tím větší bude "
        "pravděpodobnost, že se společnými silami dopracujeme k jeho "
        "požadované podobě."
    ),
    "en": (
        "Describe in as much detail as you can what's wrong with the image "
        "and how it differs from the concept we agreed on. I can't see "
        "this image — you are my eyes. The better your description, the "
        "higher the chance that we'll work our way together to the version "
        "you want."
    ),
}

# Localised apology bubble used when a manual render fails (§ 6A.4
# step 3.10).
MANUAL_RENDER_FAILED: dict[str, str] = {
    "sk": "Tento pokus sa nepodarilo dokresliť. Skúsime to inak?",
    "cs": "Tento pokus se nepodařilo dokreslit. Zkusíme to jinak?",
    "en": "That attempt didn't render. Want to try something else?",
}

# Localised exhaustion bubble emitted when the manual budget runs out
# (§ 6A.4 step 6 + § 6A.7 key 4).
MANUAL_BUDGET_EXHAUSTED: dict[str, str] = {
    "sk": (
        "Žiaľ, vyčerpali sme všetky pokusy na túto ilustráciu. Ostatné "
        "obrázky v príbehu zostávajú, ale tento nie."
    ),
    "cs": (
        "Bohužel jsme vyčerpali všechny pokusy na tuto ilustraci. Ostatní "
        "obrázky v příběhu zůstávají, ale tento ne."
    ),
    "en": (
        "I'm sorry — we've used up every attempt for this illustration. "
        "The other images in the story remain, but this one stays as-is."
    ),
}

# Session-level limits (§ 7.2)
SESSION_MESSAGE_MAX_CHARS = 4000
SESSION_MAX_MESSAGES = 60
# Cap on user-authored messages per session. Tighter than
# ``SESSION_MAX_MESSAGES`` because every user turn triggers exactly one
# Agent 0a call, so capping the user side caps paid token spend
# deterministically per session. Enforced in ``services/session.py``
# before any Anthropic request is dispatched. (§ 10, § 13 AC 20)
SESSION_USER_MESSAGES_MAX = 20

# Canonical list of HTTP routes that hit Anthropic or RunPod and
# therefore cost money. Every entry MUST mount ``require_access_key``
# from ``app/api/auth.py``. A unit test (``test_paid_endpoints_guarded``)
# asserts at import time that the live FastAPI router has the dependency
# wired on each of these routes, so a new paid endpoint cannot be merged
# without a guard. Entries are ``(method, path)`` tuples matching
# ``starlette.routing.Route`` exactly.
PAID_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("POST", "/api/sessions"),
    ("POST", "/api/sessions/{session_id}/messages"),
    ("POST", "/api/runs/{run_id}/translations"),
    ("POST", "/api/runs/{run_id}/cancel"),
    # GET because the read endpoint bootstraps the manual flow on first
    # call (open_manual_flow → Agent 6 welcome bubble = Anthropic spend).
    ("GET", "/api/illustrations/{illustration_id}/manual"),
    ("POST", "/api/illustrations/{illustration_id}/manual/messages"),
    ("POST", "/api/illustrations/{illustration_id}/accept"),
    ("POST", "/api/illustrations/{illustration_id}/manual/iterate"),
    ("POST", "/api/illustrations/{illustration_id}/regenerate"),
)

# Character role → MHA character display name mapping (§ 7.3.2)
CHARACTER_ROLE_MAP: dict[str, str] = {
    "male": "Izuku Midoriya",
    "female": "Kyoka Jiro",
    "mother": "Inko Midoriya",
}

# Negative prompt baseline injected by Agents 1 and 3 (§ 7.3.6)
NEGATIVE_PROMPT_BASELINE = (
    "nsfw, suggestive, revealing clothing, lingerie, nudity, cleavage, underwear, sexualized, "
    "bad anatomy, extra fingers, missing fingers, fused fingers, malformed hands, extra limbs, "
    "distorted face, asymmetric eyes, "
    "low quality, blurry, watermark, signature, text, jpeg artifacts, "
    "multiple characters, crowd, two girls, two boys, 2girls, 2boys, group"
)

# Hard cap on number of comma-separated tags in the negative prompt. CLIP's
# token window is ~75; we cap at the CLIP boundary because realistic scenes
# legitimately need NSFW + anatomy + cast-extras + anti-creature +
# anti-env-confusion + anti-expression-drift simultaneously, which totals
# ~50-70 tags. A tighter cap (e.g. 60) was observed in Run #1 to reject
# valid Agent 1/3 outputs repeatedly and burn the Claude retry budget
# without delivering a usable render. Hard validator on Agents 1 and 3
# rejects responses that exceed this (see `_validate_prompts` in
# services/claude.py).
MAX_NEGATIVE_TAGS = 75
