"""Offline tests (no ComfyUI needed): python -m pytest tests  (or: python tests/test_offline.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pixel_video_sprites import comfy, pipeline as P  # noqa: E402


def sprite(color=(255, 255, 255), h=24, w=14):
    a = np.zeros((32, 32, 4), np.uint8)
    a[32 - h:, 9:9 + w] = color + (255,)
    a[32 - h:32 - h + 2, 9:9 + w] = (40, 16, 48, 255)  # dark outline-ish top
    return a


def test_frame_order_is_numeric():
    names = [f"v_{i}.png" for i in (0, 1, 10, 11, 2, 20, 3)]
    assert [Path(p).stem for p in P.frames_in_order(names)] == ["v_0", "v_1", "v_2", "v_3", "v_10", "v_11", "v_20"]
    comfy_names = ["33_pvs_00010_.png", "33_pvs_00002_.png", "33_pvs_00001_.png"]
    assert P.frames_in_order(comfy_names)[0].endswith("00001_.png")


def test_choose_key_avoids_sprite_colour():
    assert P.choose_key(sprite((0, 190, 10))) != "green"
    assert P.choose_key(sprite((255, 255, 255))) in P.KEYS


def test_start_image_and_key_mask_roundtrip():
    s = sprite()
    im = np.asarray(P.start_image(s, 32, side=384, margin=0, key="green"))
    assert im.shape == (384, 384, 3)
    m = P.key_mask(im)
    small = m[6::12, 6::12]  # one sample per cell
    assert abs(int(small.sum()) - int((s[..., 3] > 0).sum())) <= 2


def test_pick_loop_finds_period():
    masks = []
    for t in range(33):
        m = np.zeros((32, 32), bool)
        x = 4 + (t % 8) * 3
        m[10:30, x:x + 4] = True
        masks.append(m)
    idx, info = P.pick_loop(masks, n=12)
    assert info["period"] == 8 and len(idx) == 8


def test_pick_once_trims_empty_tail():
    areas = [0.3] * 20 + [0.0] * 13
    idx, info = P.pick_once(areas, n=12)
    assert info["last_visible"] == 20 and idx[-1] == 20 and len(idx) == 12


def test_stabilize_aligns_feet_and_height(tmp=None):
    import tempfile
    from PIL import Image
    d = Path(tmp or tempfile.mkdtemp())
    paths = []
    for k, (y1, h) in enumerate([(300, 120), (280, 150), (320, 100)]):  # foot line and height drift like a zooming hop
        a = np.zeros((384, 384, 3), np.uint8)
        a[...] = (0, 200, 0)
        a[y1 - h:y1, 150 + 10 * k:200 + 10 * k] = (255, 255, 255)
        p = d / f"v_{k}.png"
        Image.fromarray(a).save(p)
        paths.append(p)
    out = P.stabilize_frames(paths, d / "stab", scale=True, target_h=120)
    feet, heights, centres = [], [], []
    for q in out:
        ys, xs = np.where(P.key_mask(np.asarray(Image.open(q).convert("RGB"))))
        feet.append(ys.max())
        heights.append(ys.max() - ys.min() + 1)
        centres.append(xs.mean())
    assert max(feet) - min(feet) <= 2 and max(heights) - min(heights) <= 3 and max(centres) - min(centres) <= 2


def test_templates_are_valid_graphs():
    for t in (P.WAN, P.KREA_BATCH):
        tpl, defaults = comfy.load_template(t)
        params = {k: (v if v != "" else "x.png") for k, v in defaults.items()}
        wf = comfy.fill(tpl, params)
        assert "{{" not in json.dumps(wf)
        for nid, node in wf.items():
            for v in node["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    assert v[0] in wf, f"{t.name}: node {nid} links to missing node {v[0]}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
