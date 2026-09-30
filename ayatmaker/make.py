"""Build a vertical Quran video: python -m ayatmaker.make --surah 2 --ayah 255 --reader alafasy --out output/"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from . import render
from .templates.htmlrender import check_font
from .api import CACHE_DIR, FFMPEG, READERS, Ayah, fetch_ayah, media_duration
from .footage import CLIP_MODES, pick_clips

FPS = 30
PAD_START = 0.5
PAD_END = 0.5
FADE_OUT = 1.0
XFADE = 0.8
SEG_TARGET = 9.0
TITLE_START, TITLE_END = 0.3, 2.8
TEXT_FADE = 0.25
AYAH_GAP_SECONDS = 0.20
TEMPLATES = ("elegant", "gold-frame", "glass")
FONTS = ("scheherazade", "scheherazade-bold", "naskh", "amiri", "kfgqpc")
DEFAULT_TEMPLATE = "elegant"
DEFAULT_FONT = "scheherazade-bold"


def parse_ayah_range(value: str) -> tuple[int, int]:
    a, _, b = value.partition("-")
    first, last = int(a), int(b or a)
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError(f"invalid ayah range {value!r}")
    return first, last


def build_overlays(ayahs: list[Ayah], reader_name: str, work: Path, template: str = DEFAULT_TEMPLATE,
                   font: str = DEFAULT_FONT) -> list[tuple[Path, float, float]]:
    """Return (png, start, end) overlays with text timed proportionally over the audio (HTML template via Playwright)."""
    from .templates.htmlrender import HtmlRenderer
    with HtmlRenderer(template, font) as hr:
        return _overlays(ayahs, reader_name, work, hr.render_title,
                         lambda ar, en, png, n: hr.render_body(ar, en, png, n))


def _overlays(ayahs, reader_name, work, title_fn, body_fn) -> list[tuple[Path, float, float]]:
    overlays: list[tuple[Path, float, float]] = []
    first, last = ayahs[0], ayahs[-1]
    ref = f"Ayah {first.number_in_surah}" if first is last else f"Ayat {first.number_in_surah}-{last.number_in_surah}"
    title = work / "title.png"
    title_fn(first.surah_name_ar, first.surah_name_en, ref, reader_name, title)
    overlays.append((title, TITLE_START, TITLE_END))

    t = PAD_START
    for idx, a in enumerate(ayahs):
        end = t + a.audio_duration
        ar, en = render.chunk_pair(a.arabic, a.english)
        for i, (s, e) in enumerate(render.proportional_bounds(ar, t, end)):
            png = work / f"text_{a.number_in_surah}_{i}.png"
            body_fn(ar[i], en[i], png, a.number_in_surah)
            overlays.append((png, s, e))
        t = end + (AYAH_GAP_SECONDS if idx < len(ayahs) - 1 else 0)
    return overlays


def build_video(ayahs: list[Ayah], reader: str, out_file: Path, cache: Path, template: str = DEFAULT_TEMPLATE,
                font: str = DEFAULT_FONT, clips_mode: str | None = None) -> list[dict]:
    audio_total = sum(a.audio_duration for a in ayahs) + AYAH_GAP_SECONDS * (len(ayahs) - 1)
    total = PAD_START + audio_total + PAD_END
    n = max(1, math.ceil((total - XFADE) / SEG_TARGET))
    seg = (total - XFADE) / n
    clip_objs = pick_clips(n, seg + XFADE, cache / "footage", seed=ayahs[0].global_number, mode=clips_mode)
    clips = [c.path for c in clip_objs]

    work = cache / "work"
    work.mkdir(parents=True, exist_ok=True)
    overlays = build_overlays(ayahs, READERS[reader][1], work, template, font)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    for c in clips:
        cmd += ["-t", f"{seg + XFADE:.3f}", "-i", str(c)]
    for a in ayahs:
        cmd += ["-i", str(a.audio_path)]
    for png, s, e in overlays:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{e - s:.3f}", "-i", str(png)]

    f: list[str] = []
    for i in range(n):
        f.append(
            f"[{i}:v]setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,format=yuv420p,fps={FPS}[c{i}]"
        )
    last = "c0"
    for k in range(1, n):
        f.append(f"[{last}][c{k}]xfade=transition=fade:duration={XFADE}:offset={k * seg:.3f},fps={FPS}[x{k}]")
        last = f"x{k}"
    f.append(f"[{last}]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.35:t=fill[bg0]")
    cur = "bg0"
    base = n + len(ayahs)
    for j, (png, s, e) in enumerate(overlays):
        d = e - s
        fd = min(TEXT_FADE, d / 3)
        f.append(
            f"[{base + j}:v]format=rgba,fade=t=in:st=0:d={fd:.3f}:alpha=1,"
            f"fade=t=out:st={d - fd:.3f}:d={fd:.3f}:alpha=1,setpts=PTS-STARTPTS+{s:.3f}/TB[o{j}]"
        )
        f.append(f"[{cur}][o{j}]overlay=x=0:y=0:eof_action=pass:enable='between(t,{s:.3f},{e:.3f})'[b{j}]")
        cur = f"b{j}"
    f.append(f"[{cur}]trim=duration={total:.3f},setpts=PTS-STARTPTS,format=yuv420p[v]")

    gap = lambda i: f",apad=pad_dur={AYAH_GAP_SECONDS}" if i < len(ayahs) - 1 else ""
    ains = "".join(f"[{n + i}:a]aresample=44100,aformat=channel_layouts=stereo{gap(i)}[a{i}];" for i in range(len(ayahs)))
    ajoin = "".join(f"[a{i}]" for i in range(len(ayahs)))
    f.append(
        ains + f"{ajoin}concat=n={len(ayahs)}:v=0:a=1,loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"adelay={int(PAD_START * 1000)}:all=1,apad=whole_dur={total:.3f},"
        f"afade=t=out:st={total - FADE_OUT:.3f}:d={FADE_OUT}[a]"
    )
    script = work / "filter.txt"
    script.write_text(";\n".join(f), encoding="utf-8")

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".tmp.mp4")
    cmd += [
        "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-f", "mp4", str(tmp),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{p.stderr[-2000:]}")
    tmp.replace(out_file)

    used = [
        {"index": k + 1, "source": c.source, "pexels_id": c.pexels_id, "origin": c.origin, "cached_file": c.path.name,
         "start": round(k * seg, 3), "end": round(total if k == n - 1 else (k + 1) * seg + XFADE, 3),
         "source_start": c.source_start}
        for k, c in enumerate(clip_objs)
    ]
    out_file.with_name(out_file.stem + ".clips.json").write_text(
        json.dumps({"video": out_file.name, "clips": used}, indent=2, ensure_ascii=False), encoding="utf-8")
    return used


def run_job(surah: int, first: int, last: int, ref: str, reader: str, out: Path, template: str = DEFAULT_TEMPLATE,
            font: str = DEFAULT_FONT, clips_mode: str | None = None) -> Path:
    check_font(font)  # fail before any network work
    cache = CACHE_DIR
    ayahs = [fetch_ayah(surah, n, reader, cache) for n in range(first, last + 1)]
    out_file = out / f"quran_{surah}_{ref}_{reader}_{template}.mp4"
    used = build_video(ayahs, reader, out_file, cache, template, font, clips_mode)
    print(f"{out_file}  audio={sum(a.audio_duration for a in ayahs):.2f}s  video={media_duration(out_file):.2f}s")
    print("clips used:")
    for u in used:
        ident = f"pexels id {u['pexels_id']}" if u["pexels_id"] else u["source"]
        print(f"  {u['index']}. t={u['start']:6.2f}s  [{u['source']}] {ident}  {u['cached_file']}  <- {u['origin']}")
    return out_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a Quran nature video")
    ap.add_argument("--surah", type=int, required=True)
    ap.add_argument("--ayah", type=parse_ayah_range, required=True, help="N or FROM-TO")
    ap.add_argument("--reader", required=True, choices=sorted(READERS))
    ap.add_argument("--out", type=Path, default=Path("output"))
    ap.add_argument("--template", choices=TEMPLATES, default=DEFAULT_TEMPLATE, help="HTML template")
    ap.add_argument("--font", choices=FONTS, default=DEFAULT_FONT, help="Arabic font")
    ap.add_argument("--clips", choices=CLIP_MODES, default=None,
                    help="footage source: pexels | mine (my_clips/) | mixed (default: mixed if my_clips has clips, else pexels)")
    args = ap.parse_args(argv)

    first, last = args.ayah
    ref = str(first) if first == last else f"{first}-{last}"
    run_job(args.surah, first, last, ref, args.reader, args.out, args.template, args.font, args.clips)
    return 0


if __name__ == "__main__":
    sys.exit(main())
