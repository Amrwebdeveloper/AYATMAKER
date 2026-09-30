"""Run many Quran video jobs: python -m ayatmaker.batch --config batch.json --out output"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from .api import CACHE_DIR, READERS, ayah_count, media_duration
from .footage import CLIP_MODES
from .make import DEFAULT_FONT, DEFAULT_TEMPLATE, FONTS, TEMPLATES, parse_ayah_range, run_job

ROTATION = list(TEMPLATES)


def resolve_range(surah: int, spec: str, cache: Path) -> tuple[int, int, str]:
    spec = str(spec).strip().lower()
    if spec == "all":
        n = ayah_count(surah, cache)
        return 1, n, f"1-{n}"
    first, last = parse_ayah_range(spec)
    return first, last, (str(first) if first == last else f"{first}-{last}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Batch-build Quran videos (resumable)")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("output"))
    ap.add_argument("--template", choices=["auto", *ROTATION], default=None,
                    help="auto = rotate templates per video (fixed within a video)")
    ap.add_argument("--font", choices=FONTS, default=None)
    ap.add_argument("--clips", choices=CLIP_MODES, default=None, help="pexels | mine | mixed (default: auto)")
    ap.add_argument("--dry-run", action="store_true", help="list planned outputs and skip/run status only")
    args = ap.parse_args(argv)
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    jobs = cfg["jobs"]
    rows: list[tuple[str, str, str]] = []
    idx = -1  # index over ALL (job, reader) videos, independent of skip state
    for job in jobs:
        for reader in job["readers"]:
            idx += 1
            label = f"{job['surah']}:{job['ayah']}:{reader}"
            try:
                if reader not in READERS:
                    raise ValueError(f"unknown reader {reader}")
                surah = int(job["surah"])
                first, last, ref = resolve_range(surah, job["ayah"], CACHE_DIR)
                template = job.get("template") or args.template or cfg.get("template") or DEFAULT_TEMPLATE
                if template == "auto":
                    template = ROTATION[idx % len(ROTATION)]
                font = args.font or job.get("font") or cfg.get("font") or DEFAULT_FONT
                clips = job.get("clips") or args.clips or cfg.get("clips") or None
                if clips is not None and clips not in CLIP_MODES:
                    raise ValueError(f"unknown clips mode {clips!r}")
                out_file = args.out / f"quran_{surah}_{ref}_{reader}_{template}.mp4"
                done = out_file.exists() and out_file.stat().st_size > 0
                if args.dry_run:
                    print(f"[{'skip' if done else 'run '}] {template:<10} {out_file}")
                    rows.append((label, "skipped" if done else "planned", f"{template} -> {out_file.name}"))
                    continue
                if done:
                    print(f"[skip] {out_file}")
                    rows.append((label, "skipped", f"{media_duration(out_file):.1f}s"))
                    continue
                print(f"[run ] {label}")
                run_job(surah, first, last, ref, reader, args.out, template, font, clips)
                rows.append((label, "ok", f"{media_duration(out_file):.1f}s"))
            except Exception as e:  # noqa: BLE001 - log and continue
                traceback.print_exc()
                rows.append((label, "failed", f"{type(e).__name__}: {str(e)[:80]}"))
            time.sleep(1)
    print("\n{:<28} {:<9} {}".format("job", "status", "detail"))
    for r in rows:
        print("{:<28} {:<9} {}".format(*r))
    counts = {k: sum(1 for r in rows if r[1] == k) for k in ("ok", "skipped", "failed", "planned")}
    print(f"\nok={counts['ok']} skipped={counts['skipped']} failed={counts['failed']} planned={counts['planned']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
