"""ComfyUI nodes for building animated chat-sticker GIF packs.

Wrap sticker_core so the pipeline runs inside a graph:
    StickerKeyGreen -> StickerSplitGrid -> StickerAlignGround
                    -> StickerCompose -> StickerSaveGIF

IMAGE is a float32 [B,H,W,C] tensor in 0..1, MASK is [B,H,W] where 1 = opaque.
"""

from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image

from . import sticker_core as core

CATEGORY = "sticker pack"


def _img_batch(t: torch.Tensor) -> torch.Tensor:
    """IMAGE is [B,H,W,C]; accept a bare [H,W,C] too."""
    return t.unsqueeze(0) if t.dim() == 3 else t


def _mask_batch(t: torch.Tensor) -> torch.Tensor:
    """MASK is [B,H,W]; accept a bare [H,W] too. Never confuse it with IMAGE."""
    return t.unsqueeze(0) if t.dim() == 2 else t


def _to_pil(image: torch.Tensor, mask: torch.Tensor | None = None) -> Image.Image:
    """image: [H,W,C] or [1,H,W,C]. mask: [H,W] or [1,H,W]."""
    image = _img_batch(image)
    if image.shape[0] != 1:
        raise ValueError(f"expected a single image, got a batch of {image.shape[0]}")
    arr = (image[0].clamp(0, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
    rgb = arr[..., :3]
    if mask is None:
        alpha = np.full(rgb.shape[:2], 255, np.uint8)
    else:
        m = _mask_batch(mask)
        alpha = (m[0].clamp(0, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA")


def _to_tensor(rgba: Image.Image) -> tuple[torch.Tensor, torch.Tensor]:
    arr = np.asarray(rgba).astype(np.float32) / 255.0
    image = torch.from_numpy(arr[..., :3])[None, ...]
    mask = torch.from_numpy(arr[..., 3])[None, ...]
    return image, mask


def _parse_ints(text: str, default: list[int]) -> list[int]:
    try:
        vals = [int(v) for v in text.replace(" ", "").split(",") if v != ""]
    except ValueError:
        return list(default)
    return vals or list(default)


class StickerKeyGreen:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "min_green": ("INT", {"default": 90, "min": 0, "max": 255}),
                "dominance": ("INT", {"default": 40, "min": 0, "max": 255}),
                "erode": ("INT", {"default": 1, "min": 0, "max": 6}),
                "feather": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 8.0, "step": 0.1}),
                "blank_wm_w": ("INT", {"default": 0, "min": 0, "max": 1024}),
                "blank_wm_h": ("INT", {"default": 0, "min": 0, "max": 1024}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "alpha")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, min_green, dominance, erode, feather, blank_wm_w, blank_wm_h):
        arr = (_img_batch(image)[0].clamp(0, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
        rgb, alpha = core.key_green(
            arr[..., :3], min_green, dominance, erode, feather, blank_wm_w, blank_wm_h
        )
        rgba = Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA")
        return _to_tensor(rgba)


class StickerSplitGrid:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "alpha": ("MASK",),
                "cols": ("INT", {"default": 4, "min": 1, "max": 16}),
                "rows": ("INT", {"default": 1, "min": 1, "max": 16}),
                "row_index": ("INT", {"default": 0, "min": -1, "max": 15,
                                      "tooltip": "-1 keeps every row, otherwise pick one row"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "alpha")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, alpha, cols, rows, row_index):
        rgba = _to_pil(image, alpha)
        cells = core.split_grid(rgba, cols, rows, row_index)
        imgs, masks = zip(*(_to_tensor(c) for c in cells))
        return torch.cat(imgs, dim=0), torch.cat(masks, dim=0)


class StickerAlignGround:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "alpha": ("MASK",),
                "pad": ("INT", {"default": 70, "min": 0, "max": 256}),
                "band_ratio": ("FLOAT", {"default": 0.06, "min": 0.01, "max": 0.40, "step": 0.01}),
                "lifts": ("STRING", {"default": "",
                                     "tooltip": "per-cell vertical offset, e.g. 3:-45 for a hop"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "alpha")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, alpha, pad, band_ratio, lifts):
        image, alpha = _img_batch(image), _mask_batch(alpha)
        cells = [_to_pil(image[i], alpha[i]) for i in range(image.shape[0])]
        lift_map: dict[int, int] = {}
        for part in filter(None, lifts.replace(" ", "").split(",")):
            try:
                idx, val = part.split(":")
                lift_map[int(idx)] = int(val)
            except ValueError:
                continue
        ordered = [lift_map.get(i, 0) for i in range(len(cells))]
        aligned = core.align_ground(cells, pad, band_ratio, ordered)
        imgs, masks = zip(*(_to_tensor(c) for c in aligned))
        return torch.cat(imgs, dim=0), torch.cat(masks, dim=0)


class StickerCompose:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "alpha": ("MASK",),
                "text": ("STRING", {"default": "今天也要开心！", "multiline": False}),
                "font_path": ("STRING", {"default": "C:/Windows/Fonts/msyhbd.ttc"}),
                "font_index": ("INT", {"default": 0, "min": 0, "max": 8}),
                "ink": ("STRING", {"default": "#2B2B2B"}),
                "canvas": ("INT", {"default": 512, "min": 128, "max": 1024, "step": 64}),
                "frame_order": ("STRING", {"default": "0,1,2,3,2,1",
                                           "tooltip": "cell indices in time order; repeats allowed"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("frames", "alpha")
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, image, alpha, text, font_path, font_index, ink, canvas, frame_order):
        if not os.path.exists(font_path):
            raise FileNotFoundError(
                f"font not found: {font_path}. Point font_path at a local ttf/ttc that covers the caption."
            )
        image, alpha = _img_batch(image), _mask_batch(alpha)
        cells = [_to_pil(image[i], alpha[i]) for i in range(image.shape[0])]
        order = [i for i in _parse_ints(frame_order, list(range(len(cells)))) if 0 <= i < len(cells)]
        if not order:
            raise ValueError("frame_order produced no valid cell index")
        frames = core.compose_frames(cells, order, text, font_path, font_index, ink, canvas)
        imgs, masks = zip(*(_to_tensor(f) for f in frames))
        return torch.cat(imgs, dim=0), torch.cat(masks, dim=0)


class StickerSaveGIF:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "alpha": ("MASK",),
                "filename_prefix": ("STRING", {"default": "sticker/001-今天也要开心"}),
                "durations": ("STRING", {"default": "320,180,180,600,180,180",
                                         "tooltip": "milliseconds per frame, rounded to 20ms"}),
                "loop": ("INT", {"default": 0, "min": 0, "max": 100,
                                 "tooltip": "0 = loop forever"}),
                "save_mp4": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("path",)
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, image, alpha, filename_prefix, durations, loop, save_mp4):
        import folder_paths

        image, alpha = _img_batch(image), _mask_batch(alpha)
        frames = [_to_pil(image[i], alpha[i]) for i in range(image.shape[0])]
        dur = _parse_ints(durations, [80] * len(frames))
        if len(dur) < len(frames):
            dur = dur + [dur[-1] if dur else 80] * (len(frames) - len(dur))

        out_dir = os.path.join(folder_paths.get_output_directory(), os.path.dirname(filename_prefix))
        base = os.path.basename(filename_prefix) or "sticker"
        gif_path = core.save_gif(frames, os.path.join(out_dir, base + ".gif"), dur, loop)

        if save_mp4:
            core.save_mp4(frames, os.path.join(out_dir, base + ".mp4"), dur)
        return (gif_path,)


class StickerPackBatch:
    """Whole pack in one node: N atlases in, N transparent GIFs + one ZIP out.

    Each batch item is one sticker's keyframe row. Captions are taken line by
    line, so the graph can carry a whole themed set with a single run.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "captions": ("STRING", {"default": "懂的都懂", "multiline": True}),
                "font_path": ("STRING", {"default": "C:/Windows/Fonts/msyhbd.ttc"}),
                "font_index": ("INT", {"default": 0, "min": 0, "max": 8}),
                "ink": ("STRING", {"default": "#2B2B2B"}),
                "canvas": ("INT", {"default": 512, "min": 128, "max": 1024, "step": 64}),
                "cols": ("INT", {"default": 4, "min": 1, "max": 16}),
                "rows": ("INT", {"default": 1, "min": 1, "max": 16}),
                "pad": ("INT", {"default": 70, "min": 0, "max": 256}),
                "band_ratio": ("FLOAT", {"default": 0.06, "min": 0.01, "max": 0.40, "step": 0.01}),
                "lifts": ("STRING", {"default": "", "tooltip": "cell:dy pairs, e.g. 3:-45"}),
                "blank_wm_w": ("INT", {"default": 118, "min": 0, "max": 1024}),
                "blank_wm_h": ("INT", {"default": 62, "min": 0, "max": 1024}),
                "frame_order": ("STRING", {"default": "0,1,2,3,2,1"}),
                "durations": ("STRING", {"default": "320,180,180,600,180,180"}),
                "loop": ("INT", {"default": 0, "min": 0, "max": 100}),
                "pack_name": ("STRING", {"default": "sticker-pack"}),
                "save_mp4": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("frames", "contact_sheet", "zip_path")
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, image, captions, font_path, font_index, ink, canvas, cols, rows, pad,
            band_ratio, lifts, blank_wm_w, blank_wm_h, frame_order, durations, loop,
            pack_name, save_mp4):
        import folder_paths

        if not os.path.exists(font_path):
            raise FileNotFoundError(f"font not found: {font_path}")

        image = _img_batch(image)
        n = image.shape[0]
        lines = [ln.strip() for ln in captions.splitlines() if ln.strip()] or ["sticker"]
        texts = [lines[i] if i < len(lines) else lines[-1] for i in range(n)]

        order = _parse_ints(frame_order, [0, 1, 2, 3, 2, 1])
        dur = _parse_ints(durations, [80] * len(order))
        lift_map = {}
        for part in filter(None, lifts.replace(" ", "").split(",")):
            try:
                k, v = part.split(":")
                lift_map[int(k)] = int(v)
            except ValueError:
                continue

        out_root = os.path.join(folder_paths.get_output_directory(), pack_name)
        os.makedirs(out_root, exist_ok=True)

        gif_paths: list[tuple[str, str]] = []
        all_frames: list[Image.Image] = []
        sheet_items: list[tuple[list[Image.Image], str]] = []

        for i in range(n):
            rgba = _to_pil(image[i])
            rgb = np.asarray(rgba)[:, :, :3]
            keyed, alpha = core.key_green(rgb, 90, 40, 1, 0.7, blank_wm_w, blank_wm_h)
            keyed_img = Image.fromarray(np.dstack([keyed, alpha]), "RGBA")

            cells = core.split_grid(keyed_img, cols, rows, 0)
            lifts_seq = [lift_map.get(c, 0) for c in range(len(cells))]
            aligned = core.align_ground(cells, pad, band_ratio, lifts_seq)
            frames = core.compose_frames(aligned, order, texts[i], font_path, font_index, ink, canvas)

            safe = "".join(ch for ch in texts[i] if ch not in '\\/:*?"<>|').strip() or f"{i + 1:03d}"
            name = f"{i + 1:03d}-{safe}.gif"
            gif_path = core.save_gif(frames, os.path.join(out_root, name), dur, loop)
            if save_mp4:
                core.save_mp4(frames, os.path.join(out_root, f"{i + 1:03d}-{safe}.mp4"), dur)

            gif_paths.append((name, gif_path))
            all_frames.extend(frames)
            sheet_items.append((frames, texts[i]))

        contact = core.contact_sheet(sheet_items)
        contact_path = os.path.join(out_root, "_contact_sheet.png")
        contact.save(contact_path)

        html = core.gallery_html(pack_name, [(t, n) for (n, _), (_, t) in zip(gif_paths, sheet_items)])
        zip_path = core.build_zip(gif_paths, os.path.join(out_root, f"{pack_name}.zip"))

        # The gallery and contact sheet travel inside the ZIP so it opens standalone.
        import zipfile

        with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
            z.writestr("预览.html", html)
            z.write(contact_path, "_contact_sheet.png")

        stack = torch.cat([torch.from_numpy(
            (np.asarray(f).astype(np.float32) / 255.0)[None, ...]) for f in all_frames], dim=0)
        contact_t = torch.from_numpy(
            (np.asarray(contact.convert("RGB")).astype(np.float32) / 255.0)[None, ...])

        return (stack, contact_t, zip_path)

def _sigmas_tensor(sigmas: str, steps: int):
    """按目标步数重采样 sigma 曲线。

    sigmas 里是 9 个值 = 8 步。要跑 6 步就在同一条曲线上等距取 7 个点，
    而不是硬编码一套新的 sigma —— 换模型时曲线形状仍然跟着走。
    """
    import torch as _torch

    vals = [float(x) for x in (sigmas or "").split(",") if x.strip()]
    if not vals:
        raise ValueError("sigmas 为空")
    if steps and steps + 1 != len(vals):
        src = np.linspace(0.0, 1.0, len(vals))
        dst = np.linspace(0.0, 1.0, steps + 1)
        vals = np.interp(dst, src, np.asarray(vals)).tolist()
        vals[0], vals[-1] = 1.0, 0.0
    return _torch.tensor(vals, dtype=_torch.float32), len(vals) - 1


def _to_rgb_uint8(tensor) -> np.ndarray:
    """Normalise a decoded image tensor into HxWx3 uint8.

    VAE decoders are not consistent about channel count or layout: Qwen-Image 2.1
    can come back as HWC with an alpha channel, and the tiled-VAE fallback has its
    own path. dstack-ing a 4-channel array with alpha produces 5 channels and PIL
    rejects it, so force HWC + RGB here.
    """
    arr = tensor.detach().float().clamp(0, 1).cpu().numpy()
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3:
        raise ValueError(f"解码结果维度异常：{arr.shape}")
    # CHW -> HWC when the channel axis is leading
    if arr.shape[0] in (1, 3, 4) and arr.shape[-1] not in (1, 3, 4):
        arr = arr.transpose(1, 2, 0)
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=2)
    if arr.shape[-1] < 3:
        raise ValueError(f"解码结果通道数不足：{arr.shape}")
    return (arr[..., :3] * 255.0).round().astype(np.uint8)



DEFAULT_SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0"


class StickerScriptParser:
    """一段文案 → 9 条提示词 + 9 条字幕。

    开头的角色描述会自动带进每一条提示词，所以只需要填一个框。
    """

    SLOTS = 9

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "brief": ("STRING", {"default": "", "multiline": True, "tooltip":
                    "开头写角色外形（发型/五官/服装/鞋/道具/渲染风格），"
                    "空一行后按「01｜标题 / 动作描述 / 配字：「字幕」」写条目。"
                    "编号前的文字会自动作为角色描述带进每条提示词。"}),
            }
        }

    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = ("captions",) + tuple(f"p{i}" for i in range(1, 10))
    FUNCTION = "run"
    CATEGORY = CATEGORY

    def run(self, brief):
        preamble, items = core.parse_brief(brief)
        if not items:
            raise ValueError("没有解析出任何表情包条目。检查编号行格式：01｜标题")

        captions = [it["caption"] for it in items[: self.SLOTS]]
        prompts = [core.build_keyframe_prompt(it["action"], 4, preamble)
                   for it in items[: self.SLOTS]]
        while len(captions) < self.SLOTS:
            captions.append(captions[-1])
        while len(prompts) < self.SLOTS:
            prompts.append(prompts[-1])

        print(f"[Sticker] 角色描述 {len(preamble)} 字；解析到 {len(items)} 条")
        for it in items[: self.SLOTS]:
            print(f"  {it['index']}｜{it['title']} -> 「{it['caption']}」")

        return tuple(["\n".join(captions)] + prompts)


class StickerAutoPack:
    """一个节点干完全部：解析文案 → 生成 → 合成 GIF → 打包 ZIP。

    逐条顺序生成，每条结束就释放中间张量，峰值内存远低于把九条分支铺在画布上。

    文本+参考图的编码走 ComfyUI 官方 nodes_qwen：Qwen-Image 2.1 的视觉 token 必须
    插在 tokenizer 给出的序列位置上，这套口径跟版本强相关，不能自己拼 conditioning。
    """

    @classmethod
    def INPUT_TYPES(cls):
        try:                      # 只在 ComfyUI 内可用，保留可测试性
            import comfy.samplers
            samplers = comfy.samplers.KSampler.SAMPLERS
        except Exception:
            samplers = ("euler",)

        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "ref_image": ("IMAGE",),
                "brief": ("STRING", {"default": "", "multiline": True, "tooltip":
                    "整段粘进来。开头几行写角色外形（发型/五官/服装/鞋/道具/渲染风格），"
                    "空一行后按「01｜标题」+「动作描述」+「配字：「字幕」」写每条。"
                    "开头的角色描述会自动带进每一条生成提示词，只需填这一个框。"}),
                "cells": ("INT", {"default": 4, "min": 2, "max": 6, "tooltip":
                    "一条动作拆成几个关键姿势。4 最自然；3 快 25%，动作连贯度略降。"}),
                "width": ("INT", {"default": 1280, "min": 1024, "max": 2048, "step": 64, "tooltip":
                    "单张精灵图的宽度，会被 cells 等分。1280 比 1536 省约 17% 时间，成品几乎无差。"}),
                "height": ("INT", {"default": 1024, "min": 512, "max": 2048, "step": 64, "tooltip":
                    "单张精灵图的高度。1024 给全身姿势留足纵向空间，不建议低于 768。"}),
                "ref_resolution": ("INT", {"default": 1024, "min": 512, "max": 1536, "step": 64, "tooltip":
                    "参考图缩放到的边长。调大能让五官和服装细节更准，代价是每条编码更慢。"}),
                "sampler_name": (samplers, {"tooltip": "turbo 模型配 euler；一般不用改。"}),
                "sigmas": ("STRING", {"default": DEFAULT_SIGMAS, "tooltip":
                    "逗号分隔的 sigma 序列，turbo 4-8 步专用。不要手动改，除非换模型。"}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1, "tooltip":
                    "turbo 模型必须为 1.0，调高会过曝。"}),
                "seed": ("INT", {"default": 1000, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "tooltip":
                    "第 i 条用「种子 + i」，固定它就能复现同一套表情包。"}),
                "font_path": ("STRING", {"default": "C:/Windows/Fonts/msyhbd.ttc", "tooltip":
                    "必须覆盖中文字形的 ttf/ttc。微软雅黑 Bold 最稳；换字体只影响字幕，不影响出图。"}),
                "canvas": ("INT", {"default": 512, "min": 128, "max": 1024, "step": 64, "tooltip":
                    "最终 GIF 的边长。微信/QQ 表情 512 足够，240 更省流量。"}),
                "frame_order": ("STRING", {"default": "0,1,2,3,2,1", "tooltip":
                    "按时间顺序排列的格子序号，逗号分隔，可重复。"
                    "「0,1,2,3,2,1」= 正放再倒放，首尾自然衔接成循环。"}),
                "durations": ("STRING", {"default": "320,180,180,600,180,180", "tooltip":
                    "每一帧的停留毫秒数，与 frame_order 一一对应，自动对齐到 20 的倍数。"
                    "总时长 = 各项之和。"}),
                "pack_name": ("STRING", {"default": "表情包", "tooltip":
                    "输出文件夹名，也是 zip 文件名。产物落在 ComfyUI/output/包名/ 下。"}),
                "save_mp4": ("BOOLEAN", {"default": False, "tooltip":
                    "额外为每张 GIF 生成一个 mp4。默认关：zip 里不含 mp4，开着只会让输出文件夹多一倍文件。"}),
                "steps": ("INT", {"default": 6, "min": 2, "max": 12, "tooltip":
                    "实际采样步数。会把 sigmas 曲线按这个步数重采样。"
                    "8 = 原始质量，6 = 推荐（快 25%，肉眼几乎无差），4 = 极速（快一半，细节略降）。"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("frames", "contact_sheet", "zip_path")
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, model, clip, vae, ref_image, brief, cells, width, height,
            ref_resolution, sampler_name, sigmas, cfg, seed, font_path, canvas,
            frame_order, durations, pack_name, save_mp4, steps):
        import time

        import folder_paths
        import torch as _torch

        import comfy.model_management
        import comfy.sample
        import comfy.samplers
        import comfy.utils
        import nodes as comfy_nodes
        from comfy_extras import nodes_qwen

        preamble, items = core.parse_brief(brief)
        if not items:
            raise ValueError("没有解析出任何表情包条目。检查编号行格式：01｜标题")

        # 旧版工作流的参数会整体错位一格（ComfyUI 给 seed 插了 control_after_generate 槽），
        # 这时 font_path 拿到的会是 canvas 的数字。给出可执行的提示，而不是一句 FileNotFound。
        looks_like_font = isinstance(font_path, str) and (
            os.sep in font_path or "/" in font_path
        ) and font_path.lower().endswith((".ttf", ".ttc", ".otf"))
        if not looks_like_font:
            raise ValueError(
                f"font_path 收到的不是字体路径（{font_path!r}）。\n"
                "这是旧版工作流的症状：ComfyUI 会给 seed 自动插入 control_after_generate 控件，"
                "旧文件没留这个槽位，导致 seed 之后的参数整体错位一格。\n"
                "解决：完全退出 ComfyUI 重启，重新打开 ① 贴纸表情包·一键整包，"
                "不要复用旧的标签页或旧收藏。"
            )
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"字幕字体不存在：{font_path}")

        encoder = getattr(nodes_qwen, "TextEncodeQwenImage21", None)
        if encoder is None:
            raise RuntimeError("当前 ComfyUI 没有 TextEncodeQwenImage21，无法做 Qwen-Image 2.1 参考图生成")

        order = _parse_ints(frame_order, [0, 1, 2, 3, 2, 1])
        dur = _parse_ints(durations, [80] * len(order))
        sig_tensor, eff_steps = _sigmas_tensor(sigmas, steps)
        sampler = comfy.samplers.sampler_object(sampler_name)
        ref = ref_image[:1] if ref_image.dim() == 4 else ref_image
        n = len(items)

        out_root = os.path.join(folder_paths.get_output_directory(), pack_name)
        os.makedirs(out_root, exist_ok=True)
        zip_path = os.path.join(out_root, f"{pack_name}.zip")

        print(f"[Sticker] 参数 cells={cells} size={width}x{height} canvas={canvas} "
              f"cfg={cfg} seed={seed} steps={eff_steps} font={os.path.basename(font_path)} "
              f"pack={pack_name} 条数={n}")

        pbar = comfy.utils.ProgressBar(max(1, eff_steps * n))
        t0 = time.time()

        # ---------------- 阶段 A：编码 ----------------
        # 9 条提示词一次性编完，文本编码器只加载一次。
        # 原来是「编码→采样→解码」逐条跑，每条都要把 8.9GB 的编码器换进来再换出去，
        # 9 条光模型换入换出就要多花一两分钟。
        conds = []
        for i, item in enumerate(items):
            comfy.model_management.throw_exception_if_processing_interrupted()
            prompt = core.build_keyframe_prompt(item["action"], cells, preamble)
            positive, negative, _ = encoder.execute(
                clip=clip, prompt=prompt, negative_prompt="", vae=vae,
                resolution=ref_resolution, images={"image_1": ref},
            ).result
            conds.append((positive, negative))
            print(f"[Sticker] 编码 {i + 1}/{n} {item['index']}｜{item['title']}")
        print(f"[Sticker] 阶段A 编码完成 {time.time() - t0:.0f}s")

        # 编码器退出显存，把位置让给 unet
        comfy.model_management.unload_all_models()
        comfy.model_management.soft_empty_cache()

        # ---------------- 阶段 B：采样 ----------------
        # 采样阶段只留 unet，不再和编码器抢显存。
        # 官方 SamplerCustom 的做法：取 samples 张量，并先对齐模型要求的通道数。
        latent = comfy_nodes.EmptyLatentImage().generate(width, height, 1)[0]
        base_latent = comfy.sample.fix_empty_latent_channels(model, latent["samples"])
        del latent

        latents = []
        for i, (positive, negative) in enumerate(conds):
            comfy.model_management.throw_exception_if_processing_interrupted()
            latent_samples = base_latent.clone()
            noise = comfy.sample.prepare_noise(latent_samples, seed + i)

            def _cb(step, _x0, _total, _i=i, **_kw):
                comfy.model_management.throw_exception_if_processing_interrupted()
                pbar.update_absolute(_i * eff_steps + step, max(1, eff_steps * n))

            samples = comfy.sample.sample_custom(
                model, noise, cfg, sampler, sig_tensor, positive, negative, latent_samples,
                noise_mask=None, callback=_cb, disable_pbar=True, seed=seed + i,
            )
            latents.append(samples.detach())
            del noise, latent_samples, samples
            print(f"[Sticker] 采样 {i + 1}/{n} 累计 {time.time() - t0:.0f}s")

        # conditioning 用完即弃，采样阶段结束后显存只留 unet 和 9 个小 latent
        del conds, base_latent

        # unet 退出，VAE 单独占显存 —— 这样解码能走「整张不切块」的快路径。
        # 之前 unet 还在显存里时解码必然 OOM，落到三遍分块平均，单张要 50 秒。
        comfy.model_management.unload_all_models()
        comfy.model_management.soft_empty_cache()
        print(f"[Sticker] 阶段B 采样完成 {time.time() - t0:.0f}s")

        # ---------------- 阶段 C：解码 + 合成 + 落盘 ----------------
        # 每张解完立刻写 GIF 并重建 zip，中途任何一张出错都不会让整包白跑。
        gif_paths, sheet_items, all_frames, failed = [], [], [], []
        for i, item in enumerate(items):
            comfy.model_management.throw_exception_if_processing_interrupted()
            try:
                image = vae.decode(latents[i])
                rgb = _to_rgb_uint8(image)
                del image
                keyed, alpha = core.key_green(rgb, 90, 40, 1, 0.7, 118, 62)
                keyed_img = Image.fromarray(np.dstack([keyed, alpha]), "RGBA")

                split = core.split_grid(keyed_img, cells, 1, 0)
                aligned = core.align_ground(split, 70, 0.06, None)
                frames = core.compose_frames(aligned, order, item["caption"], font_path, 0,
                                             "#2B2B2B", canvas)
            except Exception as exc:                       # noqa: BLE001
                failed.append((item["title"], repr(exc)))
                print(f"[Sticker] 第 {i + 1} 张失败，跳过：{exc!r}")
                latents[i] = None
                comfy.model_management.soft_empty_cache()
                continue

            latents[i] = None
            safe = "".join(ch for ch in item["caption"] if ch not in '\\/:*?"<>|').strip() or f"{i + 1:03d}"
            name = f"{i + 1:03d}-{safe}.gif"
            gif_paths.append((name, core.save_gif(frames, os.path.join(out_root, name), dur, 0)))
            if save_mp4:
                try:
                    core.save_mp4(frames, os.path.join(out_root, f"{i + 1:03d}-{safe}.mp4"), dur)
                except Exception as exc:                   # noqa: BLE001
                    print(f"[Sticker] mp4 生成失败（不影响主流程）：{exc!r}")

            all_frames.extend(frames)
            sheet_items.append((frames, item["caption"]))

            # 增量打包：每多一张就刷新一次 zip，中途中断也能拿到已完成的部分
            try:
                core.build_zip(gif_paths, zip_path)
            except Exception as exc:                       # noqa: BLE001
                print(f"[Sticker] 增量打包失败（最后会重试）：{exc!r}")
            print(f"[Sticker] {i + 1}/{n} {item['index']}｜{item['title']} -> 「{item['caption']}」")

        if not gif_paths:
            raise RuntimeError(f"所有条目都失败了：{failed}")

        # ---------------- 收尾：总览图 + 预览页 + 最终 zip ----------------
        contact = None
        contact_path = os.path.join(out_root, "_contact_sheet.png")
        try:
            contact = core.contact_sheet(sheet_items)
            contact.save(contact_path)
        except Exception as exc:                           # noqa: BLE001
            print(f"[Sticker] 总览图生成失败（不影响 zip）：{exc!r}")

        try:
            html = core.gallery_html(pack_name, [(t, p) for (p, _), (_, t) in zip(gif_paths, sheet_items)])
            extra = {"预览.html": html}
            core.build_zip(gif_paths, zip_path, extra=extra)
            if contact is not None:
                import zipfile

                with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
                    z.write(contact_path, "_contact_sheet.png")
        except Exception as exc:                           # noqa: BLE001
            print(f"[Sticker] 预览页写入失败（zip 内仍有 GIF）：{exc!r}")

        # ComfyUI 的 IMAGE 是 3 通道；RGBA 直接塞进去会让 PreviewImage 拿到 4 通道
        stack = _torch.cat([_torch.from_numpy(
            (np.asarray(f)[..., :3].astype(np.float32) / 255.0)[None, ...]) for f in all_frames], dim=0)
        if contact is None:
            contact = Image.new("RGB", (canvas, canvas), (236, 236, 236))
        contact_t = _torch.from_numpy(
            (np.asarray(contact.convert("RGB")).astype(np.float32) / 255.0)[None, ...])

        size_mb = os.path.getsize(zip_path) / 1048576 if os.path.isfile(zip_path) else 0
        print(f"[Sticker] 完成：{len(gif_paths)}/{n} 张，用时 {time.time() - t0:.0f}s -> {zip_path} "
              f"({size_mb:.1f} MB)")
        if failed:
            print(f"[Sticker] 失败条目：{failed}")
        return (stack, contact_t, zip_path)



class StickerSaveZip:
    """把整包 zip 落盘到 ComfyUI 输出目录，并登记为本次运行的产物。

    StickerAutoPack 已经在 output/<pack_name>/ 里写好了 zip，这个节点负责把它
    复制到一个固定的交付位置、校验完整性、并把最终路径回传给运行结果面板。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "zip_path": ("STRING", {"default": "", "tooltip":
                    "接 StickerAutoPack 的 zip_path 输出。留空会直接报错。"}),
                "folder": ("STRING", {"default": "", "tooltip":
                    "相对 ComfyUI/output 的子目录。留空 = 原地不动（zip 就留在生成它的那个文件夹里，"
                    "和 GIF 放在一起）。填了才会额外复制一份过去。"}),
                "overwrite": ("BOOLEAN", {"default": True, "tooltip":
                    "目标同名文件已存在时是否覆盖。关闭会自动加序号，不覆盖旧文件。"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, zip_path, folder, overwrite):
        import shutil
        import zipfile

        import folder_paths

        src = (zip_path or "").strip().strip('"')
        if not src:
            raise ValueError("zip_path 为空，请把 StickerAutoPack 的 zip_path 连到本节点")
        if not os.path.isfile(src):
            raise FileNotFoundError(f"找不到 zip 文件：{src}")

        if folder.strip():
            dest_dir = os.path.join(folder_paths.get_output_directory(), folder.strip())
            os.makedirs(dest_dir, exist_ok=True)
        else:
            # 留空 = 原地不动。之前默认落到 output 根目录，等于把 zip 从
            # output/包名/ 挪走，用户在那个文件夹里只看得到一堆 GIF。
            dest_dir = os.path.dirname(os.path.abspath(src))

        name = os.path.basename(src)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest) and not overwrite:
            stem, ext = os.path.splitext(name)
            i = 2
            while os.path.exists(os.path.join(dest_dir, f"{stem}-{i}{ext}")):
                i += 1
            dest = os.path.join(dest_dir, f"{stem}-{i}{ext}")

        if os.path.abspath(src) != os.path.abspath(dest):
            shutil.copy2(src, dest)

        try:
            with zipfile.ZipFile(dest) as z:
                bad = z.testzip()
                count = len(z.namelist())
            note = f"{count} 个条目，校验通过" if bad is None else f"条目 {bad} 损坏"
        except Exception as exc:                      # noqa: BLE001
            note = f"不是有效 zip：{exc}"

        print(f"[Sticker] 已保存 {dest}（{note}）")
        return {"ui": {"text": [f"{dest}  ({note})"]}, "result": (dest,)}




NODE_CLASS_MAPPINGS = {
    "StickerKeyGreen": StickerKeyGreen,
    "StickerSplitGrid": StickerSplitGrid,
    "StickerAlignGround": StickerAlignGround,
    "StickerCompose": StickerCompose,
    "StickerSaveGIF": StickerSaveGIF,
    "StickerPackBatch": StickerPackBatch,
    "StickerScriptParser": StickerScriptParser,
    "StickerAutoPack": StickerAutoPack,
    "StickerSaveZip": StickerSaveZip,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "StickerKeyGreen": "Sticker · 绿幕抠图",
    "StickerSplitGrid": "Sticker · 切分图集",
    "StickerAlignGround": "Sticker · 脚底对齐",
    "StickerCompose": "Sticker · 合成字幕帧",
    "StickerSaveGIF": "Sticker · 保存 GIF",
    "StickerPackBatch": "Sticker · 整包出图+ZIP",
    "StickerScriptParser": "Sticker · 脚本文案解析",
    "StickerAutoPack": "Sticker · 一键整包（生成+ZIP）",
    "StickerSaveZip": "Sticker · 保存 ZIP 文件",
}
