"""Character configuration loader with startup validation (§ 7.3.7)."""

import json
import os

REQUIRED_ROLES = ("male", "female", "mother")
REQUIRED_ROLE_KEYS = ("lora_filename", "trigger_tags")


class CharacterConfigError(Exception):
    """Raised when character_config.json is missing, malformed, or incomplete."""


def load_character_config(path: str) -> dict:
    """Load and validate character_config.json.

    Returns the parsed config dict on success.
    Raises CharacterConfigError if the file is missing, malformed, or any
    required role or key is absent.
    """
    if not os.path.exists(path):
        raise CharacterConfigError(f"character_config.json not found at: {path}")

    try:
        with open(path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise CharacterConfigError(f"character_config.json is malformed JSON: {e}") from e

    if not isinstance(config, dict):
        raise CharacterConfigError("character_config.json must be a JSON object at the top level")

    for role in REQUIRED_ROLES:
        if role not in config:
            raise CharacterConfigError(f"character_config.json missing required role: '{role}'")
        entry = config[role]
        if not isinstance(entry, dict):
            raise CharacterConfigError(f"character_config.json role '{role}' must be an object")
        for key in REQUIRED_ROLE_KEYS:
            if key not in entry:
                raise CharacterConfigError(
                    f"character_config.json role '{role}' missing required key: '{key}'"
                )

    return config
