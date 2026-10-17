#!/usr/bin/env python3
"""Check a Paper-Reading-Collection repository for consistency.

Usage
-----
    python3 check_collection.py [root] [--json] [--lenient-order]

``root`` defaults to the current directory and must be the repository root
(the directory containing ``index.html`` and ``README.md``).

What is checked
---------------
A. Portal cards in ``root/index.html``
   * every ``<div class="pcard">`` has a Chinese and an English title link;
   * both title links start with a circled number (①..⑳, ㉑..㉟);
   * Chinese and English numbers agree within one card;
   * numbers are unique and together are exactly 1..N;
   * numbers follow DOM order 1..N.  Duplicates/gaps are always fatal; a
     pure permutation is fatal too, unless ``--lenient-order`` is given;
   * every local href resolves to a real file (a directory href means
     ``<dir>/index.html``).

B. Paper set
   * cards' Chinese hrefs identify paper directories
     (a directory with ``index.html`` + ``figs/``);
   * directories with ``index.html`` + ``figs/`` that no card references are
     reported as orphan papers;
   * cards whose href is missing (or does not point into a paper directory)
     are reported as dangling cards.

C. ``root/README.md``
   * the ``论文总览`` table's row numbers are 1..N;
   * each row's number equals that paper's portal card number (a table can be
     1..N with the right papers yet assign the numbers to the wrong rows);
   * every paper link in those rows resolves to a paper directory;
   * README papers are compared with the portal-card set (missing README rows
     are a warning; extra or broken rows are failures);
   * collection statistics (``论文 <b>N</b> 篇`` /
     ``<b>N</b> papers``, ``图表 <b>X</b> 图 + <b>Y</b> 表`` /
     ``<b>X</b> figures + <b>Y</b> tables``) are parsed from ``index.html``
     and ``README.md`` and compared against a recount from disk:
     papers = number of portal cards, figures = ``figs/fig*.png``,
     tables = ``figs/table*.png``.

D. Category ``README.md`` files
   * every markdown link inside a table row resolves to an existing local
     file or directory.

E. Per-paper completeness (lightweight)
   * a referenced paper directory has ``index.html``;
   * ``figs/`` exists and is non-empty;
   * an existing ``en.html`` is not inspected further.

The checker is strictly read-only.  It uses only the Python standard library
and works on Python 3.8+.

Exit codes
----------
    0 = PASS (warnings are allowed)
    1 = FAIL
    2 = usage error (argparse)

Example
-------
    $ python3 check_collection.py /path/to/Paper-Reading-Collection
    === collection: /path/to/Paper-Reading-Collection ===
    [ OK ] 14 cards, 14 papers discovered, README rows aligned
    [ OK ] stats: 14 papers / 110 figures / 103 tables
    PASS

    $ python3 check_collection.py /path/to/Paper-Reading-Collection --json
    { ... machine-readable object ... }
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import unquote, urlsplit


# ---------------------------------------------------------------------------
# Circled numbers: ①..⑳ (U+2460..U+2473), ㉑..㉟ (U+3251..U+325F)
# ---------------------------------------------------------------------------

_CIRCLED_TO_INT: Dict[str, int] = {}
for _i in range(1, 21):
    _CIRCLED_TO_INT[chr(0x2460 + _i - 1)] = _i
for _i in range(21, 36):
    _CIRCLED_TO_INT[chr(0x3251 + _i - 21)] = _i


def circled(n: Optional[int]) -> str:
    """Return the circled glyph for *n* (or a readable fallback)."""
    if n is None:
        return "?"
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if 21 <= n <= 35:
        return chr(0x3251 + n - 21)
    return "({})".format(n)


# ---------------------------------------------------------------------------
# Small report model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    level: str  # "FAIL" or "WARN"
    code: str
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class Report:
    def __init__(self) -> None:
        self.errors: List[Finding] = []
        self.warnings: List[Finding] = []
        self.ok: List[str] = []
        self.info: List[str] = []

    def fail(self, code: str, message: str, **detail: Any) -> None:
        self.errors.append(Finding("FAIL", code, message, detail))

    def warn(self, code: str, message: str, **detail: Any) -> None:
        self.warnings.append(Finding("WARN", code, message, detail))

    def ok_line(self, message: str) -> None:
        self.ok.append(message)

    def info_line(self, message: str) -> None:
        self.info.append(message)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def rel(root: Path, path: Optional[Path]) -> str:
    """Path relative to *root*, always using forward slashes."""
    if path is None:
        return ""
    try:
        value = os.path.relpath(str(path), str(root))
    except ValueError:
        value = str(path)
    return value.replace(os.sep, "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _mask_match(match: "re.Match[str]") -> str:
    """Replace a matched block with spaces, preserving line breaks/offsets."""
    return re.sub(r"[^\n]", " ", match.group(0))


def blank_html_noise(text: str) -> str:
    """Blank comments/scripts/styles while preserving character offsets."""
    text = re.sub(r"<!--.*?-->", _mask_match, text, flags=re.S)
    text = re.sub(r"<script\b.*?</script>", _mask_match, text, flags=re.S | re.I)
    text = re.sub(r"<style\b.*?</style>", _mask_match, text, flags=re.S | re.I)
    return text


def strip_tags(fragment: str) -> str:
    fragment = re.sub(
        r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I
    )
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return collapse(html.unescape(fragment))


def line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def parse_attrs(attr_text: str) -> Dict[str, str]:
    """Parse a tag's attribute string into a lowercase-key dict."""
    attrs: Dict[str, str] = {}
    pattern = re.compile(
        r"([^\s=/>]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+)))?"
    )
    for match in pattern.finditer(attr_text):
        name = match.group(1).lower()
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        if value is None:
            value = ""
        attrs[name] = html.unescape(value)
    return attrs


# ---------------------------------------------------------------------------
# Href resolution
# ---------------------------------------------------------------------------


def href_target(
    href: Optional[str], base: Path, root: Path
) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a local href.

    Returns ``(path, reason)``.  ``reason`` is one of ``None`` (resolved),
    ``"empty"``, ``"fragment"`` or ``"external"``.  A leading ``/`` is treated
    as relative to the collection root, which is the useful interpretation for
    a GitHub-Pages project subpath.
    """
    if href is None:
        return None, "empty"
    raw = html.unescape(href).strip()
    if not raw:
        return None, "empty"
    if raw.startswith("#"):
        return None, "fragment"
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return None, "external"
    path = unquote(parts.path)
    if not path:
        return None, "fragment"
    if path.startswith("/"):
        target = root / path.lstrip("/")
    else:
        target = base / path
    return Path(os.path.normpath(str(target))), None


def existing_file_target(path: Optional[Path]) -> Optional[Path]:
    """Resolve a path to an existing file; a directory means index.html."""
    if path is None:
        return None
    if path.is_dir():
        index = path / "index.html"
        return index if index.is_file() else None
    if path.is_file():
        return path
    return None


def paper_dir_for(path: Optional[Path]) -> Optional[Path]:
    """Return the paper directory containing *path*, if it looks like one."""
    if path is None:
        return None
    candidate = path if path.is_dir() else path.parent
    if (candidate / "index.html").is_file() and (candidate / "figs").is_dir():
        return candidate.resolve()
    return None


# ---------------------------------------------------------------------------
# HTML card parsing
# ---------------------------------------------------------------------------


def find_pcard_blocks(text: str) -> List[str]:
    """Split the portal HTML into ``<div class="pcard">`` blocks."""
    starts: List[int] = []
    for match in re.finditer(r"<div\b([^>]*)>", text, flags=re.S | re.I):
        attrs = parse_attrs(match.group(1))
        classes = attrs.get("class", "").split()
        if "pcard" in classes:
            starts.append(match.start())

    blocks: List[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        section_end = text.find("</section>", start)
        if section_end != -1 and section_end < end:
            end = section_end
        blocks.append(text[start:end])
    return blocks


def find_title_anchor(block: str, lang: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Find the first ``i18n-zh`` / ``i18n-en`` anchor inside the card's h3."""
    h3 = re.search(r"<h3\b[^>]*>(.*?)</h3>", block, flags=re.S | re.I)
    scope = h3.group(1) if h3 else block
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", scope, flags=re.S | re.I):
        attrs = parse_attrs(match.group(1))
        classes = attrs.get("class", "").split()
        if lang in classes:
            return attrs, match.group(2)
    return None, None


def parse_title(inner: Optional[str]) -> Tuple[Optional[int], str]:
    """Extract the circled number and the short title from anchor inner HTML."""
    if inner is None:
        return None, ""
    # The card title is before <br>; the subtitle is inside a following span.
    # Only split on <br>: the title itself may be wrapped in a <span>.
    first = re.split(r"<br\s*/?>", inner, maxsplit=1, flags=re.I)[0]
    text = strip_tags(first)
    if not text:
        return None, ""
    first_char = text[0]
    number = _CIRCLED_TO_INT.get(first_char)
    if number is None:
        return None, text
    rest = text[1:]
    rest = rest.lstrip("\ufe0f \t\r\n.、:：-—–")
    return number, collapse(rest)


@dataclass
class Card:
    index: int
    number: Optional[int]
    number_en: Optional[int]
    name: str
    name_en: str
    zh_href: Optional[str]
    en_href: Optional[str]
    zh_target: Optional[Path]
    en_target: Optional[Path]
    paper_dir: Optional[Path]
    dangling_reason: Optional[str] = None

    def as_dict(self, root: Path) -> Dict[str, Any]:
        return {
            "index": self.index,
            "number": self.number,
            "number_glyph": circled(self.number),
            "number_en": self.number_en,
            "name": self.name,
            "name_en": self.name_en,
            "zh_href": self.zh_href,
            "en_href": self.en_href,
            "zh_target": rel(root, self.zh_target),
            "en_target": rel(root, self.en_target),
            "paper_dir": rel(root, self.paper_dir),
            "dangling_reason": self.dangling_reason,
        }


def parse_cards(root: Path, report: Report) -> List[Card]:
    index_path = root / "index.html"
    if not index_path.is_file():
        report.fail(
            "portal.index_missing",
            "portal index.html not found: {}".format(rel(root, index_path)),
        )
        return []

    text = blank_html_noise(read_text(index_path))
    blocks = find_pcard_blocks(text)
    if not blocks:
        report.fail(
            "portal.no_cards",
            "no <div class=\"pcard\"> cards found in {}".format(rel(root, index_path)),
        )
        return []

    cards: List[Card] = []
    for index, block in enumerate(blocks, 1):
        zh_attrs, zh_inner = find_title_anchor(block, "i18n-zh")
        en_attrs, en_inner = find_title_anchor(block, "i18n-en")

        zh_number, zh_name = parse_title(zh_inner)
        en_number, en_name = parse_title(en_inner)

        zh_href = zh_attrs.get("href") if zh_attrs else None
        en_href = en_attrs.get("href") if en_attrs else None
        name = zh_name or en_name or "card {}".format(index)
        name_en = en_name or zh_name

        if zh_attrs is None:
            report.fail(
                "portal.zh_link_missing",
                "card {} ({}): missing Chinese title link <a class=\"i18n-zh\">".format(
                    index, name
                ),
            )
        if en_attrs is None:
            report.fail(
                "portal.en_link_missing",
                "card {} ({}): missing English title link <a class=\"i18n-en\">".format(
                    index, name
                ),
            )
        if zh_attrs is not None and not zh_href:
            report.fail(
                "portal.zh_href_empty",
                "card {} ({}): Chinese title link has no href".format(index, name),
            )
        if en_attrs is not None and not en_href:
            report.fail(
                "portal.en_href_empty",
                "card {} ({}): English title link has no href".format(index, name),
            )
        if zh_number is None and en_number is None:
            report.fail(
                "portal.card_number_missing",
                "card {} ({}): title does not start with a circled number".format(
                    index, name
                ),
            )
        elif zh_attrs is not None and zh_number is None:
            report.fail(
                "portal.zh_number_missing",
                "card {} ({}): Chinese title does not start with a circled number".format(
                    index, name
                ),
            )
        elif en_attrs is not None and en_number is None:
            report.fail(
                "portal.en_number_missing",
                "card {} ({}): English title does not start with a circled number".format(
                    index, name
                ),
            )
        if zh_number is not None and en_number is not None and zh_number != en_number:
            report.fail(
                "portal.card_lang_number_mismatch",
                "card {} ({}): Chinese {} vs English {} title number".format(
                    index, name, circled(zh_number), circled(en_number)
                ),
            )

        number = zh_number if zh_number is not None else en_number

        # Chinese href -> paper directory
        zh_target: Optional[Path] = None
        paper_dir: Optional[Path] = None
        dangling_reason: Optional[str] = None
        if zh_attrs is None:
            dangling_reason = "missing Chinese title link"
        elif not zh_href:
            dangling_reason = "empty Chinese href"
        if zh_href:
            zh_target, reason = href_target(zh_href, root, root)
            if reason is not None:
                dangling_reason = "href is {}".format(reason)
            elif zh_target is None:
                dangling_reason = "href did not resolve"
            elif existing_file_target(zh_target) is None:
                if zh_target.is_dir():
                    dangling_reason = "directory has no index.html"
                else:
                    dangling_reason = "target does not exist"
            else:
                paper_dir = paper_dir_for(zh_target)
                if paper_dir is None:
                    dangling_reason = (
                        "target is not inside a paper directory "
                        "(needs index.html + figs/)"
                    )
            if dangling_reason is not None:
                report.fail(
                    "paper.dangling",
                    "dangling card {} ({}): Chinese href {!r} -> {} ({})".format(
                        index,
                        name,
                        zh_href,
                        rel(root, zh_target),
                        dangling_reason,
                    ),
                )

        # English href -> existing file
        en_target: Optional[Path] = None
        if en_href:
            en_target, reason = href_target(en_href, root, root)
            if reason is not None:
                report.fail(
                    "portal.en_href_unresolved",
                    "card {} ({}): English href {!r} is {}".format(
                        index, name, en_href, reason
                    ),
                )
            elif existing_file_target(en_target) is None:
                report.fail(
                    "portal.en_href_missing",
                    "card {} ({}): English href {!r} -> {} does not exist".format(
                        index, name, en_href, rel(root, en_target)
                    ),
                )
            else:
                en_paper = paper_dir_for(en_target)
                if paper_dir is not None and en_paper is not None and en_paper != paper_dir:
                    report.fail(
                        "portal.card_lang_target_mismatch",
                        "card {} ({}): Chinese and English links point to different "
                        "paper directories ({} vs {})".format(
                            index,
                            name,
                            rel(root, paper_dir),
                            rel(root, en_paper),
                        ),
                    )

        cards.append(
            Card(
                index=index,
                number=number,
                number_en=en_number,
                name=name,
                name_en=name_en,
                zh_href=zh_href,
                en_href=en_href,
                zh_target=zh_target,
                en_target=en_target,
                paper_dir=paper_dir,
                dangling_reason=dangling_reason,
            )
        )
    return cards


# ---------------------------------------------------------------------------
# A/order: card numbers
# ---------------------------------------------------------------------------


def check_card_numbers(cards: Sequence[Card], report: Report, strict_order: bool) -> None:
    total = len(cards)
    if not cards:
        return

    numbers = [card.number for card in cards]
    known = [number for number in numbers if number is not None]

    counts = Counter(known)
    duplicates = {
        number: [card.name for card in cards if card.number == number]
        for number, count in counts.items()
        if count > 1
    }
    if duplicates:
        parts = []
        for number in sorted(duplicates):
            parts.append("{} -> [{}]".format(number, ", ".join(duplicates[number])))
        report.fail(
            "portal.card_numbers_duplicate",
            "portal card numbers not unique: " + "; ".join(parts),
            duplicates={str(k): v for k, v in duplicates.items()},
        )

    out_of_range = sorted(n for n in set(known) if n < 1 or n > total)
    if out_of_range:
        report.fail(
            "portal.card_numbers_out_of_range",
            "portal card numbers outside 1..{}: {}".format(
                total, ", ".join(str(n) for n in out_of_range)
            ),
            numbers=out_of_range,
        )

    expected_numbers = set(range(1, total + 1))
    missing = sorted(expected_numbers - set(known))
    if missing:
        report.fail(
            "portal.card_numbers_gap",
            "portal card numbers are not 1..{}: missing {}".format(
                total,
                ", ".join("{} ({})".format(n, circled(n)) for n in missing),
            ),
            missing=missing,
        )

    mismatches: List[Tuple[int, int, str]] = []
    for expected, card in enumerate(cards, 1):
        if card.number is not None and card.number != expected:
            mismatches.append((expected, card.number, card.name))
    if mismatches:
        pieces = [
            "position {} has {} ({}), expected {}".format(
                position, circled(actual), name, circled(position)
            )
            for position, actual, name in mismatches
        ]
        message = "portal card numbers are not in 1..{} DOM order: {}".format(
            total, "; ".join(pieces)
        )
        if duplicates or missing or strict_order:
            report.fail(
                "portal.card_order",
                message,
                mismatches=[
                    {"position": p, "actual": a, "expected": p, "name": n}
                    for p, a, n in mismatches
                ],
            )
        else:
            report.warn(
                "portal.card_order",
                message
                + " (pure permutation; accepted only because --lenient-order was given)",
                mismatches=[
                    {"position": p, "actual": a, "expected": p, "name": n}
                    for p, a, n in mismatches
                ],
            )
    elif not duplicates and not missing and all(n is not None for n in numbers):
        report.ok_line(
            "portal: {} cards numbered ①..{} in DOM order".format(
                total, circled(total)
            )
        )


# ---------------------------------------------------------------------------
# B: paper discovery / orphan / dangling
# ---------------------------------------------------------------------------


def discover_paper_dirs(root: Path) -> List[Path]:
    """Recursively find directories that look like paper directories."""
    papers: List[Path] = []
    ignored = {"node_modules", "__pycache__", "vendor"}
    for dirpath, dirnames, _filenames in os.walk(str(root)):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in ignored
        ]
        path = Path(dirpath)
        if path == root:
            continue
        if (path / "index.html").is_file() and (path / "figs").is_dir():
            papers.append(path.resolve())
    return sorted(papers, key=lambda p: str(p))


def count_assets(paper_dir: Path) -> Tuple[int, int]:
    """Return (figures, tables) for a paper directory."""
    figures = 0
    tables = 0
    figs_dir = paper_dir / "figs"
    if not figs_dir.is_dir():
        return 0, 0
    try:
        entries = list(figs_dir.iterdir())
    except OSError:
        return 0, 0
    for entry in entries:
        if not entry.is_file():
            continue
        low = entry.name.lower()
        if low.startswith("fig") and low.endswith(".png"):
            figures += 1
        elif low.startswith("table") and low.endswith(".png"):
            tables += 1
    return figures, tables


def referenced_papers(
    root: Path, cards: Sequence[Card], report: Report
) -> List[Path]:
    """Unique paper directories referenced by cards; report duplicate targets."""
    seen: Dict[Path, int] = {}
    ordered: List[Path] = []
    for card in cards:
        paper = card.paper_dir
        if paper is None:
            continue
        if paper in seen:
            report.fail(
                "paper.duplicate_card_target",
                "cards {} and {} both point to the same paper directory: {}".format(
                    seen[paper], card.index, rel(root, paper)
                ),
                first_card=seen[paper],
                second_card=card.index,
                paper=rel(root, paper),
            )
        else:
            seen[paper] = card.index
            ordered.append(paper)
    return ordered


def check_paper_set(
    root: Path,
    cards: Sequence[Card],
    card_papers: Sequence[Path],
    report: Report,
) -> Tuple[List[Path], List[Path], List[Path]]:
    """Check orphans/dangling; return (discovered, orphans, dangling)."""
    card_set = set(card_papers)
    discovered = discover_paper_dirs(root)

    dangling = [card for card in cards if card.paper_dir is None]

    orphans = [paper for paper in discovered if paper not in card_set]
    if not cards:
        if discovered:
            report.warn(
                "paper.orphan_scan_skipped",
                "portal has no cards; cannot classify {} paper directories "
                "(orphan scan skipped)".format(len(discovered)),
            )
    else:
        for paper in orphans:
            figures, tables = count_assets(paper)
            report.fail(
                "paper.orphan",
                "orphan paper (not referenced by any portal card): {} "
                "({} figs / {} tables)".format(
                    rel(root, paper), figures, tables
                ),
                paper=rel(root, paper),
                figures=figures,
                tables=tables,
            )
    return discovered, orphans, dangling


# ---------------------------------------------------------------------------
# E: per-paper completeness
# ---------------------------------------------------------------------------


def check_paper_completeness(
    root: Path, cards: Sequence[Card], report: Report
) -> int:
    """Check index.html / figs/ for each referenced paper; return count."""
    seen: Set[Path] = set()
    checked = 0
    failed = False
    for card in cards:
        paper = card.paper_dir
        if paper is None or paper in seen:
            continue
        seen.add(paper)
        checked += 1

        if not (paper / "index.html").is_file():
            failed = True
            report.fail(
                "paper.index_missing",
                "paper {}: index.html missing (referenced by card {})".format(
                    rel(root, paper), card.index
                ),
                paper=rel(root, paper),
            )

        figs = paper / "figs"
        if not figs.is_dir():
            failed = True
            report.fail(
                "paper.figs_missing",
                "paper {}: figs/ directory missing (referenced by card {})".format(
                    rel(root, paper), card.index
                ),
                paper=rel(root, paper),
            )
        else:
            try:
                non_empty = any(figs.iterdir())
            except OSError:
                non_empty = False
            if not non_empty:
                failed = True
                report.fail(
                    "paper.figs_empty",
                    "paper {}: figs/ is empty (referenced by card {})".format(
                        rel(root, paper), card.index
                    ),
                    paper=rel(root, paper),
                )

    if checked and not failed:
        report.ok_line(
            "paper completeness: {}/{} (index.html + non-empty figs/)".format(
                checked, checked
            )
        )
    return checked


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(
    r"(?<!!)\[([^\]]*)\]\(\s*(?:<([^>\n]+)>|([^)\s]+))"
    r"(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)


def find_markdown_links(line: str) -> Iterator[Tuple[str, str, int]]:
    """Yield (label, href, position) for inline markdown links."""
    for match in _MD_LINK_RE.finditer(line):
        href = match.group(2) or match.group(3) or ""
        yield match.group(1), href, match.start()


def split_table_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def strip_md_inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return collapse(html.unescape(text))


def markdown_section(lines: Sequence[str], title: str) -> Tuple[Optional[List[str]], Optional[int]]:
    """Return (section lines, 1-based first line) for a ``## title`` section."""
    for index, line in enumerate(lines):
        match = re.match(
            r"^(#{1,6})\s*" + re.escape(title) + r"\s*$", line.strip()
        )
        if not match:
            continue
        level = len(match.group(1))
        start = index + 1
        end = len(lines)
        for cursor in range(start, len(lines)):
            heading = re.match(r"^(#{1,6})\s+", lines[cursor])
            if heading and len(heading.group(1)) <= level:
                end = cursor
                break
        return list(lines[start:end]), start + 1
    return None, None


# ---------------------------------------------------------------------------
# C: README 论文总览 table
# ---------------------------------------------------------------------------


@dataclass
class ReadmeRow:
    number: int
    name: str
    paper_dir: Optional[Path]
    line: int


def check_readme_table(
    root: Path, cards: Sequence[Card], card_papers: Sequence[Path], report: Report
) -> Dict[str, Any]:
    readme_path = root / "README.md"
    result: Dict[str, Any] = {
        "exists": readme_path.is_file(),
        "section_found": False,
        "rows": [],
        "row_numbers_ok": False,
        "all_rows_linked": False,
        "extra_papers": [],
        "missing_papers": [],
        "number_mismatch": [],
        "broken_links": [],
    }
    if not readme_path.is_file():
        report.fail(
            "readme.missing",
            "README.md not found at collection root: {}".format(rel(root, readme_path)),
        )
        return result

    text = blank_html_noise(read_text(readme_path))
    lines = text.splitlines()
    section, section_start = markdown_section(lines, "论文总览")
    if section is None or section_start is None:
        report.fail(
            "readme.section_missing",
            "README.md: '## 论文总览' section not found",
        )
        return result
    result["section_found"] = True

    rows: List[ReadmeRow] = []
    broken_links: List[Dict[str, str]] = []
    row_link_failures = False
    for offset, line in enumerate(section):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = split_table_row(line)
        if len(cells) < 2:
            continue
        first = strip_md_inline(cells[0])
        if not re.fullmatch(r"\d+", first):
            continue
        number = int(first)
        name = strip_md_inline(cells[1])
        # Keep only the paper title before an em/en dash.
        name = re.split(r"\s+[—–-]\s+", name, maxsplit=1)[0].strip()
        if not name:
            name = "row {}".format(number)
        line_number = section_start + offset

        candidates: Set[Path] = set()
        row_broken: List[Tuple[str, Path]] = []
        for _label, href, _position in find_markdown_links(line):
            target, reason = href_target(href, root, root)
            if reason is not None:
                continue
            if target is None:
                continue
            if not target.exists():
                row_broken.append((href, target))
                continue
            paper = paper_dir_for(target)
            if paper is not None:
                candidates.add(paper)

        for href, target in row_broken:
            report.fail(
                "readme.link_broken",
                "README 论文总览 row {} ({}), line {}: broken link {!r} -> {}".format(
                    number, name, line_number, href, rel(root, target)
                ),
                href=href,
                target=rel(root, target),
                line=line_number,
            )
            broken_links.append(
                {
                    "row": str(number),
                    "name": name,
                    "href": href,
                    "target": rel(root, target),
                    "line": str(line_number),
                }
            )

        paper_dir: Optional[Path] = None
        if len(candidates) > 1:
            row_link_failures = True
            report.fail(
                "readme.row_multiple_papers",
                "README 论文总览 row {} ({}), line {}: links to multiple paper "
                "directories: {}".format(
                    number,
                    name,
                    line_number,
                    ", ".join(sorted(rel(root, p) for p in candidates)),
                ),
                line=line_number,
            )
            paper_dir = sorted(candidates, key=str)[0]
        elif len(candidates) == 1:
            paper_dir = next(iter(candidates))
        else:
            row_link_failures = True
            report.fail(
                "readme.row_no_paper_link",
                "README 论文总览 row {} ({}), line {}: no link resolves to a paper "
                "directory".format(number, name, line_number),
                line=line_number,
            )

        rows.append(
            ReadmeRow(
                number=number,
                name=name,
                paper_dir=paper_dir,
                line=line_number,
            )
        )

    if not rows:
        report.fail(
            "readme.no_rows",
            "README 论文总览 has no numbered table rows",
        )

    result["rows"] = [
        {
            "number": row.number,
            "name": row.name,
            "paper_dir": rel(root, row.paper_dir),
            "line": row.line,
        }
        for row in rows
    ]
    result["broken_links"] = broken_links
    result["all_rows_linked"] = bool(rows) and not row_link_failures

    # Row numbers must be exactly 1..N in order.
    expected = list(range(1, len(rows) + 1))
    actual = [row.number for row in rows]
    row_numbers_ok = actual == expected
    result["row_numbers_ok"] = row_numbers_ok
    if not row_numbers_ok:
        counts = Counter(actual)
        duplicates = {
            number: [row.number for row in rows if row.number == number]
            for number, count in counts.items()
            if count > 1
        }
        missing = sorted(set(expected) - set(actual))
        pieces: List[str] = []
        if duplicates:
            pieces.append(
                "duplicate "
                + "; ".join(
                    "{} -> rows {}".format(
                        number,
                        ", ".join(
                            str(row.line)
                            for row in rows
                            if row.number == number
                        ),
                    )
                    for number in sorted(duplicates)
                )
            )
        if missing:
            pieces.append(
                "missing "
                + ", ".join("{} ({})".format(n, circled(n)) for n in missing)
            )
        position_pieces = [
            "position {} has row {}, expected {}".format(position, row.number, position)
            for position, row in enumerate(rows, 1)
            if row.number != position
        ]
        if position_pieces:
            pieces.append("; ".join(position_pieces[:8]))
        report.fail(
            "readme.row_numbers",
            "README 论文总览 row numbers are not 1..N: " + "; ".join(pieces),
            rows=actual,
        )

    # Duplicate paper rows.
    by_paper: Dict[Path, List[ReadmeRow]] = {}
    for row in rows:
        if row.paper_dir is not None:
            by_paper.setdefault(row.paper_dir, []).append(row)
    for paper, linked_rows in by_paper.items():
        if len(linked_rows) > 1:
            report.fail(
                "readme.duplicate_paper",
                "README 论文总览 has {} rows linking to the same paper {}: {}".format(
                    len(linked_rows),
                    rel(root, paper),
                    ", ".join(str(row.number) for row in linked_rows),
                ),
                paper=rel(root, paper),
            )

    readme_set = set(by_paper.keys())
    card_set = set(card_papers)

    # Cross-check: the number printed in a README row must be the SAME number the
    # portal gives that paper. Row-number continuity plus set alignment cannot
    # catch this: a table can be numbered 1..N with the right papers, yet assign
    # the numbers to the wrong rows. That drift shipped for real once (README had
    # LongHarness=13 / MMLongEmbed=14 while the portal had MMLongEmbed ⑬ /
    # LongHarness ⑭), so it is checked explicitly.
    card_number_by_paper = {
        card.paper_dir: card.number
        for card in cards
        if card.paper_dir is not None and card.number is not None
    }
    mismatches: List[Tuple[ReadmeRow, int]] = []
    for row in rows:
        if row.paper_dir is None:
            continue
        card_number = card_number_by_paper.get(row.paper_dir)
        if card_number is not None and card_number != row.number:
            mismatches.append((row, card_number))
    result["number_mismatch"] = [
        {
            "row": row.number,
            "portal": card_number,
            "paper": rel(root, row.paper_dir),
            "line": row.line,
        }
        for row, card_number in mismatches
    ]
    if mismatches:
        pieces = [
            "row {} ({}) should be {} to match the portal card for {}".format(
                row.number,
                row.name,
                circled(card_number),
                rel(root, row.paper_dir),
            )
            for row, card_number in mismatches[:8]
        ]
        report.fail(
            "readme.number_mismatch",
            "README 论文总览 row numbers disagree with the portal card numbers: "
            + "; ".join(pieces),
            mismatches=result["number_mismatch"],
        )

    extra = sorted(readme_set - card_set, key=str)
    missing = sorted(card_set - readme_set, key=str)
    result["extra_papers"] = [rel(root, p) for p in extra]
    result["missing_papers"] = [rel(root, p) for p in missing]

    for paper in extra:
        linked = by_paper.get(paper, [])
        report.fail(
            "readme.extra_paper",
            "README 论文总览 lists paper {} (row {}) but it is not in the portal "
            "cards".format(
                rel(root, paper),
                ", ".join(str(row.number) for row in linked) or "?",
            ),
            paper=rel(root, paper),
        )
    if missing:
        report.warn(
            "readme.missing_paper",
            "README 论文总览 is missing {} portal paper(s): {}".format(
                len(missing), ", ".join(rel(root, p) for p in missing)
            ),
            papers=[rel(root, p) for p in missing],
        )

    if (
        rows
        and row_numbers_ok
        and result["all_rows_linked"]
        and not extra
        and not missing
        and not broken_links
        and not mismatches
    ):
        report.ok_line(
            "README 论文总览: {} rows, aligned with {} portal cards".format(
                len(rows), len(cards)
            )
        )
    return result


# ---------------------------------------------------------------------------
# C: stats declarations
# ---------------------------------------------------------------------------

_B = r"<(?:b|strong)\b[^>]*>"
_E = r"</(?:b|strong)\s*>"

_STAT_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    (
        "papers",
        re.compile(r"论文\s*" + _B + r"\s*(\d+)\s*" + _E + r"\s*篇", re.I),
    ),
    (
        "papers",
        re.compile(_B + r"\s*(\d+)\s*" + _E + r"\s*papers?\b", re.I),
    ),
    (
        "figures",
        re.compile(
            r"图表\s*"
            + _B
            + r"\s*(\d+)\s*"
            + _E
            + r"\s*(?:张|幅)?图\s*\+\s*"
            + _B
            + r"\s*(\d+)\s*"
            + _E
            + r"\s*(?:张|幅)?表",
            re.I,
        ),
    ),
    (
        "figures",
        re.compile(
            _B
            + r"\s*(\d+)\s*"
            + _E
            + r"\s*(?:figures?|figs?)\s*\+\s*"
            + _B
            + r"\s*(\d+)\s*"
            + _E
            + r"\s*tables?",
            re.I,
        ),
    ),
]


@dataclass
class StatDeclaration:
    source: Path
    line: int
    kind: str
    papers: Optional[int] = None
    figures: Optional[int] = None
    tables: Optional[int] = None


def parse_stats(root: Path, report: Report) -> List[Dict[str, Any]]:
    declarations: List[StatDeclaration] = []
    for name in ("index.html", "README.md"):
        path = root / name
        if not path.is_file():
            continue
        text = blank_html_noise(read_text(path))
        text = text.replace("&nbsp;", " ")
        for kind, pattern in _STAT_PATTERNS:
            for match in pattern.finditer(text):
                line = line_of(text, match.start())
                if kind == "papers":
                    declarations.append(
                        StatDeclaration(
                            source=path,
                            line=line,
                            kind=kind,
                            papers=int(match.group(1)),
                        )
                    )
                else:
                    declarations.append(
                        StatDeclaration(
                            source=path,
                            line=line,
                            kind=kind,
                            figures=int(match.group(1)),
                            tables=int(match.group(2)),
                        )
                    )

    result: List[Dict[str, Any]] = []
    if not declarations:
        report.warn(
            "stats.none",
            "no collection stats declaration found in index.html/README.md "
            "(expected e.g. 论文 <b>N</b> 篇 / 图表 <b>X</b> 图 + <b>Y</b> 表 or "
            "<b>N</b> papers / <b>X</b> figures + <b>Y</b> tables)",
        )
        return result

    declarations.sort(key=lambda d: (str(d.source), d.line))
    groups: List[List[StatDeclaration]] = []
    for declaration in declarations:
        if (
            groups
            and groups[-1][0].source == declaration.source
            and declaration.line - groups[-1][-1].line <= 3
        ):
            groups[-1].append(declaration)
        else:
            groups.append([declaration])

    for group in groups:
        papers_values = {d.papers for d in group if d.papers is not None}
        figure_values = {d.figures for d in group if d.figures is not None}
        table_values = {d.tables for d in group if d.tables is not None}
        start = min(d.line for d in group)
        end = max(d.line for d in group)
        source = group[0].source
        location = "{}:{}{}".format(
            rel(root, source), start, "" if end == start else "-{}".format(end)
        )

        if len(papers_values) > 1:
            report.fail(
                "stats.disagree",
                "stats declarations disagree at {}: paper counts {}".format(
                    location, ", ".join(str(v) for v in sorted(papers_values))
                ),
            )
        if len(figure_values) > 1:
            report.fail(
                "stats.disagree",
                "stats declarations disagree at {}: figure counts {}".format(
                    location, ", ".join(str(v) for v in sorted(figure_values))
                ),
            )
        if len(table_values) > 1:
            report.fail(
                "stats.disagree",
                "stats declarations disagree at {}: table counts {}".format(
                    location, ", ".join(str(v) for v in sorted(table_values))
                ),
            )

        papers = sorted(papers_values)[0] if papers_values else None
        figures = sorted(figure_values)[0] if figure_values else None
        tables = sorted(table_values)[0] if table_values else None
        result.append(
            {
                "source": rel(root, source),
                "start_line": start,
                "end_line": end,
                "papers": papers,
                "figures": figures,
                "tables": tables,
            }
        )
    return result


def check_stats(
    root: Path,
    cards: Sequence[Card],
    card_papers: Sequence[Path],
    report: Report,
) -> Dict[str, Any]:
    actual_papers = len(cards)
    actual_figures = sum(count_assets(paper)[0] for paper in card_papers)
    actual_tables = sum(count_assets(paper)[1] for paper in card_papers)
    declarations = parse_stats(root, report)

    actual = {
        "papers": actual_papers,
        "figures": actual_figures,
        "tables": actual_tables,
    }
    mismatch_count = 0
    for declaration in declarations:
        papers = declaration["papers"]
        figures = declaration["figures"]
        tables = declaration["tables"]
        declared_parts: List[str] = []
        actual_parts: List[str] = []
        mismatched: List[str] = []
        if papers is not None:
            declared_parts.append("{} papers".format(papers))
            actual_parts.append("{}".format(actual_papers))
            if papers != actual_papers:
                mismatched.append("papers")
        if figures is not None:
            declared_parts.append("{} figures".format(figures))
            actual_parts.append("{}".format(actual_figures))
            if figures != actual_figures:
                mismatched.append("figures")
        if tables is not None:
            declared_parts.append("{} tables".format(tables))
            actual_parts.append("{}".format(actual_tables))
            if tables != actual_tables:
                mismatched.append("tables")
        if not mismatched:
            continue
        mismatch_count += 1
        location = "{}:{}".format(
            declaration["source"],
            declaration["start_line"]
            if declaration["start_line"] == declaration["end_line"]
            else "{}-{}".format(declaration["start_line"], declaration["end_line"]),
        )
        report.fail(
            "stats.mismatch",
            "stats mismatch: declared {} ({}), actual {}".format(
                " / ".join(declared_parts),
                location,
                " / ".join(actual_parts),
            ),
            declared={
                "papers": papers,
                "figures": figures,
                "tables": tables,
            },
            actual=actual,
            location=location,
        )

    if declarations and mismatch_count == 0:
        report.ok_line(
            "stats: {} papers / {} figures / {} tables".format(
                actual_papers, actual_figures, actual_tables
            )
        )
    return {
        "actual": actual,
        "declarations": declarations,
        "mismatch_count": mismatch_count,
    }


# ---------------------------------------------------------------------------
# D: category README tables
# ---------------------------------------------------------------------------


def check_category_readmes(
    root: Path, card_papers: Sequence[Path], report: Report
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    card_set = set(card_papers)
    checked_links = 0
    categories = 0

    try:
        children = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        report.warn("category.read_error", "cannot list collection root: {}".format(exc))
        return results

    ignored = {"node_modules", "__pycache__", "vendor"}
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in ignored:
            continue
        if child.resolve() in card_set:
            continue
        readme = child / "README.md"
        if not readme.is_file():
            continue
        categories += 1
        category_result: Dict[str, Any] = {
            "file": rel(root, readme),
            "links_checked": 0,
            "broken": [],
        }
        text = blank_html_noise(read_text(readme))
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip().startswith("|"):
                continue
            for _label, href, _position in find_markdown_links(line):
                target, reason = href_target(href, child, root)
                if reason is not None or target is None:
                    continue
                checked_links += 1
                category_result["links_checked"] += 1
                if not target.exists():
                    report.fail(
                        "category.link_broken",
                        "category README {}:{}: broken link {!r} -> {}".format(
                            rel(root, readme),
                            line_number,
                            href,
                            rel(root, target),
                        ),
                        file=rel(root, readme),
                        line=line_number,
                        href=href,
                        target=rel(root, target),
                    )
                    category_result["broken"].append(
                        {"line": line_number, "href": href, "target": rel(root, target)}
                    )
        results.append(category_result)

    if categories and not any(
        finding.code == "category.link_broken" for finding in report.errors
    ):
        report.ok_line(
            "category READMEs: {} file(s), {} table link(s) checked".format(
                categories, checked_links
            )
        )
    return results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def check_collection(root: Path, strict_order: bool = True) -> Dict[str, Any]:
    report = Report()

    cards = parse_cards(root, report)
    check_card_numbers(cards, report, strict_order=strict_order)

    card_papers = referenced_papers(root, cards, report)
    discovered, orphans, _dangling = check_paper_set(
        root, cards, card_papers, report
    )
    check_paper_completeness(root, cards, report)
    readme_result = check_readme_table(root, cards, card_papers, report)
    stats_result = check_stats(root, cards, card_papers, report)
    category_result = check_category_readmes(root, card_papers, report)

    dangling_cards = [card for card in cards if card.paper_dir is None]
    if (
        not orphans
        and not dangling_cards
        and readme_result.get("row_numbers_ok")
        and readme_result.get("all_rows_linked")
        and not readme_result.get("extra_papers")
        and not readme_result.get("missing_papers")
    ):
        report.ok_line(
            "{} cards, {} papers discovered, README rows aligned".format(
                len(cards), len(discovered)
            )
        )
    else:
        report.info_line(
            "{} cards, {} papers discovered, {} orphan(s), {} dangling card(s)".format(
                len(cards), len(discovered), len(orphans), len(dangling_cards)
            )
        )

    passed = not report.errors
    payload: Dict[str, Any] = {
        "root": str(root),
        "pass": passed,
        "exit_code": 0 if passed else 1,
        "strict_order": strict_order,
        "summary": {
            "cards": len(cards),
            "papers_referenced": len(card_papers),
            "papers_discovered": len(discovered),
            "orphans": len(orphans),
            "dangling_cards": len(dangling_cards),
            "readme_rows": len(readme_result.get("rows", [])),
            "figures": stats_result["actual"]["figures"],
            "tables": stats_result["actual"]["tables"],
            "errors": len(report.errors),
            "warnings": len(report.warnings),
        },
        "cards": [card.as_dict(root) for card in cards],
        "papers_discovered": [rel(root, paper) for paper in discovered],
        "orphans": [rel(root, paper) for paper in orphans],
        "dangling_cards": [card.as_dict(root) for card in dangling_cards],
        "readme": readme_result,
        "stats": stats_result,
        "category_readmes": category_result,
        "errors": [finding.as_dict() for finding in report.errors],
        "warnings": [finding.as_dict() for finding in report.warnings],
        "ok": report.ok,
        "info": report.info,
    }
    return payload


def render_text(payload: Dict[str, Any]) -> None:
    print("=== collection: {} ===".format(payload["root"]))
    for finding in payload["errors"]:
        print("[FAIL] {}".format(finding["message"]))
    for finding in payload["warnings"]:
        print("[WARN] {}".format(finding["message"]))
    for message in payload["info"]:
        print("[INFO] {}".format(message))
    for message in payload["ok"]:
        print("[ OK ] {}".format(message))
    print("PASS" if payload["pass"] else "FAIL")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_collection.py",
        description=(
            "Read-only consistency checker for a Paper-Reading-Collection "
            "repository."
        ),
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="collection repository root (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON object instead of the text report",
    )
    parser.add_argument(
        "--lenient-order",
        action="store_true",
        help=(
            "downgrade a pure permutation of card numbers to a warning "
            "(duplicates and gaps are always errors)"
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_root = Path(args.root).expanduser()
    display_root = Path(os.path.abspath(str(raw_root)))

    if not raw_root.exists() or not raw_root.is_dir():
        message = "collection root is not a directory: {}".format(display_root)
        if args.json:
            print(
                json.dumps(
                    {
                        "root": str(display_root),
                        "pass": False,
                        "exit_code": 1,
                        "errors": [
                            {
                                "level": "FAIL",
                                "code": "root.not_directory",
                                "message": message,
                                "detail": {},
                            }
                        ],
                        "warnings": [],
                        "ok": [],
                        "info": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("=== collection: {} ===".format(display_root))
            print("[FAIL] {}".format(message))
            print("FAIL")
        return 1

    root = raw_root.resolve()
    try:
        strict_order = not args.lenient_order
        payload = check_collection(root, strict_order=strict_order)
    except Exception as exc:  # defensive: never dump a traceback at CI
        message = "internal error while checking {}: {}: {}".format(
            display_root, type(exc).__name__, exc
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "root": str(display_root),
                        "pass": False,
                        "exit_code": 1,
                        "errors": [
                            {
                                "level": "FAIL",
                                "code": "internal.error",
                                "message": message,
                                "detail": {},
                            }
                        ],
                        "warnings": [],
                        "ok": [],
                        "info": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("=== collection: {} ===".format(display_root))
            print("[FAIL] {}".format(message))
            print("FAIL")
        return 1

    payload["root"] = str(display_root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_text(payload)
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
