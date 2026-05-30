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
ANTHROPIC_MODEL = "claude-sonnet-4-6"

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
