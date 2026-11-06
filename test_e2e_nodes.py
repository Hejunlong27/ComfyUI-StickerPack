"""End-to-end run of the node chain under ComfyUI's own Python (torch + PIL).

Run with the ComfyUI interpreter, not the system one:
  "<ComfyUI 的 python>" test_e2e_nodes.py <atlas.png>
"""

import os
import sys
import tempfile
import types

import numpy as np
import torch
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = tempfile.mkdtemp(prefix="sticker_e2e_")

# ComfyUI provides folder_paths at runtime; stub it for a standalone run.
fp = types.ModuleType("folder_paths")
fp.get_output_directory = lambda: OUT
sys.modules["folder_paths"] = fp

pkg = types.ModuleType("sp")
pkg.__path__ = [HERE]
sys.modules["sp"] = pkg
import importlib.util

spec = importlib.util.spec_from_file_location("sp.nodes", os.path.join(HERE, "nodes.py"))
nodes = importlib.util.module_from_spec(spec)
sys.modules["sp.nodes"] = nodes
spec.loader.exec_module(nodes)

atlas = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "..", "sticker-pack-2", "kf", "atlas", "k9-kaixin_raw.png")
text = sys.argv[2] if len(sys.argv) > 2 else "今天也要开心！"

arr = np.asarray(Image.open(atlas).convert("RGB")).astype(np.float32) / 255.0
image = torch.from_numpy(arr)[None, ...]
print(f"input  {tuple(image.shape)} from {os.path.basename(atlas)}")

key = nodes.StickerKeyGreen()
img, alpha = key.run(image, 90, 40, 1, 0.7, 118, 62)
print(f"key    image{tuple(img.shape)} alpha{tuple(alpha.shape)} "
      f"opaque={float((alpha > 0.5).float().mean()):.3f}")

split = nodes.StickerSplitGrid()
img, alpha = split.run(img, alpha, 4, 1, 0)
print(f"split  image{tuple(img.shape)} cells")

align = nodes.StickerAlignGround()
img, alpha = align.run(img, alpha, 70, 0.06, "3:-45")
print(f"align  image{tuple(img.shape)}")

comp = nodes.StickerCompose()
frames, fmask = comp.run(img, alpha, text, "C:/Windows/Fonts/msyhbd.ttc", 0, "#2B2B2B", 512,
                         "0,1,2,3,2,1")
print(f"compose frames{tuple(frames.shape)} mask{tuple(fmask.shape)}")

save = nodes.StickerSaveGIF()
(path,) = save.run(frames, fmask, "sticker/e2e-test", "320,180,180,600,180,180", 0, True)
print(f"save    {path}  {os.path.getsize(path) / 1024:.0f} KB")

gif = Image.open(path)
print(f"verify  size={gif.size} frames={gif.n_frames} loop={gif.info.get('loop')} "
      f"transparency={gif.info.get('transparency')}")
assert gif.size == (512, 512)
assert gif.n_frames == 6
assert gif.info.get("loop") == 0
assert gif.info.get("transparency") == 0
mp4 = path.replace(".gif", ".mp4")
print(f"mp4     {'ok' if os.path.exists(mp4) else 'skipped (no ffmpeg)'}")
print("\nE2E PASSED")
