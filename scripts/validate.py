#!/usr/bin/env python3
"""Validate a paper-reading HTML page: images, figures, tables, anchors, tags.

Usage:
    validate.py page.html [sibling.html ...]

Passing several files validates them as a *pair/set*: bilingual pages link to
each other with <a class="lang-toggle" href="en.html">, so validating one file
alone would fail on a sibling that is being produced in parallel. When the
siblings are given, a lang-toggle target that matches one of them counts as
resolved (this removes the chicken-and-egg between index.html and en.html).

Exit codes:
    0 = PASS, 1 = FAIL (problems printed to stdout), 2 = usage error.
"""
import os
import re
import sys


# ---------------------------------------------------------------------------
# dollar-vs-math conflict detection
# ---------------------------------------------------------------------------
# KaTeX auto-render can be wired with `{left:'$', right:'$'}` as an inline
# delimiter. That is fine for a page whose only `$` are genuine math, but a page
# that also reports USD costs (`$0.583`, `$7.23`, …) has its dollar signs paired
# up as formulas: every second amount opens a span and the prose in between is
# rendered as italic gibberish. The failure is invisible to source-level checks
# (the HTML is perfectly valid), so it must be detected here.
#
# Detection strategy: simulate the delimiter pairing the renderer performs, then
# judge whether any resulting span is prose rather than math. Genuine math
# contains LaTeX commands / operators / single-letter symbols; prose contains
# multi-letter words or CJK characters.

_MATH_FUNCS = {"sin", "cos", "tan", "log", "exp", "max", "min", "arg",
               "lim", "sup", "inf", "det", "mod", "gcd", "sec", "csc", "cot",
               "frac", "sqrt", "cdot", "times", "approx", "text", "mathrm",
               "begin", "end", "left", "right", "quad", "qquad", "sum", "prod"}
# words that essentially never appear inside genuine inline math
_PROSE_WORDS = {"the", "and", "for", "with", "compared", "than", "from", "that",
                "this", "which", "while", "where", "cost", "costs", "instance",
                "instances", "tokens", "token", "accuracy", "input", "output"}
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _strip_noise(src):
    """Remove script/style/comment blocks — their `$` are not prose."""
    src = re.sub(r"<script\b.*?</script>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<style\b.*?</style>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return src


def _inline_dollar_delimiter_enabled(src):
    """True when the page wires KaTeX with $...$ as an inline delimiter."""
    return bool(re.search(r"left\s*:\s*['\"]\$['\"]\s*,\s*right\s*:\s*['\"]\$['\"]", src))


def _math_looking(span):
    """Heuristic: does this `$…$` span look like math rather than prose?

    Judged by removing LaTeX syntax, then looking for content that only prose
    would have: CJK characters, or English function/content words. Short
    identifiers (``x``, ``wp``, ``N_k``) and LaTeX commands are treated as math
    so that legitimate pages are never flagged.
    """
    s = span.strip()
    if not s:
        return True
    if len(s) > 300:
        return False
    # strip text-in-math wrappers first: \text{块数} / \mathrm{prefill} are legal math
    s_probe = re.sub(r"\\(?:text|mathrm|mathbf|mathit|mbox|operatorname)\s*\{[^{}]*\}", " ", s)
    if _CJK.search(s_probe):
        return False
    # a backslash command anywhere is a strong signal that this is real LaTeX
    if re.search(r"\\[A-Za-z]+", s_probe):
        return True
    plain = re.sub(r"\{[^{}]*\}", " ", s_probe)
    plain = re.sub(r"[_^]", " ", plain)
    hits = 0
    for word in re.findall(r"[A-Za-z]{3,}", plain):
        low = word.lower()
        if low in _MATH_FUNCS:
            continue
        # >=4 letters, or an explicit prose stopword, counts as prose evidence
        if len(low) >= 4 or low in _PROSE_WORDS:
            hits += 1
    return hits < 2


def check_dollar_math_conflict(src):
    """Return a list of human-readable problems for `$..$` swallowing USD amounts."""
    if not _inline_dollar_delimiter_enabled(src):
        return []

    body = _strip_noise(src)
    # blank out display math $$…$$ so its dollars are not counted as inline ones
    body = re.sub(r"\$\$.*?\$\$", " ", body, flags=re.S)
    # an escaped \$ is a literal dollar sign, not a delimiter
    body = body.replace("\\$", "\x00")

    positions = [m.start() for m in re.finditer(r"\$", body)]
    problems = []
    if len(positions) % 2:
        problems.append(
            f"unbalanced `$` count ({len(positions)}) while KaTeX uses $..$ as an inline "
            f"delimiter — one amount will swallow the rest of the paragraph; use \\(...\\) "
            f"for inline math and remove the $..$ delimiter")
        return problems

    suspects = []
    for i in range(0, len(positions), 2):
        a, b = positions[i], positions[i + 1]
        span = body[a + 1:b]
        if not _math_looking(span):
            text = " ".join(span.split())[:60]
            suspects.append(text)

    if suspects:
        shown = "; ".join(f"“{s}”" for s in suspects[:3])
        more = f" (+{len(suspects) - 3} more)" if len(suspects) > 3 else ""
        problems.append(
            f"`$..$` inline delimiter conflicts with {len(suspects)} USD amount(s): the "
            f"renderer would typeset the prose between them as italic math "
            f"(e.g. {shown}{more}). Report the costs literally and use \\(...\\) for "
            f"real inline math, then drop the {{left:'$',right:'$'}} delimiter entry")
    return problems


# ---------------------------------------------------------------------------
# crops.json ↔ page cross-check
# ---------------------------------------------------------------------------
_EXHIBIT_KEY = re.compile(r"^(fig|table|algo)\d+$")


def check_crops_coverage(path, src):
    """Report (as warnings) exhibits whose crops.json wiring is incomplete.

    crops.json drives add_pagerefs.py / verify_crops.py, so a mismatch means some
    exhibit cannot get a source page ref or a geometric audit. It does not break
    the rendered page, so this stays advisory rather than failing the build.
    """
    crops_path = os.path.join(os.path.dirname(os.path.abspath(path)), "crops.json")
    if not os.path.exists(crops_path):
        return []
    import json
    try:
        with open(crops_path, encoding="utf-8") as f:
            keys = set(json.load(f).keys())
    except (ValueError, OSError):
        return [f"crops.json next to the page is unreadable ({crops_path})"]

    referenced = set()
    for m in re.finditer(r'<img src="figs/([^"/]+)\.png"', src):
        if _EXHIBIT_KEY.match(m.group(1)):
            referenced.add(m.group(1))

    warns = []
    uncovered = sorted(referenced - keys)
    if uncovered:
        warns.append(
            f"{len(uncovered)} embedded exhibit(s) missing from crops.json: {uncovered} — "
            f"add entries so scripts/add_pagerefs.py can give them a source page ref "
            f"and scripts/verify_crops.py can audit their crop boxes")
    unused = sorted(keys - referenced)
    if unused:
        warns.append(f"crops.json entries not embedded on this page: {unused}")
    return warns


# ---------------------------------------------------------------------------
# page validation
# ---------------------------------------------------------------------------
def validate_one(path, siblings=()):
    src = open(path, encoding="utf-8").read()
    problems, warns = [], []

    # 1. images exist; responsive comes from the CSS rule (figure.fig img), not inline attrs
    imgs = re.findall(r'<img src="([^"]+)"', src)
    missing = [i for i in imgs if not os.path.exists(i)]
    if missing:
        problems.append(f"missing images: {missing}\n"
                        f"        (run validate.py from the directory containing the HTML, so relative paths like figs/ resolve)")
    if not re.search(r"figure\.fig\s+img\s*\{[^}]*max-width:\s*100%[^}]*height:\s*auto", src):
        problems.append("missing CSS rule 'figure.fig img {max-width:100%; height:auto}'")
    # no fixed pixel width / height attributes on any img
    fixed = re.findall(r"<img[^>]*\b(width|height)=", src)
    if fixed:
        problems.append(f"img tags with fixed width/height attrs: {len(fixed)}")

    # 2. figures & figcaptions
    n_fig = len(re.findall(r'<figure class="fig"', src))
    n_cap = len(re.findall(r"<figcaption>", src))
    if n_fig != n_cap:
        problems.append(f"figures={n_fig} but figcaptions={n_cap}")

    # 3. data tables (real <table> with a "Table N" caption) numbered 1..N complete
    caps = sorted(int(m.group(1)) for m in re.finditer(r"<caption>Table\s*(\d+)", src))
    if caps != list(range(1, len(caps) + 1)):
        problems.append(f"table captions not 1..N complete: {caps}")

    # 3b. exhibit labels inside figcaptions (<b>Figure N:</b> / <b>Table N:</b>) must also
    # run 1..N with no gaps or duplicates: these are the paper's own exhibits, and a
    # missing or duplicated number means an exhibit was dropped or mislabelled.
    exhibit_sets = {}
    for kind in ("Figure", "Table", "Algorithm"):
        labels = sorted(int(m.group(1)) for m in re.finditer(rf"<b>{kind}\s*(\d+):", src))
        exhibit_sets[kind] = labels
        if labels != list(range(1, len(labels) + 1)):
            problems.append(f"{kind} labels not 1..N complete: {labels}")

    # 3c. self-drawn charts (data-selfchart): must announce themselves as the editor's
    # work, and must NOT consume a Figure/Table number — otherwise the 1..N checks above
    # break and readers mistake an editor's chart for one from the paper.
    # Contract: references/lieflat-charts.md
    selfcharts = re.findall(r'<figure class="fig"[^>]*data-selfchart[^>]*>.*?</figure>', src, re.S)
    for i, blk in enumerate(selfcharts, 1):
        cap = re.search(r"<figcaption>.*?</figcaption>", blk, re.S)
        cap_txt = cap.group(0) if cap else ""
        if not re.search(r"本页自绘|Self-drawn", cap_txt):
            problems.append(f"self-drawn chart #{i} is missing the '本页自绘 / Self-drawn' "
                            f"label in its figcaption (readers must be able to tell it apart "
                            f"from the paper's own exhibits)")
        numbered = re.search(r"<b>(Figure|Table)\s*(\d+):", cap_txt)
        if numbered:
            problems.append(f"self-drawn chart #{i} carries a paper exhibit number "
                            f"({numbered.group(1)} {numbered.group(2)}) — self-drawn charts "
                            f"must not consume the 1..N numbering; use a descriptive title")

    # 4. anchors
    ids = set(re.findall(r'id="([^"]+)"', src))
    hrefs = set(re.findall(r'href="#([^"]+)"', src))
    missing_anchors = sorted(hrefs - ids)
    if missing_anchors:
        problems.append(f"missing anchors: {missing_anchors}")

    # 5. tag balance
    for tag in ["section", "table", "figure", "div", "ul", "ol"]:
        o = len(re.findall(rf"<{tag}[ >]", src))
        c = len(re.findall(rf"</{tag}>", src))
        if o != c:
            problems.append(f"<{tag}> open={o} close={c}")

    # 5b. no "empty caption shells": a table that has a <caption> but no content
    # cells (<thead>/<tbody>/<td>/<tr>) is a caption-only shell — it shrinks to
    # min-content width and renders the title as a long narrow column, and it
    # invites scripts to accidentally delete nested <figure> images. Real data
    # tables (e.g. the glossary) carry cells and are unaffected.
    empty_shells = 0
    for m in re.finditer(r'<table\b[^>]*class="data"[^>]*>.*?</table>', src, re.S):
        body = m.group(0)
        if not re.search(r"<(thead|tbody|td|tr|th)\b", body):
            empty_shells += 1
    if empty_shells:
        problems.append(f"empty caption-shell tables found: {empty_shells} — "
                        f"tables must be real data tables (with cells) or be rendered as "
                        f"<figure class='fig'><img src='figs/tableN.png'>… plus figcaption; "
                        f"never nest a caption-only <table> around a table-image figure")

    # 5c. crops.json coverage (only when the file is present next to the page)
    warns += check_crops_coverage(path, src)

    # 6. key-numbers spot check (options: pass via env or skip)
    spot = os.environ.get("SPOT_CHECKS", "")
    for v in [s for s in spot.split(",") if s]:
        if v not in src:
            problems.append(f"missing spot value: {v}")

    # 7. reader experience layer (v2 template features)
    feats = {
        "dark mode css": 'data-theme="dark"' in src,
        "theme toggle button": "theme-toggle" in src,
        "sticky topbar": 'class="topbar"' in src,
        "back-to-top": 'id="backTop"' in src,
        "lightbox": 'id="lightbox"' in src and 'id="lbClose"' in src,
        "image zoom wiring": "figure.fig img" in src and "cursor:zoom-in" in src,
        "glossary section": 'id="s9"' in src,
        "print styles": "@media print" in src,
        "og meta": "og:title" in src,
    }
    missing_feats = [k for k, ok in feats.items() if not ok]
    if missing_feats:
        problems.append(f"missing reader-experience features: {missing_feats}")

    # 7b. language switcher: a lang-toggle link must point at an existing local file
    # (a switcher whose href 404s is a broken bilingual edition; the portal's
    # <button class="lang-toggle"> is inline-i18n and has no href, so it's skipped)
    sibling_names = {os.path.basename(s) for s in siblings}
    for m in re.finditer(r'<a\b[^>]*\bclass="lang-toggle"[^>]*>', src):
        h = re.search(r'href="([^"]+)"', m.group(0))
        if not h:
            continue
        href = h.group(1)
        if href.startswith(("http", "#", "mailto:", "javascript:")):
            continue
        if os.path.exists(href) or os.path.basename(href) in sibling_names:
            continue
        problems.append(f"lang-toggle target missing: {href} "
                        f"(the language switcher must link to an existing edition file; if the "
                        f"bilingual edition is not produced yet, drop a skeleton file first or "
                        f"validate the pair: validate.py zh.html en.html)")

    # 8. abbr terms recommended (at least a few for tutorial value; 0 is suspicious)
    if src.count("<abbr title=") == 0:
        problems.append("no <abbr> terms found — add hover-glosses for abbreviations in the prose")

    # 9. formula rendering (KaTeX) + no unicode combo-char math
    # Accept either the CDN bundle or a locally vendored copy: pages promised to
    # work offline vendor assets/katex/, and that is a legitimate (often required)
    # choice, not a defect.
    has_katex_css = ("katex@0.16.22/dist/katex.min.css" in src
                     or re.search(r'href="[^"]*(?:^|/)katex(?:\.min)?\.css"', src))
    if not has_katex_css or "renderMathInElement" not in src:
        problems.append("missing KaTeX wiring (css/js/auto-render) — formulas won't render")
    for ch in ["\u0124", "\u0304", "\u2080"]:  # Ĥ, combining macron, subscript zero
        if ch in src.split("</style>")[-1]:
            problems.append(f"unicode math combo char U+{ord(ch):04X} still in body — replace with KaTeX")
    if re.search(r'class="cases"', src):
        problems.append("old HTML .cases formula blocks present — migrate to KaTeX display math")

    # 9c. `$..$` inline delimiter vs literal USD amounts (the silent italic-garbage bug)
    problems += check_dollar_math_conflict(src)

    # 9b. source page refs: all-or-none. A page that labels some exhibits with the
    # source page (span.pgref) but not others is half-traceable; 0 refs stays legal
    # for pages built before this convention.
    pg = src.count('class="pgref"')
    if 0 < pg < n_cap:
        problems.append(f"only {pg} of {n_cap} figcaptions carry a source page ref (span.pgref) — "
                        f"add them for every exhibit (scripts/add_pagerefs.py) or none")

    # 10. recommended practices — reported as WARN only, never fail the build
    body = src.split("</style>")[-1]
    if "读数约定" not in src and "Reading conventions" not in src:
        warns.append("reading-conventions note (读数约定 / Reading conventions) — recommended for every page")
    if "et al." not in body:
        warns.append('inline citations like "(Author et al., 2024)" — attribute upstream methods to their papers')
    if pg == 0:
        warns.append("source page refs in figcaptions (span.pgref) — run scripts/add_pagerefs.py")
    if not any(k in body for k in ("值得补测", "未披露", "worth testing", "Not disclosed")):
        warns.append('"not disclosed / worth testing" list in the commentary — recommended')
    # every exhibit should be traceable to a source: either a paper Figure/Table label,
    # or an explicit self-drawn label (see references/lieflat-charts.md)
    unlabelled = 0
    for m in re.finditer(r'<figure class="fig"[^>]*>(.*?)</figure>', src, re.S):
        blk = m.group(1)
        if re.search(r"<b>(Figure|Table|Algorithm)\s*\d+:", blk):
            continue
        if re.search(r"本页自绘|Self-drawn", blk):
            continue
        unlabelled += 1
    if unlabelled:
        warns.append(f"{unlabelled} figure(s) with no 'Figure N:' / 'Table N:' label and no "
                     f"'本页自绘 / Self-drawn' marker — label every exhibit so readers know "
                     f"whether it comes from the paper")

    stats = {
        "exhibits": n_fig,
        "figure_labels": exhibit_sets["Figure"],
        "table_labels": exhibit_sets["Table"],
        "algorithm_labels": exhibit_sets["Algorithm"],
        "data_tables": len(caps),
        "images": len(imgs),
        "selfcharts": len(selfcharts),
    }
    return problems, warns, stats


def _fmt_exhibits(s):
    parts = []
    for kind, key in (("Figure", "figure_labels"), ("Table", "table_labels"), ("Algorithm", "algorithm_labels")):
        labels = s[key]
        if labels:
            parts.append(f"{kind} 1..{labels[-1]}" if labels == list(range(1, len(labels) + 1))
                         else f"{kind} {labels}")
    return " + ".join(parts) if parts else "none"


def main():
    paths = sys.argv[1:] or ["res.html"]
    for p in paths:
        if not os.path.exists(p):
            print(f"FAIL\n - file not found: {p}\n"
                  f"        (run validate.py from the directory containing the HTML, so "
                  f"relative paths like figs/ resolve)", file=sys.stderr)
            sys.exit(2)

    total_problems, total_warns = 0, 0
    for path in paths:
        problems, warns, stats = validate_one(path, siblings=paths)
        label = f"[{path}] " if len(paths) > 1 else ""
        if problems:
            print(f"{label}FAIL")
            for p in problems:
                print(" -", p)
            total_problems += len(problems)
        else:
            print(f"{label}PASS: exhibits={stats['exhibits']} "
                  f"({_fmt_exhibits(stats)}), data-tables={stats['data_tables']}, "
                  f"images={stats['images']}, anchors ok")
            if stats["selfcharts"]:
                print(f"      self-drawn charts (data-selfchart)={stats['selfcharts']} — "
                      f"labelled, not consuming exhibit numbers")
        for w in warns:
            print(f"{label}WARN (recommended): {w}")
        total_warns += len(warns)

    if total_problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
