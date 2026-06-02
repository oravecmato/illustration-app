"""Image key conventions + thin helpers over the configured ``ImageStore``.

This module owns the canonical *key shapes* (§ 8.7) for the three classes of
rendered images: canonical auto-pipeline scenes, per-attempt history snapshots,
and manual-flow attempts. The actual persistence is delegated to whichever
``ImageStore`` backend is configured (``LocalImageStore`` or ``R2ImageStore``)
so the orchestrator and the manual service never reach for ``aiofiles``
directly.
"""

from app.services.storage import ImageStore


def canonical_key(run_id: str, scene_index: int) -> str:
    """Logical key for the canonical, user-facing scene image."""
    return f"runs/{run_id}/scene_{scene_index}.png"


def history_key(
    run_id: str, illustration_id: str, concept_attempt: int, prompt_attempt: int
) -> str:
    """Logical key for a per-attempt history snapshot (one row in
    ``illustration_attempt_history``)."""
    return f"runs/{run_id}/history/{illustration_id}_{concept_attempt}_{prompt_attempt}.png"


def manual_key(run_id: str, scene_index: int, manual_attempt: int) -> str:
    """Logical key for a single manual-flow attempt (§ 6A.4)."""
    return f"runs/{run_id}/manual_{scene_index}_{manual_attempt}.png"


async def save_image(image_bytes: bytes, store: ImageStore, run_id: str, scene_index: int) -> str:
    """Persist the canonical scene image and return its logical key."""
    return await store.save(canonical_key(run_id, scene_index), image_bytes)


async def save_manual_image(
    image_bytes: bytes,
    store: ImageStore,
    run_id: str,
    scene_index: int,
    manual_attempt: int,
) -> str:
    """Persist a manual-flow attempt image (§ 6A) and return its logical key."""
    return await store.save(manual_key(run_id, scene_index, manual_attempt), image_bytes)


async def save_history_image(
    image_bytes: bytes,
    store: ImageStore,
    run_id: str,
    illustration_id: str,
    concept_attempt: int,
    prompt_attempt: int,
) -> str:
    """Persist an auto-pipeline attempt's image for the history table (§ 5)
    and return its logical key. Overwriting the same (c, p) pair is
    treated as a re-render of the same attempt."""
    return await store.save(
        history_key(run_id, illustration_id, concept_attempt, prompt_attempt),
        image_bytes,
    )


async def copy_image(source_key: str, store: ImageStore, dest_key: str) -> str:
    """Copy bytes already in the store from one logical key to another.
    Used by the salvage promotion (history → canonical) and by the manual
    flow when promoting an accepted attempt."""
    return await store.copy(source_key, dest_key)
