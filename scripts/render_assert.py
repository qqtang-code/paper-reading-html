#!/usr/bin/env python3
"""Render-level assertions for a paper-reading page.

`validate.py` is a *source* checker: it parses HTML and regexes. That is blind to
failures that only exist after the browser runs — the page can be perfectly valid
HTML, pass every source check, and still render as garbage. The canonical example
is a KaTeX `$..$` inline delimiter colliding with literal USD amounts: every
second dollar sign opens a formula and the prose in between is typeset as italic
math. Nothing in the source looks wrong.

This script loads the page in headless Chromium and asserts what the reader
actually sees:

    1. every ``figure.fig`` image decodes (naturalWidth > 0)
    2. every dollar amount in the source still appears literally in the rendered
       text (catches delimiter collisions)
    3. the number of KaTeX nodes matches the number of math expressions in the
       source, and no ``.katex-error`` node exists
    4. no leftover ``\\(`` / ``\\)`` delimiters leak into visible text
    5. the page does not scroll horizontally
    6. no console errors / page errors

Exit codes:
    0 = PASS
    1 = FAIL (a rendered assertion failed, or a referenced local asset is absent)
    2 = environment/usage error (page missing, Playwright/Chromium not installed,
        KaTeX CDN unreachable so math assertions would be meaningless)

Usage:
    render_assert.py page.html [sibling.html ...]
    render_assert.py page.html --json

Relative references (figs/…, en.html) are resolved against the HTML file's own
directory — exactly what the browser does for a ``file://`` page — so the working
directory does not matter and cannot produce phantom "broken image" failures.
"""
import argparse
import json
import os
import pathlib
import re
import sys

EXIT_PASS, EXIT_FAIL, EXIT_ENV = 0, 1, 2

# Relative references a reading page may use.
_ASSET_RE = re.compile(r'(?:src|href)="((?:figs/|assets/)[^"]+|[^":/]+\.(?:html|css|js))"')


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")


def strip_source_noise(src):
    """Remove script/style/comment blocks so their contents are not counted.

    Necessary because a maintainer note that *mentions* a delimiter (e.g. a
    comment showing an inline-math example) would otherwise be counted as a real
    math site and produce a false failure.
    """
    src = re.sub(r"<script\b.*?</script>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<style\b.*?</style>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return src


def amounts_from_source(body):
    """Distinct ``$1.23``-style amounts in the (noise-stripped) source."""
    found = set()
    for m in re.finditer(r"\$(\d[\d,]*(?:\.\d+)?)", body):
        found.add("$" + m.group(1).rstrip(".,"))
    return found


def count_math_sites(body):
    """Number of display + inline math expressions the renderer should typeset."""
    display = len(re.findall(r"\$\$.+?\$\$", body, flags=re.S))
    inline = len(re.findall(r"\\\(.+?\\\)", body, flags=re.S))
    return display + inline


def preflight(html_path, src):
    """Return (missing_local_assets, checked_count).

    Paths are resolved against the HTML file's own directory, not the current
    working directory. That is what a browser does for ``file://`` pages, so
    running this script from the wrong directory can no longer manufacture
    phantom "broken image" failures (a real defect found during development).
    A genuinely absent asset is therefore a page defect, not an environment one.
    """
    base = html_path.parent
    missing = []
    seen = set()
    for m in _ASSET_RE.finditer(src):
        ref = m.group(1)
        if ref in seen or ref.startswith(("http", "#", "mailto:", "javascript:", "data:")):
            continue
        seen.add(ref)
        if not (base / ref).exists():
            missing.append(ref)
    return missing, len(seen)


def run_checks(html_path, src):
    """Open the page in Chromium and collect rendered facts + failures."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("render_assert: Playwright is not installed.\n"
              "  pip install playwright && playwright install chromium\n"
              "Skipping is not equivalent to passing — without a browser this class "
              "of failure cannot be detected.", file=sys.stderr)
        sys.exit(EXIT_ENV)

    body = strip_source_noise(src)
    expect_amounts = amounts_from_source(body)
    expect_math = count_math_sites(body)

    fails, warns, facts = [], [], {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binary missing
            print(f"render_assert: cannot launch Chromium ({exc}).\n"
                  f"  run: playwright install chromium", file=sys.stderr)
            sys.exit(EXIT_ENV)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        console_errors, page_errors = [], []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        try:
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=90_000)
            page.wait_for_timeout(1200)
        except Exception as exc:
            browser.close()
            print(f"render_assert: could not load {html_path} ({exc})", file=sys.stderr)
            sys.exit(EXIT_ENV)

        # (1) figures decode
        imgs = page.eval_on_selector_all(
            "figure.fig img",
            "els => els.map(e => ({src: e.getAttribute('src'), ok: !!e.complete && e.naturalWidth > 0}))")
        broken = [i["src"] for i in imgs if not i["ok"]]
        facts["figures"] = len(imgs)
        facts["broken_images"] = broken

        # (2)/(3)/(4) KaTeX state
        katex_nodes = page.eval_on_selector_all(".katex", "els => els.length")
        katex_errors = page.eval_on_selector_all(".katex-error", "els => els.length")
        facts["katex_nodes"] = katex_nodes
        facts["katex_errors"] = katex_errors
        facts["expected_math"] = expect_math

        # (5) visible text
        text = page.evaluate("() => document.body.innerText")
        # CDN unreachable: page expects math, none rendered, and the renderer is absent
        if expect_math and katex_nodes == 0:
            renderer_present = page.evaluate(
                "() => typeof window.renderMathInElement !== 'undefined'")
            if not renderer_present:
                page.close(); browser.close()
                print("render_assert: KaTeX did not load (CDN unreachable — is this machine "
                      "offline?). Math assertions would be meaningless, so aborting.\n"
                      "  vendor KaTeX under assets/katex/ for offline pages.", file=sys.stderr)
                sys.exit(EXIT_ENV)

        missing_amounts = sorted(a for a in expect_amounts if a not in text)
        facts["amounts"] = len(expect_amounts)
        facts["amounts_swallowed"] = missing_amounts
        facts["dollar_signs_rendered"] = text.count("$")

        leaked = bool(re.search(r"\\\(|\\\)", text))
        facts["delimiter_leak"] = leaked

        # (5) overflow
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        facts["overflow_px"] = overflow

        facts["console_errors"] = console_errors[:5]
        facts["page_errors"] = page_errors[:5]
        page.close()
        browser.close()

    # ---- verdicts -------------------------------------------------------
    if broken:
        fails.append(f"{len(broken)} figure image(s) failed to decode: {broken[:5]}")
    if missing_amounts:
        fails.append(
            f"{len(missing_amounts)} of {len(expect_amounts)} dollar amount(s) are not rendered "
            f"literally — the renderer consumed them as math delimiters "
            f"(e.g. {missing_amounts[:5]}). Remove the {{left:'$',right:'$'}} KaTeX "
            f"delimiter and write inline math as \\(...\\)")
    if katex_errors:
        fails.append(f"{katex_errors} KaTeX error node(s) — a formula failed to parse")
    if expect_math and katex_nodes != expect_math:
        fails.append(
            f"KaTeX nodes ({katex_nodes}) != math expressions in source ({expect_math}): "
            f"delimiters are mismatched — either a formula did not render or stray "
            f"delimiters created extra ones")
    if leaked:
        fails.append("literal \\( or \\) leaked into visible text — inline-math delimiters "
                     "were not consumed by the renderer")
    if overflow > 2:
        fails.append(f"page scrolls horizontally by {overflow}px (overflow) — a wide "
                     f"element is not constrained to max-width:100%")
    if console_errors or page_errors:
        fails.append(f"runtime errors: {len(console_errors)} console / {len(page_errors)} page "
                     f"error(s): {(console_errors + page_errors)[:3]}")
    if not expect_math:
        warns.append("no math expressions found in source — KaTeX assertions were vacuous")
    if not expect_amounts:
        warns.append("no dollar amounts found in source — delimiter-collision check was vacuous")
    return fails, warns, facts


def main():
    ap = argparse.ArgumentParser(description="Render-level assertions for a reading page")
    ap.add_argument("pages", nargs="*", default=["index.html"],
                    help="HTML files to check (default: index.html)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    exit_code = EXIT_PASS
    report = {}
    for name in args.pages:
        path = pathlib.Path(name)
        if not path.exists():
            print(f"render_assert: file not found: {name}", file=sys.stderr)
            sys.exit(EXIT_ENV)
        src = _read(path)

        missing_assets, checked = preflight(path, src)
        fails, warns, facts = run_checks(path, src)
        if missing_assets:
            fails.insert(0, f"{len(missing_assets)} referenced local asset(s) do not exist "
                            f"next to the page: {missing_assets[:8]}")
        report[name] = {"fail": fails, "warn": warns, "facts": facts}
        print(f"=== {name} ===")
        print(f"  图表      figures={facts['figures']} broken={len(facts['broken_images'])}")
        print(f"  金额      source={facts['amounts']} distinct  "
              f"被吞={len(facts['amounts_swallowed'])}  rendered-$={facts['dollar_signs_rendered']}")
        print(f"  KaTeX     期望={facts['expected_math']} 节点={facts['katex_nodes']} "
              f"错误={facts['katex_errors']} 残留分隔符={facts['delimiter_leak']}")
        print(f"  布局      横向溢出={facts['overflow_px']}px  "
              f"console/pageerror={len(facts['console_errors']) + len(facts['page_errors'])}")
        for w in warns:
            print(f"  WARN (recommended): {w}")
        if fails:
            exit_code = EXIT_FAIL
            for f in fails:
                print(f"  FAIL: {f}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if exit_code == EXIT_PASS:
        print("\nRENDER-ASSERT PASS: 图表可解码 / 金额字面存活 / KaTeX 无错误 / 无溢出 / 无运行期错误")
    else:
        print("\nRENDER-ASSERT FAIL")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
