#!/usr/bin/env python3
"""Build the Smithery upload from a release .mcpb.

Smithery's server card needs every tool with its input schema, which the
MCPB manifest format does not carry. This runs the bundled worker over
stdio, asks it for tools/list, writes the result into manifest.json and
zips the bundle again.

usage: smithery-bundle.py <in.mcpb> <out.mcpb>
"""

import json
import os
import select
import subprocess
import sys
import tempfile
import time
import zipfile

ORDER = [
    "reddit", "twitter", "linkedin", "facebook", "pinterest", "medium",
    "devto", "bhw", "trends", "news", "search_console", "ga4", "clarity",
    "browse", "mcpbrowser",
]


def sort_key(tool):
    name = tool["name"]
    for i, prefix in enumerate(ORDER):
        if name.startswith(prefix):
            return (i, name)
    return (len(ORDER), name)


def list_tools(worker):
    env = {**os.environ, "MCPBROWSER_SELF_SIGNIN": "1"}
    proc = subprocess.Popen(
        [worker], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env,
    )

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "smithery-bundle", "version": "0"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    deadline = time.time() + 30
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 2:
                return msg["result"]["tools"]
    finally:
        proc.kill()
    sys.exit("worker did not answer tools/list")


def main(src, dst):
    with tempfile.TemporaryDirectory() as work:
        with zipfile.ZipFile(src) as z:
            z.extractall(work)
        worker = os.path.join(work, "server", "mcpbrowser-worker")
        os.chmod(worker, 0o755)

        manifest_path = os.path.join(work, "manifest.json")
        manifest = json.load(open(manifest_path))
        tools = sorted(list_tools(worker), key=sort_key)
        manifest["tools"] = [{
            "name": t["name"],
            "description": (t.get("description") or "").strip(),
            "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
        } for t in tools]
        json.dump(manifest, open(manifest_path, "w"), indent=2)

        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for name in ("manifest.json", "icon.png", "server/mcpbrowser-worker"):
                out.write(os.path.join(work, name), name)
    print(f"{dst}: {len(tools)} tools")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
