from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

# Bump on every behaviour change so the console log tells you which build is live.
PLUGIN_VERSION = "1.5"
print(f"[ComfyUI-StickerPack] v{PLUGIN_VERSION} 已加载 {len(NODE_CLASS_MAPPINGS)} 个节点："
      + "、".join(NODE_CLASS_MAPPINGS))
