"""Contract check: node definitions vs the shipped workflows.

Catches the failure mode that actually breaks a custom node pack - a widget the
workflow sets but the node does not declare, a renamed output slot, or a
class_type the pack never registers. Runs without torch or ComfyUI.
"""

import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

# --- stub the imports nodes.py needs at module level -----------------------
sys.modules.setdefault("torch", types.ModuleType("torch"))
pkg = types.ModuleType("sticker_pack_pkg")
pkg.__path__ = [HERE]
sys.modules["sticker_pack_pkg"] = pkg
spec = importlib.util.spec_from_file_location("sticker_pack_pkg.nodes", os.path.join(HERE, "nodes.py"))
nodes = importlib.util.module_from_spec(spec)
sys.modules["sticker_pack_pkg.nodes"] = nodes
spec.loader.exec_module(nodes)

MAPPING = nodes.NODE_CLASS_MAPPINGS
fail = []

# --- 1. every node declares a valid contract ------------------------------
for name, cls in MAPPING.items():
    spec_i = cls.INPUT_TYPES()
    assert "required" in spec_i, f"{name} has no required inputs"
    assert isinstance(cls.RETURN_TYPES, tuple), f"{name} RETURN_TYPES must be a tuple"
    assert len(cls.RETURN_TYPES) == len(getattr(cls, "RETURN_NAMES", cls.RETURN_TYPES)), \
        f"{name} RETURN_NAMES length mismatch"
    for key, decl in spec_i["required"].items():
        # ("IMAGE",) and ("INT", {...}) are both legal ComfyUI declarations.
        assert isinstance(decl, tuple) and 1 <= len(decl) <= 2, f"{name}.{key} malformed"
        if len(decl) == 2:
            assert isinstance(decl[1], dict), f"{name}.{key} options malformed"
    print(f"  {name:22s} widgets={[k for k in spec_i['required']]:}")
print(f"contract: {len(MAPPING)} nodes registered")

# --- 2. widget order in every UI workflow matches INPUT_TYPES ------------
import glob
ui_files = sorted(glob.glob(os.path.join(HERE, "workflows", "*_ui.json")))
for ui_path in ui_files:
  ui = json.load(open(ui_path, encoding="utf-8"))
  for n in ui["nodes"]:
    cls = MAPPING.get(n["type"])
    if cls is None:
        continue
    spec_i = cls.INPUT_TYPES()["required"]
    # A widget keeps its slot in widgets_values even after it is converted to an
    # input socket, so count by declared type rather than by remaining sockets.
    prim = {"STRING", "INT", "FLOAT", "BOOLEAN", "COMBO"}
    widgets = [k for k, d in spec_i.items()
               if isinstance(d[0], (list, tuple)) or d[0] in prim]
    # ComfyUI inserts a control_after_generate value right after a seed widget.
    extra = 1 if any(w in ("seed", "noise_seed") for w in widgets) else 0
    if len(widgets) + extra != len(n["widgets_values"]):
        fail.append(f"{os.path.basename(ui_path)} {n['type']}: workflow has "
                    f"{len(n['widgets_values'])} widget values, expected {len(widgets) + extra} "
                    f"({len(widgets)} declared + {extra} seed control) {widgets}")
    else:
        print(f"  {os.path.basename(ui_path):28s} {n['type']:22s} {len(widgets)} widgets OK")
  print(f"  -> {len(ui['nodes'])} nodes checked")

# --- 3. every class_type in the API workflow is registered ----------------
api_path = os.path.join(HERE, "workflows", "sticker_full_qwen_api.json")
api = json.load(open(api_path, encoding="utf-8"))
for nid, node in api.items():
    ct = node["class_type"]
    if ct.startswith("Sticker") and ct not in MAPPING:
        fail.append(f"api node {nid}: unregistered class_type {ct}")
    if ct in MAPPING:
        cls = MAPPING[ct]
        spec_i = cls.INPUT_TYPES()["required"]
        for key, val in node["inputs"].items():
            if key not in spec_i:
                fail.append(f"api node {nid} ({ct}): unknown input '{key}'")
        for key in spec_i:
            if key not in node["inputs"]:
                fail.append(f"api node {nid} ({ct}): missing input '{key}'")
        if not (cls.RETURN_TYPES,):
            fail.append(f"api node {nid} ({ct}): no outputs")
    # output slot indices referenced must exist on the source node
    for key, val in node["inputs"].items():
        if isinstance(val, list):
            src = api.get(val[0])
            if src is None:
                fail.append(f"api node {nid}.{key}: dangling link to {val[0]}")
            elif src["class_type"] in MAPPING:
                n_out = len(MAPPING[src["class_type"]].RETURN_TYPES)
                if val[1] >= n_out:
                    fail.append(f"api node {nid}.{key}: slot {val[1]} but "
                                f"{src['class_type']} returns {n_out}")
print(f"api workflow: {len(api)} nodes checked")

if fail:
    print("\nFAILURES")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("\nall contract checks passed")
