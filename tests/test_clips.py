"""Quick assertions (no pytest): python tests/test_clips.py"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ayatmaker import footage  # noqa: E402
from ayatmaker.api import FFMPEG  # noqa: E402
from ayatmaker.exclude import Exclusions, cmd_add, cmd_remove, normalize, pexels_id_from_url, url_hash  # noqa: E402

URL_A = "https://videos.pexels.com/video-files/3571264/3571264-hd_1080_1920_30fps.mp4"
URL_B = "https://videos.pexels.com/video-files/999001/999001-hd_1080_1920_30fps.mp4"

# --- exclusion parsing
assert pexels_id_from_url(URL_A) == "3571264"
assert pexels_id_from_url("https://www.pexels.com/video/green-forest-3571264/") == "3571264"
assert pexels_id_from_url("https://www.pexels.com/video/3571264/") == "3571264"
assert normalize("https://www.pexels.com/video/green-forest-3571264/") == "3571264"
ex = Exclusions.parse(f"""# comment
3571264   # inline comment
vid-{url_hash(URL_B)}_1080x1920.mp4
Beach.MP4
trips/Sea.mov
my_clips/old/*
*.webm
""")
assert ex.pexels_excluded(URL_A) and ex.pexels_excluded(URL_B)
assert not ex.pexels_excluded("https://videos.pexels.com/video-files/42/42-x.mp4")
assert ex.local_excluded("beach.mp4") and ex.local_excluded("sub/BEACH.mp4")
assert ex.local_excluded("trips/sea.mov") and not ex.local_excluded("other/sea.mov")
assert ex.local_excluded("old/a/b.mp4") and not ex.local_excluded("new/a.mp4")
assert ex.local_excluded("x/y.webm") and not ex.local_excluded("x/y.mp4")
assert not Exclusions.parse("# only comments\n\n")

# --- add/remove helpers keep file restorable, no duplicates
tmp = Path(tempfile.mkdtemp())
try:
    f = tmp / "exclude.txt"
    f.write_text("# header\n", encoding="utf-8")
    orig = f.read_bytes()
    assert cmd_add(f, "https://www.pexels.com/video/x-77/").startswith("added: 77")
    assert cmd_add(f, "77").startswith("already")
    assert "https://www.pexels.com/video/x-77/" in f.read_text()
    assert cmd_remove(f, "77").startswith("removed 1")
    assert f.read_bytes() == orig

    # --- pool building with stubbed Pexels + real synthetic local clips
    clips_dir = tmp / "my_clips"
    clips_dir.mkdir()
    for name, size, color in (("a.mp4", "1920x1080", "red"), ("b.mp4", "1080x1920", "blue")):
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=24:d=5",
                        "-pix_fmt", "yuv420p", str(clips_dir / name)], check=True)
    (clips_dir / "broken.mp4").write_bytes(b"not a video")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=green:s=640x480:r=24:d=1",
                    "-pix_fmt", "yuv420p", str(clips_dir / "short.mp4")], check=True)

    def fake_search(q, need, cache):
        return [{"url": URL_A, "width": 1080, "height": 1920, "duration": 20},
                {"url": URL_B, "width": 1080, "height": 1920, "duration": 20}] if q == footage.QUERIES[0] else []

    def fake_download(item, cache):
        p = cache / f"fake-{footage.pexels_id_from_url(item['url'])}.mp4"
        p.write_bytes(b"x")
        return p

    footage._search, footage._download = fake_search, fake_download
    cache = tmp / "cache" / "footage"
    none = Exclusions()

    assert footage.default_mode(none, clips_dir) == "mixed"
    assert footage.default_mode(none, tmp / "empty") == "pexels"
    assert footage.default_mode(Exclusions.parse("*.mp4"), clips_dir) == "pexels"

    r = footage.pick_clips(6, 6.0, cache, 1, "pexels", none, clips_dir)
    assert {c.source for c in r} == {"pexels"} and {c.pexels_id for c in r} == {"3571264", "999001"}
    r = footage.pick_clips(6, 6.0, cache, 1, "mine", none, clips_dir)
    assert {c.source for c in r} == {"mine"} and {Path(c.origin).name for c in r} == {"a.mp4", "b.mp4"}
    assert all(r[i] is not r[i + 1] for i in range(5)), "back-to-back repeat"
    assert all(c.path.parent.name == "mine" for c in r)
    r = footage.pick_clips(4, 6.0, cache, 1, "mixed", none, clips_dir)  # 4 unique clips available
    assert {c.source for c in r} == {"pexels", "mine"} and len({id(c) for c in r}) == 4
    r = footage.pick_clips(4, 6.0, cache, 1, "mixed", Exclusions.parse("999001\na.mp4"), clips_dir)
    assert {c.pexels_id for c in r if c.source == "pexels"} == {"3571264"}
    assert "a.mp4" not in {Path(c.origin).name for c in r}
    # same seed, same result
    a = [c.origin for c in footage.pick_clips(5, 6.0, cache, 7, "mixed", none, clips_dir)]
    b = [c.origin for c in footage.pick_clips(5, 6.0, cache, 7, "mixed", none, clips_dir)]
    assert a == b
    # mine mode errors
    try:
        footage.pick_clips(3, 6.0, cache, 1, "mine", Exclusions.parse("*.mp4"), clips_dir)
        raise SystemExit("expected FootageError (empty)")
    except footage.FootageError as e:
        assert "no usable clips" in str(e)
    try:
        footage.pick_clips(3, 60.0, cache, 1, "mine", none, clips_dir)
        raise SystemExit("expected FootageError (too little)")
    except footage.FootageError as e:
        assert "not enough footage" in str(e)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("test_clips: all assertions passed")
