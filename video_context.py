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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_PROG = threading.local()


def set_progress(cb):
    """cb(message) is called with short status lines while a video is processed (the MCP server turns
    them into progress notifications so Claude shows 'Pulling out the audio...')."""
    _PROG.cb = cb


def progress(msg):
    print(msg, flush=True)
    cb = getattr(_PROG, "cb", None)
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def space_sentences(text):
    """Blank line between sentences, so a dialog or Claude is easy to read."""
    text = (text or "").strip()
    if "\n\n" in text:
        return text
    return re.sub(r"(?<=[.?!])[ \t]+(?=[A-Z])", "\n\n", text)


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


def _safe_exists(p):
    """os.path.exists that cannot hang on a macOS permission popup (answers False if it does not reply)."""
    try:
        return bool(guarded("exists:" + p, lambda: os.path.exists(p)))
    except (Blocked, OSError):
        return False


def _safe_isfile(p):
    try:
        return bool(guarded("isfile:" + p, lambda: os.path.isfile(p)))
    except (Blocked, OSError):
        return False


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
    if not _safe_exists(s) and "\\ " in s:
        s2 = s.replace("\\ ", " ")
        if _safe_exists(s2):
            s = s2
    if not os.path.isabs(s):
        for base in (os.getcwd(), os.path.expanduser("~")):
            cand = os.path.join(base, s)
            if _safe_exists(cand):
                s = cand
                break
        else:
            s = os.path.join(os.path.expanduser("~"), s)
    return os.path.normpath(s)


# ---- Never-hang folder access ---------------------------------------------------------------
# On a Mac, the first time a program opens Desktop / Downloads / Documents, macOS shows a permission
# popup and the program is FROZEN until the user answers. So every folder access runs in a helper
# thread with a short time limit; if it doesn't answer, we skip the folder and tell the user to click
# the popup, instead of hanging.
_G_LOCK = threading.Lock()
_G_PEND = {}
_TLS = threading.local()
SCAN_TIMEOUT = float(os.environ.get("UTV_SCAN_TIMEOUT", "4"))
LIST_BUDGET = float(os.environ.get("UTV_LIST_BUDGET", "6"))
RESOLVE_BUDGET = float(os.environ.get("UTV_RESOLVE_BUDGET", "10"))


class Blocked(Exception):
    pass


def blocked_dirs():
    return list(getattr(_TLS, "blocked", []))


def reset_blocked():
    _TLS.blocked = []


def begin_budget(secs):
    """All folder lookups in this call together may wait at most `secs` (so a frozen folder costs a few seconds once)."""
    _TLS.deadline = time.time() + secs


def _remaining(default):
    dl = getattr(_TLS, "deadline", None)
    if dl is None:
        return default
    return max(0.0, min(default, dl - time.time()))


def _note_blocked(key):
    if not hasattr(_TLS, "blocked"):
        _TLS.blocked = []
    if key not in _TLS.blocked:
        _TLS.blocked.append(key)


def guarded(key, fn, secs=None):
    """Run fn() in a helper thread; wait at most `secs`. Raises Blocked if the OS is not answering
    (e.g. a macOS permission popup is waiting). Errors inside fn raise OSError-like as usual."""
    secs = SCAN_TIMEOUT if secs is None else secs
    with _G_LOCK:
        ent = _G_PEND.get(key)
        if ent is not None and ent["done"].is_set():
            ent = None  # earlier call finished (user clicked OK?): run again, it is fast now
        if ent is None:
            box = {"done": threading.Event(), "val": None, "err": None}

            def work():
                try:
                    box["val"] = fn()
                except BaseException as e:  # noqa
                    box["err"] = e
                finally:
                    box["done"].set()
            t = threading.Thread(target=work, daemon=True)
            box["thread"] = t
            _G_PEND[key] = box
            t.start()
            ent = box
    ent["done"].wait(_remaining(secs))
    if not ent["done"].is_set():
        _note_blocked(key)
        raise Blocked(key)
    with _G_LOCK:
        if _G_PEND.get(key) is ent:
            del _G_PEND[key]
    if ent["err"] is not None:
        raise ent["err"]
    return ent["val"]


def blocked_message():
    ds = blocked_dirs()
    if not ds:
        return ""
    home = os.path.expanduser("~")
    tops = set()
    for x in ds:
        p = x.split(":", 1)[-1]
        rel = os.path.relpath(p, home) if p.startswith(home) else p
        tops.add(rel.split(os.sep)[0] or p)
    names = ", ".join(sorted(tops))
    return space_sentences(
        "macOS has not let me open the folder (%s) yet.\n\n"
        "Look for a popup that says the AI app (Claude / Cursor) would like to access files in your folder "
        "(it may be hidden behind other windows) and click OK or Allow, then ask again.\n\n"
        "If you never see a popup: System Settings > Privacy & Security > Files and Folders, "
        "and turn on that folder for Claude (or Cursor)." % names)


# ---- Easy file finding: the "Understand This Video" folder on the Desktop -------------------
FOLDER_NAME = "Understand This Video"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts")
LATEST_WORDS = {"", "latest", "newest", "last", "recent", "newest video", "latest video", "last video",
                "my latest video", "my newest video", "latest one", "newest one", "the latest", "the newest",
                "my last video", "most recent", "most recent video", "the latest video", "the newest video",
                "my most recent video"}
GENERIC_WORDS = {"video", "my video", "the video", "this video", "a video", "it", "this", "that", "that video", "my videos", "the file", "my file"}


def desktop_dirs():
    """Every Desktop folder that exists (handles OneDrive-redirected Desktops on Windows).
    Only looks at the Desktop folder itself and the home folder (neither triggers a Mac popup)."""
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
        try:
            if os.path.isdir(c) and c not in out:
                out.append(c)
        except OSError:
            pass
    return out


def inbox_dirs():
    """The Understand This Video folder(s), wherever the Desktop really is."""
    out = []
    for d in desktop_dirs():
        p = os.path.join(d, FOLDER_NAME)
        try:
            if guarded("isdir:" + p, lambda p=p: os.path.isdir(p)):
                out.append(p)
        except Blocked:
            out.append(p)  # it is there but macOS is asking; _videos_in will report it as blocked
        except OSError:
            pass
    return out


def ensure_inbox():
    """Create the Understand This Video folder on the Desktop if it is missing. Returns its path or ''."""
    existing = inbox_dirs()
    if existing:
        return existing[0]
    for d in desktop_dirs():
        p = os.path.join(d, FOLDER_NAME)
        try:
            guarded("mkdir:" + p, lambda p=p: os.makedirs(p, exist_ok=True))
            return p
        except (Blocked, OSError):
            continue
    return ""


def other_dirs():
    """Other places videos usually are. Never Documents (huge, and another Mac popup)."""
    home = os.path.expanduser("~")
    dirs = desktop_dirs() + [os.path.join(home, n) for n in ("Downloads", "Movies", "Videos")]
    out = []
    for d in dirs:
        try:
            if d not in out and (d in desktop_dirs() or guarded("isdir:" + d, lambda d=d: os.path.isdir(d), 2)):
                out.append(d)
        except (Blocked, OSError):
            pass
    return out


def search_dirs():
    """All folders searched for a video, best first (inbox first)."""
    out = list(inbox_dirs())
    for d in other_dirs():
        if d not in out:
            out.append(d)
    return out


def _scan(d):
    res = []
    with os.scandir(d) as it:          # one pass, not recursive, one stat per video file only
        for e in it:
            n = e.name
            if n.startswith(".") or os.path.splitext(n)[1].lower() not in VIDEO_EXTS:
                continue
            try:
                if e.is_file():
                    res.append((e.stat().st_mtime, e.path))
            except OSError:
                pass
    res.sort(reverse=True)
    return [p for _, p in res]


def _videos_in(d):
    """Videos directly inside folder d, newest first. [] if missing, forbidden, or the OS is not answering."""
    try:
        return guarded("ls:" + d, lambda: _scan(d))
    except (Blocked, OSError):
        return []


def list_videos(limit=30, everywhere=False):
    """[(path, size_bytes, mtime)] newest first. Looks ONLY in the Understand This Video folder, unless it has
    no videos or everywhere=True; then Desktop, Downloads, Movies/Videos (not recursive, never ffprobe)."""
    seen, out = set(), []

    def add(d):
        for p in _videos_in(d):
            if p not in seen:
                seen.add(p)
                try:
                    st = os.stat(p)
                    out.append((p, st.st_size, st.st_mtime))
                except OSError:
                    pass
    inbox = inbox_dirs()
    for d in inbox:
        add(d)
    if everywhere or not out:
        for d in other_dirs():
            add(d)
    first = [x for x in out if os.path.dirname(x[0]) in inbox]
    rest = [x for x in out if x not in first]
    return (first + rest)[:limit]


def _norm_name(n):
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def _newest(note_where=True):
    """Newest video: inbox first; only if it is empty, other folders."""
    inbox = inbox_dirs()
    for d in inbox:
        vids = _videos_in(d)
        if vids:
            return vids[0], "Newest video in your Understand This Video folder"
    for d in other_dirs():
        vids = _videos_in(d)
        if vids:
            return vids[0], "Newest video in %s" % d
    return "", ""


def resolve_source(src):
    """Turn what the user/AI typed into a real video file.
    Returns (path_or_url, note). Accepts a full path, a bare file name (any case, with or without the
    extension, or just part of the name), or nothing / 'latest' for the newest video."""
    begin_budget(RESOLVE_BUDGET)
    raw = (src or "").strip()
    cleaned = raw
    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'`":
        cleaned = cleaned[1:-1].strip()
    if is_url(cleaned):
        return cleaned, ""
    if _norm_name(cleaned) in LATEST_WORDS:
        return _newest()
    # 1. exactly what was given (full path, ~, relative to home, etc.)
    p = normalize_source(cleaned)
    try:
        if os.path.isabs(cleaned.replace("~", "/")) or cleaned.startswith("~"):
            if guarded("isfile:" + p, lambda: os.path.isfile(p)):
                return p, ""
    except (Blocked, OSError):
        pass
    # 2. look the NAME up (inbox first, then other folders), case-insensitive, partial match
    base = os.path.basename(cleaned.replace("\\", "/").rstrip("/")) or cleaned
    want = _norm_name(base)
    want_stem = _norm_name(os.path.splitext(base)[0])

    def find(dirs):
        tiers = ([], [], [], [])
        for d in dirs:
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
                note = "Matched your words to %s" % t[0]
                others = [os.path.basename(x) for x in t[1:4]]
                if others:
                    note += " (other possible matches: %s)" % ", ".join(others)
                return t[0], note
        return None
    hit = find(inbox_dirs()) or find(other_dirs())
    if hit:
        return hit
    # nothing matched by name: "Understand my latest video", "the video", ... -> newest video
    if re.search(r"\b(latest|newest|last|recent)\b", cleaned.lower()) or _norm_name(cleaned) in GENERIC_WORDS:
        return _newest()
    # relative path / bare name that exists somewhere under cwd or home (last resort, exact only)
    try:
        if guarded("isfile:" + p, lambda: os.path.isfile(p)):
            return p, ""
    except (Blocked, OSError):
        pass
    return p, ""


def missing_file_message(original, path):
    bm = blocked_message()
    if bm:
        return "ERROR: " + bm
    vids = list_videos(15)
    if vids:
        return space_sentences(
            "ERROR: can't find a video called '%s'.\n\nVideos I can see: %s\n\n"
            "Put the video in the '%s' folder on your Desktop, then say 'Understand my latest video'." %
            (original, ", ".join(os.path.basename(v[0]) for v in vids), FOLDER_NAME))
    if not (original or "").strip():
        return space_sentences(
            "ERROR: no videos found.\n\nPut a video in the '%s' folder on your Desktop "
            "(I will create it if needed), then ask again." % FOLDER_NAME)
    msg = "ERROR: can't find the video file.\n  You gave: %s\n  Looked at: %s" % (original, path)
    parent = os.path.dirname(path)
    try:
        names = sorted(n for n in guarded("lsall:" + parent, lambda: os.listdir(parent)) if not n.startswith("."))
        vids = [n for n in names if os.path.splitext(n)[1].lower() in
                (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")]
        msg += "\n  That folder exists; videos in it: %s" % (", ".join(vids[:15]) or "none")
    except Blocked:
        msg += "\n  " + (blocked_message() or "The computer is not answering for that folder.")
    except PermissionError:
        msg += ("\n  The computer blocked access to %s. On a Mac, allow it in System Settings > "
                "Privacy & Security > Files and Folders (for Claude / Cursor), or move the video "
                "to another folder, then try again." % parent)
    except OSError:
        msg += "\n  The folder %s doesn't exist. Check the path." % parent
    return space_sentences(msg)


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
                        "scale=320:-2,select='gt(scene,%s)',showinfo" % threshold, "-f", "null", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr.decode(errors="replace"))]


WORKERS = max(2, min(6, (os.cpu_count() or 4)))


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


def dedupe_visual(video, times, tol, cache=None):
    out, last = [], None
    cache = {} if cache is None else cache
    need = [t for t in times if t not in cache]
    if need:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for t, th in zip(need, ex.map(lambda t: thumb(video, t), need)):
                cache[t] = th
    thumbs = [cache[t] for t in times]
    for t, th in zip(times, thumbs):
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


# model name -> (approx download size in MB)
MODEL_MB = {"tiny": 75, "base": 145, "small": 480}
_MODELS = {}
_MODEL_LOCK = threading.Lock()


def pick_model(duration, requested):
    """'auto' (default): best accuracy that stays fast. Long videos use a smaller model."""
    if requested and requested != "auto":
        return requested
    if not duration or duration <= 15 * 60:
        return "small"
    if duration <= 45 * 60:
        return "base"
    return "tiny"



def model_on_disk(size):
    """True if the speech model is already downloaded (no network, no full load)."""
    home = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    hub = home / "hub" / ("models--Systran--faster-whisper-%s" % size)
    if not hub.is_dir():
        return False
    # A completed snapshot has the CTranslate2 model.bin (or model.safetensors)
    for pat in ("**/model.bin", "**/model.safetensors"):
        if any(hub.glob(pat)):
            return True
    return False


def get_model(size):
    """Load a faster-whisper model once per process and keep it (loading is the slow part).
    First tries only the files already on disk (no network check, so no waiting on a bad connection)."""
    with _MODEL_LOCK:
        m = _MODELS.get(size)
        if m is not None:
            return m
        from faster_whisper import WhisperModel  # type: ignore
        threads = int(os.environ.get("UTV_THREADS", "0") or 0) or max(4, min(8, os.cpu_count() or 4))
        try:
            m = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads, local_files_only=True)
        except Exception:
            progress("Downloading the speech model '%s' (one time, about %d MB). This can take a few minutes on a slow connection..." % (size, MODEL_MB.get(size, 500)))
            m = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads)
        _MODELS[size] = m
        return m


def transcribe(audio, out_dir, model_size, language=None):
    """Returns (path, note, segments, language). Tries model_size, then smaller models."""
    order = ["small", "base", "tiny"]
    sizes = [model_size] + [x for x in order if x != model_size and order.index(x) > order.index(model_size)] \
        if model_size in order else [model_size, "base"]
    last_err = None
    try:
        import faster_whisper  # type: ignore  # noqa: F401
        for size in sizes:
            try:
                m = get_model(size)
                progress("Writing out every word (speech model: %s)..." % size)
                it, info = m.transcribe(_pcm(audio), language=language, vad_filter=True, beam_size=1,
                                        condition_on_previous_text=False)
                segs = [(x.start, x.end, x.text.strip()) for x in it]
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


def warmup(models=("small", "base")):
    """One-time setup run by the installer: download every model/tool now so the first real video is fast.
    Re-runs skip the big downloads when the speech models are already on this computer."""
    t0 = time.time()
    ensure_path()
    ok = True
    try:
        check_tools()
        print("  ffmpeg and ffprobe: ready", flush=True)
    except SystemExit:
        print("  ffmpeg and ffprobe: NOT found. Run the installer again.", flush=True)
        ok = False
    try:
        import faster_whisper  # type: ignore  # noqa: F401
        print("  Python packages (faster-whisper): ready", flush=True)
    except ImportError:
        print("  faster-whisper is not installed", flush=True)
        return False
    missing = [size for size in models if not model_on_disk(size)]
    if not missing:
        print("Speech models already on this computer. Skipping the download.", flush=True)
    else:
        print("Getting the video tools ready (one time).", flush=True)
        for size in models:
            try:
                get_model(size)
                print("  speech model '%s': ready" % size, flush=True)
            except Exception as e:
                print("  speech model '%s' could not be downloaded (%s). It will be tried again the first time you use it." % (size, e), flush=True)
                if size == models[0]:
                    ok = False
        # tiny warm-up only on first download, so caches/codecs are hot
        try:
            import numpy as np  # type: ignore
            m = get_model(models[0])
            it, _ = m.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=False, beam_size=1)
            list(it)
            print("  warm-up transcription: ok", flush=True)
        except Exception as e:
            print("  warm-up transcription skipped (%s)" % e, flush=True)
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                clip = os.path.join(td, "t.mp4")
                run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=1:s=160x120:r=10",
                     "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", "-shortest", clip])
                probe(clip)
                extract_frame(clip, 0.5, Path(td) / "f.jpg", 128, 8)
            print("  warm-up frame cut: ok", flush=True)
        except Exception as e:
            print("  warm-up frame cut skipped (%s)" % e, flush=True)
    folder = ensure_inbox()
    if folder:
        print("  Desktop folder: %s" % folder, flush=True)
    print("All tools ready in %.0f seconds." % (time.time() - t0), flush=True)
    return ok


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
    ap.add_argument("--whisper-model", default="auto", help="auto (default: small, base for long videos), tiny, base, small, medium; falls back to a smaller one")
    ap.add_argument("--language", default=None, help="force language code (default: auto-detect)")
    ap.add_argument("--transcript-only", action="store_true",
                    help="no frames or contact sheet: speech transcript only (cheapest)")
    ap.add_argument("--no-sheet", action="store_true", help="skip contact-sheet grid image")
    ap.add_argument("--warmup", action="store_true", help="download all models/tools now (the installer does this)")
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
        sys.exit(space_sentences("This plugin only processes video files on your computer.\n\nDownload or export the video first, then put it in the Understand This Video folder on your Desktop."))
    elif not _safe_isfile(source):
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

    progress("Processing: %s (%.1fs, audio=%s)" % (title, duration, has_audio))
    t_start = time.time()
    if a.no_transcript:
        note = "skipped (--no-transcript)"
    elif not has_audio:
        note = "video has no audio stream"
    else:
        note = ""

    # Speech: runs in a background thread WHILE the frames are cut (they use different resources).
    audio_box = {"audio": None, "res": (None, note, [], None)}

    def do_audio():
        if not has_audio:
            return
        progress("Pulling out the audio...")
        audio_box["audio"] = extract_audio(source, out, a.wav)
        if not note:
            model = pick_model(duration, getattr(a, "whisper_model", "auto"))
            audio_box["res"] = transcribe(audio_box["audio"], out, model, a.language)

    audio_err = []

    parent_cb = getattr(_PROG, "cb", None)

    def audio_job():
        set_progress(parent_cb)
        try:
            do_audio()
        except BaseException as e:  # noqa
            audio_err.append(e)
    th = threading.Thread(target=audio_job, daemon=True)
    th.start()

    frames, sheet = [], None
    n_scene = None
    if not getattr(a, "transcript_only", False):
        progress("Grabbing frames throughout the video...")
        min_gap = max(0.5, min(1.0, duration / 40.0)) if duration else 0.5
        times, n_scene = pick_times(source, duration, a.scene, a.interval, a.min_frames,
                                    a.max_frames, a.threshold, min_gap)
        cache = {}
        deduped = dedupe_visual(source, times, tol=4.0, cache=cache)
        if len(deduped) < a.min_frames:  # static footage: only drop true duplicates
            deduped = dedupe_visual(source, times, tol=1.0, cache=cache)
        times = downsample(deduped, a.max_frames)

        paths = [frames_dir / ("frame_%04d_t%.1fs.jpg" % (i, t)) for i, t in enumerate(times, 1)]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(lambda pt: extract_frame(source, pt[1], pt[0], a.max_side, a.quality), zip(paths, times)))
        frames = [{"file": "frames/" + p.name, "time_s": round(t, 2), "bytes": p.stat().st_size}
                  for p, t in zip(paths, times)]
        print("Frames: %d (scene candidates: %s)" % (len(frames), n_scene if a.scene else "n/a"))
        sheet = None if a.no_sheet else contact_sheet(frames_dir, out / "contact_sheet.jpg")
        progress("Frames done (%d). Waiting for the transcript..." % len(frames))

    th.join()
    if audio_err:
        raise audio_err[0]
    audio = audio_box["audio"]
    tpath, tnote, segs, lang = audio_box["res"]
    if has_audio and not note:
        note = tnote
        if tpath and not segs:
            note += ", no speech detected"
    if audio is not None and a.no_audio:
        audio.unlink()
        audio = None
    print("Audio: %s | Transcript: %s" % (audio.name if audio else "none", note))
    print("Timing: %.1fs" % (time.time() - t_start))
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
    if argv[:1] == ["--warmup"]:
        sys.exit(0 if warmup() else 1)
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
