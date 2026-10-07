"""Command line: `pvs animate …`, `pvs check`.

  pvs check --url http://127.0.0.1:8188
  pvs animate examples/knuddel-bear-walk/input.png --view "side view facing left" \
      --action "stomps forward grumpily, swinging his short arms, the body bobbing heavily with each step ..." \
      --description "a small grumpy pink gummy bear with a dark plum outline and an angry frown" \
      --mode loop --frames 6 --stabilize scale --out out/bear-walk
"""
from __future__ import annotations

import argparse
import json
import sys

from . import comfy
from .pipeline import KREA_BATCH, WAN, animate

NODES = {"UnetLoaderGGUF": "ComfyUI-GGUF (github.com/city96/ComfyUI-GGUF)",
         "MiniMaxH3PixelArtRefiner": "ComfyUI-Krea2-Pixel-Art-Refiner (github.com/envy-ai/ComfyUI-Krea2-Pixel-Art-Refiner)",
         "WanImageToVideo": "ComfyUI core (update ComfyUI)", "ModelComputeDtype": "ComfyUI core (update ComfyUI)"}


def _kv(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k] = _coerce(v)
    return out


def _coerce(v: str):
    for f in (int, float):
        try:
            return f(v)
        except ValueError:
            pass
    return v


def check(url: str) -> int:
    c = comfy.ComfyClient(url)
    ok = True
    try:
        s = c.stats()
    except Exception as e:  # noqa: BLE001
        print(f"cannot reach ComfyUI at {url}: {e}")
        return 2
    dev = (s.get("devices") or [{}])[0]
    print(f"ComfyUI {s.get('system', {}).get('comfyui_version', '?')} at {url}; GPU: {dev.get('name', '?')}, "
          f"VRAM {dev.get('vram_total', 0) / 2**30:.1f} GB")
    types = c.node_types()
    for n, src in NODES.items():
        hit = n in types
        ok &= hit
        print(f"  {'ok     ' if hit else 'MISSING'} node  {n:28s} {'' if hit else '-> install ' + src}")
    _, wd = comfy.load_template(WAN)
    _, kd = comfy.load_template(KREA_BATCH)
    want = [("unet_gguf", "wan_high", wd), ("unet_gguf", "wan_low", wd), ("loras", "lightx2v_low", wd),
            ("text_encoders", "text_encoder", wd), ("vae", "vae", wd), ("diffusion_models", "krea_model", kd),
            ("text_encoders", "text_encoder", kd), ("vae", "vae", kd)]
    flag = {id(wd): "--wan", id(kd): "--krea"}
    rows = [(folder, key, d[key], flag[id(d)]) for folder, key, d in want]
    rows += [("loras", "lora", "k2-pixel32.safetensors", "--krea"), ("loras", "lora", "k2-pixel64.safetensors", "--krea")]
    for folder, key, name, fl in rows:
        files = c.models(folder) if folder != "unet_gguf" else (c.models("unet_gguf") or c.models("unet"))
        if files is None:
            print(f"  ?       model {folder}/{name} (server does not list this folder, cannot check)")
            continue
        if name in files:
            print(f"  ok      model {folder}/{name}")
            continue
        sub = next((f for f in files if f.replace("\\", "/").endswith("/" + name)), None)
        if sub:
            hint = f"{fl} lora_dir={sub[:-len(name)]}" if key == "lora" else f"{fl} {key}={sub}"
            print(f"  ok      model {folder}/{sub}  (in a subfolder: pass {hint})")
            continue
        ok = False
        print(f"  MISSING model {folder}/{name}  (see MODELS.md)")
    print("all good" if ok else "something is missing – see README, section Installation")
    return 0 if ok else 1


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(prog="pvs", description="Pixel-perfect sprite animations from a video model (ComfyUI).")
    ap.add_argument("--url", default=comfy.DEFAULT_URL, help="ComfyUI URL (default: env COMFY_URL or http://127.0.0.1:8188)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="check ComfyUI, custom nodes and model files")
    a = sub.add_parser("animate", help="animate one sprite")
    a.add_argument("sprite", help="native sprite PNG with alpha (<= 64 px)")
    a.add_argument("--action", required=True, help='what happens, e.g. "spreads its wings and flies"')
    a.add_argument("--description", required=True, help="the character, precisely (colours, clothes)")
    a.add_argument("--out", required=True, help="output folder")
    a.add_argument("--mode", choices=["loop", "once"], default="loop", help="loop = one motion period, once = one-shot action")
    a.add_argument("--frames", type=int, default=12, help="number of frames (default 12)")
    a.add_argument("--view", default="side view facing right")
    a.add_argument("--margin", type=int, default=0, help="extra cells of air (wings 6, explosion 8)")
    a.add_argument("--no-hold", action="store_true", help="let the camera follow / allow big changes (flight, explosions)")
    a.add_argument("--denoise", type=float, default=0.4, help="Krea re-draw strength (0.3 for effects, 0.4 default)")
    a.add_argument("--seed", type=int, default=3)
    a.add_argument("--length", type=int, default=33, help="video frames (4n+1: 33, 49)")
    a.add_argument("--side", type=int, default=384, help="video resolution (multiple of 16)")
    a.add_argument("--steps", type=int, default=8, help="Wan steps (half on the high-noise stage)")
    a.add_argument("--cell", type=int, choices=[32, 16], default=32, help="Krea cell size: 32 = best look, 16 = faster")
    a.add_argument("--fps", type=int, default=10)
    a.add_argument("--canvas", type=int, help="canvas edge in sprite pixels (default 32 up to 30 px, else 64; 80 for big bosses)")
    a.add_argument("--stabilize", choices=["pos", "scale"], help="calm foot line/centre (pos) and height (scale) before the re-draw")
    a.add_argument("--pick", help="own choice of video frames, e.g. 1,2,3,5,7,9,10,11 (default: automatic)")
    a.add_argument("--palette", choices=["base", "video"], help="palette from the sprite (base) or the video (default: base, video with --no-hold)")
    a.add_argument("--extra-colors", help='extra palette colours for --palette base, e.g. "96,102,128;128,136,160"')
    a.add_argument("--wan", action="append", metavar="KEY=VALUE", help="override a Wan template parameter (e.g. wan_high=my.gguf)")
    a.add_argument("--krea", action="append", metavar="KEY=VALUE", help="override a Krea template parameter")
    a.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        sys.exit(check(args.url))
    meta = animate(args.sprite, args.action, args.description, args.out, mode=args.mode, n=args.frames, seed=args.seed,
                   length=args.length, denoise=args.denoise, view=args.view, margin=args.margin, hold=not args.no_hold,
                   side=args.side, steps=args.steps, cell=args.cell, fps=args.fps, canvas=args.canvas,
                   stabilize=args.stabilize, picked=[int(x) for x in args.pick.split(",")] if args.pick else None,
                   palette=args.palette, extra_colors=[[int(v) for v in c.split(",")] for c in args.extra_colors.split(";")]
                   if args.extra_colors else None, client=comfy.ComfyClient(args.url),
                   wan_params=_kv(args.wan), krea_params=_kv(args.krea), verbose=not args.quiet)
    print(json.dumps({k: meta[k] for k in ("spritesheet", "gif", "picked", "cycle", "timing")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
