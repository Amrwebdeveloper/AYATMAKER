"""HTML/CSS templates rendered to transparent 1080x1920 PNG overlays with Playwright (Chromium shapes Arabic).

Public API mirrors render.py: HtmlRenderer(template, font).render_title(...) / .render_body(...).
Text is passed to the page via JSON + textContent, so it is never altered or interpreted as HTML.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
TEMPLATES = ("elegant", "gold-frame", "glass")

# name -> (file, css weight, css format, default arabic size)
FONT_CHOICES: dict[str, tuple[str, str, str, int]] = {
    "scheherazade": ("ScheherazadeNew-Regular.ttf", "400", "truetype", 80),
    "scheherazade-bold": ("ScheherazadeNew-Bold.ttf", "700", "truetype", 80),
    "naskh": ("NotoNaskhArabic-VF.ttf", "400 700", "truetype", 76),
    "amiri": ("AmiriQuran-Regular.ttf", "400", "truetype", 72),
    "kfgqpc": ("UthmanicHafs1-Ver09.woff2", "400", "woff2", 72),
}
DEFAULT_FONT = "scheherazade-bold"

KFGQPC_HELP = (
    "The 'kfgqpc' font is not bundled (KFGQPC license, not OFL). Download 'KFGQPC Uthmanic Script HAFS' (woff2) from the "
    "King Fahd Complex fonts page (https://qurancomplex.gov.sa, fonts section) and save it as: {path}"
)


def check_font(font: str) -> None:
    """Fail early with a clear message when the chosen font file is missing (only 'kfgqpc' is user-supplied)."""
    if font not in FONT_CHOICES:
        raise ValueError(f"unknown font {font!r}; choose from {tuple(FONT_CHOICES)}")
    path = FONT_DIR / FONT_CHOICES[font][0]
    if not path.is_file():
        if font == "kfgqpc":
            raise FileNotFoundError(KFGQPC_HELP.format(path=path))
        raise FileNotFoundError(f"font file missing: {path}")

_GOLD = "#d9b76a"
ORN_DIAMOND = (
    f'<svg viewBox="0 0 26 26"><path d="M13 2 L24 13 L13 24 L2 13 Z" fill="none" stroke="{_GOLD}" stroke-width="1.6"/>'
    f'<path d="M13 8 L18 13 L13 18 L8 13 Z" fill="{_GOLD}"/></svg>'
)
ORN_MEDALLION = (
    f'<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="47" fill="rgba(0,0,0,.35)" stroke="{_GOLD}" stroke-width="2.5"/>'
    f'<circle cx="50" cy="50" r="40" fill="none" stroke="{_GOLD}" stroke-width="1.2" stroke-dasharray="1 4.2" stroke-linecap="round"/>'
    f'<circle cx="50" cy="50" r="35" fill="none" stroke="{_GOLD}" stroke-width="1.6"/>'
    f'<g fill="{_GOLD}"><circle cx="50" cy="3" r="3"/><circle cx="50" cy="97" r="3"/><circle cx="3" cy="50" r="3"/><circle cx="97" cy="50" r="3"/></g></svg>'
)
ORN_CORNER = (
    f'<svg viewBox="0 0 74 74" fill="none" stroke="{_GOLD}" stroke-linecap="round">'
    f'<path d="M4 70 V18 Q4 4 18 4 H70" stroke-width="3"/><path d="M16 70 V30 Q16 16 30 16 H70" stroke-width="1.6"/>'
    f'<path d="M4 4 L30 30" stroke-width="1.2"/><circle cx="32" cy="32" r="4.5" fill="{_GOLD}" stroke="none"/>'
    f'<path d="M30 4 Q40 4 40 14 Q40 24 30 24" stroke-width="1.4"/><path d="M4 30 Q4 40 14 40 Q24 40 24 30" stroke-width="1.4"/></svg>'
)

JS = """<script>
function fit(view, card, start) {
  let size = start;
  const root = document.documentElement;
  for (;;) {
    root.style.setProperty('--ar-size', size + 'px');
    if (card.getBoundingClientRect().height <= view.clientHeight || size <= 30) break;
    size -= 2;
  }
  return size;
}
function setEn(el, text) {
  el.textContent = '';
  String(text).split(' ').forEach((w, i, a) => {
    if (w.indexOf('-') > 0) { const n = document.createElement('span'); n.className = 'nb'; n.textContent = w; el.appendChild(n); }
    else el.appendChild(document.createTextNode(w));
    if (i < a.length - 1) el.appendChild(document.createTextNode(' '));
  });
}
function toAr(n) { return String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]); }
window.setBody = (ar, en, num, size) => {
  document.getElementById('title').classList.add('hidden');
  const view = document.getElementById('body'); view.classList.remove('hidden');
  document.getElementById('ar').textContent = ar;
  const enEl = document.getElementById('en'); setEn(enEl, en || '');
  enEl.style.display = en ? '' : 'none';
  const m = document.getElementById('marker');
  if (num) { document.getElementById('num').textContent = toAr(num); m.classList.remove('none'); } else m.classList.add('none');
  return fit(view, document.getElementById('card'), size);
};
window.setTitle = (ar, en, ref, reader) => {
  document.getElementById('body').classList.add('hidden');
  const view = document.getElementById('title'); view.classList.remove('hidden');
  document.getElementById('t-ar').textContent = ar;
  document.getElementById('t-en').textContent = document.body.hasAttribute('data-compact') ? [en, ref, reader].join(' · ') : en;
  document.getElementById('t-ref').textContent = ref;
  document.getElementById('t-reader').textContent = reader;
  return 0;
};
</script>"""


def _build_html(template: str, font: str) -> str:
    fname, weight, fmt, _ = FONT_CHOICES[font]
    faces = (
        f"@font-face{{font-family:'QVArabic';src:url('{(FONT_DIR / fname).as_uri()}') format('{fmt}');font-weight:{weight};}}"
        f"@font-face{{font-family:'QVSans';src:url('{(FONT_DIR / 'BeVietnamPro-Medium.ttf').as_uri()}');font-weight:400 600;}}"
    )
    # Regular-weight faces must not be synthetically bolded by the CSS weight 700.
    weight_css = ":root{--ar-weight:%s;}" % ("700" if weight in ("700", "400 700") else "400")
    html = (HERE / f"{template}.html").read_text(encoding="utf-8")
    base = (HERE / "base.css").read_text(encoding="utf-8") + weight_css
    for k, v in {"{{BASE_CSS}}": base, "{{FONT_FACES}}": faces, "{{ORN_DIAMOND}}": ORN_DIAMOND,
                 "{{ORN_MEDALLION}}": ORN_MEDALLION, "{{ORN_CORNER}}": ORN_CORNER, "{{JS}}": JS}.items():
        html = html.replace(k, v)
    return html


class HtmlRenderer:
    """One Chromium instance reused for every overlay. Use as a context manager (or call close())."""

    def __init__(self, template: str = "elegant", font: str = DEFAULT_FONT, work: Path | None = None):
        if template not in TEMPLATES:
            raise ValueError(f"unknown template {template!r}; choose from {TEMPLATES}")
        check_font(font)
        from playwright.sync_api import sync_playwright

        self.template, self.font = template, font
        self.ar_size = FONT_CHOICES[font][3]
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        self._file = HERE / f".render_{template}_{font}_{id(self)}.html"
        self._file.write_text(_build_html(template, font), encoding="utf-8")
        self._page.goto(self._file.as_uri())
        self._page.evaluate("document.fonts.ready")

    def _shot(self, path: Path) -> None:
        self._page.evaluate("document.fonts.ready")
        self._page.screenshot(path=str(path), omit_background=True, clip={"x": 0, "y": 0, "width": 1080, "height": 1920})

    def render_body(self, arabic: str, english: str, path: Path, ayah_number: int | None = None) -> int:
        size = self._page.evaluate("([a,e,n,s]) => setBody(a,e,n,s)", [arabic, english, ayah_number, self.ar_size])
        self._shot(path)
        return size

    def render_title(self, surah_ar: str, surah_en: str, ayah_ref: str, reader: str, path: Path) -> None:
        self._page.evaluate("([a,e,r,d]) => setTitle(a,e,r,d)", [surah_ar, surah_en, ayah_ref, reader])
        self._shot(path)

    def close(self) -> None:
        try:
            self._browser.close()
            self._pw.stop()
        finally:
            self._file.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
