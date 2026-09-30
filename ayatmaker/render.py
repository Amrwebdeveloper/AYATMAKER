"""Text chunking and timing (the visuals are rendered by templates/htmlrender.py)."""
from __future__ import annotations


# ---------- chunking & timing ----------

def chunk_words(text: str, target: int = 10) -> list[str]:
    """Split into chunks of roughly `target` words (8-12 for typical ayahs)."""
    words = text.split()
    n = max(1, round(len(words) / target))
    base, extra = divmod(len(words), n)
    out, i = [], 0
    for k in range(n):
        size = base + (1 if k < extra else 0)
        out.append(" ".join(words[i:i + size]))
        i += size
    return out


def align_english(text: str, ar_chunks: list[str]) -> list[str]:
    """Split English into len(ar_chunks) pieces; cut i sits at the cumulative Arabic char fraction,
    snapped to the nearest punctuation (, . ; :) within a small window. Never empty."""
    words = text.split()
    n = len(ar_chunks)
    if n <= 1:
        return [text]
    if len(words) < n:
        return _even(words, n)
    total = sum(len(c) for c in ar_chunks) or 1
    cuts, acc = [], 0
    for i, c in enumerate(ar_chunks[:-1]):
        acc += len(c)
        target = round(len(words) * acc / total)
        lo = (cuts[-1] if cuts else 0) + 1
        hi = len(words) - (n - 1 - i)
        target = min(max(target, lo), hi)
        win = max(2, len(words) // (n * 3))
        best, bestd = target, None
        for k in range(max(lo, target - win), min(hi, target + win) + 1):
            if words[k - 1][-1:] in ",.;:":
                d = abs(k - target)
                if bestd is None or d < bestd:
                    best, bestd = k, d
        cuts.append(best)
    out, prev = [], 0
    for k in cuts + [len(words)]:
        out.append(" ".join(words[prev:k]))
        prev = k
    return out


def _even(words: list[str], n: int) -> list[str]:
    base, extra = divmod(len(words), n)
    out, i = [], 0
    for k in range(n):
        size = base + (1 if k < extra else 0)
        out.append(" ".join(words[i:i + size]))
        i += size
    return out


def chunk_pair(arabic: str, english: str, target: int = 10, max_en: int = 25) -> tuple[list[str], list[str]]:
    """Arabic chunks + English chunks of equal count; shrinks the Arabic chunk size until English fits."""
    limit = min(len(arabic.split()), len(english.split()))
    while True:
        ar = chunk_words(arabic, target)
        en = align_english(english, ar)
        if all(len(e.split()) <= max_en for e in en) or target <= 3 or len(ar) >= limit:
            return ar, en
        target -= 1


def proportional_bounds(chunks: list[str], start: float, end: float) -> list[tuple[float, float]]:
    total = sum(len(c) for c in chunks) or 1
    t, out = start, []
    for c in chunks:
        d = (end - start) * len(c) / total
        out.append((t, t + d))
        t += d
    return out
