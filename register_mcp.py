#!/usr/bin/env python3
"""Register (or remove) the Understand This Video MCP server in Claude Desktop and Cursor configs.
Usage: python register_mcp.py <path-to-understand-this-video-mcp> [--remove]
Existing configs are backed up (*.bak) and merged, never overwritten."""
import json
import os
import shutil
import sys
from pathlib import Path

NAME = "Understand This Video"
CLI_NAME = "understand-this-video"  # Claude Code only allows letters, numbers, - and _
OLD_NAMES = ("video-context", "Understand This Video For Me")


def config_paths():
    home = Path.home()
    if sys.platform == "darwin":
        claude = home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif os.name == "nt":
        claude = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming"))) / "Claude/claude_desktop_config.json"
    else:
        claude = home / ".config/Claude/claude_desktop_config.json"
    paths = {"Claude Desktop": claude, "Cursor": home / ".cursor/mcp.json"}
    # Other apps: only registered if the app's config folder already exists (i.e. it is installed)
    optional = {"Windsurf": home / ".codeium/windsurf/mcp_config.json",
                "Gemini CLI": home / ".gemini/settings.json",
                "Cline (VS Code)": None}
    for app, path in optional.items():
        if path is not None and path.parent.exists():
            paths[app] = path
    return paths


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
    claude = shutil.which("claude")
    if claude:  # Claude Code
        import subprocess
        subprocess.call([claude, "mcp", "remove", "--scope", "user", CLI_NAME],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not remove:
            rc = subprocess.call([claude, "mcp", "add", "--scope", "user", CLI_NAME, "--", cmd],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  %s Claude Code" % ("Registered in" if rc == 0 else "Could not register in"))
    if not remove:
        print("  Grok Bot / other MCP clients: add a stdio server with command:\n    %s" % cmd)


if __name__ == "__main__":
    main()
