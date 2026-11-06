"""Offline check of the core pipeline against a real generated atlas.

Run:  python test_core.py <atlas.png> [--cols 4] [--rows 1] [--text 文案] [--out out.gif]
Needs only PIL + numpy, no ComfyUI and no torch.
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sticker_core as core

ap = argparse.ArgumentParser()
ap.add_argument("atlas")
ap.add_argument("--cols", type=int, default=4)
ap.add_argument("--rows", type=int, default=1)
ap.add_argument("--row", type=int, default=0)
ap.add_argument("--text", default="今天也要开心！")
ap.add_argument("--order", default="0,1,2,3,2,1")
ap.add_argument("--durations", default="320,180,180,600,180,180")
ap.add_argument("--lifts", default="")
ap.add_argument("--font", default="C:/Windows/Fonts/msyhbd.ttc")
ap.add_argument("--out", default="test_out.gif")
args = ap.parse_args()

rgb = np.asarray(Image.open(args.atlas).convert("RGB"))
keyed, alpha = core.key_green(rgb, blank_w=118, blank_h=62)
rgba = Image.fromarray(np.dstack([keyed, alpha]), "RGBA")
print(f"key: removed {100 * (alpha < 128).mean():.1f}% of pixels")

cells = core.split_grid(rgba, args.cols, args.rows, args.row)
print(f"split: {len(cells)} cells of {cells[0].size}")

lift_map = {}
for part in filter(None, args.lifts.split(",")):
    i, v = part.split(":")
    lift_map[int(i)] = int(v)
lifts = [lift_map.get(i, 0) for i in range(len(cells))]
aligned = core.align_ground(cells, 70, 0.06, lifts)
print(f"align: output cell {aligned[0].size}")

order = [int(v) for v in args.order.split(",")]
frames = core.compose_frames(aligned, order, args.text, args.font, 0, "#2B2B2B", 512)
print(f"compose: {len(frames)} frames of {frames[0].size}")

durations = [int(v) for v in args.durations.split(",")]
core.save_gif(frames, args.out, durations, 0)
print(f"saved: {args.out}  {os.path.getsize(args.out) / 1024:.0f} KB")

im = Image.open(args.out)
print(f"verify: size={im.size} frames={im.n_frames} loop={im.info.get('loop')} "
      f"transparency={im.info.get('transparency')}")
