"""Save and load image files to/from disk."""

import os

import aiofiles


async def save_image(image_bytes: bytes, output_dir: str, run_id: str, scene_index: int) -> str:
    """Save image bytes to OUTPUT_DIR/runs/<run_id>/scene_<scene_index>.png.

    Returns the relative path (relative to output_dir).
    """
    relative_path = f"runs/{run_id}/scene_{scene_index}.png"
    full_path = os.path.join(output_dir, relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(image_bytes)
    return relative_path


async def save_manual_image(
    image_bytes: bytes,
    output_dir: str,
    run_id: str,
    scene_index: int,
    manual_attempt: int,
) -> str:
    """Save a manual-attempt image (§ 6A).

    Path: ``OUTPUT_DIR/runs/<run_id>/manual_<scene_index>_<manual_attempt>.png``.
    Returns the relative path (relative to ``output_dir``).
    """
    relative_path = f"runs/{run_id}/manual_{scene_index}_{manual_attempt}.png"
    full_path = os.path.join(output_dir, relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(image_bytes)
    return relative_path


async def copy_image(source_relative_path: str, output_dir: str, dest_relative_path: str) -> str:
    """Copy an already-saved image to a new relative path under output_dir.

    Used by the manual flow when promoting an accepted manual render to the
    canonical ``scene_<scene_index>.png`` location.
    Returns the destination relative path.
    """
    source_full = os.path.join(output_dir, source_relative_path)
    dest_full = os.path.join(output_dir, dest_relative_path)
    os.makedirs(os.path.dirname(dest_full), exist_ok=True)
    async with aiofiles.open(source_full, "rb") as src:
        data = await src.read()
    async with aiofiles.open(dest_full, "wb") as dst:
        await dst.write(data)
    return dest_relative_path
