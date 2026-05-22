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
