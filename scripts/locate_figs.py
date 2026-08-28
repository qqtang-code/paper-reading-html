#!/usr/bin/env python3
"""Locate figures/tables in a PDF and emit a crops.json for extract_figs.py.

Usage:
    locate_figs.py paper.pdf [crops.json]
    # → prints per-page figure/table caption positions + image/vector extents,
    #   writes crops.json when candidate elements are found.

How it works (no visual guesswork):
  - raster figures: page.get_images() + get_image_rects() → actual pixel boxes
  - vector figures: page.get_drawings() → union rect of the drawing band
  - captions: page.search_for("Figure") / page.search_for("Table")
The two signals are cross-checked; the caption bottom usually bounds a figure's
crop. Inspect the printed table, then hand-tune crops.json rects if needed.
"""
import fitz, json, sys

def detect(page):
    """Return (raster_boxes, vector_bands, caption_bottom)."""
    raster = []
    for im in page.get_images(full=True):
        try:
            for r in page.get_image_rects(im[0]):
                raster.append([round(r.x0, 1), round(r.y0, 1),
                               round(r.x1, 1), round(r.y1, 1)])
        except Exception:
            pass
    drawings = page.get_drawings()
    bands = []
    for d in drawings:
        y0, y1 = d["rect"].y0, d["rect"].y1
        for b in bands:
            if y0 < b[1] + 8 and y1 > b[0] - 8:
                b[0], b[1] = min(b[0], y0), max(b[1], y1)
                break
        else:
            bands.append([y0, y1])
    bands = [[round(a, 1), round(b1, 1)] for a, b1 in bands]
    cap_bottom = None
    for kw in ("Figure", "Table"):
        for r in page.search_for(kw):
            cap_bottom = max(cap_bottom or 0, r.y1)
    return raster, bands, cap_bottom

def main():
    pdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    doc = fitz.open(pdf)
    crops = {}
    print(f"{'pg':>3} {'captionBottom':>13}  raster boxes / vector bands")
    for pno in range(len(doc)):
        page = doc[pno]
        raster, bands, cap = detect(page)
        print(f"{pno+1:>3} {str(cap):>13}  {len(raster)} raster, {len(bands)} bands")
        for r in raster: print(f"      raster {r}")
        for b in bands: print(f"      vector y={b[0]}-{b[1]}")
        # auto-propose a crop: figure region ends at caption bottom
        if cap and (raster or bands):
            top = min([r[1] for r in raster] + [b[0] for b in bands])
            left = min([r[0] for r in raster] + [108])
            right = max([r[2] for r in raster] + [504])
            crops[f"p{pno+1}"] = {"page": pno,
                                  "rect": [left, round(top - 4), right, round(cap + 4)]}
    if out and crops:
        with open(out, "w") as f:
            json.dump(crops, f, indent=2)
        print(f"\nwrote {out}: {len(crops)} candidate crops (page-level; refine rects per figure)")

if __name__ == "__main__":
    main()