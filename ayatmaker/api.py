"""alquran.cloud client with on-disk caching. Text is used exactly as returned."""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import requests

API = "https://api.alquran.cloud/v1/ayah/{surah}:{ayah}/{edition}"
AUDIO = "https://cdn.islamic.network/quran/audio/{bitrate}/{edition}/{number}.mp3"

AUDIO_BITRATES = (128, 192, 64)

# reader key -> (audio edition, display name)
READERS: dict[str, tuple[str, str]] = {
    "alafasy": ("ar.alafasy", "Mishary Alafasy"),
    "mahermuaiqly": ("ar.mahermuaiqly", "Maher Al-Muaiqly"),
    "sudais": ("ar.abdurrahmaansudais", "Abdur-Rahman As-Sudais"),
}

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"


class QuranApiError(RuntimeError):
    pass


@dataclass
class Ayah:
    surah: int
    number_in_surah: int
    global_number: int
    arabic: str
    english: str
    surah_name_ar: str
    surah_name_en: str
    audio_path: Path
    audio_duration: float


def _get_json(surah: int, ayah: int, edition: str, cache: Path) -> dict:
    path = cache / f"{edition}_{surah}_{ayah}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    r = None
    for attempt in range(4):
        try:
            r = requests.get(API.format(surah=surah, ayah=ayah, edition=edition), timeout=30)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            break
        time.sleep(1.5 * (attempt + 1))
    if r is None:
        raise QuranApiError(f"alquran.cloud {edition} {surah}:{ayah} unreachable")
    if r.status_code != 200:
        raise QuranApiError(f"alquran.cloud {edition} {surah}:{ayah} -> HTTP {r.status_code}")
    data = r.json()
    if data.get("code") != 200 or "data" not in data:
        raise QuranApiError(f"unexpected API response for {surah}:{ayah} ({edition})")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _get_audio(edition: str, number: int, cache: Path) -> Path:
    """Download the mp3. 128kbps is preferred; some editions only exist at 192/64kbps."""
    path = cache / f"audio_{edition}_{number}.mp3"
    if path.exists() and path.stat().st_size > 0:
        return path
    errors: list[str] = []
    for bitrate in AUDIO_BITRATES:
        url = AUDIO.format(bitrate=bitrate, edition=edition, number=number)
        for _ in range(2):
            try:
                r = requests.get(url, timeout=(15, 120))
            except requests.RequestException as e:
                errors.append(f"{bitrate}: {type(e).__name__}")
                continue
            if r.status_code == 200 and r.content:
                tmp = path.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(path)
                return path
            errors.append(f"{bitrate}: HTTP {r.status_code}")
            if r.status_code in (403, 404):
                break
    raise QuranApiError(f"audio download failed for {edition}/{number}: {'; '.join(errors)}")


TRIM_THRESHOLD_DB = -45
TRIM_EDGE_SECONDS = 0.06


def _trim_audio(raw: Path, cache: Path) -> Path:
    """Strip leading/trailing silence, then keep a short pad at each edge. Cached apart from the raw mp3."""
    out = cache / raw.name.replace("audio_", "audio_trim_", 1).replace(".mp3", ".wav")
    if out.exists() and out.stat().st_size > 0:
        return out
    strip = f"silenceremove=start_periods=1:start_threshold={TRIM_THRESHOLD_DB}dB:start_silence=0"
    pad_ms = int(TRIM_EDGE_SECONDS * 1000)
    af = (f"{strip},areverse,{strip},areverse,"
          f"adelay={pad_ms}:all=1,apad=pad_dur={TRIM_EDGE_SECONDS}")
    tmp = out.with_suffix(".part.wav")
    p = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                        "-af", af, "-ar", "44100", "-ac", "2", str(tmp)], capture_output=True, text=True)
    if p.returncode != 0 or not tmp.exists():
        raise QuranApiError(f"audio trim failed for {raw.name}: {p.stderr[-500:]}")
    tmp.replace(out)
    return out


def media_duration(path: Path) -> float:
    """Duration in seconds, read from ffmpeg's stream info (no ffprobe needed)."""
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not m:
        raise QuranApiError(f"cannot read duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def fetch_ayah(surah: int, ayah: int, reader: str, cache: Path) -> Ayah:
    if reader not in READERS:
        raise QuranApiError(f"unsupported reader {reader!r}; choose from {sorted(READERS)}")
    cache.mkdir(parents=True, exist_ok=True)
    ar = _get_json(surah, ayah, "quran-uthmani", cache)["data"]
    en = _get_json(surah, ayah, "en.sahih", cache)["data"]
    audio = _trim_audio(_get_audio(READERS[reader][0], ar["number"], cache), cache)
    return Ayah(
        surah=surah,
        number_in_surah=ar["numberInSurah"],
        global_number=ar["number"],
        arabic=ar["text"],
        english=en["text"],
        surah_name_ar=ar["surah"]["name"],
        surah_name_en=ar["surah"]["englishName"],
        audio_path=audio,
        audio_duration=media_duration(audio),
    )


def ayah_count(surah: int, cache: Path) -> int:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"surah_{surah}_meta.json"
    if not path.exists():
        for attempt in range(4):
            try:
                r = requests.get(f"https://api.alquran.cloud/v1/surah/{surah}", timeout=15)
                break
            except requests.RequestException:
                if attempt == 3:
                    raise
        if r.status_code != 200:
            raise QuranApiError(f"surah {surah} meta -> HTTP {r.status_code}")
        path.write_text(json.dumps(r.json(), ensure_ascii=False), encoding="utf-8")
    return int(json.loads(path.read_text(encoding="utf-8"))["data"]["numberOfAyahs"])
