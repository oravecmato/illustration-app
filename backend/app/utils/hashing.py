"""Utilities for computing source hashes for translation staleness detection."""

import hashlib


def compute_source_hash(text: str) -> str:
    """Compute SHA-256 hash of source text for translation staleness detection.

    Returns a hex-encoded string of the hash digest. Used to determine if a
    translation is stale by comparing against the current source hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
