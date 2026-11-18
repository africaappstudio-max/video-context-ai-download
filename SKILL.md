---
name: understand-this-video
description: Let an AI "watch" a video. Turns a local video file on the user's computer into a small set of timestamped key frames, a timestamped transcript, one contact-sheet image, and a single context.md timeline. Does not download videos from the internet. Use whenever a user asks what a video file shows, wants steps/summary/notes from a video, or asks questions about a recording or tutorial.
---

# Understand This Video For Me AI Plugin

## When to use
- The user gives a local video file path and asks about its contents (summary, steps, bugs, Q&A).
- Your model reads images and text but not video.
- If the user gives a video URL, tell them this plugin only processes video files on their computer. They should download or export the video first, then give you the file path.

## Requirements
- An Understand This Video For Me license (activated once by the installer, or `understand-this-video activate KEY`).
  Exit code 5 / "License error" means not activated: tell the user to activate, don't retry.
- `ffmpeg` + `ffprobe` (found on PATH or in /opt/homebrew/bin, /usr/local/bin) (macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg`, Windows `winget install ffmpeg`).
- Python 3.9+. Installed by `install.sh` / `install.ps1` (ffmpeg, faster-whisper).

## Command
```bash
understand-this-video "/path/to/video.mp4" --scene --out understand_this_video_output
# or, if pip-installed:  understand-this-video "/path/to/video.mp4" --scene
```
Useful flags: `--max-frames 20`, `--min-frames 8`, `--whisper-model small` (falls back to base),
`--language en` (default auto-detect), `--no-transcript`, `--wav`, `--no-audio`,
`--no-sheet`.
Exit codes: 2 = ffmpeg missing, 5 = license.

## Reading the output (do this in order)
1. `context.md` — ONE file: header (duration, transcript source, language) and a timeline
   interleaving `FRAME frames/...jpg` lines with `[mm:ss] speech` lines. Read this first.
2. `contact_sheet.jpg` — all frames in one grid (left→right, top→bottom). Use it when your
   image budget is tight; open individual `frames/frame_NNNN_tX.Xs.jpg` for detail.
3. `transcript.txt` — `[mm:ss.ss - mm:ss.ss] text` lines (local Whisper). Absent if no audio/no transcriber.
4. `MANIFEST.json` — machine-readable: frames[{file,time_s,bytes}], language, sizes.
Answer from both visuals and speech, citing timestamps. If there's no transcript but `audio.m4a`
exists, transcribe it with whatever tool you have.

## MCP
`understand-this-video-mcp` (or `python mcp_server.py`) is a stdio MCP server with one tool,
`understand_this_video(source, out?, max_frames?, transcript?, include_images?)`.
`source` must be a path like `~/Desktop/My Video.mp4` (spaces fine, no quotes). URLs are not accepted.
