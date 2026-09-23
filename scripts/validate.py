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

    # 3b. exhibit labels inside figcaptions (<b>Figure N:</b> / <b>Table N:</b>) must also
    # run 1..N with no gaps or duplicates: these are the paper's own exhibits, and a
    # missing or duplicated number means an exhibit was dropped or mislabelled.
    for kind in ("Figure", "Table"):
        labels = sorted(int(m.group(1)) for m in re.finditer(rf'<b>{kind}\s*(\d+):', src))
        if labels != list(range(1, len(labels) + 1)):
            problems.append(f"{kind} labels not 1..N complete: {labels}")

    # 3c. self-drawn charts (data-selfchart): must announce themselves as the editor's
    # work, and must NOT consume a Figure/Table number — otherwise the 1..N checks above
    # break and readers mistake an editor's chart for one from the paper.
    # Contract: references/lieflat-charts.md
    selfcharts = re.findall(r'<figure class="fig"[^>]*data-selfchart[^>]*>.*?</figure>', src, re.S)
    for i, blk in enumerate(selfcharts, 1):
        cap = re.search(r'<figcaption>.*?</figcaption>', blk, re.S)
        cap_txt = cap.group(0) if cap else ""
        if not re.search(r'本页自绘|Self-drawn', cap_txt):
            problems.append(f"self-drawn chart #{i} is missing the '本页自绘 / Self-drawn' "
                            f"label in its figcaption (readers must be able to tell it apart "
                            f"from the paper's own exhibits)")
        numbered = re.search(r'<b>(Figure|Table)\s*(\d+):', cap_txt)
        if numbered:
            problems.append(f"self-drawn chart #{i} carries a paper exhibit number "
                            f"({numbered.group(1)} {numbered.group(2)}) — self-drawn charts "
                            f"must not consume the 1..N numbering; use a descriptive title")

    # 4. anchors
    ids = set(re.findall(r'id="([^"]+)"', src))
    hrefs = set(re.findall(r'href="#([^"]+)"', src))
    missing_anchors = sorted(hrefs - ids)
    if missing_anchors: problems.append(f"missing anchors: {missing_anchors}")

    # 5. tag balance
    for tag in ["section", "table", "figure", "div", "ul", "ol"]:
        o = len(re.findall(rf"<{tag}[ >]", src)); c = len(re.findall(rf"</{tag}>", src))
        if o != c: problems.append(f"<{tag}> open={o} close={c}")

    # 5b. no "empty caption shells": a table that has a <caption> but no content
    # cells (<thead>/<tbody>/<td>/<tr>) is a caption-only shell — it shrinks to
    # min-content width and renders the title as a long narrow column, and it
    # invites scripts to accidentally delete nested <figure> images. Real data
    # tables (e.g. the glossary) carry cells and are unaffected.
    empty_shells = 0
    for m in re.finditer(r'<table\b[^>]*class="data"[^>]*>.*?</table>', src, re.S):
        body = m.group(0)
        if not re.search(r'<(thead|tbody|td|tr|th)\b', body):
            empty_shells += 1
    if empty_shells:
        problems.append(f"empty caption-shell tables found: {empty_shells} — "
                        f"tables must be real data tables (with cells) or be rendered as "
                        f"<figure class='fig'><img src='figs/tableN.png'>… plus figcaption; "
                        f"never nest a caption-only <table> around a table-image figure")

    # 6. key-numbers spot check (options: pass via env or skip)
    spot = os.environ.get("SPOT_CHECKS", "")
    for v in [s for s in spot.split(",") if s]:
        if v not in src: problems.append(f"missing spot value: {v}")

    # 7. reader experience layer (v2 template features)
    feats = {
        "dark mode css": 'data-theme="dark"' in src,
        "theme toggle button": 'theme-toggle' in src,
        "sticky topbar": 'class="topbar"' in src,
        "back-to-top": 'id="backTop"' in src,
        "lightbox": 'id="lightbox"' in src and 'id="lbClose"' in src,
        "image zoom wiring": 'figure.fig img' in src and 'cursor:zoom-in' in src,
        "glossary section": 'id="s9"' in src,
        "print styles": '@media print' in src,
        "og meta": 'og:title' in src,
    }
    missing_feats = [k for k, ok in feats.items() if not ok]
    if missing_feats: problems.append(f"missing reader-experience features: {missing_feats}")

    # 7b. language switcher: a lang-toggle link must point at an existing local file
    # (a switcher whose href 404s is a broken bilingual edition; the portal's
    # <button class="lang-toggle"> is inline-i18n and has no href, so it's skipped)
    for m in re.finditer(r'<a\b[^>]*\bclass="lang-toggle"[^>]*>', src):
        h = re.search(r'href="([^"]+)"', m.group(0))
        if not h:
            continue
        href = h.group(1)
        if href.startswith(("http", "#", "mailto:", "javascript:")):
            continue
        if not os.path.exists(href):
            problems.append(f"lang-toggle target missing: {href} "
                            f"(the language switcher must link to an existing edition file)")

    # 8. abbr terms recommended (at least a few for tutorial value; 0 is suspicious)
    if src.count('<abbr title=') == 0:
        problems.append("no <abbr> terms found — add hover-glosses for abbreviations in the prose")

    # 9. formula rendering (KaTeX) + no unicode combo-char math
    if 'katex@0.16.22/dist/katex.min.css' not in src or 'renderMathInElement' not in src:
        problems.append("missing KaTeX wiring (css/js/auto-render) — formulas won't render")
    for ch in ['\u0124', '\u0304', '\u2080']:  # Ĥ, combining macron, subscript zero
        if ch in src.split('</style>')[-1]:
            problems.append(f"unicode math combo char U+{ord(ch):04X} still in body — replace with KaTeX ($...$)")
    if re.search(r'class="cases"', src):
        problems.append("old HTML .cases formula blocks present — migrate to KaTeX display math")

        # 9b. source page refs: all-or-none. A page that labels some exhibits with the
    # source page (span.pgref) but not others is half-traceable; 0 refs stays legal
    # for pages built before this convention.
    pg = src.count('class="pgref"')
    if 0 < pg < n_cap:
        problems.append(f"only {pg} of {n_cap} figcaptions carry a source page ref (span.pgref) — "
                        f"add them for every exhibit (scripts/add_pagerefs.py) or none")

    # 10. recommended practices — reported as WARN only, never fail the build
    body = src.split('</style>')[-1]
    warns = []
    if '读数约定' not in src and 'Reading conventions' not in src:
        warns.append("reading-conventions note (读数约定 / Reading conventions) — recommended for every page")
    if 'et al.' not in body:
        warns.append("inline citations like \"(Author et al., 2024)\" — attribute upstream methods to their papers")
    if pg == 0:
        warns.append("source page refs in figcaptions (span.pgref) — run scripts/add_pagerefs.py")
    if not any(k in body for k in ('值得补测', '未披露', 'worth testing', 'Not disclosed')):
        warns.append("\"not disclosed / worth testing\" list in the commentary — recommended")
    # every exhibit should be traceable to a source: either a paper Figure/Table label,
    # or an explicit self-drawn label (see references/lieflat-charts.md)
    unlabelled = 0
    for m in re.finditer(r'<figure class="fig"[^>]*>(.*?)</figure>', src, re.S):
        blk = m.group(1)
        if re.search(r'<b>(Figure|Table|Algorithm)\s*\d+:', blk):
            continue
        if re.search(r'本页自绘|Self-drawn', blk):
            continue
        unlabelled += 1
    if unlabelled:
        warns.append(f"{unlabelled} figure(s) with no 'Figure N:' / 'Table N:' label and no "
                     f"'本页自绘 / Self-drawn' marker — label every exhibit so readers know "
                     f"whether it comes from the paper")

    if problems:
        print("FAIL"); [print(" -", p) for p in problems]
        [print("WARN (recommended):", w) for w in warns]
        sys.exit(1)
    print(f"PASS: figures={n_fig}, tables={len(caps)}, images={len(imgs)}, anchors ok")
    if selfcharts:
        print(f"      self-drawn charts (data-selfchart)={len(selfcharts)} — labelled, not consuming exhibit numbers")
    [print("WARN (recommended):", w) for w in warns]

if __name__ == "__main__":
    main()