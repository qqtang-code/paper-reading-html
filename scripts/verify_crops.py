#!/usr/bin/env python3
"""Verify figure/table crops against the source PDF (geometric audit).

The extraction pipeline is easy to get subtly wrong: a crop box can land on the
neighbouring page, capture body text instead of the table, lose the caption's
first characters, or cut the bottom rule line. PNG dimensions still look fine —
only a geometric/content audit catches these.

This script audits every entry of ``crops.json`` against the PDF:

  1. **page identity** — the rect must contain ink on its own page, and rendering
     the *same* rect on the neighbouring pages must produce a different image
     (guards against the classic off-by-one: writing a 1-based page number into a
     0-based field silently crops the next page at the same coordinates)
  2. **pixel identity** — when ``figs/<key>.png`` exists, it must be pixel-for-pixel
     what re-rendering ``page[rect]`` at the same DPI produces (catches stale or
     hand-edited PNGs)
  3. **caption containment** — when the crop is meant to include the paper's own
     caption (default), that caption block must be fully inside the rect
     (catches a crop whose left/top edge clips "Figure 3:" into "ure 3:")
  4. **border bleed** — ink on the outer 1px ring is reported; a *continuous*
     line is classified as an expected table rule, while scattered ink warns
     about clipped content
  5. **coverage sanity** — duplicate rects, rects outside the page, and rects
     intruding into the running-header/footer margin are flagged
  6. **crops.json ↔ figs/ consistency** — a key with no PNG, or a PNG with no key

Exit codes:
    0 = PASS (warnings allowed)
    1 = FAIL (a hard geometric/content error was found)
    2 = environment/usage error

Usage:
    verify_crops.py paper.pdf crops.json
    verify_crops.py paper.pdf crops.json --figs figs --dpi 300
    verify_crops.py paper.pdf crops.json --no-caption   # crops exclude the caption
    verify_crops.py paper.pdf crops.json --json
"""
import argparse
import json
import pathlib
import re
import sys

EXIT_PASS, EXIT_FAIL, EXIT_ENV = 0, 1, 2

KIND_NUM = re.compile(r"^(fig|figure|table|algo|algorithm)\s*[-_]?\s*(\d+)$", re.I)
CAPTION_RE = re.compile(r"^\s*(Figure|Table|Algorithm)\s+(\d+)\s*[:.]")
MARGIN_PT = 45.0  # running header/footer band that must not be cropped into


def _gray(pix):
    """Return a list-of-rows grayscale approximation from a fitz Pixmap."""
    n = pix.n
    s = pix.samples
    w, h = pix.width, pix.height
    out = bytearray(w * h)
    if n >= 3:
        for i in range(w * h):
            j = i * n
            out[i] = (s[j] + s[j + 1] + s[j + 2]) // 3
    else:
        out[:] = s[: w * h]
    return out, w, h


def _ink_stats(pix):
    """Return (ink_ratio, border_info) for a rendered crop."""
    g, w, h = _gray(pix)
    ink = sum(1 for v in g if v < 248)
    ratio = ink / float(w * h) if w * h else 0.0
    border = {}
    for name, coords in {
        "top": [(x, 0) for x in range(w)],
        "bottom": [(x, h - 1) for x in range(w)],
        "left": [(0, y) for y in range(h)],
        "right": [(w - 1, y) for y in range(h)],
    }.items():
        hits = sum(1 for (x, y) in coords if g[y * w + x] < 248)
        frac = hits / float(len(coords)) if coords else 0.0
        border[name] = frac
    return ratio, border


def _caption_blocks(page):
    """Map (kind, number) -> fitz.Rect for caption blocks on a page."""
    out = {}
    for b in page.get_text("blocks"):
        txt = (b[4] or "").strip()
        m = CAPTION_RE.match(txt)
        if not m:
            continue
        kind = "Figure" if m.group(1).lower().startswith("fig") else m.group(1).capitalize()
        if kind == "Algorithm":
            kind = "Algorithm"
        import fitz
        out.setdefault((kind, int(m.group(2))), fitz.Rect(b[0], b[1], b[2], b[3]))
    return out


def _expected_caption_key(name):
    m = KIND_NUM.match(name)
    if not m:
        return None
    kind = {"fig": "Figure", "figure": "Figure", "table": "Table",
            "algo": "Algorithm", "algorithm": "Algorithm"}[m.group(1).lower()]
    return kind, int(m.group(2))


def main():
    ap = argparse.ArgumentParser(description="Geometric audit of crops.json against the PDF")
    ap.add_argument("pdf")
    ap.add_argument("crops")
    ap.add_argument("--figs", default=None,
                    help="directory with extracted PNGs (default: ./figs next to crops.json)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-caption", action="store_true",
                    help="crops are meant to exclude the paper caption (disables check 3)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        import fitz
    except ImportError:
        print("verify_crops: PyMuPDF is required (pip install pymupdf)", file=sys.stderr)
        return EXIT_ENV

    pdf_path, crops_path = pathlib.Path(args.pdf), pathlib.Path(args.crops)
    if not pdf_path.exists() or not crops_path.exists():
        print(f"verify_crops: missing input ({pdf_path} / {crops_path})", file=sys.stderr)
        return EXIT_ENV
    try:
        crops = json.loads(crops_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"verify_crops: crops.json is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_ENV
    if not isinstance(crops, dict) or not crops:
        print("verify_crops: crops.json must be a non-empty object", file=sys.stderr)
        return EXIT_ENV

    figs_dir = pathlib.Path(args.figs) if args.figs else crops_path.parent / "figs"

    doc = fitz.open(str(pdf_path))
    problems, warns, report = [], [], {}
    seen_rects = {}

    # Cross-page caption index: if the caption for an exhibit lives on a different
    # page than the crop claims, the page index is wrong. This catches the
    # off-by-one even when no extracted PNG is available to compare against.
    caption_page = {}
    if not args.no_caption:
        for pno in range(doc.page_count):
            for (kind, num) in _caption_blocks(doc[pno]):
                caption_page.setdefault((kind, num), pno)

    print(f"{'key':10s} {'pdf':>4s} {'rect':>28s} {'ink%':>6s}  notes")
    for name, spec in crops.items():
        try:
            pno = int(spec["page"])
            x0, y0, x1, y1 = [float(v) for v in spec["rect"]]
        except (KeyError, TypeError, ValueError):
            problems.append(f"{name}: malformed entry (need page: int, rect: [x0,y0,x1,y1])")
            continue
        if not (0 <= pno < doc.page_count):
            problems.append(f"{name}: page {pno} out of range (document has {doc.page_count} pages; "
                            f"page is 0-based)")
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        page = doc[pno]
        if rect.is_empty or rect.width <= 1 or rect.height <= 1:
            problems.append(f"{name}: degenerate rect {list(rect)}")
            continue

        notes = []
        # --- 1. page identity: this page has ink; neighbours differ -------------
        pix = page.get_pixmap(dpi=args.dpi, clip=rect)
        ink, border = _ink_stats(pix)
        if ink == 0.0:
            problems.append(f"{name}: crop renders blank on page {pno} — wrong page or wrong rect")
            continue
        differing = []
        for off in (-1, 1):
            q = pno + off
            if 0 <= q < doc.page_count:
                other = doc[q].get_pixmap(dpi=args.dpi, clip=rect)
                differing.append(other.samples != pix.samples)
            else:
                differing.append(True)
        if not any(differing):
            problems.append(f"{name}: identical pixels on adjacent pages — cannot confirm the page "
                            f"index (this is the signature of an off-by-one page number)")

        # --- 2. pixel identity vs extracted PNG ------------------------------
        png = figs_dir / f"{name}.png"
        if png.exists():
            try:
                saved = fitz.Pixmap(str(png))
                same_size = (saved.width, saved.height) == (pix.width, pix.height)
                if not same_size:
                    problems.append(
                        f"{name}: PNG is {saved.width}x{saved.height} but the pdf rect renders "
                        f"{pix.width}x{pix.height} at {args.dpi} DPI — the PNG is stale or was "
                        f"extracted from a different rect")
                elif saved.samples[: pix.width * pix.height * saved.n] != pix.samples[: pix.width * pix.height * pix.n]:
                    problems.append(f"{name}: PNG differs pixel-for-pixel from a fresh render — "
                                    f"re-run scripts/extract_figs.py")
            except Exception as exc:  # unreadable PNG
                warns.append(f"{name}: could not re-read {png.name} for comparison ({exc})")
        else:
            warns.append(f"{name}: no extracted PNG at {png} (skipped pixel-identity check)")

        # --- 3. caption containment ------------------------------------------
        # Two failure modes look similar but are not:
        #   * the crop deliberately excludes the caption  -> fine (the page's own
        #     <figcaption> still carries the caption text)
        #   * the crop *overlaps* the caption but cuts it -> broken: the rendered
        #     image shows a truncated caption ("ure 3:"), which readers see
        if not args.no_caption:
            want = _expected_caption_key(name)
            if want:
                actual_page = caption_page.get(want)
                if actual_page is not None and actual_page != pno:
                    problems.append(
                        f"{name}: page index says {pno} (0-based) but the caption "
                        f"“{want[0]} {want[1]}:” lives on page {actual_page} "
                        f"({actual_page + 1} 1-based) — the page field is wrong "
                        f"(remember: crops.json 'page' is 0-based)")
                caps = _caption_blocks(page)
                cap = caps.get(want)
                if cap is None:
                    notes.append("no-caption-found")
                elif rect.intersects(cap):
                    inside = (rect.x0 <= cap.x0 + 0.5 and rect.y0 <= cap.y0 + 0.5
                              and cap.x1 <= rect.x1 + 0.5 and cap.y1 <= rect.y1 + 0.5)
                    if not inside:
                        problems.append(
                            f"{name}: the crop overlaps the paper caption “{want[0]} {want[1]}:” "
                            f"but does not contain it (caption "
                            f"{list(round(v,1) for v in cap)} vs crop "
                            f"{list(round(v,1) for v in rect)}) — the image will show a "
                            f"truncated caption; either include it fully or exclude it entirely")
                else:
                    notes.append("caption-excluded")

        # --- 4. border bleed classification ----------------------------------
        for edge, frac in border.items():
            if frac >= 0.5:
                notes.append(f"rule-on-{edge}")          # continuous line = table rule
            elif frac > 0.02:
                warns.append(f"{name}: sparse ink on the {edge} edge (frac={frac:.2f}) — "
                             f"content may be clipped")

        # --- 5. coverage sanity ----------------------------------------------
        if rect.y0 < MARGIN_PT or rect.y1 > page.rect.height - MARGIN_PT:
            warns.append(f"{name}: rect enters the header/footer margin "
                         f"(y {rect.y0:.1f}–{rect.y1:.1f}, page height {page.rect.height:.1f}) — "
                         f"a running header may have been cropped in")
        key = (pno, round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
        if key in seen_rects:
            warns.append(f"{name}: same rect as “{seen_rects[key]}” — duplicated crop box")
        seen_rects[key] = name

        snippet = " ".join(page.get_text("text", clip=rect).split())[:52]
        report[name] = {"page": pno, "rect": [round(v, 1) for v in rect],
                        "ink_ratio": round(ink, 4), "border": border, "text": snippet}
        print(f"{name:10s} {pno + 1:>4d} {str([round(v,1) for v in rect]):>28s} "
              f"{ink*100:5.1f}%  {';'.join(notes)}")

    # --- 6. crops ↔ figs consistency -----------------------------------------
    if figs_dir.exists():
        png_keys = {p.stem for p in figs_dir.glob("*.png")
                    if re.match(r"^(fig|figure|table|algo|algorithm)\d+$|^\w+$", p.stem)}
        missing_png = sorted(set(crops) - png_keys)
        orphan_png = sorted(k for k in png_keys - set(crops)
                            if re.match(r"^(fig|table|algo|algorithm)\d+$", k))
        for k in missing_png:
            warns.append(f"crops key “{k}” has no extracted PNG in {figs_dir}")
        for k in orphan_png:
            warns.append(f"figs/{k}.png has no crops.json entry — cannot be audited or "
                         f"page-referenced")
    else:
        warns.append(f"no figs directory at {figs_dir} (skipped crops↔figs check)")

    print()
    for w in warns:
        print("WARN:", w)
    for p in problems:
        print("FAIL:", p)
    if args.json:
        print(json.dumps({"report": report, "warn": warns, "fail": problems},
                         ensure_ascii=False, indent=2))
    if problems:
        print(f"\nVERIFY-CROPS FAIL: {len(problems)} problem(s), {len(warns)} warning(s)")
        return EXIT_FAIL
    print(f"\nVERIFY-CROPS PASS: {len(crops)} crops audited, {len(warns)} warning(s)")
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
