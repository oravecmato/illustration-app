"""Unit tests for small helpers inside app.services.claude."""

from app.constants import NEGATIVE_PROMPT_BASELINE
from app.services.claude import (
    _strip_json_fences,
    _validate_required_negative_tags,
    combined_negative_baseline,
)


def test_strip_json_fences_passthrough():
    assert _strip_json_fences('{"phase": "gathering"}') == '{"phase": "gathering"}'


def test_strip_json_fences_with_language_tag():
    raw = '```json\n{"phase": "gathering", "reply": "Hi"}\n```'
    assert _strip_json_fences(raw) == '{"phase": "gathering", "reply": "Hi"}'


def test_strip_json_fences_plain_triple_backtick():
    raw = '```\n{"phase": "gathering"}\n```'
    assert _strip_json_fences(raw) == '{"phase": "gathering"}'


def test_strip_json_fences_handles_surrounding_whitespace():
    raw = '\n\n```json\n{"a": 1}\n```\n\n'
    assert _strip_json_fences(raw) == '{"a": 1}'


def test_strip_json_fences_no_closing_fence_is_tolerated():
    # The model sometimes cuts off the trailing fence; still try to recover.
    raw = '```json\n{"phase": "gathering"}'
    assert _strip_json_fences(raw) == '{"phase": "gathering"}'


# ── combined_negative_baseline + _validate_required_negative_tags ────────
# § 7.3.6 "Per-character negative baseline" + § 7.1 hard validators
# "Required-negative-baseline coverage".

_CHAR_CONFIG = {
    "male": {
        "lora_filename": "m.safetensors",
        "trigger_tags": "midoriya izuku, green hair",
        "outfit_baseline": "school uniform",
    },
    "female": {
        "lora_filename": "f.safetensors",
        "trigger_tags": "jirou kyouka, black hair",
        "outfit_baseline": "school uniform",
        "negative_baseline": "ear jacks, earphone jack, mechanical ears",
    },
    "mother": {
        "lora_filename": "mo.safetensors",
        "trigger_tags": "midoriya inko, green hair",
        "outfit_baseline": "apron",
    },
}


def test_combined_baseline_appends_per_character_when_present():
    out = combined_negative_baseline("female", _CHAR_CONFIG)
    assert out.startswith(NEGATIVE_PROMPT_BASELINE)
    assert out.endswith("ear jacks, earphone jack, mechanical ears")


def test_combined_baseline_returns_global_only_for_role_without_field():
    assert combined_negative_baseline("male", _CHAR_CONFIG) == NEGATIVE_PROMPT_BASELINE
    assert combined_negative_baseline("mother", _CHAR_CONFIG) == NEGATIVE_PROMPT_BASELINE


def test_combined_baseline_returns_global_only_for_null_role():
    assert combined_negative_baseline(None, _CHAR_CONFIG) == NEGATIVE_PROMPT_BASELINE


def test_required_negative_tags_passes_when_all_present():
    baseline = "nsfw, bad anatomy, ear jacks"
    negative = "ear jacks, nsfw, bad anatomy, extra tag"
    assert _validate_required_negative_tags(negative, baseline) is None


def test_required_negative_tags_is_case_and_whitespace_tolerant():
    baseline = "Ear Jacks, nsfw"
    negative = "  ear  jacks ,  NSFW  "
    assert _validate_required_negative_tags(negative, baseline) is None


def test_required_negative_tags_enumerates_missing():
    baseline = "nsfw, bad anatomy, ear jacks, earphone jack"
    negative = "nsfw, bad anatomy"
    err = _validate_required_negative_tags(negative, baseline)
    assert err is not None
    assert "ear jacks" in err
    assert "earphone jack" in err


def test_required_negative_tags_empty_baseline_passes():
    assert _validate_required_negative_tags("anything", "") is None
