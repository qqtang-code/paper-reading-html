#!/usr/bin/env python3
"""Extract paper figures at 300 DPI from crop boxes.

Usage:
    extract_figs.py paper.pdf crops.json out_dir

crops.json format (0-based page index, rect in PDF points):
    {"fig1": {"page": 2, "rect": [336, 294, 516, 454]}, ...}

"page" is a 0-BASED index passed straight to doc[page]. Writing 1-based
page numbers silently crops the SAME rect from the NEXT page — PNG size
still matches the rect, so only a pixel/content check can catch it.
"""
import fitz, json, os, sys

def main():
    if len(sys.argv) != 4:
        print(__doc__); sys.exit(1)
    pdf, crops_json, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf)
    with open(crops_json) as f:
        crops = json.load(f)
    for name, spec in crops.items():
        page = doc[spec["page"]]
        rect = fitz.Rect(*spec["rect"])
        pix = page.get_pixmap(dpi=300, clip=rect)
        path = os.path.join(out_dir, f"{name}.png")
        pix.save(path)
        snippet = " ".join(page.get_text("text", clip=rect).split())[:48]
        print(f"{name}: {pix.width}x{pix.height}px page_idx={spec['page']} (PDF p.{spec['page']+1}) rect={rect} text≈[{snippet}]")

if __name__ == "__main__":
    main()