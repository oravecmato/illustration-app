"""Unit tests for character_config.json loader (§11.1)."""

import json
import os
import tempfile

import pytest

from app.services.character_config import CharacterConfigError, load_character_config

VALID_CONFIG = {
    "male": {
        "display_name": "Izuku Midoriya",
        "lora_filename": "midoriya_v1.safetensors",
        "trigger_tags": "midoriya izuku, green hair",
        "outfit_baseline": "school uniform",
    },
    "female": {
        "display_name": "Kyoka Jiro",
        "lora_filename": "jirou_v1.safetensors",
        "trigger_tags": "jirou kyouka, short hair",
        "outfit_baseline": "school uniform",
    },
    "mother": {
        "display_name": "Inko Midoriya",
        "lora_filename": "inko_v1.safetensors",
        "trigger_tags": "midoriya inko, green hair",
        "outfit_baseline": "casual clothes",
    },
}


def write_config(data, path):
    with open(path, "w") as f:
        json.dump(data, f)


def test_loads_valid_config():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(VALID_CONFIG, f)
        path = f.name
    try:
        config = load_character_config(path)
        assert set(config.keys()) == {"male", "female", "mother"}
        assert config["male"]["lora_filename"] == "midoriya_v1.safetensors"
        assert config["female"]["trigger_tags"] == "jirou kyouka, short hair"
    finally:
        os.unlink(path)


def test_refuses_missing_file():
    with pytest.raises(CharacterConfigError, match="not found"):
        load_character_config("/nonexistent/path/character_config.json")


def test_refuses_malformed_json():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        f.write("{ this is not valid json }")
        path = f.name
    try:
        with pytest.raises(CharacterConfigError, match="malformed"):
            load_character_config(path)
    finally:
        os.unlink(path)


def test_refuses_missing_role():
    config = {k: v for k, v in VALID_CONFIG.items() if k != "mother"}
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(config, f)
        path = f.name
    try:
        with pytest.raises(CharacterConfigError, match="mother"):
            load_character_config(path)
    finally:
        os.unlink(path)


def test_refuses_missing_lora_filename():
    config = {
        **VALID_CONFIG,
        "male": {k: v for k, v in VALID_CONFIG["male"].items() if k != "lora_filename"},
    }
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(config, f)
        path = f.name
    try:
        with pytest.raises(CharacterConfigError, match="lora_filename"):
            load_character_config(path)
    finally:
        os.unlink(path)


def test_refuses_missing_trigger_tags():
    config = {
        **VALID_CONFIG,
        "female": {k: v for k, v in VALID_CONFIG["female"].items() if k != "trigger_tags"},
    }
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(config, f)
        path = f.name
    try:
        with pytest.raises(CharacterConfigError, match="trigger_tags"):
            load_character_config(path)
    finally:
        os.unlink(path)


def test_refuses_non_object_at_top_level():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump(["list", "not", "dict"], f)
        path = f.name
    try:
        with pytest.raises(CharacterConfigError):
            load_character_config(path)
    finally:
        os.unlink(path)
