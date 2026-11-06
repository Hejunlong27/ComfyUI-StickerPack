"""Regenerate 节点参数说明.md from the node definitions.

Run: python gen_docs.py
Keeps the doc in sync with nodes.py so the tables can never drift.
"""

import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

sys.modules.setdefault("torch", types.ModuleType("torch"))
pkg = types.ModuleType("sp")
pkg.__path__ = [HERE]
sys.modules["sp"] = pkg
spec = importlib.util.spec_from_file_location("sp.nodes", os.path.join(HERE, "nodes.py"))
nodes = importlib.util.module_from_spec(spec)
sys.modules["sp.nodes"] = nodes
spec.loader.exec_module(nodes)

HEAD = """# 节点参数说明

`ComfyUI-StickerPack` 全部 9 个节点、每个参数的逐条说明。
这份文件是从节点定义自动生成的，改完 `nodes.py` 后跑 `python gen_docs.py` 会同步更新。

参数名保持英文（ComfyUI 生态通用，也方便 API 格式调用），中文解释写在「说明」列，
同时在画布里把鼠标悬停到参数上也会显示同样的说明。

---

## 一、主链路（日常只用这三个）

```
StickerAutoPack  →  StickerSaveZip
        ↑
   LoadImage / 模型加载器
```

"""

FOOT = """
---

## 二、参数速查

### 最常调的四个

| 想改什么 | 改哪个 | 怎么改 |
|---|---|---|
| 文案和角色 | `brief` | 开头写角色外形，空一行后写 `01｜标题` 条目 |
| 更快出图 | `width` 1280 或 `cells` 3 | 分别省约 17% 和 25% 时间 |
| 字幕太小/太大 | `canvas` | 512 → 640 字更大，但文件也更大 |
| 动作更顺 | `cells` 4 或 5 | 关键姿势更多，但更慢 |

### 一般不用动的

`sigmas`（turbo 专用步进）、`cfg`（必须 1.0）、`sampler_name`（euler）、
`ref_resolution`（1024 够用）、`loop`（0 = 无限循环）。

### 出问题先看这三个

| 现象 | 检查 |
|---|---|
| 报「没有解析出任何表情包条目」 | `brief` 里的编号行格式，必须是 `01｜标题` |
| 报「字幕字体不存在」 | `font_path` 指向的 ttf/ttc 在不在，路径用正斜杠 |
| 报「找不到 zip 文件」 | `StickerSaveZip.zip_path` 有没有接上 `StickerAutoPack.zip_path` |
"""

ORDER = [
    "StickerAutoPack", "StickerSaveZip", "StickerScriptParser", "StickerPackBatch",
    "StickerKeyGreen", "StickerSplitGrid", "StickerAlignGround", "StickerCompose",
    "StickerSaveGIF",
]


def table(cls):
    out = ["| 参数 | 类型 | 默认 | 说明 |", "|---|---|---|---|"]
    for key, decl in cls.INPUT_TYPES()["required"].items():
        tname = decl[0] if isinstance(decl[0], str) else "COMBO"
        opt = decl[1] if len(decl) > 1 else {}
        if tname == "COMBO":
            opts = list(decl[0]) if not isinstance(decl[0], str) else []
            default = "、".join(str(x) for x in opts[:3]) + ("…" if len(opts) > 3 else "")
        else:
            default = opt.get("default", "")
            if isinstance(default, str) and len(default) > 40:
                default = default[:37] + "…"
            default = f"`{default}`" if default != "" else "—"
        out.append(f"| `{key}` | {tname} | {default} | {opt.get('tooltip') or '—'} |")
    return out


def main():
    body = []
    for name in ORDER:
        cls = nodes.NODE_CLASS_MAPPINGS[name]
        disp = nodes.NODE_DISPLAY_NAME_MAPPINGS.get(name, name)
        body.append(f"### {disp}　`{name}`\n")
        body.extend(table(cls))
        outs = ", ".join(getattr(cls, "RETURN_NAMES", cls.RETURN_TYPES))
        body.append(f"\n输出：`{outs}`\n")
    path = os.path.join(HERE, "节点参数说明.md")
    open(path, "w", encoding="utf-8").write(HEAD + "\n".join(body) + FOOT)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
