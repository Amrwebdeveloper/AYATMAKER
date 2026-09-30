# Fonts

Bundled fonts are all SIL Open Font License 1.1 (see `LICENSES.md` and the `OFL-*.txt` files).

| `--font` | File | Bundled |
|---|---|---|
| `scheherazade` | ScheherazadeNew-Regular.ttf | yes |
| `scheherazade-bold` (default) | ScheherazadeNew-Bold.ttf | yes |
| `naskh` | NotoNaskhArabic-VF.ttf | yes |
| `amiri` | AmiriQuran-Regular.ttf | yes |
| `kfgqpc` | UthmanicHafs1-Ver09.woff2 | **no - you must add it yourself** |
| (English text) | BeVietnamPro-Medium.ttf / -Bold.ttf | yes |

## Using `--font kfgqpc` (KFGQPC Uthmanic Script HAFS)

This font belongs to the King Fahd Glorious Quran Printing Complex (KFGQPC) and is published under its own terms,
not the OFL, so it is not distributed with this project.

1. Download "Uthmanic Script HAFS" (woff2) from the King Fahd Complex fonts page (https://qurancomplex.gov.sa, fonts section) and read its terms.
2. Save it exactly as `ayatmaker/templates/fonts/UthmanicHafs1-Ver09.woff2`.

If the file is missing, `--font kfgqpc` stops with an error that shows the expected path. The file is git-ignored.
