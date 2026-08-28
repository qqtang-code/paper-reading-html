#!/usr/bin/env python3
"""Validate a paper-reading HTML page: images, figures, tables, anchors, tags.

Usage:
    validate.py page.html
Exit code 0 = PASS, 1 = FAIL (missing items printed).
"""
import os, re, sys

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "res.html"
    src = open(path, encoding="utf-8").read()
    problems = []

    # 1. images exist; responsive comes from the CSS rule (figure.fig img), not inline attrs
    imgs = re.findall(r'<img src="([^"]+)"', src)
    missing = [i for i in imgs if not os.path.exists(i)]
    if missing:
        problems.append(f"missing images: {missing}\n"
                        f"        (run validate.py from the directory containing the HTML, so relative paths like figs/ resolve)")
    if not re.search(r'figure\.fig\s+img\s*\{[^}]*max-width:\s*100%[^}]*height:\s*auto', src):
        problems.append("missing CSS rule 'figure.fig img {max-width:100%; height:auto}'")
    # no fixed pixel width / height attributes on any img
    fixed = re.findall(r'<img[^>]*\b(width|height)=', src)
    if fixed: problems.append(f"img tags with fixed width/height attrs: {len(fixed)}")

    # 2. figures & figcaptions
    n_fig = len(re.findall(r'<figure class="fig"', src))
    n_cap = len(re.findall(r'<figcaption>', src))
    if n_fig != n_cap: problems.append(f"figures={n_fig} but figcaptions={n_cap}")

    # 3. tables numbered 1..N complete (order follows the narrative, so sort)
    caps = sorted(int(m.group(1)) for m in re.finditer(r'<caption>Table\s*(\d+)', src))
    if caps != list(range(1, len(caps) + 1)):
        problems.append(f"table captions not 1..N complete: {caps}")

    # 4. anchors
    ids = set(re.findall(r'id="([^"]+)"', src))
    hrefs = set(re.findall(r'href="#([^"]+)"', src))
    missing_anchors = sorted(hrefs - ids)
    if missing_anchors: problems.append(f"missing anchors: {missing_anchors}")

    # 5. tag balance
    for tag in ["section", "table", "figure", "div", "ul", "ol"]:
        o = len(re.findall(rf"<{tag}[ >]", src)); c = len(re.findall(rf"</{tag}>", src))
        if o != c: problems.append(f"<{tag}> open={o} close={c}")

    # 6. key-numbers spot check (options: pass via env or skip)
    spot = os.environ.get("SPOT_CHECKS", "")
    for v in [s for s in spot.split(",") if s]:
        if v not in src: problems.append(f"missing spot value: {v}")

    if problems:
        print("FAIL"); [print(" -", p) for p in problems]; sys.exit(1)
    print(f"PASS: figures={n_fig}, tables={len(caps)}, images={len(imgs)}, anchors ok")

if __name__ == "__main__":
    main()