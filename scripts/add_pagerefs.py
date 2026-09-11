#!/usr/bin/env python3
"""Inject source-page references (span.pgref) into figcaptions, driven by crops.json.

Usage:
    add_pagerefs.py page.html crops.json [--label "报告 p.{p}"] [--dry-run]

- crops.json: {"fig1": {"page": 0, "rect": [...]}, ...}; `page` is the 0-based
  index used for rendering, the label prints page + 1 (the 1-based PDF page).
- For every <img src="figs/<key>.png"> an entry is inserted right before that
  figure's </figcaption>: <span class="pgref">报告 p.7</span>.
  English editions: --label "Report p.{p}".
- Idempotent: exhibits that already carry a pgref are left untouched.
- If the .pgref CSS rule is missing, it is inserted before </style>, so a fresh
  page needs no manual template edit.

Exit code 1 if any crops.json key has no matching image on the page.
"""
import argparse
import json
import re
import sys

CSS = ("  figure.fig figcaption .pgref{display:block; margin-top:6px; padding-top:5px; "
       "border-top:1px dashed var(--border); font-size:12px; color:var(--muted)}\n")


def main():
    ap = argparse.ArgumentParser(description="Add source page refs to figcaptions")
    ap.add_argument("page", help="HTML file to edit in place")
    ap.add_argument("crops", help="crops.json produced for this paper")
    ap.add_argument("--label", default="报告 p.{p}",
                    help='span text, "{p}" is replaced by the 1-based page (default: 报告 p.{p})')
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    src = original = open(args.page, encoding="utf-8").read()
    crops = json.load(open(args.crops, encoding="utf-8"))

    # CSS lives in <style>; add it once if absent
    if "pgref{" not in src:
        i = src.find("</style>")
        if i < 0:
            print("!! no </style> found — is this a reading page?", file=sys.stderr)
            sys.exit(2)
        src = src[:i] + CSS + src[i:]

    added, skipped, missing = 0, 0, []
    for key, meta in crops.items():
        m = re.search(r'src="figs/%s\.(?:png|jpe?g|webp)"' % re.escape(key), src)
        if not m:
            missing.append(key)
            continue
        end = src.find("</figcaption>", m.end())
        if end < 0 or 'class="pgref"' in src[m.end():end]:
            if end < 0:
                missing.append(key)
            else:
                skipped += 1
            continue
        span = '      <span class="pgref">%s</span>\n    ' % args.label.format(p=meta["page"] + 1)
        src = src[:end] + span + src[end:]
        added += 1

    if missing:
        print(f"!! crops keys with no matching <img>: {missing}", file=sys.stderr)
        sys.exit(1)

    if src != original:
        if not args.dry_run:
            open(args.page, "w", encoding="utf-8").write(src)
        print(f"{'[dry-run] ' if args.dry_run else ''}{args.page}: +{added} page refs, {skipped} already present")
    else:
        print(f"{args.page}: no changes (+{added}, {skipped} already present)")


if __name__ == "__main__":
    main()