"""Workflow placeholder replacement for ComfyUI API format JSON."""

import copy
import logging

logger = logging.getLogger(__name__)

PLACEHOLDER_KEYS = [
    "CHARACTER_POSITIVE_PROMPT",
    "CHARACTER_NEGATIVE_PROMPT",
    "ENVIRONMENT_PROMPT",
    "CHARACTER_LORA",
    "STYLE_POSITIVE_PROMPT",
    "STYLE_NEGATIVE_PROMPT",
]


def replace_placeholders(
    workflow: dict,
    replacements: dict[str, str],
) -> tuple[dict, list[str]]:
    """Replace placeholder strings in workflow recursively.

    Returns a deep copy of the workflow with replacements applied, and a list
    of placeholder keys that were not found anywhere in the workflow.
    """
    workflow_copy = copy.deepcopy(workflow)
    found: set[str] = set()
    _replace_recursive(workflow_copy, replacements, found)
    missing = [key for key in replacements if key not in found]
    if missing:
        logger.warning("Workflow placeholders not found: %s", missing)
    return workflow_copy, missing


def _replace_recursive(obj, replacements: dict[str, str], found: set[str]) -> object:
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = _replace_recursive(v, replacements, found)
        return obj
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = _replace_recursive(item, replacements, found)
        return obj
    if isinstance(obj, str):
        if obj in replacements:
            found.add(obj)
            return replacements[obj]
        return obj
    return obj
