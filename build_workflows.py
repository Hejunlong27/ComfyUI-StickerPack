"""Generate the two shipped workflows from one declarative spec.

Emits:
  workflows/sticker_postprocess_ui.json  - UI graph, only StickerPack nodes + LoadImage
  workflows/sticker_full_qwen_api.json   - API graph, local Qwen-Image 2.1 + StickerPack nodes

Run: python build_workflows.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "workflows")

FONT = "C:/Windows/Fonts/msyhbd.ttc"
BRIEF_SKELETON = (
    "【角色】写清角色外形：渲染风格、脸型、发型、肤色五官、上衣、裤子、鞋、标志性道具\n\n"
    "01｜示例标题\n动作描述：只写看得见的身体动作和表情。\n配字：「示例字幕」"
)
PROMPT = (
    "角色关键帧序列图，4 列 1 行，共 4 格横向并排，按时间顺序从左到右。"
    "画面中的角色必须与参考图完全一致：3D 渲染风格的动漫 Q 版少年，蓬松凌乱的黑色碎发、"
    "精致的五官、白皙皮肤、宽松纯白 T 恤、黑色阔腿九分裤配浅灰色翻边、黑白帆布高帮鞋。"
    "高质量 3D 动画电影质感，柔和的皮克斯式光影，干净的棚拍布光。\n"
    "严格对齐：4 格中角色的头部中心、头部大小、身体比例、机位、镜头、光线与躯干基线必须完全一致，"
    "双脚始终踩在同一条地平线上。不要缩放、平移或改变角色大小。只改变指定的一只手与面部表情。"
    "每格都必须完整显示角色，头发、手肘、手指都不能被裁切，格与格之间留出宽阔的空白间隔。\n"
    "背景：纯色绿幕（#00FF00），完全均匀，没有渐变、没有地面、没有阴影、没有反射、"
    "没有边框、没有网格线、没有文字、没有水印。\n"
    "姿势从左到右：\n"
    "第 1 格：正面站立，双臂自然垂在身侧，表情平静，正常睁眼。\n"
    "第 2 格：一边眉毛挑起，嘴角上扬露出坏笑。\n"
    "第 3 格：单眼眨眼，另一只眼睁开，坏笑，一只手开始抬向胸前。\n"
    "第 4 格：保持眨眼与坏笑，手抬到脸颊旁比出 OK 手势。"
)


# --------------------------------------------------------------------- UI graph

def build_ui():
    """Only nodes this pack ships, so the widget order is fully under our control."""
    nodes, links = [], []
    link_id = [0]

    def add(node_id, ntype, pos, size, widgets, inputs, outputs):
        nodes.append({
            "id": node_id,
            "type": ntype,
            "pos": list(pos),
            "size": list(size),
            "flags": {},
            "order": len(nodes),
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in inputs],
            "outputs": [{"name": n, "type": t, "links": [], "slot_index": i}
                        for i, (n, t) in enumerate(outputs)],
            "properties": {"Node name for S&R": ntype},
            "widgets_values": widgets,
        })
        return nodes[-1]

    def connect(src_id, src_slot, dst_id, dst_slot, dtype):
        link_id[0] += 1
        lid = link_id[0]
        links.append([lid, src_id, src_slot, dst_id, dst_slot, dtype])
        src = next(n for n in nodes if n["id"] == src_id)
        dst = next(n for n in nodes if n["id"] == dst_id)
        src["outputs"][src_slot]["links"].append(lid)
        dst["inputs"][dst_slot]["link"] = lid
        return lid

    add(1, "LoadImage", (40, 300), (320, 340),
        ["atlas.png", "image"], [], [("IMAGE", "IMAGE"), ("MASK", "MASK")])
    add(2, "StickerKeyGreen", (420, 300), (330, 210),
        [90, 40, 1, 0.7, 118, 62],
        [("image", "IMAGE")], [("image", "IMAGE"), ("alpha", "MASK")])
    add(3, "StickerSplitGrid", (800, 300), (320, 170),
        [4, 1, 0],
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("image", "IMAGE"), ("alpha", "MASK")])
    add(4, "StickerAlignGround", (1170, 300), (320, 160),
        [70, 0.06, ""],
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("image", "IMAGE"), ("alpha", "MASK")])
    add(5, "StickerCompose", (1540, 300), (350, 250),
        ["今天也要开心！", FONT, 0, "#2B2B2B", 512, "0,1,2,3,2,1"],
        [("image", "IMAGE"), ("alpha", "MASK")],
        [("frames", "IMAGE"), ("alpha", "MASK")])
    add(6, "StickerSaveGIF", (1940, 300), (340, 200),
        ["sticker/001-test", "320,180,180,600,180,180", 0, False],
        [("image", "IMAGE"), ("alpha", "MASK")], [("path", "STRING")])
    add(7, "PreviewImage", (2330, 300), (300, 300),
        [], [("images", "IMAGE")], [])

    connect(1, 0, 2, 0, "IMAGE")
    connect(2, 0, 3, 0, "IMAGE")
    connect(2, 1, 3, 1, "MASK")
    connect(3, 0, 4, 0, "IMAGE")
    connect(3, 1, 4, 1, "MASK")
    connect(4, 0, 5, 0, "IMAGE")
    connect(4, 1, 5, 1, "MASK")
    connect(5, 0, 6, 0, "IMAGE")
    connect(5, 1, 6, 1, "MASK")
    connect(5, 0, 7, 0, "IMAGE")

    return {
        "last_node_id": 7,
        "last_link_id": link_id[0],
        "nodes": nodes,
        "links": links,
        "groups": [{
            "title": "贴纸后处理链 · 绿幕抠图 → 切分 → 脚底对齐 → 合成字幕 → 存 GIF",
            "bounding": [10, 180, 2650, 500],
            "color": "#3f789e",
            "font_size": 24,
            "flags": {},
        }],
        "config": {},
        "extra": {"ds": {"scale": 0.62, "offset": [40, 120]}},
        "version": 0.4,
    }


# -------------------------------------------------------------------- API graph

def build_api():
    """Reuse the node set proven in qwen_image_21_turbo_i2i, then the sticker chain."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors",
            "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors",
            "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
        "5": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": PROMPT}},
        "6": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "prompt": ["5", 0], "negative_prompt": "", "resolution": 1024,
            "clip": ["2", 0], "images.image_1": ["4", 0], "vae": ["3", 0]}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1536, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "ManualSigmas", "inputs": {
            "sigmas": "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0"}},
        "10": {"class_type": "SamplerCustom", "inputs": {
            "add_noise": True, "noise_seed": 42, "cfg": 1,
            "model": ["1", 0], "positive": ["6", 0], "negative": ["6", 1],
            "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["7", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "StickerKeyGreen", "inputs": {
            "image": ["11", 0], "min_green": 90, "dominance": 40, "erode": 1,
            "feather": 0.7, "blank_wm_w": 118, "blank_wm_h": 62}},
        "13": {"class_type": "StickerSplitGrid", "inputs": {
            "image": ["12", 0], "alpha": ["12", 1], "cols": 4, "rows": 1, "row_index": 0}},
        "14": {"class_type": "StickerAlignGround", "inputs": {
            "image": ["13", 0], "alpha": ["13", 1], "pad": 70,
            "band_ratio": 0.06, "lifts": ""}},
        "15": {"class_type": "StickerCompose", "inputs": {
            "image": ["14", 0], "alpha": ["14", 1], "text": "懂的都懂",
            "font_path": FONT, "font_index": 0, "ink": "#2B2B2B", "canvas": 512,
            "frame_order": "0,1,2,3,2,1"}},
        "16": {"class_type": "StickerSaveGIF", "inputs": {
            "image": ["15", 0], "alpha": ["15", 1],
            "filename_prefix": "sticker/006-懂的都懂",
            "durations": "320,180,180,600,180,180", "loop": 0, "save_mp4": False}},
    }


# ------------------------------------------------------- one-click pack (API)

STICKERS = [
    ("无所谓啦～", "第 1 格：正面站立，双臂自然垂在身侧，表情平静，正常睁眼。",
     "第 2 格：半眯眼，右手抬到胸前摊开手掌，头开始歪。",
     "第 3 格：手掌推得更外，嘴角上扬成淡笑，头歪约 15 度。",
     "第 4 格：保持摊手，肩膀微耸，头歪约 20 度，一脸无所谓。"),
    ("真的假的？！", "第 1 格：平静，正常睁眼，单手拿着冰咖啡杯在胸前。",
     "第 2 格：眼睛睁大，眉毛抬高，嘴开始张开。",
     "第 3 格：瞪眼张嘴，身体后仰，咖啡杯倾斜。",
     "第 4 格：最大震惊，眼睛瞪到最大，身体后仰更多，咖啡明显晃动。"),
    ("让我再睡五分钟……", "第 1 格：站立，眼皮下垂，头微低，双臂下垂。",
     "第 2 格：一只手抬到眼睛旁揉眼，嘴开始张开。",
     "第 3 格：张大嘴打哈欠，手还在揉眼，头更低，肩塌下。",
     "第 4 格：手放回身侧，头低到最低，肩完全塌下，闭眼疲惫。"),
    ("喝一口，活过来。", "第 1 格：正常表情，冰咖啡杯在胸前，吸管朝上。",
     "第 2 格：把杯子抬到嘴边，吸管碰到嘴唇，眼睛还睁着。",
     "第 3 格：叼着吸管吸一大口，闭眼享受，头微仰。",
     "第 4 格：杯子放回胸前，仍闭着眼，露出满足的微笑，头微仰。"),
    ("才、才没有呢！", "第 1 格：正面站立，正常表情，看着镜头，双臂垂在身侧。",
     "第 2 格：眼神往旁边躲，脸颊开始泛红，嘴微抿。",
     "第 3 格：脸红明显，一只手挠后脑，身体侧转，不好意思地笑。",
     "第 4 格：脸红更深，手还在后脑，头低下去，身体侧转更多。"),
    ("懂的都懂", "第 1 格：平静，双眼正常睁开，双臂垂在身侧。",
     "第 2 格：一边眉毛挑起，嘴角上扬露出坏笑，眼睛还睁着。",
     "第 3 格：单眼眨眼，另一只眼睁开，坏笑，手开始抬向胸前。",
     "第 4 格：保持眨眼坏笑，手抬到脸颊旁比出 OK 手势。"),
    ("哼！不理你了！", "第 1 格：正面站立，正常表情，看着镜头，双臂垂在身侧。",
     "第 2 格：鼓腮，皱眉，嘟嘴，双臂开始抱向胸前。",
     "第 3 格：鼓腮皱眉，双手紧紧抱胸，身体转向一侧。",
     "第 4 格：仍抱胸侧身，但头转回来看向镜头，嘟嘴偷瞄。"),
    ("我真的会谢……", "第 1 格：双手抱着冰咖啡杯贴在胸前，正常表情，头平视。",
     "第 2 格：嘴角下垂，眼睛开始泛泪光，头开始低下去。",
     "第 3 格：眼睛含泪，委屈嘟嘴，头低下去，脸颊上一滴泪。",
     "第 4 格：头低到最低，闭眼含泪，嘴角下垂，一滴泪滑到下巴。"),
    ("今天也要开心！", "第 1 格：温柔的微笑，双臂垂在身侧，咖啡杯拿得很低。",
     "第 2 格：张大嘴灿烂笑，眼睛弯成月牙，一只手把咖啡举到肩高。",
     "第 3 格：同样月牙笑眼，咖啡举高，另一只手在脸旁比耶，站在地上。",
     "第 4 格：同样表情与手势，双脚离地跳起，膝盖微屈，一只脚后跟踢起。"),
]

CHAR = (
    "画面中的角色必须与参考图完全一致：3D 渲染风格的动漫 Q 版少年，蓬松凌乱的黑色碎发、"
    "精致的五官、白皙皮肤、宽松纯白 T 恤、黑色阔腿九分裤配浅灰色翻边、黑白帆布高帮鞋。"
    "高质量 3D 动画电影质感，柔和的皮克斯式光影，干净的棚拍布光。"
)


def _prompt(poses):
    return (
        "角色关键帧序列图，4 列 1 行，共 4 格横向并排，按时间顺序从左到右。"
        + CHAR
        + "\n严格对齐：4 格中角色的头部中心、头部大小、身体比例、机位、镜头、光线与躯干基线必须完全一致，"
        "双脚始终踩在同一条地平线上。不要缩放、平移或改变角色大小。只改变指定的一只手与面部表情。"
        "每格都必须完整显示角色，头发、手肘、手指都不能被裁切，格与格之间留出宽阔的空白间隔。"
        "\n背景：纯色绿幕（#00FF00），完全均匀，没有渐变、没有地面、没有阴影、没有反射、"
        "没有边框、没有网格线、没有文字、没有水印。\n姿势从左到右：\n"
        + "\n".join(poses)
    )


def build_full9_api():
    """One run: paste a brief, generate 9 pose rows, pack, zip, preview."""
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors",
            "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors",
            "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
        "5": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "6": {"class_type": "ManualSigmas", "inputs": {
            "sigmas": "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0"}},
        "7": {"class_type": "StickerScriptParser", "inputs": {"提示词": BRIEF_SKELETON}},
    }

    decode_ids = []
    for b in range(9):
        base = 100 + b * 10
        tid, lid, sid, did = (str(base + i) for i in range(4))
        wf[tid] = {"class_type": "TextEncodeQwenImage21", "inputs": {
            "prompt": ["7", b + 1], "negative_prompt": "", "resolution": 1024,
            "clip": ["2", 0], "images.image_1": ["4", 0], "vae": ["3", 0]}}
        wf[lid] = {"class_type": "EmptyLatentImage", "inputs": {
            "width": 1536, "height": 1024, "batch_size": 1}}
        wf[sid] = {"class_type": "SamplerCustom", "inputs": {
            "add_noise": True, "noise_seed": 1000 + b, "cfg": 1,
            "model": ["1", 0], "positive": [tid, 0], "negative": [tid, 1],
            "sampler": ["5", 0], "sigmas": ["6", 0], "latent_image": [lid, 0]}}
        wf[did] = {"class_type": "VAEDecode", "inputs": {"samples": [sid, 0], "vae": ["3", 0]}}
        decode_ids.append(did)

    prev = decode_ids[0]
    for i, nid in enumerate(decode_ids[1:]):
        mid = str(900 + i)
        wf[mid] = {"class_type": "ImageBatch", "inputs": {"image1": [prev, 0], "image2": [nid, 0]}}
        prev = mid

    wf["910"] = {"class_type": "StickerPackBatch", "inputs": {
        "image": [prev, 0], "captions": ["7", 0],
        "font_path": FONT, "font_index": 0, "ink": "#2B2B2B", "canvas": 512,
        "cols": 4, "rows": 1, "pad": 70, "band_ratio": 0.06, "lifts": "",
        "blank_wm_w": 118, "blank_wm_h": 62,
        "frame_order": "0,1,2,3,2,1", "durations": "320,180,180,600,180,180",
        "loop": 0, "pack_name": "表情包", "save_mp4": True}}
    wf["920"] = {"class_type": "PreviewImage", "inputs": {"images": ["910", 0]}}
    wf["921"] = {"class_type": "PreviewImage", "inputs": {"images": ["910", 1]}}
    return wf


def build_pack_only_api(n: int = 9):
    """Same pack stage, but fed by atlas images already on disk."""
    wf = {}
    ids = []
    for i in range(n):
        nid = str(i + 1)
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": f"atlas_{i + 1:02d}.png"}}
        ids.append(nid)
    prev = ids[0]
    for i, nid in enumerate(ids[1:]):
        mid = str(100 + i)
        wf[mid] = {"class_type": "ImageBatch", "inputs": {"image1": [prev, 0], "image2": [nid, 0]}}
        prev = mid
    wf["910"] = {"class_type": "StickerPackBatch", "inputs": {
        "image": [prev, 0], "captions": "\n".join(c for c, *_ in STICKERS[:n]),
        "font_path": FONT, "font_index": 0, "ink": "#2B2B2B", "canvas": 512,
        "cols": 4, "rows": 1, "pad": 70, "band_ratio": 0.06, "lifts": "",
        "blank_wm_w": 118, "blank_wm_h": 62,
        "frame_order": "0,1,2,3,2,1", "durations": "320,180,180,600,180,180",
        "loop": 0, "pack_name": "atlas-pack", "save_mp4": True}}
    wf["920"] = {"class_type": "PreviewImage", "inputs": {"images": ["910", 0]}}
    wf["921"] = {"class_type": "PreviewImage", "inputs": {"images": ["910", 1]}}
    return wf


# --------------------------------------------------------------------- checks

def validate_ui(wf):
    ids = {n["id"] for n in wf["nodes"]}
    assert len(ids) == len(wf["nodes"]), "duplicate node id"
    seen = set()
    for lid, src, sslot, dst, dslot, dtype in wf["links"]:
        assert src in ids and dst in ids, f"link {lid} points at a missing node"
        assert lid not in seen, f"duplicate link id {lid}"
        seen.add(lid)
        s = next(n for n in wf["nodes"] if n["id"] == src)
        d = next(n for n in wf["nodes"] if n["id"] == dst)
        assert sslot < len(s["outputs"]), f"link {lid} bad origin slot"
        assert dslot < len(d["inputs"]), f"link {lid} bad target slot"
        assert lid in s["outputs"][sslot]["links"], f"link {lid} missing on origin"
        assert d["inputs"][dslot]["link"] == lid, f"link {lid} missing on target"
        assert s["outputs"][sslot]["type"] == d["inputs"][dslot]["type"] == dtype, \
            f"link {lid} type mismatch"
    for n in wf["nodes"]:
        for i in n["inputs"]:
            if i["link"] is not None:
                assert i["link"] in seen, f"{n['type']} has dangling input link"
    assert wf["last_link_id"] == len(wf["links"])
    assert wf["last_node_id"] == max(ids)


def validate_api(wf):
    for nid, node in wf.items():
        assert "class_type" in node and "inputs" in node, f"{nid} malformed"
        for k, v in node["inputs"].items():
            if isinstance(v, list):
                assert len(v) == 2, f"{nid}.{k} not a link"
                assert v[0] in wf, f"{nid}.{k} links to missing node {v[0]}"


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)

    ui = build_ui()
    validate_ui(ui)
    with open(os.path.join(OUT, "sticker_postprocess_ui.json"), "w", encoding="utf-8") as f:
        json.dump(ui, f, ensure_ascii=False, indent=2)
    print(f"ui   ok  nodes={len(ui['nodes'])} links={len(ui['links'])}")

    api = build_api()
    validate_api(api)
    with open(os.path.join(OUT, "sticker_full_qwen_api.json"), "w", encoding="utf-8") as f:
        json.dump(api, f, ensure_ascii=False, indent=2)
    print(f"api  ok  nodes={len(api)}")

    full9 = build_full9_api()
    validate_api(full9)
    with open(os.path.join(OUT, "sticker_pack_9qwen_api.json"), "w", encoding="utf-8") as f:
        json.dump(full9, f, ensure_ascii=False, indent=2)
    print(f"9x   ok  nodes={len(full9)}")

    pack_only = build_pack_only_api()
    validate_api(pack_only)
    with open(os.path.join(OUT, "sticker_pack_from_atlas_api.json"), "w", encoding="utf-8") as f:
        json.dump(pack_only, f, ensure_ascii=False, indent=2)
    print(f"pack ok  nodes={len(pack_only)}")
