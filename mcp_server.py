#!/usr/bin/env python3
"""Understand This Video For Me AI Plugin: stdlib MCP server (stdio, JSON-RPC 2.0).

Tools:
  understand_this_video(source, out?, max_frames?, transcript?, include_images?)
      -> context.md text (+ contact-sheet image) and output folder path.
  (The old name "video_context" is still accepted as a hidden alias.)
Register e.g.:  claude mcp add "Understand This Video For Me" -- understand-this-video-mcp
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_context as vc  # noqa: E402

PROTOCOL = "2024-11-05"
TOOL_NAME = "understand_this_video"
HIDDEN_ALIASES = ("video_context",)  # old name; still callable, never listed
TOOLS = [{
    "name": "understand_this_video",
    "title": "Understand This Video For Me",
    "description": ("Understand This Video For Me: lets the AI watch AND hear a local video file: extracts timestamped key frames, a transcript "
                    "(local Whisper) and a contact-sheet image from a file path on your computer. "
                    "It does not download videos from the internet. Returns a timeline "
                    "(context.md) plus the overview image; individual frames are on disk."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Local video file path (e.g. ~/Desktop/My Video.mp4; spaces fine, no quotes needed). URLs are not accepted."},
            "out": {"type": "string", "description": "Output folder (default: temp dir)"},
            "max_frames": {"type": "integer", "default": 20},
            "transcript": {"type": "boolean", "default": True},
            "include_images": {"type": "boolean", "default": True,
                               "description": "Return contact sheet image inline"},
        },
        "required": ["source"],
    },
}]


def _err(text):
    return {"isError": True, "content": [{"type": "text", "text": text.strip()}]}


def call_tool(args):
    import licensing
    try:
        licensing.require_license()
    except licensing.LicenseError as e:
        return {"isError": True, "content": [{"type": "text", "text": "License error: %s" % e}]}
    src = args.get("source")
    if not src or not str(src).strip():
        return _err("Understand This Video For Me: no video given. Pass a local file path as 'source'.")
    out = os.path.expanduser(args.get("out") or "") or tempfile.mkdtemp(prefix="understand_this_video_")
    argv = [str(src), "--scene", "--out", out,
            "--max-frames", str(int(args.get("max_frames", 20)))]
    if not args.get("transcript", True):
        argv.append("--no-transcript")
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            vc.build(vc.make_parser().parse_args(argv))
    except SystemExit as e:
        detail = e.code if isinstance(e.code, str) else "exit code %s" % e.code
        return _err("Understand This Video For Me failed: %s\n%s" % (detail, log.getvalue()[-1500:]))
    except Exception as e:
        return _err("Understand This Video For Me error: %s\n%s" % (e, log.getvalue()[-1500:]))
    ctx = (Path(out) / "context.md").read_text(encoding="utf-8")
    content = [{"type": "text", "text": "Output folder: %s\n\n%s" % (os.path.abspath(out), ctx)}]
    sheet = Path(out) / "contact_sheet.jpg"
    if args.get("include_images", True) and sheet.exists():
        content.append({"type": "image", "mimeType": "image/jpeg",
                        "data": base64.b64encode(sheet.read_bytes()).decode()})
    return {"content": content}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "understand-this-video", "title": "Understand This Video For Me AI Plugin", "version": "1.1.0"}}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        if p.get("name") not in (TOOL_NAME,) + HIDDEN_ALIASES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        res = call_tool(p.get("arguments", {}))
    elif method == "ping":
        res = {}
    elif mid is None:  # notification
        return None
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line))
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
