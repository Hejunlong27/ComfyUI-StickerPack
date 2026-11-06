"""Core image pipeline for chat-sticker GIF packs.

Pure PIL/numpy functions, no ComfyUI imports, so they can be unit tested
outside ComfyUI. The node layer in nodes.py only wraps these.

Pipeline, mirroring the pixel-gif-sticker-pack skill:
    key_green   -> chroma key a flat green background into alpha
    split_grid  -> cut an atlas into equal cells
    align_ground-> re-anchor cells on the feet so the character cannot slide
    compose     -> fit each pose into a 512 canvas, draw an outlined caption
    save_gif    -> one shared palette, binary alpha, disposal 2, infinite loop
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS = 512
SPRITE_MAX_W = 400
SPRITE_MAX_H = 330
BASELINE_Y = 390
CAPTION_Y = 450
CAPTION_MAX_W = 440


# --------------------------------------------------------------------------- key

def key_green(
    rgb: np.ndarray,
    min_green: int = 90,
    dominance: int = 40,
    erode: int = 1,
    feather: float = 0.7,
    blank_w: int = 0,
    blank_h: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Chroma-key a flat green background.

    rgb: HxWx3 uint8. Returns (despilled rgb, alpha uint8).
    blank_w/h: wipe that many pixels in the bottom-right corner first, for
    generator watermarks. Filled with the clean green from the top-right.
    """
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"key_green 需要 HxWx3 的图，收到 {rgb.shape}")
    rgb = rgb[:, :, :3]

    a = rgb.astype(np.int16).copy()
    h, w = a.shape[:2]

    if blank_w > 0 and blank_h > 0:
        green = a[6, w - 6].copy()
        a[h - blank_h:, w - blank_w:] = green

    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (g > min_green) & (g - r > dominance) & (g - b > dominance)

    # Despill kept pixels that sit next to the key, so no green fringe survives.
    edge = mask
    for _ in range(2):
        edge = np.asarray(
            Image.fromarray((edge * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
        ) > 0
    spill = edge & ~mask & (g > (r + b) / 2 + 12)
    avg = ((a[:, :, 0] + a[:, :, 2]) // 2).astype(np.uint8)
    a[:, :, 1] = np.where(spill, avg, a[:, :, 1])

    alpha = np.where(mask, 0, 255).astype(np.uint8)
    if erode > 0:
        am = Image.fromarray(alpha).filter(ImageFilter.MinFilter(erode * 2 + 1))
    else:
        am = Image.fromarray(alpha)
    if feather > 0:
        am = am.filter(ImageFilter.GaussianBlur(feather))

    return np.clip(a, 0, 255).astype(np.uint8), np.asarray(am)


# ------------------------------------------------------------------ grid split

def split_grid(rgba: Image.Image, cols: int, rows: int, row_index: int = -1) -> list[Image.Image]:
    """Cut an atlas into equal cells, row-major. row_index -1 keeps every row."""
    w, h = rgba.size
    cw, ch = w // cols, h // rows
    out = []
    for r in range(rows):
        if row_index >= 0 and r != row_index:
            continue
        for c in range(cols):
            out.append(rgba.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)))
    return out


# --------------------------------------------------------------- ground align

def align_ground(
    cells: Sequence[Image.Image],
    pad: int = 70,
    band_ratio: float = 0.06,
    lifts: Sequence[int] | None = None,
) -> list[Image.Image]:
    """Re-anchor cells on the feet so the sprite cannot slide between frames.

    The generator puts each pose at a slightly different x inside its cell. The
    exporter fits every frame with one common transform, so those offsets would
    read as sideways drift. Anchor on the x centroid of the lowest rows of the
    alpha bbox (the feet), and on the bbox bottom as the ground line.

    lifts: per-cell vertical offset in source pixels, for a hop where the feet
    legitimately leave the ground (negative moves up).
    """
    if not cells:
        return []
    w, h = cells[0].size
    out_w = w + pad * 2
    out = []
    for i, cell in enumerate(cells):
        alpha = np.asarray(cell)[:, :, 3]
        ys, xs = np.nonzero(alpha > 128)
        if len(ys) == 0:
            out.append(Image.new("RGBA", (out_w, h), (0, 0, 0, 0)))
            continue
        y0, y1 = int(ys.min()), int(ys.max())
        band = max(3, int((y1 - y0) * band_ratio))
        foot = alpha[max(0, y1 - band):y1 + 1, :]
        fx = np.nonzero(foot > 128)[1]
        anchor_x = float(fx.mean()) if len(fx) else float(xs.mean())

        canvas = Image.new("RGBA", (out_w, h), (0, 0, 0, 0))
        dx = int(round(pad + w / 2 - anchor_x))
        dy = int(lifts[i]) if lifts and i < len(lifts) else 0
        canvas.paste(cell, (dx, dy), cell)
        out.append(canvas)
    return out


# ------------------------------------------------------------------- caption

def _caption_layer(text: str, ink: str, font_path: str, font_index: int, canvas: int) -> Image.Image:
    face = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(face)
    size = 62 if len(text) <= 4 else 56
    font = ImageFont.truetype(font_path, size, index=font_index)
    while font.getlength(text) > CAPTION_MAX_W and size > 18:
        size -= 1
        font = ImageFont.truetype(font_path, size, index=font_index)
    pen.text((canvas // 2, CAPTION_Y), text, font=font, anchor="mm", fill=ink,
             stroke_width=1, stroke_fill=ink)

    border = Image.new("RGBA", face.size, (255, 255, 255, 255))
    border.putalpha(face.getchannel("A").filter(ImageFilter.MaxFilter(9)))
    border.alpha_composite(face)
    return border


def compose_frames(
    cells: Sequence[Image.Image],
    order: Sequence[int],
    text: str,
    font_path: str,
    font_index: int = 0,
    ink: str = "#2B2B2B",
    canvas: int = CANVAS,
) -> list[Image.Image]:
    """Fit every pose into a square canvas and stamp the caption.

    One common scale for all poses, so the character cannot zoom between frames.
    """
    label = _caption_layer(text, ink, font_path, font_index, canvas) if text.strip() else None

    boxes = [c.getbbox() for c in cells]
    boxes = [b for b in boxes if b]
    if not boxes:
        raise ValueError("no visible pixels in any cell")
    union_w = max(b[2] - b[0] for b in boxes)
    union_h = max(b[3] - b[1] for b in boxes)
    ratio = min(SPRITE_MAX_H / union_h, SPRITE_MAX_W / union_w)

    frames = []
    for idx in order:
        cell = cells[idx]
        bbox = cell.getbbox()
        sprite = cell.crop(bbox) if bbox else cell
        w = max(1, round(sprite.width * ratio))
        h = max(1, round(sprite.height * ratio))
        sprite = sprite.resize((w, h), Image.LANCZOS)

        frame = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        frame.alpha_composite(sprite, (round((canvas - w) / 2), round(BASELINE_Y - h)))
        if label is not None:
            frame.alpha_composite(label)
        # GIF transparency is binary; threshold once at final resolution.
        frame.putalpha(frame.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
        frames.append(frame)
    return frames


# ----------------------------------------------------------------------- gif

def _shared_palette(frames: Iterable[Image.Image]) -> np.ndarray:
    """One 255-colour palette for the whole loop, index 0 reserved for alpha."""
    samples = []
    for f in frames:
        arr = np.asarray(f)
        opaque = arr[arr[:, :, 3] >= 128][:, :3]
        if len(opaque):
            step = max(1, len(opaque) // 20000)
            samples.append(opaque[::step])
    pool = np.concatenate(samples, axis=0) if samples else np.zeros((1, 3), np.uint8)
    mosaic = Image.fromarray(pool.reshape(1, -1, 3))
    pal = mosaic.quantize(colors=255, method=Image.MEDIANCUT).getpalette()[: 255 * 3]
    table = np.array(pal, dtype=np.int16).reshape(-1, 3)
    # Index 0 is transparent, so shift every real colour up by one slot.
    return np.vstack([[0, 0, 0], table]).astype(np.uint8)


def _apply_palette(frame: Image.Image, palette: np.ndarray) -> Image.Image:
    arr = np.asarray(frame)
    rgb = arr[:, :, :3].astype(np.int16)
    alpha = arr[:, :, 3]

    flat = rgb.reshape(-1, 3).astype(np.int32)
    out = np.zeros(len(flat), np.uint8)
    # int32 is required: 255**2 overflows int16 and silently corrupts the match.
    cols = palette[1:].astype(np.int32)
    chunk = 16384
    for i in range(0, len(flat), chunk):
        block = flat[i:i + chunk]
        d = ((block[:, None, :] - cols[None, :, :]) ** 2).sum(axis=2)
        out[i:i + chunk] = d.argmin(axis=1) + 1

    out = out.reshape(alpha.shape)
    out[alpha < 128] = 0

    p = Image.fromarray(out, mode="P")
    p.putpalette(palette.reshape(-1).tolist())
    p.info["transparency"] = 0
    return p


def save_gif(
    frames: Sequence[Image.Image],
    path: str,
    durations: Sequence[int] | None = None,
    loop: int = 0,
) -> str:
    """Write one transparent looping GIF with a palette shared by every frame."""
    if not frames:
        raise ValueError("no frames to save")
    palette = _shared_palette(frames)
    pal_frames = [_apply_palette(f, palette) for f in frames]

    if durations is None:
        durations = [80] * len(frames)
    durations = [max(20, int(round(d / 20.0)) * 20) for d in durations]

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pal_frames[0].save(
        path,
        save_all=True,
        append_images=pal_frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
        transparency=0,
        optimize=False,
    )
    return path


def save_mp4(frames: Sequence[Image.Image], path: str, durations: Sequence[int], fps: int = 25) -> str | None:
    """Optional playable preview. Returns None when ffmpeg is unavailable."""
    if not frames:
        return None
    tmp = tempfile.mkdtemp(prefix="sticker_")
    for i, f in enumerate(frames):
        bg = Image.new("RGB", f.size, (236, 236, 236))
        bg.paste(f, (0, 0), f)
        bg.save(os.path.join(tmp, f"{i:04d}.png"))
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
             "-i", os.path.join(tmp, "%04d.png"), "-c:v", "libx264",
             "-pix_fmt", "yuv420p", path],
            check=True,
        )
        return path
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


# --------------------------------------------------------------- pack / zip

def contact_sheet(
    stickers: Sequence[tuple[Sequence[Image.Image], str]],
    cols: int = 3,
    tile: int = 256,
    pad: int = 10,
) -> Image.Image:
    """One still per sticker in a grid, for a quick look at the whole pack."""
    if not stickers:
        return Image.new("RGB", (tile, tile), (240, 240, 240))
    rows = (len(stickers) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tile + pad) + pad, rows * (tile + pad) + pad), (244, 244, 244))
    for i, (frames, _) in enumerate(stickers):
        still = frames[len(frames) // 2].resize((tile, tile), Image.LANCZOS)
        bg = Image.new("RGB", (tile, tile), (250, 250, 250))
        bg.paste(still, (0, 0), still)
        sheet.paste(bg, (pad + (i % cols) * (tile + pad), pad + (i // cols) * (tile + pad)))
    return sheet


def build_zip(entries: Sequence[tuple[str, str]], zip_path: str, extra: dict[str, str] | None = None) -> str:
    """entries: (arcname, file_path). extra: arcname -> text content."""
    import zipfile

    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, path in entries:
            z.write(path, arcname)
        for arcname, text in (extra or {}).items():
            z.writestr(arcname, text)
    return zip_path


def gallery_html(title: str, items: Sequence[tuple[str, str]]) -> str:
    """items: (caption, relative gif path). Offline browsable page inside the zip."""
    cells = "\n".join(
        f'<figure><img src="{p}" alt="{c}"><figcaption>{c}</figcaption></figure>'
        for c, p in items
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{title}</title>
<style>
body{{margin:0;padding:28px;background:#f6f3ef;color:#2b2b2b;
     font:15px/1.5 system-ui,"Microsoft YaHei",sans-serif}}
h1{{font-size:20px;margin:0 0 20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px}}
figure{{margin:0;background:#fff;border:1px solid #e4ded6;border-radius:14px;padding:10px;text-align:center}}
img{{width:100%;height:auto;max-width:180px}}
figcaption{{font-size:13px;padding-top:6px;color:#5c5650}}
</style>
<h1>{title}</h1>
<div class="grid">
{cells}
</div>
"""



# ------------------------------------------------------- script parsing

import re as _re

_HEAD = _re.compile(r"^\s*(\d{1,2})\s*[｜|、.．:：]\s*(.+?)\s*$")
_SECTION = _re.compile(r"^\s*[一二三四五六七八九十百]+\s*[、.．]\s*")
_CAPTION = _re.compile(r"配\s*字\s*[:：]?\s*[「『\"“']?(.+?)[」』\"”']?\s*$")


def parse_brief(brief: str) -> tuple[str, list[dict]]:
    """Split one free-form brief into (character preamble, ordered items).

    Everything before the first numbered heading is treated as the character /
    style description and is carried into every generation prompt, so the user
    only ever fills in one box.

    Understands the common Chinese brief shape:

        01｜收到！
        少年突然站直身体……点头两下。
        配字：「收到！保证完成！」

    Falls back to blank-line blocks, then to single lines, when no numbered
    headings are present. Each item: index, title, action, caption.
    """
    text = (brief or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "", []

    lines = text.split("\n")
    pre: list[str] = []
    started = False
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _SECTION.match(line) and not _HEAD.match(line):
            # A top-level section title such as "二、9款表情包具体设计" is not a sticker.
            if current:
                blocks.append(current)
                current = []
            continue
        if _HEAD.match(line):
            started = True
            if current:
                blocks.append(current)
            current = [line]
        elif line.strip():
            if started:
                current.append(line)
            else:
                pre.append(line.strip())
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    # No numbered headings anywhere: fall back to blank-line blocks.
    if not any(_HEAD.match(b[0]) for b in blocks):
        blocks = [[ln for ln in b if ln.strip()] for b in text.split("\n\n") if b.strip()]
        pre = []

    items = []
    for i, block in enumerate(blocks):
        head = _HEAD.match(block[0])
        if not head and len(block) < 2:
            # Heading-only fragment with no action and no caption: drop it.
            continue
        if head:
            index, title = head.group(1), head.group(2)
            body = block[1:]
        else:
            index, title = str(i + 1), block[0].strip()
            body = block[1:]

        caption = ""
        action_lines = []
        for line in body:
            m = _CAPTION.search(line.strip())
            if m and ("配" in line):
                caption = m.group(1).strip()
            else:
                action_lines.append(line.strip())

        # A block with only a heading and no body is still a sticker.
        items.append({
            "index": index or str(i + 1),
            "title": title,
            "action": " ".join(a for a in action_lines if a),
            "caption": caption or title,
        })

    preamble = " ".join(
        ln for ln in pre
        if ln and not _re.match(r"^[=＝\-—_·\s]+$", ln) and not ln.startswith("===")
    )
    preamble = _re.sub(r"^【?角色(?:描述|设定)?】?\s*[:：]?\s*", "", preamble).strip()
    return preamble, items


def build_keyframe_prompt(action: str, cells: int = 4, preamble: str = "") -> str:
    """Wrap one sticker's action into the proven green-screen keyframe prompt."""
    return (
        f"角色关键帧序列图，{cells} 列 1 行，共 {cells} 格横向并排，按时间顺序从左到右。"
        + (preamble.strip() + " " if preamble.strip() else "")
        + "严格对齐：所有格中角色的头部中心、头部大小、身体比例、机位、镜头、光线与躯干基线必须完全一致，"
        "双脚踩在同一条地平线上（跳跃或瘫坐等动作除外）。不要缩放、平移或改变角色大小。"
        "只改变动作涉及的手脚与面部表情。每格都必须完整显示角色，头发、手肘、手指都不能被裁切，"
        "格与格之间留出宽阔的空白间隔。"
        "背景：纯色绿幕（#00FF00），完全均匀，没有渐变、没有地面、没有阴影、没有反射、"
        "没有边框、没有网格线、没有文字、没有水印。\n"
        f"把下面这段连续动作按时间顺序拆成 {cells} 个关键姿势，从左到右每格一个姿势，"
        "最后一格停在动作的收尾状态（便于循环回第一格）：\n"
        + action.strip()
    )


# ------------------------------------------------------- script parsing

import re as _re

_HEAD = _re.compile(r"^\s*(\d{1,2})\s*[｜|、.．:：]\s*(.+?)\s*$")
_SECTION = _re.compile(r"^\s*[一二三四五六七八九十百]+\s*[、.．]\s*")
_CAPTION = _re.compile(r"配\s*字\s*[:：]?\s*[「『\"“']?(.+?)[」』\"”']?\s*$")


def parse_brief(brief: str) -> tuple[str, list[dict]]:
    """Split one free-form brief into (character preamble, ordered items).

    Everything before the first numbered heading is treated as the character /
    style description and is carried into every generation prompt, so the user
    only ever fills in one box.

    Understands the common Chinese brief shape:

        01｜收到！
        少年突然站直身体……点头两下。
        配字：「收到！保证完成！」

    Falls back to blank-line blocks, then to single lines, when no numbered
    headings are present. Each item: index, title, action, caption.
    """
    text = (brief or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "", []

    lines = text.split("\n")
    pre: list[str] = []
    started = False
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _SECTION.match(line) and not _HEAD.match(line):
            # A top-level section title such as "二、9款表情包具体设计" is not a sticker.
            if current:
                blocks.append(current)
                current = []
            continue
        if _HEAD.match(line):
            started = True
            if current:
                blocks.append(current)
            current = [line]
        elif line.strip():
            if started:
                current.append(line)
            else:
                pre.append(line.strip())
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    # No numbered headings anywhere: fall back to blank-line blocks.
    if not any(_HEAD.match(b[0]) for b in blocks):
        blocks = [[ln for ln in b if ln.strip()] for b in text.split("\n\n") if b.strip()]
        pre = []

    items = []
    for i, block in enumerate(blocks):
        head = _HEAD.match(block[0])
        if not head and len(block) < 2:
            # Heading-only fragment with no action and no caption: drop it.
            continue
        if head:
            index, title = head.group(1), head.group(2)
            body = block[1:]
        else:
            index, title = str(i + 1), block[0].strip()
            body = block[1:]

        caption = ""
        action_lines = []
        for line in body:
            m = _CAPTION.search(line.strip())
            if m and ("配" in line):
                caption = m.group(1).strip()
            else:
                action_lines.append(line.strip())

        # A block with only a heading and no body is still a sticker.
        items.append({
            "index": index or str(i + 1),
            "title": title,
            "action": " ".join(a for a in action_lines if a),
            "caption": caption or title,
        })

    preamble = " ".join(
        ln for ln in pre
        if ln and not _re.match(r"^[=＝\-—_·\s]+$", ln) and not ln.startswith("===")
    )
    preamble = _re.sub(r"^【?角色(?:描述|设定)?】?\s*[:：]?\s*", "", preamble).strip()
    return preamble, items


def build_keyframe_prompt(action: str, cells: int = 4, preamble: str = "") -> str:
    """Wrap one sticker's action into the proven green-screen keyframe prompt."""
    return (
        f"角色关键帧序列图，{cells} 列 1 行，共 {cells} 格横向并排，按时间顺序从左到右。"
        + (preamble.strip() + " " if preamble.strip() else "")
        + "严格对齐：所有格中角色的头部中心、头部大小、身体比例、机位、镜头、光线与躯干基线必须完全一致，"
        "双脚踩在同一条地平线上（跳跃或瘫坐等动作除外）。不要缩放、平移或改变角色大小。"
        "只改变动作涉及的手脚与面部表情。每格都必须完整显示角色，头发、手肘、手指都不能被裁切，"
        "格与格之间留出宽阔的空白间隔。"
        "背景：纯色绿幕（#00FF00），完全均匀，没有渐变、没有地面、没有阴影、没有反射、"
        "没有边框、没有网格线、没有文字、没有水印。\n"
        f"把下面这段连续动作按时间顺序拆成 {cells} 个关键姿势，从左到右每格一个姿势，"
        "最后一格停在动作的收尾状态（便于循环回第一格）：\n"
        + action.strip()
    )


DEFAULT_CHARACTER = (
    "画面中的角色必须与参考图完全一致：3D 渲染风格的动漫 Q 版少年，蓬松凌乱的黑色碎发、"
    "精致的五官、白皙皮肤、宽松纯白 T 恤、黑色阔腿九分裤配浅灰色翻边、黑白帆布高帮鞋。"
    "高质量 3D 动画电影质感，柔和的皮克斯式光影，干净的棚拍布光。"
)

DEFAULT_SCRIPT = """二、9款表情包具体设计
01｜收到！
少年突然站直身体，眼神变得认真，右手抬起做出敬礼动作，随后快速点头两下，露出自信的笑容。
配字：「收到！保证完成！」
02｜谢谢老板
少年双手捧着咖啡，眼睛笑成月牙，身体微微前倾，连续鞠躬两次，表现出开心又礼貌的感觉。
配字：「老板大气！」
03｜我想想
少年一只手托着下巴，另一只手轻轻敲着脑袋，眼睛左右转动，头顶出现一个小小的思考气泡。
配字：「让我思考一下……」
04｜无语住了
少年眼神逐渐呆滞，嘴角抽动，缓缓抬手捂住额头，随后轻轻摇头，表现出无奈又好笑的情绪。
配字：「我真的服了。」
05｜给你一个赞
少年露出灿烂笑容，举起右手竖起大拇指，身体轻轻向前倾，眼睛闪烁一下，表现出真诚的赞赏。
配字：「这个可以！」
06｜不想上班
少年双手插兜，身体懒洋洋地向下蹲，眼神失去光彩，随后慢慢瘫坐在地上，头顶出现一个灰色小乌云。
配字：「不想动，真的不想动。」
07｜偷偷观察
少年躲在画面边缘，只露出半张脸，眼睛左右偷偷张望，随后探出脑袋，发现有人注意后迅速缩回去。
配字：「我就看看，不说话。」
08｜开心转圈
少年双眼弯成月牙，开心地举起双手，原地轻轻转一圈，头发和衣角随着动作自然摆动，最后比出胜利手势。
配字：「开心到飞起！」
09｜晚安啦
少年抱着咖啡杯（可替换成小抱枕），眼睛逐渐闭上，轻轻打一个哈欠，脑袋慢慢歪向一边，画面出现几颗漂浮的星星和 Zzz 符号。
配字：「晚安，好梦～」"""
