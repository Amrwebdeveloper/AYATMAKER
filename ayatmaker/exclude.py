"""Exclusion list (exclude.txt) for footage + CLI: python -m ayatmaker.exclude add|list|remove <entry>"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .api import ROOT

EXCLUDE_FILE = ROOT / "exclude.txt"
MY_CLIPS_DIR = ROOT / "my_clips"

_URL_ID = (re.compile(r"/video-files/(\d+)/"), re.compile(r"/video/(?:[^/?#]*-)?(\d+)(?:[/?#]|$)"))
_PEXELS_FILE = re.compile(r"^vid-([0-9a-f]{32})(?:_1080x1920)?\.mp4$")


def url_hash(url: str) -> str:
    """Same hash footage.py uses to name downloaded files."""
    return hashlib.md5(url.split("#", 1)[0].encode()).hexdigest()


def pexels_id_from_url(url: str) -> str | None:
    for rx in _URL_ID:
        m = rx.search(url)
        if m:
            return m.group(1)
    return None


def _clean(line: str) -> str:
    line = line.strip()
    if line.startswith("#"):
        return ""
    return re.sub(r"\s+#.*$", "", line).strip()


def classify(entry: str) -> tuple[str, str]:
    """Return (kind, value); kind in id | file | glob | local."""
    e = entry.strip()
    if e.isdigit():
        return "id", e
    if re.match(r"^https?://", e, re.I):
        pid = pexels_id_from_url(e)
        if not pid:
            raise ValueError(f"cannot extract a Pexels video id from URL: {e}")
        return "id", pid
    low = e.replace("\\", "/").lower()
    m = _PEXELS_FILE.match(low)
    if m:
        return "file", m.group(1)  # md5 of the download url
    low = re.sub(r"^\./", "", low)
    if low.startswith("my_clips/"):
        low = low[len("my_clips/"):]
    if any(c in low for c in "*?["):
        return "glob", low
    return "local", low


def normalize(entry: str) -> str:
    """Canonical text stored in exclude.txt for an entry."""
    kind, val = classify(entry)
    if kind == "id":
        return val
    if kind == "file":
        return entry.strip().lower()
    return val


@dataclass
class Exclusions:
    ids: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)
    globs: list[str] = field(default_factory=list)
    locals_: set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, text: str) -> "Exclusions":
        ex = cls()
        for raw in text.splitlines():
            entry = _clean(raw)
            if not entry:
                continue
            try:
                kind, val = classify(entry)
            except ValueError:
                continue
            if kind == "id":
                ex.ids.add(val)
            elif kind == "file":
                ex.hashes.add(val)
            elif kind == "glob":
                ex.globs.append(val)
            else:
                ex.locals_.add(val)
        return ex

    @classmethod
    def load(cls, path: Path = EXCLUDE_FILE) -> "Exclusions":
        return cls.parse(path.read_text(encoding="utf-8")) if path.exists() else cls()

    def __bool__(self) -> bool:
        return bool(self.ids or self.hashes or self.globs or self.locals_)

    def pexels_excluded(self, url: str) -> bool:
        pid = pexels_id_from_url(url)
        return (pid in self.ids if pid else False) or url_hash(url) in self.hashes

    def local_excluded(self, relpath: str) -> bool:
        rel = relpath.replace("\\", "/").lower()
        base = rel.rsplit("/", 1)[-1]
        if rel in self.locals_ or base in self.locals_:
            return True
        return any(fnmatch.fnmatchcase(rel, g) or ("/" not in g and fnmatch.fnmatchcase(base, g)) for g in self.globs)


# ---- CLI -------------------------------------------------------------------------------------------------------

def _entries(lines: list[str]) -> list[tuple[int, str]]:
    return [(i, _clean(l)) for i, l in enumerate(lines) if _clean(l)]


def cmd_add(path: Path, raw: str) -> str:
    norm = normalize(raw)
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    nl = "\r\n" if "\r\n" in text else "\n"
    for _, e in _entries(text.splitlines(keepends=True)):
        try:
            if normalize(e) == norm:
                return f"already excluded: {norm}"
        except ValueError:
            pass
    if text and not text.endswith("\n"):
        text += nl
    comment = f"  # {raw.strip()}" if raw.strip() != norm else ""
    path.write_bytes((text + norm + comment + nl).encode("utf-8"))
    return f"added: {norm}"


def cmd_remove(path: Path, raw: str) -> str:
    norm = normalize(raw)
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True) if path.exists() else []
    keep, removed = [], 0
    for l in lines:
        e = _clean(l)
        try:
            hit = bool(e) and normalize(e) == norm
        except ValueError:
            hit = False
        if hit:
            removed += 1
        else:
            keep.append(l)
    if removed:
        path.write_bytes("".join(keep).encode("utf-8"))
    return f"removed {removed}: {norm}" if removed else f"not found: {norm}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ayatmaker.exclude", description="Manage exclude.txt")
    ap.add_argument("action", choices=["add", "list", "remove"])
    ap.add_argument("entry", nargs="?", help="Pexels id / URL / cached file name / my_clips file or glob")
    ap.add_argument("--file", type=Path, default=EXCLUDE_FILE)
    a = ap.parse_args(argv)
    if a.action == "list":
        text = a.file.read_text(encoding="utf-8") if a.file.exists() else ""
        es = _entries(text.splitlines(keepends=True))
        print("\n".join(e for _, e in es) if es else "(no exclusions)")
        return 0
    if not a.entry:
        ap.error(f"'{a.action}' needs an entry")
    try:
        print((cmd_add if a.action == "add" else cmd_remove)(a.file, a.entry))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
