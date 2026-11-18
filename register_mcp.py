#!/usr/bin/env python3
"""Register (or remove) the Understand This Video For Me MCP server in Claude Desktop and Cursor configs.
Usage: python register_mcp.py <path-to-understand-this-video-mcp> [--remove]
Existing configs are backed up (*.bak) and merged, never overwritten."""
import json
import os
import shutil
import sys
from pathlib import Path

NAME = "Understand This Video For Me"
OLD_NAMES = ("video-context",)


def config_paths():
    home = Path.home()
    if sys.platform == "darwin":
        claude = home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif os.name == "nt":
        claude = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))) / "Claude/claude_desktop_config.json"
    else:
        claude = home / ".config/Claude/claude_desktop_config.json"
    return {"Claude Desktop": claude, "Cursor": home / ".cursor/mcp.json"}


def update(path, entry, remove=False):
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError:
            print("  ! %s is not valid JSON; skipped (fix it or add the entry by hand)" % path)
            return False
        shutil.copy2(str(path), str(path) + ".bak")
    servers = data.setdefault("mcpServers", {})
    for old in OLD_NAMES:
        servers.pop(old, None)
    if remove:
        servers.pop(NAME, None)
    else:
        servers[NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = str(Path(sys.argv[1]).resolve())
    remove = "--remove" in sys.argv
    extra_path = [p for p in ("/opt/homebrew/bin", "/usr/local/bin") if os.path.isdir(p)]
    env = {}
    ff = shutil.which("ffmpeg")
    dirs = ([os.path.dirname(ff)] if ff else []) + extra_path
    if dirs:  # GUI apps don't inherit the shell PATH, so ffmpeg must be findable
        env["PATH"] = os.pathsep.join(dict.fromkeys(dirs + os.environ.get("PATH", "").split(os.pathsep)))
    entry = {"command": cmd, "args": [], "env": env}
    for app, path in config_paths().items():
        if update(path, entry, remove):
            print("  %s %s: %s" % ("Removed from" if remove else "Registered in", app, path))
    if not remove:
        print("  Grok Bot / other MCP clients: add a stdio server with command:\n    %s" % cmd)


if __name__ == "__main__":
    main()
