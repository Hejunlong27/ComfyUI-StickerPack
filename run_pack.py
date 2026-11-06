"""Submit a sticker workflow to a running ComfyUI and report the ZIP.

  python run_pack.py --workflow workflows/sticker_pack_9qwen_api.json --ref path/to/char.jpg

Uploads the reference image as ref.png, queues the prompt, waits, then prints the
ZIP path plus every preview/text output the graph returned.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

ap = argparse.ArgumentParser()
ap.add_argument("--workflow", required=True)
ap.add_argument("--server", default="http://127.0.0.1:8188")
ap.add_argument("--ref", default="", help="character reference image, uploaded as ref.png")
ap.add_argument("--timeout", type=int, default=3600)
ap.add_argument("--dry", action="store_true", help="only validate the prompt, do not wait")
args = ap.parse_args()

BASE = args.server.rstrip("/")


def post_json(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def upload(path):
    boundary = "----sticker" + uuid.uuid4().hex
    name = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + (
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput"
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
        f"\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        BASE + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        info = json.loads(r.read().decode())
    return info.get("name", name)


wf = json.load(open(args.workflow, encoding="utf-8"))

if args.ref:
    uploaded = upload(args.ref)
    print(f"uploaded reference -> {uploaded}")
    for nid, node in wf.items():
        if node["class_type"] == "LoadImage" and node["inputs"].get("image") == "ref.png":
            node["inputs"]["image"] = uploaded

try:
    res = post_json("/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
except urllib.error.HTTPError as e:
    print("PROMPT REJECTED")
    print(e.read().decode()[:4000])
    sys.exit(1)

pid = res["prompt_id"]
print(f"queued {pid}")
if args.dry:
    post_json("/queue", {"clear": True})
    post_json("/interrupt", {})
    print("dry run: prompt accepted, queue cleared")
    sys.exit(0)

t0 = time.time()
last = ""
while time.time() - t0 < args.timeout:
    with urllib.request.urlopen(f"{BASE}/history/{pid}", timeout=30) as r:
        hist = json.loads(r.read().decode())
    if pid in hist:
        entry = hist[pid]
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            print("EXECUTION ERROR")
            for m in status.get("messages", []):
                print(" ", m)
            sys.exit(1)
        print(f"done in {time.time() - t0:.0f}s")
        for nid, out in entry.get("outputs", {}).items():
            for key in ("text", "string"):
                if key in out:
                    print(f"  node {nid} {key}: {out[key]}")
            if "images" in out:
                print(f"  node {nid} images: {len(out['images'])} "
                      f"-> {[i.get('filename') for i in out['images']][:4]}")
        sys.exit(0)
    with urllib.request.urlopen(f"{BASE}/queue", timeout=30) as r:
        q = json.loads(r.read().decode())
    running = len(q.get("queue_running", []))
    pending = len(q.get("queue_pending", []))
    msg = f"  [{time.time() - t0:.0f}s] running={running} pending={pending}"
    if msg != last:
        print(msg)
        last = msg
    time.sleep(5)

print("timeout")
sys.exit(1)
