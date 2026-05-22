"""Unit tests for workflow placeholder replacement (§11.1)."""

from app.services.workflow import replace_placeholders

PLACEHOLDERS = {
    "CHARACTER_POSITIVE_PROMPT": "brave knight",
    "CHARACTER_NEGATIVE_PROMPT": "blurry, ugly",
    "ENVIRONMENT_PROMPT": "enchanted forest",
    "CHARACTER_LORA": "knight_v1",
    "STYLE_POSITIVE_PROMPT": "watercolor illustration",
    "STYLE_NEGATIVE_PROMPT": "photorealistic",
}


def test_replaces_all_six_placeholders_at_top_level():
    workflow = {
        "node1": {"inputs": {"text": "CHARACTER_POSITIVE_PROMPT"}},
        "node2": {"inputs": {"text": "CHARACTER_NEGATIVE_PROMPT"}},
        "node3": {"inputs": {"lora": "CHARACTER_LORA"}},
        "node4": {"inputs": {"style": "STYLE_POSITIVE_PROMPT"}},
        "node5": {"inputs": {"neg_style": "STYLE_NEGATIVE_PROMPT"}},
        "node6": {"inputs": {"env": "ENVIRONMENT_PROMPT"}},
    }
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["text"] == "brave knight"
    assert result["node2"]["inputs"]["text"] == "blurry, ugly"
    assert result["node3"]["inputs"]["lora"] == "knight_v1"
    assert result["node4"]["inputs"]["style"] == "watercolor illustration"
    assert result["node5"]["inputs"]["neg_style"] == "photorealistic"
    assert result["node6"]["inputs"]["env"] == "enchanted forest"
    assert missing == []


def test_replaces_placeholders_nested_arbitrarily_deep():
    workflow = {"a": {"b": {"c": "CHARACTER_POSITIVE_PROMPT"}}}
    single_replacement = {"CHARACTER_POSITIVE_PROMPT": "brave knight"}
    result, missing = replace_placeholders(workflow, single_replacement)
    assert result["a"]["b"]["c"] == "brave knight"
    assert missing == []


def test_leaves_unrelated_strings_untouched():
    workflow = {
        "node1": {"inputs": {"text": "some random value"}},
        "node2": {"inputs": {"other": 42}},
    }
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["text"] == "some random value"
    assert result["node2"]["inputs"]["other"] == 42


def test_reports_missing_placeholders():
    workflow = {
        "node1": {"inputs": {"text": "CHARACTER_POSITIVE_PROMPT"}},
    }
    # Only CHARACTER_POSITIVE_PROMPT is present in workflow; others are missing
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["text"] == "brave knight"
    assert set(missing) == {
        "CHARACTER_NEGATIVE_PROMPT",
        "ENVIRONMENT_PROMPT",
        "CHARACTER_LORA",
        "STYLE_POSITIVE_PROMPT",
        "STYLE_NEGATIVE_PROMPT",
    }


def test_workflow_not_mutated():
    original = {"node1": {"inputs": {"text": "CHARACTER_POSITIVE_PROMPT"}}}
    replace_placeholders(original, PLACEHOLDERS)
    # original should not be mutated
    assert original["node1"]["inputs"]["text"] == "CHARACTER_POSITIVE_PROMPT"


def test_placeholder_in_list():
    workflow = {"node1": {"inputs": {"texts": ["CHARACTER_POSITIVE_PROMPT", "static value"]}}}
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["texts"][0] == "brave knight"
    assert result["node1"]["inputs"]["texts"][1] == "static value"


def test_character_lora_sourced_per_illustration_role():
    """CHARACTER_LORA placeholder is filled from character_config[role].lora_filename (§ 7.3.7)."""
    character_config = {
        "male": {"lora_filename": "midoriya_v1.safetensors"},
        "female": {"lora_filename": "jirou_v1.safetensors"},
        "mother": {"lora_filename": "inko_v1.safetensors"},
    }
    for role, expected_lora in [
        ("male", "midoriya_v1.safetensors"),
        ("female", "jirou_v1.safetensors"),
        ("mother", "inko_v1.safetensors"),
    ]:
        workflow = {"lora_node": {"inputs": {"lora_name": "CHARACTER_LORA"}}}
        replacements = {**PLACEHOLDERS, "CHARACTER_LORA": character_config[role]["lora_filename"]}
        result, _ = replace_placeholders(workflow, replacements)
        assert result["lora_node"]["inputs"]["lora_name"] == expected_lora
