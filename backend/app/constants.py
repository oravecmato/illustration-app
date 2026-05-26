MAX_ILLUSTRATIONS = 5
MAX_PROMPT_ATTEMPTS_PER_CONCEPT = 3
MAX_CONCEPT_ATTEMPTS = 3
COMFYUI_POLL_TIMEOUT_S = 600
COMFYUI_POLL_INTERVAL_S = 3
MAX_CONCURRENT_BRANCHES = 5
CLAUDE_JSON_RETRY = 2
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
