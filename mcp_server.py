#!/usr/bin/env python3
"""Understand This Video Plugin: stdlib MCP server (stdio, JSON-RPC 2.0).

Tools:
  understand_this_video(source, out?, max_frames?, transcript?, include_images?)
      -> context.md text (+ contact-sheet image) and output folder path.
  list_videos() -> the videos it can see (Understand This Video folder on the Desktop first).
  (The old name "video_context" is still accepted as a hidden alias.)
Register e.g.:  claude mcp add "Understand This Video" -- understand-this-video-mcp
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_context as vc  # noqa: E402

PROTOCOL = "2024-11-05"
TOOL_NAME = "understand_this_video"
HIDDEN_ALIASES = ("video_context",)  # old name; still callable, never listed
TOOLS = [{
    "name": "understand_this_video",
    "title": "Understand This Video",
    "description": ("Understand This Video: lets the AI watch AND hear a video file on the user's computer: extracts timestamped key frames, "
                    "a transcript (local Whisper) and a contact-sheet image. "
                    "HOW TO FIND THE FILE: the user keeps videos in the 'Understand This Video' folder on their Desktop. "
                    "Pass just the file NAME as 'source' (e.g. 'My Video.mp4', or even part of the name; capitals and the extension "
                    "don't matter), or a full path if they gave one. If the user says 'my latest/newest/last video' or doesn't name a "
                    "file, leave 'source' empty and the newest video is used. NEVER ask the user for a file path: call list_videos "
                    "if you are unsure which files exist. Files attached to the chat cannot be used; tell the user to put the video in "
                    "the 'Understand This Video' folder on their Desktop. It does not download videos from links. "
                    "Returns a timeline (context.md) plus the overview image; individual frames are on disk."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Video file NAME (e.g. 'My Video.mp4' or part of it) from the user's 'Understand This Video' Desktop folder, or a full path. Leave empty for the newest video. Links are not accepted."},
            "out": {"type": "string", "description": "Output folder (default: temp dir)"},
            "max_frames": {"type": "integer", "default": 12, "description": "Max key frames (default 12; raise for more detail, costs more tokens)"},
            "max_side": {"type": "integer", "default": 512, "description": "Longest frame side in px (default 512)"},
            "transcript_only": {"type": "boolean", "default": False,
                                "description": "Speech transcript only, no frames or images (cheapest)"},
            "transcript": {"type": "boolean", "default": True},
            "include_images": {"type": "boolean", "default": True,
                               "description": "Return contact sheet image inline"},
        },
        "required": [],
    },
}, {
    "name": "list_videos",
    "title": "List my videos",
    "description": ("List the videos on the user's computer that Understand This Video can read: first the ones in their "
                    "'Understand This Video' Desktop folder (newest first), then recent videos on the Desktop, Downloads, "
                    "Movies/Videos. Use it to see what is there or to pick the right file name. Creates the folder if it is missing."),
    "inputSchema": {"type": "object", "properties": {
        "include_other_folders": {"type": "boolean", "default": False,
                                  "description": "Also look in Desktop, Downloads and Movies (default: only the Understand This Video folder, which is instant)"}},
        "required": []},
}]


def _err(text):
    return {"isError": True, "content": [{"type": "text", "text": text.strip()}]}


def list_videos_tool(args=None):
    args = args or {}
    vc.reset_blocked()
    vc.begin_budget(vc.LIST_BUDGET)
    folder = vc.ensure_inbox()
    vids = vc.list_videos(30, everywhere=bool(args.get("include_other_folders")))
    lines = ["Understand This Video folder: %s" % (folder or "(could not create it on the Desktop)")]
    bm = vc.blocked_message()
    if bm:
        lines.append("NOTE: " + bm)
    if not vids and not bm:
        lines.append("No videos found yet. Ask the user to put a video in that folder (they can move or save it in from anywhere), then ask again.")
    import datetime
    for p, size, mt in vids:
        lines.append("- %s  (%.1f MB, %s)  %s" % (os.path.basename(p), size / 1048576.0,
                     datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M"), os.path.dirname(p)))
    if vids and not args.get("include_other_folders") and all(os.path.dirname(v[0]) == os.path.dirname(vids[0][0]) for v in vids):
        lines.append("(Only the Understand This Video folder was checked. Use include_other_folders=true to also look in Desktop, Downloads and Movies.)")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def call_tool(args, progress_cb=None):
    import licensing
    try:
        licensing.require_license()
    except licensing.LicenseError as e:
        return {"isError": True, "content": [{"type": "text", "text": str(e)}]}
    vc.reset_blocked()
    src = str(args.get("source") or "").strip()
    out = os.path.expanduser(args.get("out") or "") or tempfile.mkdtemp(prefix="understand_this_video_")
    argv = ([src] if src else []) + ["--scene", "--out", out,
            "--max-frames", str(int(args.get("max_frames", 12))),
            "--max-side", str(int(args.get("max_side", 512)))]
    if args.get("transcript_only"):
        argv.append("--transcript-only")
    if not args.get("transcript", True):
        argv.append("--no-transcript")
    log = []

    def cb(msg):
        log.append(msg)
        if progress_cb:
            progress_cb(msg)
    vc.set_progress(cb)
    parsed = vc.make_parser().parse_args(argv)
    tail = lambda: "\n".join(log)[-1500:]  # noqa: E731
    try:
        vc.build(parsed)
    except SystemExit as e:
        detail = e.code if isinstance(e.code, str) else "exit code %s" % e.code
        return _err("Understand This Video failed: %s\n%s" % (detail, tail()))
    except Exception as e:
        return _err("Understand This Video error: %s\n%s" % (e, tail()))
    ctx = (Path(out) / "context.md").read_text(encoding="utf-8")
    note = getattr(parsed, "resolved_note", "")
    head = ("%s: %s\n" % (note, parsed.video)) if note else ""
    content = [{"type": "text", "text": "%sOutput folder: %s\n\n%s" % (head, os.path.abspath(out), ctx)}]
    sheet = Path(out) / "contact_sheet.jpg"
    if args.get("include_images", True) and sheet.exists():
        content.append({"type": "image", "mimeType": "image/jpeg",
                        "data": base64.b64encode(sheet.read_bytes()).decode()})
    return {"content": content}


TIMEOUT_LIST = float(os.environ.get("UTV_LIST_TIMEOUT", "25"))
TIMEOUT_UNDERSTAND = float(os.environ.get("UTV_TIMEOUT", "1200"))
_OUT = None
_OUT_LOCK = threading.Lock()


def _send(obj):
    with _OUT_LOCK:
        _OUT.write(json.dumps(obj) + "\n")
        _OUT.flush()


def run_tool(name, args, progress_cb=None):
    """Run a tool with a hard time limit so a stuck folder, popup or model can never freeze the chat."""
    box = {}
    secs = TIMEOUT_LIST if name == "list_videos" else TIMEOUT_UNDERSTAND

    def work():
        try:
            box["res"] = list_videos_tool(args) if name == "list_videos" else call_tool(args, progress_cb)
        except BaseException as e:  # noqa
            box["res"] = _err("Understand This Video error: %s" % e)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(secs)
    if t.is_alive():
        bm = ""
        try:
            bm = vc.blocked_message()
        except Exception:
            pass
        if name == "list_videos":
            return _err("Listing videos took longer than %d seconds and was stopped. %s" % (secs, bm or
                        "Check that the 'Understand This Video' folder on the Desktop opens in Finder/Explorer, then try again."))
        return _err("Understand This Video was stopped after %d minutes without finishing. %s Try a shorter video, or "
                    "ask for 'transcript only'. If this keeps happening, email video@shipmonthly.com." % (secs // 60, bm))
    return box.get("res") or _err("Understand This Video returned nothing.")


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "understand-this-video", "title": "Understand This Video Plugin", "version": "1.2.6"}}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        name = p.get("name")
        if name not in ("list_videos", TOOL_NAME) + HIDDEN_ALIASES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        token = (p.get("_meta") or {}).get("progressToken")
        counter = [0]

        def pcb(m):
            if token is None:
                return
            counter[0] += 1
            _send({"jsonrpc": "2.0", "method": "notifications/progress",
                   "params": {"progressToken": token, "progress": counter[0], "message": m}})
        res = run_tool("list_videos" if name == "list_videos" else TOOL_NAME, p.get("arguments", {}) or {}, pcb)
    elif method == "ping":
        res = {}
    elif mid is None:  # notification
        return None
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _dispatch(msg):
    try:
        resp = handle(msg)
    except Exception as e:
        resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
    if resp is not None:
        _send(resp)


def main():
    global _OUT
    _OUT = sys.stdout
    sys.stdout = sys.stderr   # stray prints must never corrupt the JSON stream
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}})
            continue
        if msg.get("method") == "tools/call":   # one thread per call: a slow tool never blocks ping/list
            threading.Thread(target=_dispatch, args=(msg,), daemon=True).start()
        else:
            _dispatch(msg)


if __name__ == "__main__":
    main()
