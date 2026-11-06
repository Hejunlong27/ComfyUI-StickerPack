"""Run StickerAutoPack end to end with ComfyUI stubbed out.

Catches the wiring mistakes that only show up at sampling time - notably passing
the {"samples": ...} dict where a tensor is required.

Run with ComfyUI's interpreter (needs torch):
  "<ComfyUI 的 python>" test_autopack_mock.py
"""

import importlib.util
import os
import sys
import tempfile
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = tempfile.mkdtemp(prefix="autopack_mock_")
seen = {}


# ----------------------------------------------------------------- stubs
def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Bar:
    def __init__(self, total):
        self.total = total

    def update_absolute(self, value, total=None):
        pass


def _prepare_noise(latent_image, seed, noise_inds=None):
    assert torch.is_tensor(latent_image), f"prepare_noise got {type(latent_image)}"
    return torch.zeros_like(latent_image)


def _fix_empty(model, latent_image, a=None, b=None):
    assert torch.is_tensor(latent_image), "fix_empty_latent_channels needs a tensor"
    return latent_image


def _sample_custom(model, noise, cfg, sampler, sigmas, positive, negative,
                   latent_image, noise_mask=None, callback=None, disable_pbar=False, seed=None):
    # This is the check that matters: comfy.samplers calls latent_image.is_nested.
    assert torch.is_tensor(latent_image), f"sample_custom latent_image is {type(latent_image)}"
    assert not isinstance(latent_image, dict)
    seen["latent_shape"] = tuple(latent_image.shape)
    seen["noise_mask"] = noise_mask
    seen["seed"] = seed
    if callback:
        callback(0, latent_image, len(sigmas) - 1)
    return torch.zeros_like(latent_image)


class _Encoder:
    # real ComfyUI V3 nodes expose execute as a classmethod, called on the class
    @staticmethod
    def execute(clip=None, prompt="", negative_prompt="", vae=None, resolution=0, images=None):
        seen.setdefault("prompts", []).append(prompt)
        return types.SimpleNamespace(result=("POS", "NEG", None))


class _EmptyLatent:
    @staticmethod
    def generate(width, height, batch_size=1):
        return ({"samples": torch.zeros([1, 4, height // 8, width // 8])},)


class _VAE:
    def decode(self, samples):
        assert torch.is_tensor(samples)
        # deliberately 4-channel HWC: this is what broke the real run
        return torch.rand(1, 256, 256, 4)


_mod("folder_paths", get_output_directory=lambda: OUT)
_mod("comfy")
def _unload():
    seen["unloads"] = seen.get("unloads", 0) + 1


_mod("comfy.model_management",
     throw_exception_if_processing_interrupted=lambda: None,
     soft_empty_cache=lambda: None,
     unload_all_models=_unload)
_mod("comfy.sample",
     prepare_noise=_prepare_noise,
     fix_empty_latent_channels=_fix_empty,
     sample_custom=_sample_custom)
_mod("comfy.samplers", sampler_object=lambda name: object(), KSampler=types.SimpleNamespace(SAMPLERS=("euler",)))
_mod("comfy.utils", ProgressBar=_Bar)
_mod("nodes", EmptyLatentImage=_EmptyLatent)
_mod("comfy_extras")
_mod("comfy_extras.nodes_qwen", TextEncodeQwenImage21=_Encoder)

# make `comfy.samplers` / `comfy.sample` reachable as attributes too
_comfy = sys.modules["comfy"]
for _n in ("sample", "samplers", "utils", "model_management"):
    setattr(_comfy, _n, sys.modules[f"comfy.{_n}"])
sys.modules["comfy_extras"].nodes_qwen = sys.modules["comfy_extras.nodes_qwen"]

pkg = types.ModuleType("sp")
pkg.__path__ = [HERE]
sys.modules["sp"] = pkg
spec = importlib.util.spec_from_file_location("sp.nodes", os.path.join(HERE, "nodes.py"))
nodes = importlib.util.module_from_spec(spec)
sys.modules["sp.nodes"] = nodes
spec.loader.exec_module(nodes)


BRIEF = """【角色】3D 渲染 Q 版少年，黑色碎发，白 T 恤

01｜收到！
少年站直，右手敬礼，点头两下。
配字：「收到！」
02｜谢谢老板
少年双手捧咖啡，笑成月牙，鞠躬两次。
配字：「老板大气！」"""

# --- _to_rgb_uint8 must normalise every layout a VAE might return ---------
cases = {
    "HWC 3ch": torch.rand(256, 256, 3),
    "HWC 4ch": torch.rand(256, 256, 4),
    "CHW 3ch": torch.rand(3, 256, 256),
    "CHW 4ch": torch.rand(4, 256, 256),
    "batch 4ch": torch.rand(1, 256, 256, 4),
}
for label, t in cases.items():
    out = nodes._to_rgb_uint8(t)
    assert out.shape == (256, 256, 3), f"{label} -> {out.shape}"
    assert out.dtype == np.uint8, f"{label} dtype {out.dtype}"
print("_to_rgb_uint8 ok:", ", ".join(cases))

node = nodes.StickerAutoPack()
frames, sheet, zip_path = node.run(
    model=object(), clip=object(), vae=_VAE(), ref_image=torch.rand(1, 64, 64, 3),
    brief=BRIEF, cells=3, width=512, height=512, ref_resolution=512,
    sampler_name="euler",
    sigmas="1.0,0.9,0.5,0", cfg=1.0, seed=7,
    font_path="C:/Windows/Fonts/msyhbd.ttc", canvas=256,
    frame_order="0,1,2,1", durations="200,100,300,100",
    pack_name="mock-pack", save_mp4=False, steps=2,
)

# --- 阶段顺序：9 条先全编码，再全采样，中间和之后各卸载一次模型 ---------
print("unload_all_models calls:", seen.get("unloads"))
assert seen.get("unloads") == 2, "编码→采样、采样→解码 各需要一次模型卸载"
# --- steps 会重采样 sigma 曲线 -------------------------------------------
t, n = nodes._sigmas_tensor("1.0,0.9,0.5,0.25,0", 2)
assert n == 2, n
assert abs(float(t[0]) - 1.0) < 1e-6 and abs(float(t[-1])) < 1e-6
print("sigmas resample:", [round(float(x), 3) for x in t])

print("latent passed as tensor:", seen["latent_shape"])
print("sample_custom calls:", len(seen["prompts"]))
print("frames:", tuple(frames.shape), "sheet:", tuple(sheet.shape))
print("zip:", zip_path, os.path.getsize(zip_path), "bytes")

import zipfile

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    assert z.testzip() is None
print("zip entries:", names)

assert len(seen["prompts"]) == 2, seen["prompts"]
assert "【角色】" in seen["prompts"][0] or "3D 渲染" in seen["prompts"][0], "preamble lost"
assert frames.shape[0] == 8, frames.shape          # 2 stickers x 4 frames
assert frames.shape[-1] == 3, f"IMAGE must be RGB, got {frames.shape}"
assert any(n.endswith(".gif") for n in names)
assert any(n.endswith(".zip") is False and n.endswith("预览.html") for n in names)
print("\nAUTOPACK MOCK TEST PASSED")
