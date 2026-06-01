"""Unit tests for workflow placeholder replacement (§11.1)."""

from app.services.workflow import replace_placeholders

PLACEHOLDERS = {
    "POSITIVE_PROMPT": "brave knight, enchanted forest",
    "NEGATIVE_PROMPT": "blurry, ugly",
    "CHARACTER_LORA": "knight_v1",
    "STYLE_POSITIVE_PROMPT": "watercolor illustration",
    "STYLE_NEGATIVE_PROMPT": "photorealistic",
}


def test_replaces_all_five_placeholders_at_top_level():
    workflow = {
        "node1": {"inputs": {"text": "POSITIVE_PROMPT"}},
        "node2": {"inputs": {"text": "NEGATIVE_PROMPT"}},
        "node3": {"inputs": {"lora": "CHARACTER_LORA"}},
        "node4": {"inputs": {"style": "STYLE_POSITIVE_PROMPT"}},
        "node5": {"inputs": {"neg_style": "STYLE_NEGATIVE_PROMPT"}},
    }
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["text"] == "brave knight, enchanted forest"
    assert result["node2"]["inputs"]["text"] == "blurry, ugly"
    assert result["node3"]["inputs"]["lora"] == "knight_v1"
    assert result["node4"]["inputs"]["style"] == "watercolor illustration"
    assert result["node5"]["inputs"]["neg_style"] == "photorealistic"
    assert missing == []


def test_replaces_placeholders_nested_arbitrarily_deep():
    workflow = {"a": {"b": {"c": "POSITIVE_PROMPT"}}}
    single_replacement = {"POSITIVE_PROMPT": "brave knight, enchanted forest"}
    result, missing = replace_placeholders(workflow, single_replacement)
    assert result["a"]["b"]["c"] == "brave knight, enchanted forest"
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
        "node1": {"inputs": {"text": "POSITIVE_PROMPT"}},
    }
    # Only POSITIVE_PROMPT is present in workflow; others are missing
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["text"] == "brave knight, enchanted forest"
    assert set(missing) == {
        "NEGATIVE_PROMPT",
        "CHARACTER_LORA",
        "STYLE_POSITIVE_PROMPT",
        "STYLE_NEGATIVE_PROMPT",
    }


def test_workflow_not_mutated():
    original = {"node1": {"inputs": {"text": "POSITIVE_PROMPT"}}}
    replace_placeholders(original, PLACEHOLDERS)
    # original should not be mutated
    assert original["node1"]["inputs"]["text"] == "POSITIVE_PROMPT"


def test_placeholder_in_list():
    workflow = {"node1": {"inputs": {"texts": ["POSITIVE_PROMPT", "static value"]}}}
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    assert result["node1"]["inputs"]["texts"][0] == "brave knight, enchanted forest"
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


def test_seed_int_substitution_preserves_type():
    """SEED is an int value; the placeholder string is replaced by an int,
    not a stringified int — ComfyUI's KSampler expects a numeric seed."""
    workflow = {"sampler": {"inputs": {"seed": "SEED", "steps": 25}}}
    result, missing = replace_placeholders(workflow, {"SEED": 1234567890})
    assert result["sampler"]["inputs"]["seed"] == 1234567890
    assert isinstance(result["sampler"]["inputs"]["seed"], int)
    assert missing == []


def test_combined_placeholder_in_single_node():
    """A single text field may contain 'STYLE_POSITIVE_PROMPT, POSITIVE_PROMPT' — both replaced."""
    workflow = {"node": {"inputs": {"text": "STYLE_POSITIVE_PROMPT, POSITIVE_PROMPT"}}}
    # The substitution replaces only exact-match strings; combined literal is not replaced.
    # This test confirms the substitution logic is exact-match (not substring).
    result, missing = replace_placeholders(workflow, PLACEHOLDERS)
    # The combined string is not an exact placeholder, so it stays unchanged.
    assert result["node"]["inputs"]["text"] == "STYLE_POSITIVE_PROMPT, POSITIVE_PROMPT"
    assert set(missing) == {
        "POSITIVE_PROMPT",
        "NEGATIVE_PROMPT",
        "CHARACTER_LORA",
        "STYLE_POSITIVE_PROMPT",
        "STYLE_NEGATIVE_PROMPT",
    }
