"""Pixel-perfect sprite animation from a video model.

Chain (see README):
  1. your native sprite (PNG with alpha, <= 64 px) -> bottom-centre on a chroma-key canvas (green / magenta / blue,
     whichever is furthest from the sprite's colours), nearest-upscaled to `side`² (default 384)
  2. Wan 2.2 I2V A14B (GGUF): high-noise stage WITHOUT the lightx2v speed LoRA (real CFG 3.5), low-noise stage with it
     -> the motion comes from the text (`action`): run, fly, drink, explode ...
  3. pick frames: `loop` = one motion period (cycle search on key masks), `once` = n frames spread over the clip,
     trimmed after the last frame where the subject is still visible
  4. re-draw every picked frame with Krea 2 Turbo + k2-pixel LoRA img2img (denoise 0.4), 6 frames per job,
     MiniMax H3 refiner collapses to the exact grid with ONE shared palette (sprite colours, or video colours for effects)
  5. key out the background -> frames, spritesheet, preview GIF, meta JSON
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import comfy

WORKFLOWS = Path(__file__).resolve().parent / "workflows"
WAN = WORKFLOWS / "wan22_i2v_motion.json"
KREA_BATCH = WORKFLOWS / "krea2_pixel_img2img_batch6.json"

KEYS = {"green": (0, 200, 0), "magenta": (230, 0, 230), "blue": (0, 60, 255)}
TRIGGER = {32: "8-bit pixel art sprite", 64: "Low resolution 8-bit game sprite"}  # k2-pixel32 / k2-pixel64
HOLD = ("Static camera, no zoom: the character keeps exactly its size, proportions, colors and outfit from the start image "
        "and stays in the center of the frame. Plain solid bright {key} background ({key} screen).")
FOLLOW = ("The camera follows the character so it stays in the center of the frame. "
          "Plain solid bright {key} background ({key} screen).")


# ------------------------------------------------------------------------------------------------- image helpers
def bbox(mask: np.ndarray):
    ys, xs = np.where(mask)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None


def choose_key(sprite: np.ndarray) -> str:
    """Background colour with the largest distance to the closest sprite colour (green beetle -> magenta/blue)."""
    cols = sprite[sprite[..., 3] >= 128][:, :3].astype(np.float32)
    return max(KEYS, key=lambda k: float(np.sqrt(((cols - np.array(KEYS[k], np.float32)) ** 2).sum(-1)).min()))


def start_image(sprite: np.ndarray, canvas: int, side: int = 384, margin: int = 0, key: str = "green") -> Image.Image:
    """Sprite bottom-centre on a canvas² grid (+ margin cells of air for wide motion), key colour, nearest to side²."""
    bb = bbox(sprite[..., 3] >= 128)
    if bb is None:
        raise ValueError("sprite is fully transparent")
    obj = sprite[bb[1]:bb[3], bb[0]:bb[2]]
    c = canvas + 2 * margin
    out = np.zeros((c, c, 4), np.uint8)
    h, w = obj.shape[:2]
    if h > c or w > c:
        raise ValueError(f"sprite {w}x{h} does not fit the {c}x{c} canvas")
    x0, y0 = (c - w) // 2, c - margin - 1 - h if margin else c - 1 - h
    out[max(0, y0):max(0, y0) + h, x0:x0 + w] = obj
    bg = Image.new("RGBA", (c, c), KEYS[key] + (255,))
    bg.alpha_composite(Image.fromarray(out))
    return bg.convert("RGB").resize((side, side), Image.NEAREST)


def frames_in_order(paths) -> list[str]:
    """Sort by the LAST number in the file name. Plain text sorting gives v_0, v_1, v_10, v_11 ... and silently shuffles
    every video – this bug cost us a day."""
    return sorted(map(str, paths), key=lambda p: int((re.findall(r"(\d+)", Path(p).stem) or ["0"])[-1]))


def key_mask(img: np.ndarray, tol: float = 70.0) -> np.ndarray:
    """Subject mask in front of a flat background (background = median of the border ring). Fringe pixels tinted towards
    the background colour (dominant channel > both others + 40) are removed as well."""
    a = img[..., :3].astype(np.float32)
    ring = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(ring, 0)
    m = np.sqrt(((a - bg) ** 2).sum(-1)) > tol
    dom = [c for c in range(3) if bg[c] > 150]
    others = [c for c in range(3) if c not in dom]
    if dom and others:
        tint = np.all([a[..., c] > a[..., o] + 40 for c in dom for o in others], axis=0)
        m &= ~tint
    return m


def key_out(path) -> np.ndarray:
    a = np.asarray(Image.open(path).convert("RGB"))
    m = key_mask(a)
    out = np.zeros(a.shape[:2] + (4,), np.uint8)
    out[m, :3] = a[m]  # transparent pixels stay (0, 0, 0, 0): no key colour hidden under alpha
    out[m, 3] = 255
    return out


def video_palette(paths, grid: int, n: int = 24) -> np.ndarray:
    """Shared palette from the subject pixels of the picked video frames (used when the action brings new colours)."""
    px = []
    for p in paths:
        a = np.asarray(Image.open(p).convert("RGB").resize((grid, grid), Image.BOX))
        px.append(a[key_mask(a)])
    px = np.concatenate(px) if px else np.zeros((1, 3), np.uint8)
    if len(px) == 0:
        px = np.zeros((1, 3), np.uint8)
    q = Image.fromarray(px.reshape(1, -1, 3).astype(np.uint8)).quantize(colors=min(n, max(2, len(px))), method=Image.Quantize.MEDIANCUT)
    return np.array(q.getpalette()[: 3 * len(q.getcolors())], np.uint8).reshape(-1, 3)


def pick_loop(masks: list[np.ndarray], n: int = 12, skip: int = 4, pmin: int = 6) -> tuple[list[int], dict]:
    """One motion period: smallest mean mask difference between window i..i+3 and i+p..i+p+3."""
    N, best = len(masks), None
    for per in range(pmin, N // 2 + 1):
        ds = [np.mean([(masks[i + j] ^ masks[i + per + j]).mean() for j in range(4)]) for i in range(skip, N - per - 3)]
        if ds:
            d, i0 = float(min(ds)), skip + int(np.argmin(ds))
            if best is None or d < best[0] - 1e-4:
                best = (d, per, i0)
    if best is None:
        return [int(i) for i in np.linspace(skip, N - 1, n).round()], {"period": None}
    d, per, i0 = best
    idx = list(range(i0, i0 + per)) if per <= n else [i0 + round(k * per / n) for k in range(n)]
    return idx, {"period": per, "loop_diff": round(d, 4), "start": i0}


def pick_once(areas: list[float], n: int = 12, skip: int = 2) -> tuple[list[int], dict]:
    """One-shot action: n frames up to just after the last frame whose subject is still visible (no empty tail)."""
    vis = [i for i, a in enumerate(areas) if a > 0.1 * max(areas or [1])]
    last = min(len(areas) - 1, (vis[-1] + 1) if vis else len(areas) - 1)
    return [int(i) for i in np.linspace(skip, last, n).round()], {"period": None, "last_visible": last}


def hstack(frames: list[np.ndarray], gap: int = 0) -> np.ndarray:
    h = max(f.shape[0] for f in frames)
    out = np.zeros((h, sum(f.shape[1] for f in frames) + gap * (len(frames) - 1), 4), np.uint8)
    x = 0
    for f in frames:
        out[h - f.shape[0]:, x:x + f.shape[1]] = f
        x += f.shape[1] + gap
    return out


def save_gif(frames: list[np.ndarray], path: Path, fps: int = 10, target: int = 256, bg=(231, 233, 251)):
    h = max(f.shape[0] for f in frames)
    w = max(f.shape[1] for f in frames)
    s = max(1, target // max(w, h))
    imgs = []
    for f in frames:
        c = Image.new("RGBA", (w, h), bg + (255,))
        c.alpha_composite(Image.fromarray(f), ((w - f.shape[1]) // 2, h - f.shape[0]))
        imgs.append(c.convert("RGB").resize((w * s, h * s), Image.NEAREST)
                    .quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    imgs[0].save(path, "GIF", save_all=True, append_images=imgs[1:], duration=int(1000 / fps), loop=0, disposal=1)


# ------------------------------------------------------------------------------------------------- the pipeline
def animate(sprite: str | Path, action: str, description: str, out_dir: str | Path, *, mode: str = "loop", n: int = 12,
            seed: int = 3, length: int = 33, denoise: float = 0.4, view: str = "side view facing right", margin: int = 0,
            hold: bool = True, side: int = 384, steps: int = 8, cell: int = 32, fps: int = 10,
            client: comfy.ComfyClient | None = None, wan_params: dict | None = None, krea_params: dict | None = None,
            verbose: bool = True) -> dict:
    """Any animation for an existing sprite.

    sprite:      native sprite (PNG with alpha, <= 64 px), drawn as `view`
    action:      what happens, as a sentence ("spreads its wings and flies", "explodes into pieces", ...)
    description: the character described precisely (colours, clothes) – keeps both models on the character
    mode:        'loop' (one period: run, fly, idle) or 'once' (n frames over the whole clip: explosion, drinking)
    margin:      extra cells of air around the sprite for wide motion (wings 6, explosion 8)
    hold:        True = prompt demands same size/proportions (safe against zoom, but damps big actions);
                 False = camera follows, palette taken from the video (fire, smoke)
    side/steps:  video resolution (multiple of 16) and Wan steps (half with real CFG on the high-noise stage)
    cell:        Krea cell size: 32 = k2-pixel32 at grid*32 px (best look), 16 = k2-pixel64 at grid*16 px (faster)
    """
    client = client or comfy.ComfyClient()
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    T = {"t0": time.time()}
    base = np.asarray(Image.open(sprite).convert("RGBA"))
    bb = bbox(base[..., 3] >= 128)
    if bb is None:
        raise ValueError("sprite is fully transparent")
    size = max(bb[3] - bb[1], bb[2] - bb[0])
    if size > 64:
        raise ValueError(f"sprite is {size} px; this pipeline is tuned for native sprites up to 64 px")
    canvas = 32 if size <= 30 else 64
    grid = canvas + 2 * margin
    lora = 32 if (cell == 32 and grid <= 48) else 64
    key = choose_key(base)
    st = d / "start.png"
    start_image(base, canvas, side, margin, key).save(st)

    # 2) motion from the video model
    prompt = (f"Pixel art video game sprite animation of {description}, {view}. The character from the start image {action}. "
              + (HOLD if hold else FOLLOW).format(key=key))
    wp = dict(start="@" + str(st), prompt=prompt, length=length, seed=seed, hi_cfg=3.5, steps=steps, split=steps // 2,
              width=side, height=side)
    wp.update(wan_params or {})
    if verbose:
        print(f"[1/2] Wan 2.2 video: {length} frames at {side}², {steps} steps, key={key}", flush=True)
    m = comfy.run(WAN, wp, d / "video", client, verbose)
    T["wan"] = time.time()
    paths = frames_in_order(m["out_files"])

    # 3) frame picking
    if mode == "loop":
        masks = [key_mask(np.asarray(Image.open(p).convert("RGB").resize((32, 32), Image.BOX))) for p in paths]
        idx, info = pick_loop(masks, n=n)
    else:
        areas = [float(key_mask(np.asarray(Image.open(p).convert("RGB").resize((64, 64), Image.BOX))).mean()) for p in paths]
        idx, info = pick_once(areas, n=n)

    # 4) Krea re-draw, 6 frames per job, one shared palette
    cols = base[base[..., 3] >= 128][:, :3] if hold else video_palette([paths[i] for i in idx], grid, n=24)
    pal = np.unique(np.concatenate([cols, np.array([KEYS[key]], np.uint8)]), axis=0)
    pp = d / "palette.png"
    Image.fromarray(pal.reshape(1, -1, 3).astype(np.uint8)).save(pp)
    kc = grid * (32 if lora == 32 else 16)  # Krea canvas = grid x LoRA cell size (16-px token grid of Krea 2)
    cans = []
    for k, i in enumerate(idx):
        can = d / "canvas" / f"c_{k:02d}.png"
        can.parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(paths[i]).convert("RGB")
        im.resize((kc, kc), Image.NEAREST if kc % im.width == 0 else Image.LANCZOS).save(can)
        cans.append(can)
    kprompt = f"{TRIGGER[lora]}, plain solid bright {key} background\n\n{description}, {action}, {view}"
    frames = []
    for c0 in range(0, len(cans), 6):
        chunk = cans[c0:c0 + 6]
        imgs = {f"img{j}": "@" + str(chunk[min(j, len(chunk) - 1)]) for j in range(6)}
        kp = dict(imgs, palette="@" + str(pp), prompt=kprompt, seed=1, denoise=denoise, lora=f"k2-pixel{lora}.safetensors",
                  grid_w=grid, grid_h=grid, colors=max(8, len(pal)))
        extra = dict(krea_params or {})
        kp["lora"] = extra.pop("lora_dir", "") + kp["lora"]  # e.g. lora_dir=krea2/ if the LoRAs live in a subfolder
        kp.update(extra)
        if verbose:
            print(f"[2/2] Krea 2 re-draw: frames {c0 + 1}-{c0 + len(chunk)} of {len(cans)} ({kc}² -> {grid}²)", flush=True)
        mk = comfy.run(KREA_BATCH, kp, d / "krea" / f"b{c0:02d}", client, verbose)
        frames += [key_out(o) for o in frames_in_order(mk["out_files"])[:len(chunk)]]
    T["krea"] = time.time()

    # 5) outputs
    files = []
    (d / "frames").mkdir(exist_ok=True)
    for k, f in enumerate(frames):
        p = d / "frames" / f"frame_{k:02d}.png"
        Image.fromarray(f).save(p)
        files.append(str(p))
    Image.fromarray(hstack(frames)).save(d / "spritesheet.png")
    save_gif(frames, d / "preview.gif", fps=fps)
    meta = {"action": action, "description": description, "mode": mode, "key": key, "grid": grid, "lora": f"k2-pixel{lora}",
            "video_frames": len(paths), "picked": idx, "cycle": info, "hold": hold, "margin": margin, "seed": seed,
            "length": length, "side": side, "steps": steps, "denoise": denoise, "frames": files,
            "spritesheet": str(d / "spritesheet.png"), "gif": str(d / "preview.gif"),
            "timing": {"wan_s": round(T["wan"] - T["t0"], 1), "krea_s": round(T["krea"] - T["wan"], 1),
                       "total_s": round(T["krea"] - T["t0"], 1)}}
    (d / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta
