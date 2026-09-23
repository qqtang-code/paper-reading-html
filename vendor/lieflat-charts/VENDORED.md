# Vendored copy: lieflat-charts

This directory is a **verbatim copy** of the `lieflat-charts` skill, vendored so the
`paper-reading-html` skill can select, build and export charts **offline**, without
requiring a separate skill installation.

| | |
|---|---|
| Upstream | `lieflat-charts` skill (Agent Skills format) |
| Upstream location at vendoring time | `~/.agents/skills/lieflat-charts/` (installed copy, not a git checkout) |
| Vendored on | 2026-09-23 |
| Manifest digest | `sha256:NOTE: manifest digest changed: recorded 8b41020ed2a67ce9… != current f26d201acdb08a41… (expected if you re-vendored — update VENDORED.md)
f26d201acdb08a419932e46e3d0dbcbd990d16da5b8b1c6a336b77d857a41732` |
| Files | 66 (1.4 MB) |
| License | **PolyForm Noncommercial License 1.0.0** — see `LICENSE` in this directory |

## What was copied

Everything functional and documentary:

```
SKILL.md              the chart codex (selection order, hard rules, self-check)
README.md / README.en.md
catalog.md            chart-type catalogue (L1–L20, F1–F17, G3–G22, M1–M2, B1–B3)
report-catalog.md     R01–R12 full-page report templates
mono-tokens.js        design tokens: Mono grey ladder, type, radii, animation, obsReveal
color-presets.js      porcelain / palm / wire presets
templates/            galleries (lupi, basics, glance, maps, big-*), color samples, reports
scripts/              validate.mjs, smoke-new-charts.mjs
agents/openai.yaml
examples/
LICENSE               PolyForm Noncommercial 1.0.0
THIRD_PARTY_NOTICES.md
```

## What was left out

`docs/` (58 files, 19 MB) — README hero images, animated GIFs and gallery preview
PNGs. It is presentation media for browsing the upstream README, takes ~93% of the
upstream size, and is not used by any step of the chart workflow. Because of this,
image links inside the vendored `README.md` / `README.en.md` will not resolve
locally; read those files for their text, not their screenshots.

## Verification performed on this copy

Vendored content is checked mechanically by `python3 scripts/vendor_check.py` (also a CI
step): required files present, licence title + canonical URL intact, galleries non-empty,
manifest digest matches the one recorded above.

Beyond the structural check, the copy was rendered for real — headless Chrome, all DNS
blackholed (`--host-resolver-rules="MAP * 127.0.0.1:1"`) to simulate being offline:

| Template | Result offline |
|---|---|
| `templates/lupi-gallery.html` | renders — 19 `<svg>`, 204 `<path>`, 768 `<circle>` in the DOM, artwork confirmed visually (Launch Fan / barcode / convergence cards all draw) |
| `templates/basics-gallery.html` | **partially fails** — 16 `<svg>` containers but 0 `<path>/<circle>/<rect>`; charts appear only with network. It relies on CDN ECharts for some cards. |
| `templates/glance-gallery.html`, `maps-gallery.html`, `big-circular.html`, `big-force.html` | not offline-capable — load ECharts / Chart.js / GeoJSON from CDNs |
| `templates/big-threads.html` | no chart library; only the Inter webfont is remote |

Practical consequence for the reading pages, which promise "no network needed when opened
locally": build self-drawn charts from **Lupi Editorial** (hand-written SVG) and inline
`mono-tokens.js`; do not assume the Basics or Glance galleries work offline.

## Updating this copy

Re-copy from a fresh upstream install, then refresh `VENDORED.md`:

```bash
SRC=~/.agents/skills/lieflat-charts
DST=$(git rev-parse --show-toplevel)/vendor/lieflat-charts
rm -rf "$DST" && mkdir -p "$DST"
cd "$SRC" && for i in SKILL.md README.md README.en.md catalog.md report-catalog.md \
    mono-tokens.js color-presets.js LICENSE THIRD_PARTY_NOTICES.md \
    templates scripts agents examples; do cp -R "$i" "$DST/"; done
cd "$DST" && find . -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256
```

Use `scripts/vendor_check.py` to confirm the copy is still intact after any edit.

## Licence and attribution

`lieflat-charts` is licensed under the **PolyForm Noncommercial License 1.0.0**, which
permits noncommercial use, modification, and redistribution **provided every recipient
also receives the licence terms**. The full text is in `LICENSE` next to this file, and
the URL is <https://polyformproject.org/licenses/noncommercial/1.0.0>.

Consequences for this repository, stated plainly:

- This repository as a whole may be used **for noncommercial purposes only** while this
  directory is present, because it redistributes PolyForm Noncommercial software.
  The MIT licence in the repository root continues to cover everything *outside* this
  directory, but it cannot relicense this directory's contents.
- The upstream `LICENSE` file is copied unmodified and must not be removed or altered.
  The upstream provided no `Required Notice:` lines (only the licence's own example);
  if a future version adds any, they must be carried over too.
- If you ever need a commercially usable copy of this repository, delete
  `vendor/lieflat-charts/` and reference an independently licensed install instead.

Credit: the upstream author is 「躺在废墟里」, and the skill was made at
[moxt.ai](https://moxt.ai). Per the upstream's own request, say so when publicly
distributing charts produced with it.