"""Nature footage: a small self-contained Pexels client (search, download, normalise to 1080x1920)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import requests

from .api import FFMPEG, ROOT, media_duration
from .exclude import MY_CLIPS_DIR, Exclusions, pexels_id_from_url

SEARCH_URL = "https://api.pexels.com/videos/search"
TARGET_W, TARGET_H = 1080, 1920
MIN_W = 720  # smallest portrait rendition still considered HD
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"

QUERIES = [
    "forest nature",
    "ocean waves",
    "mountains sunrise",
    "clouds sky",
    "waterfall nature",
]


CLIP_MODES = ("pexels", "mine", "mixed")
LOCAL_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
MIN_LOCAL_SECONDS = 2.0


class FootageError(RuntimeError):
    pass


@dataclass
class Clip:
    path: Path
    source: str  # "pexels" | "mine"
    origin: str  # Pexels download url or local file path
    pexels_id: str | None = None
    source_start: float = 0.0  # offset inside the original file (local clips only)


def get_api_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        cfg = ROOT / "config.toml"
        if cfg.exists():
            key = str(tomllib.loads(cfg.read_text(encoding="utf-8")).get("pexels_api_key", "")).strip()
    if not key:
        raise FootageError(
            "Pexels API key missing: set env PEXELS_API_KEY or add pexels_api_key = \"...\" to "
            f"{ROOT / 'config.toml'} (see config.example.toml; free key at https://www.pexels.com/api/)"
        )
    return key


def _best_file(video: dict) -> dict | None:
    """Exact 1080x1920 if offered, else the closest HD portrait mp4 (upscaling avoided when possible)."""
    best, best_key = None, None
    for f in video.get("video_files") or []:
        try:
            w, h = int(f["width"]), int(f["height"])
        except (KeyError, TypeError, ValueError):
            continue
        link = f.get("link")
        if not isinstance(link, str) or not link or h <= w or w < MIN_W:
            continue
        if f.get("file_type") not in (None, "video/mp4"):
            continue
        key = ((w, h) != (TARGET_W, TARGET_H), w < TARGET_W or h < TARGET_H, abs(w - TARGET_W) + abs(h - TARGET_H))
        if best_key is None or key < best_key:
            best, best_key = {"url": link, "width": w, "height": h}, key
    return best


def _search(query: str, min_duration: int, cache: Path) -> list[dict]:
    path = cache / f"search_{query.replace(' ', '_')}_{min_duration}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    headers = {"Authorization": get_api_key(), "User-Agent": UA}
    params = {"query": query, "orientation": "portrait", "size": "medium", "per_page": 20}
    videos: list = []
    for attempt in range(3):
        try:
            r = requests.get(SEARCH_URL, headers=headers, params=params, timeout=(15, 45))
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (401, 403):
            raise FootageError(f"Pexels rejected the API key (HTTP {r.status_code})")
        if r.status_code == 200:
            videos = r.json().get("videos") or []
            if videos:
                break
        time.sleep(3 * (attempt + 1))
    out = []
    for v in videos:
        dur = v.get("duration")
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or dur < min_duration:
            continue
        f = _best_file(v)
        if f:
            out.append({**f, "duration": dur})
    time.sleep(0.5)
    if out:  # never cache an empty/failed search
        path.write_text(json.dumps(out), encoding="utf-8")
    return out


def _download(item: dict, cache: Path) -> Path | None:
    """Download (size cap, retries, timeouts), validate, and return a 1080x1920 clip path (cached)."""
    h = hashlib.md5(item["url"].split("#", 1)[0].encode()).hexdigest()
    raw = cache / f"vid-{h}.mp4"
    exact = (item["width"], item["height"]) == (TARGET_W, TARGET_H)
    final = raw if exact else cache / f"vid-{h}_1080x1920.mp4"
    if final.exists() and final.stat().st_size > 0:
        return final

    if not (raw.exists() and raw.stat().st_size > 0):
        tmp = raw.with_suffix(".part")
        ok = False
        for attempt in range(3):
            try:
                with requests.get(item["url"], headers={"User-Agent": UA}, stream=True, timeout=(30, 120)) as r:
                    r.raise_for_status()
                    try:
                        if int(r.headers.get("Content-Length", 0)) > MAX_DOWNLOAD_BYTES:
                            raise FootageError("video exceeds size cap")
                    except ValueError:
                        pass
                    size = 0
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise FootageError("video exceeds size cap")
                            fh.write(chunk)
                if size > 0:
                    ok = True
                    break
            except FootageError:
                break
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
        if not ok:
            tmp.unlink(missing_ok=True)
            return None
        try:
            media_duration(tmp)  # validates that ffmpeg can read it
        except Exception:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(raw)

    if exact:
        return raw
    part = final.with_suffix(".part.mp4")
    vf = f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H},setsar=1,fps=30"
    p = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-an", "-vf", vf,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(part)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not part.exists():
        part.unlink(missing_ok=True)
        return None
    part.replace(final)
    return final


def scan_local(root: Path = MY_CLIPS_DIR) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in LOCAL_EXTS),
                  key=lambda p: p.relative_to(root).as_posix().lower())


def default_mode(exclusions: Exclusions | None = None, root: Path = MY_CLIPS_DIR) -> str:
    ex = exclusions if exclusions is not None else Exclusions.load()
    usable = [p for p in scan_local(root) if not ex.local_excluded(p.relative_to(root).as_posix())]
    return "mixed" if usable else "pexels"


def probe_video(path: Path) -> tuple[float, int, int] | None:
    """(duration, width, height) parsed from ffmpeg stderr, or None if unreadable / no video stream."""
    try:
        p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    except OSError:
        return None
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    v = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", p.stderr)
    if not d or not v:
        return None
    h, m, s = d.groups()
    return int(h) * 3600 + int(m) * 60 + float(s), int(v.group(1)), int(v.group(2))


def _normalize_local(path: Path, dur: float, need: float, start: float, cache: Path) -> Path | None:
    """Convert a user clip to 1080x1920 30fps, no audio, cached by (path, size, mtime, start, length)."""
    st = path.stat()
    length = math.ceil(need) + 1
    key = hashlib.md5(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{start:.2f}|{length}".encode()).hexdigest()
    mine = cache.parent / "mine"
    mine.mkdir(parents=True, exist_ok=True)
    final = mine / f"mine-{key}.mp4"
    if final.exists() and final.stat().st_size > 0:
        return final
    part = final.with_suffix(".part.mp4")
    vf = f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H},setsar=1,fps=30"
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    if dur < length:
        cmd += ["-stream_loop", "-1"]  # short clip: loop it to cover one segment
    else:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", str(path), "-t", str(length), "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-f", "mp4", str(part)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not part.exists() or part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        return None
    part.replace(final)
    return final


def pick_clips(count: int, min_duration: float, cache: Path, seed: int, mode: str | None = None,
               exclusions: Exclusions | None = None, clips_dir: Path = MY_CLIPS_DIR) -> list[Clip]:
    """Return `count` clips (1080x1920 files), never the same clip twice in a row (when >1 clip is available)."""
    cache.mkdir(parents=True, exist_ok=True)
    ex = exclusions if exclusions is not None else Exclusions.load()
    mode = mode or default_mode(ex, clips_dir)
    if mode not in CLIP_MODES:
        raise FootageError(f"unknown clips mode {mode!r}; choose from {CLIP_MODES}")
    rng = random.Random(seed)
    need = int(min_duration) + 1
    pool: list[dict] = []
    ex_pex = ex_loc = 0

    local_all = scan_local(clips_dir) if mode in ("mine", "mixed") else []
    local: list[dict] = []
    if mode in ("pexels", "mixed"):
        seen: set[str] = set()
        try:
            for q in QUERIES:
                for it in _search(q, need, cache):
                    if it["url"] in seen:
                        continue
                    seen.add(it["url"])
                    if ex.pexels_excluded(it["url"]):
                        ex_pex += 1
                        continue
                    pool.append({**it, "source": "pexels"})
        except FootageError as e:
            if mode == "pexels" or not local_all:
                raise
            print(f"[clips] warning: Pexels unavailable ({e}); using my_clips only")
    for p in local_all:
        rel = p.relative_to(clips_dir).as_posix()
        if ex.local_excluded(rel):
            ex_loc += 1
            continue
        info = probe_video(p)
        if info is None:
            print(f"[clips] warning: skipping unreadable file {rel}")
            continue
        if info[0] < MIN_LOCAL_SECONDS:
            print(f"[clips] warning: skipping {rel} (only {info[0]:.1f}s, minimum {MIN_LOCAL_SECONDS:.0f}s)")
            continue
        local.append({"source": "mine", "path": p, "rel": rel, "duration": info[0]})
    n_pex = len(pool)
    pool += local
    print(f"[clips] mode={mode} pexels={n_pex} mine={len(local)} excluded: pexels={ex_pex} mine={ex_loc}")

    if mode == "mine":
        if not local:
            raise FootageError(f"no usable clips in {clips_dir} (mp4/mov/webm/mkv, >= {MIN_LOCAL_SECONDS:.0f}s)")
        total = sum(it["duration"] for it in local)
        if total < min_duration:
            raise FootageError(f"not enough footage in {clips_dir}: {total:.1f}s total, need at least "
                               f"{min_duration:.1f}s (one segment); add more or longer clips")
    if not pool:
        raise FootageError("no portrait nature footage found on Pexels (after exclusions)" if mode == "pexels"
                           else "no usable clips (Pexels or my_clips) after exclusions")
    rng.shuffle(pool)

    clips: list[Clip] = []
    length = math.ceil(min_duration) + 1
    for it in pool:
        if len(clips) >= min(count, len(pool)):
            break
        if it["source"] == "pexels":
            p = _download(it, cache)
            if p:
                clips.append(Clip(p, "pexels", it["url"], pexels_id_from_url(it["url"])))
        else:
            start = round(rng.uniform(0, it["duration"] - length), 1) if it["duration"] > length else 0.0
            p = _normalize_local(it["path"], it["duration"], min_duration, start, cache)
            if p:
                clips.append(Clip(p, "mine", str(it["path"]), None, start))
            else:
                print(f"[clips] warning: could not convert {it['rel']}; skipped")
    if not clips:
        raise FootageError("could not obtain any footage")

    # Cycle if fewer unique clips than needed, keeping neighbours different.
    seq: list[Clip] = []
    while len(seq) < count:
        block = clips[:]
        rng.shuffle(block)
        if seq and len(clips) > 1 and block[0] is seq[-1]:
            block.append(block.pop(0))
        seq.extend(block)
    if len(clips) < count:
        print(f"[clips] note: only {len(clips)} unique clip(s) for {count} segments; clips are reused")
    return seq[:count]
