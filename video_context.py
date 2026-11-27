#!/usr/bin/env python3
"""
Understand This Video Plugin: turn a video into a small set of key frames + compressed audio
(+ optional timestamped transcript) that any AI agent can read.

Usage:
  python video_context.py input.mp4 --scene
  python video_context.py input.mp4 --interval 3 --max-frames 20 --out ctx
Requires ffmpeg + ffprobe on PATH. Python 3.9+, stdlib only.
Optional transcription: pip install faster-whisper  (or openai-whisper)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

INSTALL_HINT = (
    "ffmpeg/ffprobe not found (looked on PATH, /opt/homebrew/bin, /usr/local/bin). Install it:\n"
    "  macOS:   brew install ffmpeg\n"
    "  Ubuntu:  sudo apt install ffmpeg\n"
    "  Windows: winget install ffmpeg   (or choco install ffmpeg)"
)


EXTRA_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin",
                  os.path.expanduser("~/.local/bin"), "/snap/bin",
                  r"C:\ffmpeg\bin", r"C:\ProgramData\chocolatey\bin")


def ensure_path():
    """GUI apps (Claude Desktop, Cursor) start MCP servers with a minimal PATH, so add the
    usual Homebrew/system bin dirs (and this venv's bin) to PATH."""
    cur = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    extra = [os.path.dirname(os.path.abspath(sys.executable))] + list(EXTRA_BIN_DIRS)
    add = [d for d in extra if d not in cur and os.path.isdir(d)]
    if add:
        os.environ["PATH"] = os.pathsep.join(cur + add)


def check_tools():
    ensure_path()
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        sys.stderr.write("ERROR: missing %s\n%s\n" % (", ".join(missing), INSTALL_HINT))
        sys.exit(2)


def normalize_source(src):
    """Make a user/AI-supplied path usable: trim, strip quotes, file:// URLs, ~, $VARS,
    shell-escaped spaces; relative paths resolve against cwd, then the home folder."""
    s = (src or "").strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        s = s[1:-1].strip()
    if is_url(s):
        return s
    if s.lower().startswith("file:"):
        from urllib.parse import unquote, urlparse
        u = urlparse(s)
        s = unquote(u.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", s):
            s = s[1:]
    s = os.path.expandvars(os.path.expanduser(s))
    if not os.path.exists(s) and "\\ " in s:
        s2 = s.replace("\\ ", " ")
        if os.path.exists(s2):
            s = s2
    if not os.path.isabs(s):
        for base in (os.getcwd(), os.path.expanduser("~")):
            cand = os.path.join(base, s)
            if os.path.exists(cand):
                s = cand
                break
        else:
            s = os.path.join(os.path.expanduser("~"), s)
    return os.path.normpath(s)


# ---- Easy file finding: the "Understand This Video" folder on the Desktop -------------------
FOLDER_NAME = "Understand This Video"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts")
LATEST_WORDS = {"", "latest", "newest", "last", "recent", "newest video", "latest video", "last video",
                "my latest video", "my newest video", "latest one", "newest one", "the latest", "the newest", "my last video", "most recent",
                "most recent video", "the latest video", "the newest video", "my most recent video"}
GENERIC_WORDS = {"video", "my video", "the video", "this video", "a video", "it", "this", "that", "that video", "my videos", "the file", "my file"}


def desktop_dirs():
    """Every Desktop folder that exists (handles OneDrive-redirected Desktops on Windows)."""
    home = os.path.expanduser("~")
    cands = [os.path.join(home, "Desktop")]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v:
            cands.append(os.path.join(v, "Desktop"))
    try:
        for n in sorted(os.listdir(home)):
            if n.lower().startswith("onedrive"):
                cands.append(os.path.join(home, n, "Desktop"))
    except OSError:
        pass
    out = []
    for c in cands:
        if os.path.isdir(c) and c not in out:
            out.append(c)
    return out


def inbox_dirs():
    """The Understand This Video folder(s), wherever the Desktop really is."""
    return [os.path.join(d, FOLDER_NAME) for d in desktop_dirs() if os.path.isdir(os.path.join(d, FOLDER_NAME))]


def ensure_inbox():
    """Create the Understand This Video folder on the Desktop if it is missing. Returns its path or ''."""
    existing = inbox_dirs()
    if existing:
        return existing[0]
    for d in desktop_dirs():
        p = os.path.join(d, FOLDER_NAME)
        try:
            os.makedirs(p, exist_ok=True)
            return p
        except OSError:
            continue
    return ""


def search_dirs():
    """Folders searched for a video, best first."""
    home = os.path.expanduser("~")
    dirs = list(inbox_dirs()) + desktop_dirs() + [os.path.join(home, n) for n in ("Downloads", "Movies", "Videos", "Documents")]
    out = []
    for d in dirs:
        if os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def _videos_in(d):
    try:
        names = os.listdir(d)
    except OSError:
        return []
    res = []
    for n in names:
        p = os.path.join(d, n)
        if not n.startswith(".") and os.path.splitext(n)[1].lower() in VIDEO_EXTS and os.path.isfile(p):
            try:
                res.append((os.path.getmtime(p), p))
            except OSError:
                pass
    res.sort(reverse=True)
    return [p for _, p in res]


def list_videos(limit=30):
    """[(path, size_bytes, mtime)] newest first: the inbox folder first, then Desktop/Downloads/etc."""
    seen, out = set(), []
    for d in search_dirs():
        for p in _videos_in(d):
            if p not in seen:
                seen.add(p)
                try:
                    st = os.stat(p)
                    out.append((p, st.st_size, st.st_mtime))
                except OSError:
                    pass
    inbox = [x for x in out if os.path.dirname(x[0]) in inbox_dirs()]
    rest = [x for x in out if x not in inbox]
    return (inbox + rest)[:limit]


def _norm_name(n):
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def resolve_source(src):
    """Turn what the user/AI typed into a real video file.
    Returns (path_or_url, note). Accepts a full path, a bare file name (any case, with or without the
    extension, or just part of the name), or nothing / 'latest' for the newest video."""
    raw = (src or "").strip()
    cleaned = raw
    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'`":
        cleaned = cleaned[1:-1].strip()
    if is_url(cleaned):
        return cleaned, ""
    if _norm_name(cleaned) in LATEST_WORDS:
        for d in search_dirs():
            vids = _videos_in(d)
            if vids:
                where = "your Understand This Video folder" if os.path.dirname(vids[0]) in inbox_dirs() else d
                return vids[0], "Newest video in %s" % where
        return "", ""
    # 1. exactly what was given (full path, ~, relative to home, etc.)
    p = normalize_source(cleaned)
    if os.path.isfile(p):
        return p, ""
    # 2. look the NAME up in the usual folders (inbox first), case-insensitive, partial match
    base = os.path.basename(cleaned.replace("\\", "/").rstrip("/")) or cleaned
    want = _norm_name(base)
    want_stem = _norm_name(os.path.splitext(base)[0])
    tiers = ([], [], [], [])
    for d in search_dirs():
        for v in _videos_in(d):
            n = os.path.basename(v)
            nn, ns = _norm_name(n), _norm_name(os.path.splitext(n)[0])
            if nn == want or ns == want_stem:
                tiers[0].append(v)
            elif want_stem and (ns.startswith(want_stem) or want_stem.startswith(ns) and ns):
                tiers[1].append(v)
            elif want_stem and want_stem in ns:
                tiers[2].append(v)
            elif want_stem and all(tok in nn for tok in _norm_name(base).split()):
                tiers[3].append(v)
    for t in tiers:
        if t:
            # keep folder priority: first hit in the best folder; same-folder ties -> newest first (list order)
            best = t[0]
            others = [os.path.basename(x) for x in t[1:4]]
            note = "Matched your words to %s" % best
            if others:
                note += " (other possible matches: %s)" % ", ".join(others)
            return best, note
    # nothing matched by name: "Understand my latest video", "the video", ... -> newest video
    if re.search(r"\b(latest|newest|last|recent)\b", cleaned.lower()) or _norm_name(cleaned) in GENERIC_WORDS:
        for d in search_dirs():
            vids = _videos_in(d)
            if vids:
                where = "your Understand This Video folder" if os.path.dirname(vids[0]) in inbox_dirs() else d
                return vids[0], "Newest video in %s" % where
    return p, ""


def missing_file_message(original, path):
    vids = list_videos(15)
    if vids:
        return ("ERROR: can't find a video called '%s'.\n  Videos I can see: %s\n  Tell the user to put the video in the "
                "'%s' folder on their Desktop, then say 'Understand my latest video'." %
                (original, ", ".join(os.path.basename(v[0]) for v in vids), FOLDER_NAME))
    if not (original or "").strip():
        return ("ERROR: no videos found. Tell the user to put a video in the '%s' folder on their Desktop "
                "(I will create it if needed), then ask again." % FOLDER_NAME)
    msg = "ERROR: can't find the video file.\n  You gave: %s\n  Looked at: %s" % (original, path)
    parent = os.path.dirname(path)
    try:
        names = sorted(n for n in os.listdir(parent) if not n.startswith("."))
        vids = [n for n in names if os.path.splitext(n)[1].lower() in
                (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")]
        msg += "\n  That folder exists; videos in it: %s" % (", ".join(vids[:15]) or "none")
    except PermissionError:
        msg += ("\n  The computer blocked access to %s. On a Mac, allow it in System Settings > "
                "Privacy & Security > Files and Folders (for Claude / Cursor), or move the video "
                "to another folder, then try again." % parent)
    except OSError:
        msg += "\n  The folder %s doesn't exist. Check the path." % parent
    return msg


def run(cmd, binary=False):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("Command failed: %s\n%s" % (" ".join(cmd), r.stderr.decode(errors="replace")[-2000:]))
    return r if binary else r.stdout.decode(errors="replace")


def probe(video):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
               "-of", "json", video])
    d = json.loads(out)
    dur = float(d.get("format", {}).get("duration", 0) or 0)
    types = [s.get("codec_type") for s in d.get("streams", [])]
    return dur, "video" in types, "audio" in types


def scene_times(video, threshold):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-an", "-vf",
                        "select='gt(scene,%s)',showinfo" % threshold, "-f", "null", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr.decode(errors="replace"))]


def thumb(video, t):
    """16x16 grayscale bytes used for near-duplicate detection."""
    r = run(["ffmpeg", "-v", "error", "-ss", "%.3f" % t, "-i", video, "-frames:v", "1",
             "-vf", "scale=16:16,format=gray", "-f", "rawvideo", "-"], binary=True)
    return r.stdout


def diff(a, b):
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def pick_times(video, duration, use_scene, interval, min_frames, max_frames, threshold, min_gap):
    cands = [0.0]
    if use_scene:
        cands += scene_times(video, threshold)
    n_scene = len(cands)
    if not use_scene or n_scene < min_frames:
        step = interval
        if use_scene and duration > 0:
            step = min(interval, duration / max(min_frames, 1))
        t = step
        while t < duration - 0.2:
            cands.append(t)
            t += step
    cands = sorted(set(round(c, 2) for c in cands if c < max(duration - 0.05, 0.01)))
    # time-gap dedupe
    kept = []
    for c in cands:
        if not kept or c - kept[-1] >= min_gap:
            kept.append(c)
    return kept, n_scene


def dedupe_visual(video, times, tol):
    out, last = [], None
    for t in times:
        th = thumb(video, t)
        if last is None or diff(th, last) > tol:
            out.append(t)
            last = th
    return out


def downsample(times, n):
    if len(times) <= n:
        return times
    if n == 1:
        return times[:1]
    idx = sorted(set(round(i * (len(times) - 1) / (n - 1)) for i in range(n)))
    return [times[i] for i in idx]


def extract_frame(video, t, path, max_side, q):
    vf = "scale='if(gt(iw,ih),min(%d,iw),-2)':'if(gt(iw,ih),-2,min(%d,ih))'" % (max_side, max_side)
    run(["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", video, "-frames:v", "1",
         "-vf", vf, "-q:v", str(q), str(path)])
    # shrink further if over budget
    while path.stat().st_size > 80 * 1024 and q < 15:
        q += 3
        run(["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", video, "-frames:v", "1",
             "-vf", vf, "-q:v", str(q), str(path)])


def extract_audio(video, out_dir, wav):
    if wav:
        p = out_dir / "audio.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(p)])
    else:
        p = out_dir / "audio.m4a"
        run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "aac", "-b:a", "32k", str(p)])
    return p


def fmt(t):
    return "%02d:%05.2f" % (int(t // 60), t % 60)


def _write_transcript(segs, out_dir):
    p = out_dir / "transcript.txt"
    with open(p, "w", encoding="utf-8") as f:
        for a, b, txt in segs:
            f.write("[%s - %s] %s\n" % (fmt(a), fmt(b), txt))
    return p


def _pcm(audio):
    """Decode audio to 16 kHz mono float32 via ffmpeg (avoids PyAV version issues)."""
    import numpy as np  # type: ignore  # installed with whisper packages
    r = run(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1",
             "-ar", "16000", "-"], binary=True)
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(audio, out_dir, model_size, language=None):
    """Returns (path, note, segments, language). Tries model_size, then 'base'."""
    sizes = [model_size] + (["base"] if model_size != "base" else [])
    last_err = None
    try:
        from faster_whisper import WhisperModel  # type: ignore
        for size in sizes:
            try:
                m = WhisperModel(size, device="auto", compute_type="int8")
                it, info = m.transcribe(_pcm(audio), language=language, vad_filter=True)
                segs = [(s.start, s.end, s.text.strip()) for s in it]
                return (_write_transcript(segs, out_dir), "faster-whisper (%s)" % size,
                        segs, info.language)
            except Exception as e:  # download/runtime failure -> try smaller
                last_err = e
        return None, "transcription failed: %s" % last_err, [], None
    except ImportError:
        pass
    try:
        import whisper  # type: ignore
    except ImportError:
        return None, "no transcriber installed (pip install faster-whisper)", [], None
    for size in sizes:
        try:
            m = whisper.load_model(size)
            res = m.transcribe(str(audio), language=language)
            segs = [(x["start"], x["end"], x["text"].strip()) for x in res["segments"]]
            return (_write_transcript(segs, out_dir), "openai-whisper (%s)" % size,
                    segs, res.get("language"))
        except Exception as e:
            last_err = e
    return None, "transcription failed: %s" % last_err, [], None


def is_url(s):
    return bool(re.match(r"^https?://", s, re.I))


def contact_sheet(frames_dir, out_path, cols=4, cell=256):
    files = sorted(frames_dir.glob("frame_*.jpg"))
    if not files:
        return None
    lst = frames_dir.parent / "_sheet.txt"
    with open(lst, "w") as f:
        for p in files:
            f.write("file '%s'\n" % str(p.resolve()).replace("'", "'\\''"))
    rows = (len(files) + cols - 1) // cols
    try:
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-vf", "scale=%d:-2,tile=%dx%d:padding=4:margin=4" % (cell, cols, rows),
             "-frames:v", "1", "-q:v", "8", str(out_path)])
    finally:
        lst.unlink()
    return out_path


def write_context_md(out, title, duration, frames, segs, lang, transcript_note, sheet):
    lines = ["# Understand This Video: %s" % title, "",
             "- Duration: %s (%.1fs)" % (fmt(duration), duration),
             "- Frames: %d (files in frames/, chronological)" % len(frames),
             "- Transcript: %s%s" % (transcript_note, (", language: %s" % lang) if lang else ""),
             ]
    if sheet:
        lines.append("- Overview grid: %s (all frames in one image, left-to-right, top-to-bottom)"
                     % sheet.name)
    lines += ["", "How to use: view each referenced frame and read the speech next to it. "
              "Timestamps are mm:ss.", "", "## Timeline", ""]
    events = [(f["time_s"], 0, "**[%s] FRAME** `%s`" % (fmt(f["time_s"]), f["file"]))
              for f in frames]
    events += [(a, 1, "[%s] %s" % (fmt(a), t)) for a, b, t in segs]
    for _, _, line in sorted(events):
        lines.append(line + "  ")
    p = out / "context.md"
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def make_parser():
    ap = argparse.ArgumentParser(prog="understand-this-video",
                                 description="Understand This Video Plugin: turn a video "
                                             "into timestamped key frames + transcript for AI agents")
    ap.add_argument("video", nargs="?", default="",
                    help="video file: full path, or just its name, or leave empty / say 'latest' for the newest video "
                         "in the 'Understand This Video' folder on your Desktop")
    ap.add_argument("--out", default="understand_this_video_output")
    ap.add_argument("--scene", action="store_true", help="scene detection (+interval fill if too few)")
    ap.add_argument("--threshold", type=float, default=0.3, help="scene threshold 0-1")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between interval frames")
    ap.add_argument("--min-frames", type=int, default=6)
    ap.add_argument("--max-frames", type=int, default=12)
    ap.add_argument("--max-side", type=int, default=512, help="max long side of frames in px")
    ap.add_argument("--quality", type=int, default=8, help="ffmpeg JPEG q:v (2=best, 31=worst)")
    ap.add_argument("--wav", action="store_true", help="write uncompressed audio.wav instead of .m4a")
    ap.add_argument("--no-audio", action="store_true", help="don't keep an audio file")
    ap.add_argument("--no-transcript", action="store_true")
    ap.add_argument("--whisper-model", default="small", help="falls back to base if unavailable")
    ap.add_argument("--language", default=None, help="force language code (default: auto-detect)")
    ap.add_argument("--transcript-only", action="store_true",
                    help="no frames or contact sheet: speech transcript only (cheapest)")
    ap.add_argument("--no-sheet", action="store_true", help="skip contact-sheet grid image")
    return ap


def build(a):
    """Run the pipeline for parsed args; returns the manifest dict."""
    check_tools()
    orig_source = a.video
    out = Path(os.path.expanduser(a.out))
    out.mkdir(parents=True, exist_ok=True)
    ensure_inbox()
    a.video, a.resolved_note = resolve_source(a.video)
    source, title = a.video, os.path.basename(a.video)
    if is_url(a.video):
        sys.exit("This plugin only processes video files on your computer. Download or export the video first, then give me the file path.")
    elif not os.path.isfile(source):
        sys.exit(missing_file_message(orig_source, source))
    duration, has_video, has_audio = probe(source)
    if not has_video:
        sys.exit("ERROR: no video stream in %s" % source)

    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.jpg"):
        old.unlink()
    for old in ("audio.wav", "audio.m4a", "transcript.txt", "contact_sheet.jpg", "context.md"):
        if (out / old).exists():
            (out / old).unlink()

    print("Processing: %s (%.1fs, audio=%s)" % (title, duration, has_audio))
    frames, sheet = [], None
    if not getattr(a, "transcript_only", False):
        min_gap = max(0.5, min(1.0, duration / 40.0)) if duration else 0.5
        times, n_scene = pick_times(source, duration, a.scene, a.interval, a.min_frames,
                                    a.max_frames, a.threshold, min_gap)
        deduped = dedupe_visual(source, times, tol=4.0)
        if len(deduped) < a.min_frames:  # static footage: only drop true duplicates
            deduped = dedupe_visual(source, times, tol=1.0)
        times = downsample(deduped, a.max_frames)

        frames = []
        for i, t in enumerate(times, 1):
            p = frames_dir / ("frame_%04d_t%.1fs.jpg" % (i, t))
            extract_frame(source, t, p, a.max_side, a.quality)
            frames.append({"file": "frames/" + p.name, "time_s": round(t, 2), "bytes": p.stat().st_size})
        print("Frames: %d (scene candidates: %s)" % (len(frames), n_scene if a.scene else "n/a"))
        sheet = None if a.no_sheet else contact_sheet(frames_dir, out / "contact_sheet.jpg")

    audio, tpath, segs, lang = None, None, [], None
    if a.no_transcript:
        note = "skipped (--no-transcript)"
    elif not has_audio:
        note = "video has no audio stream"
    else:
        note = ""
    if has_audio and not (a.no_audio and tpath):
        audio = extract_audio(source, out, a.wav)
        if not note:
            tpath, note, segs, lang = transcribe(audio, out, a.whisper_model, a.language)
            if tpath and not segs:
                note += ", no speech detected"
        if a.no_audio:
            audio.unlink()
            audio = None
    print("Audio: %s | Transcript: %s" % (audio.name if audio else "none", note))
    ctx = write_context_md(out, title, duration, frames, segs, lang, note, sheet)

    if not frames:
        instructions = "Read context.md: it holds the timestamped speech transcript (transcript-only mode, no frames)."
    else:
      instructions = ("Read context.md first: it interleaves timestamped frames and speech. "
                    "View the referenced frames (or contact_sheet.jpg for a one-image overview).")
    with open(out / "README.txt", "w") as f:
        f.write(instructions + "\n")
    def fsize(p):
        return {"file": p.name, "bytes": p.stat().st_size} if p else None
    manifest = {
        "source": a.video,
        "title": title,
        "duration_seconds": round(duration, 2),
        "has_audio": has_audio,
        "frame_mode": "scene+interval" if a.scene else "interval",
        "frame_count": len(frames),
        "frames": frames,
        "contact_sheet": fsize(sheet),
        "context_md": fsize(ctx),
        "audio": fsize(audio),
        "transcript": fsize(tpath),
        "transcript_source": note,
        "language": lang,
        "instructions": instructions,
    }
    manifest["total_output_bytes"] = sum(
        p.stat().st_size for p in out.rglob("*") if p.is_file() and p.name != "MANIFEST.json")
    with open(out / "MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print("Done: %s  (total %.1f KB)" % (out, manifest["total_output_bytes"] / 1024.0))
    return manifest


def main(argv=None):
    import licensing
    argv = sys.argv[1:] if argv is None else argv
    if licensing.cli(argv):
        return
    if any(a in ("-h", "--help") for a in argv):
        make_parser().parse_args(["--help"])  # help needs no license
    try:
        licensing.require_license()
    except licensing.LicenseError as e:
        sys.stderr.write("License error: %s\n" % e)
        sys.exit(5)
    build(make_parser().parse_args(argv))


if __name__ == "__main__":
    main()
