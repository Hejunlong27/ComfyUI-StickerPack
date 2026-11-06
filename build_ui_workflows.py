"""Emit real UI-format (canvas) workflows and validate them in a live ComfyUI.

The sidebar "open workflow" path only accepts {nodes, links}. API-format prompts
are rejected there even though the frontend can convert them elsewhere, so the
shipped workflows must be canvas graphs.

Every graph built here is checked twice:
  1. structurally, by graph_check()
  2. in the browser, by validate_ui.py -> app.loadGraphData() + graphToPrompt()

Run: python build_ui_workflows.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "workflows")

FONT = "C:/Windows/Fonts/msyhbd.ttc"
def _role_prompt_text():
    """Read the ready-to-paste system prompt out of the markdown so there is one
    source of truth; the canvas note shows exactly what the doc ships."""
    import re as _re
    path = os.path.join(HERE, "表情包设计角色提示词.md")
    raw = open(path, encoding="utf-8").read()
    m = _re.search(r"```text\n(.*?)\n```", raw, _re.S)
    return (m.group(1) if m else raw).strip()


ROLE_TEXT = _role_prompt_text()

SPEC_TEXT = (
    "文案规范\n"
    "─────\n"
    "【结构】\n"
    "01｜标题\n"
    "动作描述（一行或多行）\n"
    "配字：「字幕」\n\n"
    "【硬性规则】\n"
    "· 编号支持 01｜ 01| 01、 01. 01：，决定条数与顺序\n"
    "· 「配字」开头的行才是字幕，「」自动去掉\n"
    "· 没有配字行 → 用标题当字幕\n"
    "· 没有编号 → 按空行分块，再不行按行分\n"
    "· 一、二、三… 开头的章节标题自动跳过\n"
    "· 支持 3-9 条；不足 9 条重复最后一条，超过 9 条只用前 9 条\n\n"
    "【动作怎么写】\n"
    "· 只写看得见的身体动作和表情，不写心理活动\n"
    "· 一条 1-3 个动作节拍，模型会拆成 4 个关键姿势\n"
    "· 结尾给一个可停留的收尾状态，方便循环\n"
    "· ✓ 双手抱胸、身体转向一侧、再偷偷回头瞄一眼\n"
    "· ✗ 他感到有点不好意思\n\n"
    "【字幕】\n"
    "· 2-10 字最好读，长句会自动缩字号\n"
    "· 不要用 emoji，字体没有字形会变豆腐块\n\n"
    "【character 字段】\n"
    "参考图不能替代文字。写清年龄/脸型/肤色/发型/五官/上衣/裤子/鞋/配色/渲染风格。\n"
    "判断标准：换一个模型，光看这段文字能不能还原同一个人。"
)

NOTE_TEXT = (
    "用法（只需填一个框）\n"
    "1. 左边 ref 节点上传角色参考图\n"
    "2. 把整段提示词粘进 ④ SAMPLING 区节点的「提示词」框：\n"
    "   开头几行写角色外形（发型/五官/服装/鞋/道具/渲染风格）\n"
    "   空一行后按「01｜标题」「动作描述」「配字：「字幕」」写每条\n"
    "3. 点 Run，等约 12 分钟（steps=6 / width=1280 的默认档）\n"
    "4. 产物在 ComfyUI/output/包名/ 下，交付物是同目录的 包名.zip\n"
    "   跑完 ⑥ OUTPUT 区的节点会直接显示 zip 完整路径\n\n"
    "嫌慢：steps 改 4（再快 1/3，细节略降）、width 改 1024、cells 改 3\n"
    "想更好：steps 改 8（原始质量，慢 1/3）\n\n"
    "开头的角色描述会自动带进每一条生成提示词，不用分开填。\n"
    "每个参数把鼠标悬停上去都有说明。\n"
    "注意：绿幕背景不能换成透明背景，模型会把透明画成棋盘格，抠图会把白 T 恤一起抠掉。"
)
SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0"
DEFAULT_SIGMAS = SIGMAS
FRAME_ORDER = "0,1,2,3,2,1"
DURATIONS = "320,180,180,600,180,180"

# type -> (link inputs, outputs, widget names)
SPEC = {
    "UNETLoader": ([], [("MODEL", "MODEL")], ["unet_name", "weight_dtype"]),
    "CLIPLoader": ([], [("CLIP", "CLIP")], ["clip_name", "type", "device"]),
    "VAELoader": ([], [("VAE", "VAE")], ["vae_name"]),
    "LoadImage": ([], [("IMAGE", "IMAGE"), ("MASK", "MASK")], ["image", "upload"]),
    "LoraLoaderModelOnly": ([("model", "MODEL")], [("MODEL", "MODEL")], ["lora_name", "strength_model"]),
    "KSamplerSelect": ([], [("SAMPLER", "SAMPLER")], ["sampler_name"]),
    "ManualSigmas": ([], [("SIGMAS", "SIGMAS")], ["sigmas"]),
    "PrimitiveStringMultiline": ([], [("STRING", "STRING")], ["value"]),
    "EmptyLatentImage": ([], [("LATENT", "LATENT")], ["width", "height", "batch_size"]),
    "TextEncodeQwenImage21": (
        [("clip", "CLIP"), ("prompt", "STRING"), ("images.image_1", "IMAGE"), ("vae", "VAE")],
        [("positive", "CONDITIONING"), ("negative", "CONDITIONING"), ("latent", "LATENT")],
        ["prompt", "negative_prompt", "resolution"],
    ),
    "SamplerCustom": (
        [("model", "MODEL"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING"),
         ("sampler", "SAMPLER"), ("sigmas", "SIGMAS"), ("latent_image", "LATENT")],
        [("output", "LATENT"), ("denoised_output", "LATENT")],
        ["add_noise", "noise_seed", "control_after_generate", "cfg"],
    ),
    "VAEDecode": ([("samples", "LATENT"), ("vae", "VAE")], [("IMAGE", "IMAGE")], []),
    "ImageBatch": ([("image1", "IMAGE"), ("image2", "IMAGE")], [("IMAGE", "IMAGE")], []),
    "PreviewImage": ([("images", "IMAGE")], [("images", "IMAGE")], []),
    "StickerPackBatch": (
        [("image", "IMAGE")],
        [("frames", "IMAGE"), ("contact_sheet", "IMAGE"), ("zip_path", "STRING")],
        ["captions", "font_path", "font_index", "ink", "canvas", "cols", "rows", "pad",
         "band_ratio", "lifts", "blank_wm_w", "blank_wm_h", "frame_order", "durations",
         "loop", "pack_name", "save_mp4"],
    ),
    "StickerKeyGreen": (
        [("image", "IMAGE")],
        [("image", "IMAGE"), ("alpha", "MASK")],
        ["min_green", "dominance", "erode", "feather", "blank_wm_w", "blank_wm_h"],
    ),
    "StickerSplitGrid": (
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("image", "IMAGE"), ("alpha", "MASK")],
        ["cols", "rows", "row_index"],
    ),
    "StickerAlignGround": (
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("image", "IMAGE"), ("alpha", "MASK")],
        ["pad", "band_ratio", "lifts"],
    ),
    "StickerCompose": (
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("frames", "IMAGE"), ("alpha", "MASK")],
        ["text", "font_path", "font_index", "ink", "canvas", "frame_order"],
    ),
    "Note": ([], [], ["text"]),
    "StickerAutoPack": (
        [("model", "MODEL"), ("clip", "CLIP"), ("vae", "VAE"), ("ref_image", "IMAGE")],
        [("frames", "IMAGE"), ("contact_sheet", "IMAGE"), ("zip_path", "STRING")],
        ["brief", "cells", "width", "height", "ref_resolution", "sampler_name", "sigmas",
         "cfg", "seed", "font_path", "canvas", "frame_order", "durations", "pack_name",
         "save_mp4", "steps"],
    ),
    "PreviewAny": ([("source", "*")], [], []),
    "StickerSaveZip": ([], [("saved_path", "STRING")], ["zip_path", "folder", "overwrite"]),
    "StickerScriptParser": (
        [],
        [("captions", "STRING")] + [(f"p{i}", "STRING") for i in range(1, 10)],
        ["brief"],
    ),
    "StickerSaveGIF": (
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("path", "STRING")],
        ["filename_prefix", "durations", "loop", "save_mp4"],
    ),
}


SEED_NAMES = ("seed", "noise_seed")


def _with_seed_control(widget_names, values):
    """ComfyUI injects a control_after_generate widget right after any seed input.

    It occupies a slot in widgets_values, so the stored array needs an extra
    entry there - otherwise every following parameter silently shifts by one.
    """
    out = list(values)
    for i, name in enumerate(widget_names):
        if name in SEED_NAMES:
            out.insert(i + 1, "randomize")
            break
    return out


class Graph:
    def __init__(self):
        self.nodes = []
        self.links = []
        self._link_id = 0
        self._by_key = {}

    def add(self, key, ntype, widgets, pos, size=None, widget_inputs=()):
        """widget_inputs: widget names exposed as input sockets (ComfyUI converts
        a widget to an input by adding an entry that carries {"widget": {...}})."""
        spec = SPEC[ntype]
        node = {
            "id": len(self.nodes) + 1,
            "type": ntype,
            "pos": list(pos),
            "size": list(size) if size else [320, 110 + 22 * len(spec[2])],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in spec[0]]
                      + [{"name": w, "type": "STRING", "widget": {"name": w}, "link": None}
                         for w in widget_inputs],
            "outputs": [{"name": n, "type": t, "links": [], "slot_index": i}
                        for i, (n, t) in enumerate(spec[1])],
            "properties": {"Node name for S&R": ntype},
            "widgets_values": _with_seed_control(spec[2], widgets),
        }
        self.nodes.append(node)
        self._by_key[key] = node
        return node

    def node(self, key):
        return self._by_key[key]

    def link(self, src_key, out_slot, dst_key, in_name):
        src = self._by_key[src_key]
        dst = self._by_key[dst_key]
        slot = next(i for i, x in enumerate(dst["inputs"]) if x["name"] == in_name)
        dtype = src["outputs"][out_slot]["type"]
        want = dst["inputs"][slot]["type"]
        assert dtype == want or "*" in (dtype, want), \
            f"{src['type']}.{out_slot} is {dtype}, {dst['type']}.{in_name} wants {want}"
        self._link_id += 1
        lid = self._link_id
        self.links.append([lid, src["id"], out_slot, dst["id"], slot, dtype])
        src["outputs"][out_slot]["links"].append(lid)
        dst["inputs"][slot]["link"] = lid

    def dump(self, title, extra_groups=None):
        return {
            "last_node_id": max(n["id"] for n in self.nodes),
            "last_link_id": self._link_id,
            "nodes": self.nodes,
            "links": self.links,
            "groups": extra_groups or [],
            "config": {},
            "extra": {"ds": {"scale": 0.42, "offset": [40, 40]}},
            "version": 0.4,
        }


def graph_check(wf):
    ids = {n["id"] for n in wf["nodes"]}
    assert len(ids) == len(wf["nodes"])
    seen = set()
    for lid, src, sslot, dst, dslot, dtype in wf["links"]:
        assert src in ids and dst in ids, f"link {lid} dangling"
        assert lid not in seen, f"duplicate link {lid}"
        seen.add(lid)
        s = next(n for n in wf["nodes"] if n["id"] == src)
        d = next(n for n in wf["nodes"] if n["id"] == dst)
        assert lid in s["outputs"][sslot]["links"], f"link {lid} not on origin"
        assert d["inputs"][dslot]["link"] == lid, f"link {lid} not on target"
        st, wt = s["outputs"][sslot]["type"], d["inputs"][dslot]["type"]
        assert st == wt or "*" in (st, wt)
    for n in wf["nodes"]:
        for i in n["inputs"]:
            if i["link"] is not None:
                assert i["link"] in seen
        declared = SPEC[n["type"]][2]
        extra = 1 if any(w in SEED_NAMES for w in declared) else 0
        assert len(n["widgets_values"]) == len(declared) + extra, \
            f"{n['type']} has {len(n['widgets_values'])} widgets, expected {len(declared) + extra}"
    assert wf["last_link_id"] == len(wf["links"])
    assert wf["last_node_id"] == max(ids)


# ------------------------------------------------------------------ builders

def _sticker_specs():
    """Import the sticker table from the API builder so both stay in sync."""
    import build_workflows as bw
    return bw.STICKERS, bw._prompt


def build_full9_ui():
    g = Graph()
    g.add("note", "Note", [NOTE_TEXT], (140, 40), (860, 470))

    g.add("unet", "UNETLoader", ["qwen_image_2.1_turbo_int8_convrot.safetensors", "default"], (140, 620))
    g.add("clip", "CLIPLoader", ["qwen3vl_8b_int8_convrot.safetensors", "qwen_image", "default"], (140, 780))
    g.add("vae", "VAELoader", ["qwen_image_2.1_vae_bf16.safetensors"], (140, 960))
    g.add("ref", "LoadImage", ["ref.png", "image"], (140, 1100))
    g.add("sampler_sel", "KSamplerSelect", ["euler"], (140, 1480))
    g.add("sigmas", "ManualSigmas", [SIGMAS], (140, 1590))
    g.add("lora", "LoraLoaderModelOnly", [LORA_NAME, 0.0], (140, 1720), (330, 190))
    g.link("unet", 0, "lora", "model")

    g.add("spec", "Note", [SPEC_TEXT], (140, 1760), (430, 560))
    g.add("role", "Note", [ROLE_TEXT], (600, 980), (620, 720))

    # One brief in, nine prompts + nine captions out.
    g.add("script", "StickerScriptParser", [""], (600, 1760), (470, 380))

    y0, step = 1800, 400
    decodes = []
    for i in range(9):
        y = y0 + i * step
        g.add(f"lat{i}", "EmptyLatentImage", [1536, 1024, 1], (1120, y))
        g.add(f"te{i}", "TextEncodeQwenImage21", ["", "", 1024], (1520, y))
        g.add(f"s{i}", "SamplerCustom", [True, 1000 + i, "fixed", 1], (1900, y))
        g.add(f"d{i}", "VAEDecode", [], (2280, y))

        g.link("clip", 0, f"te{i}", "clip")
        g.link("ref", 0, f"te{i}", "images.image_1")
        g.link("vae", 0, f"te{i}", "vae")
        g.link("script", i + 1, f"te{i}", "prompt")
        g.link("lora", 0, f"s{i}", "model")
        g.link(f"te{i}", 0, f"s{i}", "positive")
        g.link(f"te{i}", 1, f"s{i}", "negative")
        g.link("sampler_sel", 0, f"s{i}", "sampler")
        g.link("sigmas", 0, f"s{i}", "sigmas")
        g.link(f"lat{i}", 0, f"s{i}", "latent_image")
        g.link(f"s{i}", 0, f"d{i}", "samples")
        g.link("vae", 0, f"d{i}", "vae")
        decodes.append(f"d{i}")

    prev = decodes[0]
    for i, key in enumerate(decodes[1:]):
        g.add(f"b{i}", "ImageBatch", [], (2660, 1800 + i * 260))
        g.link(prev, 0, f"b{i}", "image1")
        g.link(key, 0, f"b{i}", "image2")
        prev = f"b{i}"

    g.add("pack", "StickerPackBatch", [
        "", FONT, 0, "#2B2B2B", 512, 4, 1, 70, 0.06, "", 118, 62,
        FRAME_ORDER, DURATIONS, 0, "表情包", True], (3040, 2120),
        widget_inputs=("captions",))
    g.link(prev, 0, "pack", "image")
    g.link("script", 0, "pack", "captions")

    g.add("pv_frames", "PreviewImage", [], (3420, 2020))
    g.add("pv_sheet", "PreviewImage", [], (3420, 2380))
    g.link("pack", 0, "pv_frames", "images")
    g.link("pack", 1, "pv_sheet", "images")
    g.add("zip_out", "StickerSaveZip", ["", "", True], (3420, 2760), (360, 210),
          widget_inputs=("zip_path",))
    g.add("zip_show", "PreviewAny", [], (3420, 3010), (360, 120))
    g.link("pack", 2, "zip_out", "zip_path")
    g.link("pack", 2, "zip_show", "source")

    groups = [
        {"title": "用法说明",
         "bounding": [120, 20, 920, 520], "color": "#B58B00", "font_size": 26, "flags": {}},
        {"title": "② MODELS + ③ LORAS · 模型加载（本地 Qwen-Image 2.1 turbo）",
         "bounding": [120, 570, 340, 1380], "color": "#4A7C59", "font_size": 22, "flags": {}},
        {"title": "① INPUT · 文案规范 + 粘贴框（script / character）",
         "bounding": [120, 1710, 990, 640], "color": "#A0522D", "font_size": 22, "flags": {}},
        {"title": "① INPUT · 角色提示词（整段复制给大模型）",
         "bounding": [580, 930, 660, 800], "color": "#7B4F9D", "font_size": 22, "flags": {}},
        {"title": "④ SAMPLING · 9 条生成分支，每条产出 4 个连续姿势",
         "bounding": [1100, 1760, 1600, 3620], "color": "#8C6D31", "font_size": 22, "flags": {}},
        {"title": "⑤ PREVIEWS + ⑥ OUTPUT · 合并 → 合成 → GIF + 保存 ZIP",
         "bounding": [2640, 1760, 1200, 1220], "color": "#2E7D32", "font_size": 22, "flags": {}},
    ]
    return g.dump("表情包·一键", groups)


def build_pack_only_ui(n=9):
    stickers, _ = _sticker_specs()
    g = Graph()
    keys = []
    for i in range(n):
        key = f"a{i}"
        g.add(key, "LoadImage", [f"atlas_{i + 1:02d}.png", "image"], (40, 40 + i * 360))
        keys.append(key)

    prev = keys[0]
    for i, key in enumerate(keys[1:]):
        g.add(f"b{i}", "ImageBatch", [], (420, 40 + i * 380))
        g.link(prev, 0, f"b{i}", "image1")
        g.link(key, 0, f"b{i}", "image2")
        prev = f"b{i}"

    g.add("pack", "StickerPackBatch", [
        "\n".join(c for c, *_ in stickers[:n]), FONT, 0, "#2B2B2B", 512, 4, 1, 70, 0.06, "",
        118, 62, FRAME_ORDER, DURATIONS, 0, "atlas-pack", True], (820, 300))
    g.link(prev, 0, "pack", "image")
    g.add("pv_frames", "PreviewImage", [], (1180, 220))
    g.add("pv_sheet", "PreviewImage", [], (1180, 560))
    g.link("pack", 0, "pv_frames", "images")
    g.link("pack", 1, "pv_sheet", "images")
    return g.dump("atlas-pack")


LORA_NAME = "Qwen-Image-2.1-viggle-turbo-4step-lora-r64.safetensors"

OUTPUT_NOTE = (
    "产物路径\n"
    "─────\n"
    "ComfyUI/output/表情包/\n"
    "  表情包.zip      ← 交付物（9 张 GIF + 预览页 + 总览图）\n"
    "  001-字幕.gif\n"
    "  ...\n"
    "  _contact_sheet.png\n"
    "  预览.html\n\n"
    "改 pack_name 就换文件夹名。\n"
    "上面那个节点跑完会显示 zip 的完整路径；\n"
    "folder 留空 = 原地不动，填了才额外复制一份。"
)

INPUT_NOTE = (
    "INPUT 区只放参考图。\n"
    "─────\n"
    "整段提示词在右边\n"
    "④ SAMPLING 区的「提示词」框里，\n"
    "开头写角色外形，空一行后写条目：\n\n"
    "【角色】发型/五官/服装/鞋/道具/风格\n\n"
    "01｜标题\n"
    "动作描述\n"
    "配字：「字幕」\n\n"
    "想先看解析结果：\n"
    "拖一个「Sticker · 脚本文案解析」\n"
    "接 PreviewAny 即可。"
)


def build_autopack_ui():
    """Zoned layout: INPUT | MODELS | LORAS | SAMPLING | PREVIEWS | OUTPUT."""
    g = Graph()
    g.add("note", "Note", [NOTE_TEXT], (120, 20), (900, 480))

    # ① INPUT
    g.add("ref", "LoadImage", ["ref.png", "image"], (140, 660), (320, 380))
    g.add("in_note", "Note", [INPUT_NOTE], (140, 1090), (330, 400))

    # ② MODELS
    g.add("unet", "UNETLoader", ["qwen_image_2.1_turbo_int8_convrot.safetensors", "default"], (580, 640))
    g.add("clip", "CLIPLoader", ["qwen3vl_8b_int8_convrot.safetensors", "qwen_image", "default"], (580, 810))
    g.add("vae", "VAELoader", ["qwen_image_2.1_vae_bf16.safetensors"], (580, 990))

    # ③ LORAS (strength 0 = no-op until the user wants it)
    g.add("lora", "LoraLoaderModelOnly", [LORA_NAME, 0.0], (1020, 660), (330, 190))

    # ④ SAMPLING + 文案 + 合成 + 打包
    g.add("pack", "StickerAutoPack", [
        "", 4, 1280, 1024, 1024, "euler", DEFAULT_SIGMAS, 1.0, 1000,
        "C:/Windows/Fonts/msyhbd.ttc", 512, "0,1,2,3,2,1", "320,180,180,600,180,180",
        "表情包", False, 6], (1460, 640), (560, 800))

    # ⑤ PREVIEWS
    g.add("pv_frames", "PreviewImage", [], (2060, 640), (340, 400))
    g.add("pv_sheet", "PreviewImage", [], (2060, 1120), (340, 400))

    # ⑥ OUTPUT
    g.add("zip_out", "StickerSaveZip", ["", "", True], (2460, 640), (360, 210),
          widget_inputs=("zip_path",))
    g.add("zip_show", "PreviewAny", [], (2460, 900), (360, 120))
    g.add("out_note", "Note", [OUTPUT_NOTE], (2460, 1060), (360, 340))

    g.link("unet", 0, "lora", "model")
    g.link("lora", 0, "pack", "model")
    g.link("clip", 0, "pack", "clip")
    g.link("vae", 0, "pack", "vae")
    g.link("ref", 0, "pack", "ref_image")
    g.link("pack", 0, "pv_frames", "images")
    g.link("pack", 1, "pv_sheet", "images")
    g.link("pack", 2, "zip_out", "zip_path")
    g.link("pack", 2, "zip_show", "source")

    groups = [
        {"title": "用法说明", "bounding": [100, 0, 940, 520],
         "color": "#B58B00", "font_size": 26, "flags": {}},
        {"title": "① INPUT · 角色参考图", "bounding": [120, 590, 380, 940],
         "color": "#3f789e", "font_size": 26, "flags": {}},
        {"title": "② MODELS · 模型加载", "bounding": [560, 590, 400, 600],
         "color": "#4A7C59", "font_size": 26, "flags": {}},
        {"title": "③ LORAS · 可选风格 LoRA（强度 0 = 不生效）", "bounding": [1000, 590, 380, 320],
         "color": "#8C6D31", "font_size": 24, "flags": {}},
        {"title": "④ SAMPLING · 提示词 + 采样 + 合成 + 打包", "bounding": [1440, 590, 600, 860],
         "color": "#A0522D", "font_size": 26, "flags": {}},
        {"title": "⑤ PREVIEWS · 预览", "bounding": [2040, 590, 380, 980],
         "color": "#5B6FA8", "font_size": 26, "flags": {}},
        {"title": "⑥ OUTPUT · 保存 ZIP 文件 + 路径回显 + 产物说明", "bounding": [2440, 590, 420, 860],
         "color": "#2E7D32", "font_size": 26, "flags": {}},
    ]
    return g.dump("表情包·一键整包", groups)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, builder in (("sticker_autopack_ui.json", build_autopack_ui),
                          ("sticker_pack_9qwen_ui.json", build_full9_ui),
                          ("sticker_pack_from_atlas_ui.json", build_pack_only_ui)):
        wf = builder()
        graph_check(wf)
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
        print(f"{name}: {len(wf['nodes'])} nodes, {len(wf['links'])} links, graph_check OK")
