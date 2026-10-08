"""Still pixel art with the same models: scenes (no LoRA, 4 px per art pixel) and sprites/items (k2-pixel LoRA).

  scene("a fairytale castle above a mountain lake at sunset", "out/castle.png", size=(384, 216))
  sprite("a heroic knight in silver armor with a blue cape, full body, side view facing right", "out/knight.png", size=64)

Krea 2 draws the picture, the MiniMax H3 refiner collapses it to the exact grid (one art pixel = one output pixel).
Sprites come on white; the white background connected to the border is keyed out to alpha 0.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy

T2I = Path(__file__).resolve().parent / "workflows" / "krea2_pixel_t2i.json"
SCENE_STYLE = ("A detailed 16-bit pixel art game scene, crisp pixels, rich limited palette, atmospheric lighting, "
               "masterpiece pixel art illustration. No text, no UI, no border.")
SPRITE_TRIGGER = {32: "8-bit pixel art sprite", 64: "Low resolution 8-bit game sprite"}
ITEM_TRIGGER = "8-bit pixel art icon"


def _pick(files, tag):
    return next(f for f in files if f"_{tag}" in Path(f).name)


def key_white(img: Image.Image, tol: int = 24) -> Image.Image:
    """Flood-fill the near-white background from the border to alpha 0 (hard alpha, 0/255)."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w = a.shape[:2]
    white = (a.min(-1) >= 255 - tol)
    bg = np.zeros((h, w), bool)
    stack = [(y, x) for y in range(h) for x in (0, w - 1)] + [(y, x) for x in range(w) for y in (0, h - 1)]
    while stack:
        y, x = stack.pop()
        if bg[y, x] or not white[y, x]:
            continue
        bg[y, x] = True
        stack += [(yy, xx) for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)) if 0 <= yy < h and 0 <= xx < w]
    out = np.dstack([a.astype(np.uint8), np.where(bg, 0, 255).astype(np.uint8)])
    return Image.fromarray(out, "RGBA")


def _run(params: dict, out: Path, client, extra: dict | None, verbose: bool) -> tuple[Path, Path, dict]:
    _, p = comfy.load_template(T2I)
    p.update(params)
    p.update(extra or {})
    if "lora_dir" in p:
        p["lora"] = p.pop("lora_dir") + p["lora"]
    work = out.parent / (out.stem + "_work")
    m = comfy.run(T2I, p, work, client or comfy.ComfyClient(), verbose=verbose)
    return Path(_pick(m["out_files"], "native")), Path(_pick(m["out_files"], "raw")), m


def scene(subject: str, out: str | Path, size=(384, 216), seed: int = 1, colors: int = 32, client=None, extra=None,
          verbose: bool = True) -> dict:
    gw, gh = size
    out = Path(out)
    native, raw, m = _run(dict(prompt=f"{SCENE_STYLE}\n\n{subject}", seed=seed, width=gw * 4, height=gh * 4, grid_w=gw, grid_h=gh,
                               colors=colors, lora_strength=0.0, prefix="pvs/scene"), out, client, extra, verbose)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(native, out)
    return {"image": str(out), "raw": str(raw), "size": [gw, gh], "exec_s": m["exec_s"]}


def sprite(subject: str, out: str | Path, size: int = 64, seed: int = 1, colors: int = 16, item: bool = False, client=None,
           extra=None, verbose: bool = True) -> dict:
    lora = 32 if size <= 32 else 64
    cell = 1024 // lora
    trig = ITEM_TRIGGER if item else SPRITE_TRIGGER[lora]
    out = Path(out)
    native, raw, m = _run(dict(prompt=f"{trig}, white background\n\n{subject}. No ground shadow.", seed=seed, width=size * cell,
                               height=size * cell, grid_w=size, grid_h=size, colors=colors, lora=f"k2-pixel{lora}.safetensors",
                               lora_strength=1.0, auto_offset=True, prefix="pvs/sprite"), out, client, extra, verbose)
    out.parent.mkdir(parents=True, exist_ok=True)
    key_white(Image.open(native)).save(out)
    return {"image": str(out), "raw": str(raw), "size": [size, size], "exec_s": m["exec_s"]}
