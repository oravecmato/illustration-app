"""Unit tests for small helpers inside app.services.claude."""

from app.services.claude import _strip_json_fences


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
