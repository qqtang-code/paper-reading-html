#!/usr/bin/env python3
"""Check that the vendored lieflat-charts copy is intact and licence-complete.

Usage:
    vendor_check.py [repo_root]        # default: the directory containing scripts/
    vendor_check.py --digest           # also print the current manifest digest

Verifies:
  * every file the chart workflow needs is present (codex, catalogues, tokens,
    galleries, report templates, licence, third-party notices);
  * the upstream PolyForm Noncommercial licence text is unmodified in substance
    (title + canonical URL present) — it must be redistributed with the copy;
  * optionally, the recorded manifest digest still matches (set STRICT=1 to fail
    on mismatch, useful in CI once the copy is frozen).

Exit 0 = intact, 1 = something is missing or altered.
"""
import hashlib
import os
import re
import sys

REQUIRED = [
    "SKILL.md",
    "catalog.md",
    "report-catalog.md",
    "mono-tokens.js",
    "color-presets.js",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "VENDORED.md",
    "templates/lupi-gallery.html",
    "templates/basics-gallery.html",
    "templates/glance-gallery.html",
    "templates/maps-gallery.html",
    "scripts/validate.mjs",
]
LICENCE_URL = "polyformproject.org/licenses/noncommercial/1.0.0"
LICENCE_TITLE = "PolyForm Noncommercial License 1.0.0"


def manifest_digest(root):
    """sha256 over '<sha256>  <relpath>' lines, path-sorted.

    Covers the *upstream* content only: VENDORED.md (our provenance note) is skipped,
    otherwise writing the digest into that file would change the digest it records.
    """
    rows = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn == "VENDORED.md":
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            with open(p, "rb") as fh:
                rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {rel}")
    rows.sort()
    return hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest()


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_digest = "--digest" in sys.argv
    repo = os.path.abspath(argv[0]) if argv else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    root = os.path.join(repo, "vendor", "lieflat-charts")

    problems = []
    if not os.path.isdir(root):
        print(f"FAIL: vendored copy missing at {root}")
        return 1

    for rel in REQUIRED:
        if not os.path.exists(os.path.join(root, rel)):
            problems.append(f"missing: vendor/lieflat-charts/{rel}")

    lic_path = os.path.join(root, "LICENSE")
    if os.path.exists(lic_path):
        lic = open(lic_path, encoding="utf-8").read()
        if LICENCE_TITLE not in lic:
            problems.append("LICENSE does not carry the PolyForm Noncommercial 1.0.0 title")
        if LICENCE_URL not in lic:
            problems.append(f"LICENSE does not carry the canonical URL ({LICENCE_URL})")
        # the licence must travel with every copy we hand out
        if not os.path.exists(os.path.join(repo, "vendor", "README.md")):
            problems.append("vendor/README.md missing — recipients need the licence pointer")

    # a sanity read of the codex: it drives every selection decision
    skill = os.path.join(root, "SKILL.md")
    if os.path.exists(skill):
        s = open(skill, encoding="utf-8").read()
        for needle, why in [
            ("catalog.md", "codex must still point at the catalogue"),
            ("mono-tokens.js", "codex must still point at the design tokens"),
        ]:
            if needle not in s:
                problems.append(f"SKILL.md no longer references {needle} ({why})")

    digest = manifest_digest(root)
    recorded = None
    vp = os.path.join(root, "VENDORED.md")
    if os.path.exists(vp):
        m = re.search(r"Manifest digest \| `sha256:([0-9a-f]{64})`", open(vp, encoding="utf-8").read())
        recorded = m.group(1) if m else None
    if recorded and recorded != digest:
        msg = (f"manifest digest changed: recorded {recorded[:16]}… != current {digest[:16]}… "
               f"(expected if you re-vendored — update VENDORED.md)")
        if os.environ.get("STRICT") == "1":
            problems.append(msg)
        else:
            print(f"NOTE: {msg}")

    # the galleries must be renderable HTML, not empty stubs
    galleries = sorted(f for f in os.listdir(os.path.join(root, "templates"))
                       if f.endswith(".html")) if os.path.isdir(os.path.join(root, "templates")) else []
    if len(galleries) < 4:
        problems.append(f"expected >=4 gallery templates, found {len(galleries)}: {galleries}")
    for g in galleries:
        p = os.path.join(root, "templates", g)
        if os.path.getsize(p) < 3000:
            problems.append(f"gallery looks truncated: templates/{g} ({os.path.getsize(p)} bytes)")

    if show_digest:
        print(f"manifest digest: sha256:{digest}")

    if problems:
        print("FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print(f"PASS: vendored lieflat-charts intact ({len(REQUIRED)} required files, "
          f"{len(galleries)} galleries, licence present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())