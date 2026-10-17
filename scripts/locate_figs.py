#!/usr/bin/env python3
"""Locate figures, tables and algorithms in a PDF and emit crops.json.

Usage
-----
    locate_figs.py paper.pdf [crops.json]
    locate_figs.py paper.pdf crops.json --no-caption --margin 45 --gap 14

The JSON format consumed by ``extract_figs.py`` is::

    {"fig1": {"page": 0, "rect": [x0, y0, x1, y1]}, ...}

``page`` is a 0-based page index and ``rect`` is in PDF points.  Keys use the
real caption numbers (``fig1``, ``table2``, ``algo1``).  With no output path
the script only prints a report.

How it works
------------
1. Captions are anchored on text *blocks* whose text starts with
   ``Figure|Table|Algorithm <n>:`` -- not on every word "Figure" in the body.
2. The page is split into columns from the x gaps between text lines.  A
   caption that is wider than 65% of the text block gets the full page width.
3. A 150-DPI ink map of the caption's column is scanned outwards from the
   caption.  The contiguous run of ink rows (bridging ordinary inter-line
   whitespace) is the figure/table body.  This works for raster, vector and
   ruled-table content alike.
4. The caption is included in the crop by default; ``--no-caption`` crops only
   the body.  Rects get 3 pt of padding and are clamped to the text area.

Diagnostics (``cap-outside``, ``edge-ink``, ``no-body``, ``wide-span``) are
printed for every crop but never change the exit status.
"""

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - only hit on a broken install
    sys.stderr.write(
        "error: PyMuPDF is required (pip install PyMuPDF); import fitz failed\n"
    )
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

CAPTION_RE = re.compile(r"^\s*(Figure|Table|Algorithm)\s+(\d+)\s*[:.]", re.IGNORECASE)

DEFAULT_MARGIN = 45.0   # pt removed from every page edge (header/footer guard)
DEFAULT_GAP = 14.0      # pt; a blank run longer than this ends a body band
PADDING = 3.0           # pt of whitespace around the final crop
INK_DPI = 150           # rasterisation DPI for the row/column ink profile
INK_CUTOFF = 245        # grayscale value below which a pixel counts as ink
EDGE_TOLERANCE = 1.0    # pt strip used by the edge-ink check
PROSE_WIDTH = 0.68      # line wider than this fraction of the band = prose
PROSE_STOP = 0.72       # same test used to stop a table running into prose
MIN_PROSE_STOP_HEIGHT = 20.0  # don't apply the prose stop to a table header

CAPTION_KIND = {"figure": "fig", "table": "table", "algorithm": "algo"}

# bytes.translate map: ink pixels become NUL, paper-white stays 0xff.
_INK_TABLE = bytes(255 if value >= INK_CUTOFF else 0 for value in range(256))


# ---------------------------------------------------------------------------
# Small data holders
# ---------------------------------------------------------------------------

@dataclass
class Caption:
    """A real caption block (not a in-text reference)."""

    kind: str
    number: int
    rect: "fitz.Rect"
    text: str

    @property
    def key_prefix(self) -> str:
        return CAPTION_KIND[self.kind]


@dataclass
class SideInfo:
    """What lies immediately above/below a caption on one side."""

    found: bool = False
    first: Optional[float] = None
    prose: bool = False
    strength: int = 0


@dataclass
class Crop:
    """One output entry plus its diagnostics."""

    key: str
    page_index: int
    caption: Caption
    rect: "fitz.Rect"
    flags: List[str]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _to_display(rect: "fitz.Rect", page: "fitz.Page") -> "fitz.Rect":
    """Map a content rectangle into the page's displayed coordinate system.

    PyMuPDF returns text/drawing/image coordinates in the *unrotated* page
    space while ``get_pixmap(clip=...)`` expects display coordinates.  For
    rotated pages the two differ by ``page.rotation_matrix``.
    """
    rect = fitz.Rect(rect)
    if page.rotation and hasattr(page, "rotation_matrix"):
        return rect * page.rotation_matrix
    return rect


def _body_rect(page: "fitz.Page", margin: float) -> "fitz.Rect":
    """Page rectangle shrunk by ``margin`` on all sides."""
    page_rect = page.rect
    mx = min(max(margin, 0.0), page_rect.width * 0.4)
    my = min(max(margin, 0.0), page_rect.height * 0.4)
    return fitz.Rect(
        page_rect.x0 + mx,
        page_rect.y0 + my,
        page_rect.x1 - mx,
        page_rect.y1 - my,
    )


def _clamp(rect: "fitz.Rect", bounds: "fitz.Rect") -> "fitz.Rect":
    """Clamp ``rect`` inside ``bounds``."""
    return fitz.Rect(
        max(rect.x0, bounds.x0),
        max(rect.y0, bounds.y0),
        min(rect.x1, bounds.x1),
        min(rect.y1, bounds.y1),
    )


def _round_rect(rect: "fitz.Rect") -> "fitz.Rect":
    """Round a rectangle to 0.1 pt."""
    return fitz.Rect(
        round(rect.x0, 1),
        round(rect.y0, 1),
        round(rect.x1, 1),
        round(rect.y1, 1),
    )


def _union(a: "fitz.Rect", b: "fitz.Rect") -> "fitz.Rect":
    """Bounding box of two rectangles."""
    return fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0),
                     max(a.x1, b.x1), max(a.y1, b.y1))


def _contains(outer: "fitz.Rect", inner: "fitz.Rect", tol: float = 0.5) -> bool:
    """True when ``inner`` is inside ``outer`` up to ``tol`` points."""
    return (inner.x0 >= outer.x0 - tol and inner.y0 >= outer.y0 - tol
            and inner.x1 <= outer.x1 + tol and inner.y1 <= outer.y1 + tol)


# ---------------------------------------------------------------------------
# Ink map
# ---------------------------------------------------------------------------

class InkMap:
    """A grayscale raster of the text area with fast row/extent queries."""

    def __init__(self, page: "fitz.Page", clip: "fitz.Rect"):
        pix = page.get_pixmap(dpi=INK_DPI, clip=clip,
                              colorspace=fitz.csGRAY, alpha=False)
        self.data: bytes = pix.samples
        self.stride: int = pix.stride
        self.width: int = pix.width
        self.height: int = pix.height
        self.origin_x: float = clip.x0
        self.origin_y: float = clip.y0
        self.scale_x: float = clip.width / max(1, self.width)
        self.scale_y: float = clip.height / max(1, self.height)

    def _cols(self, x0: float, x1: float) -> Tuple[int, int]:
        """Convert point x-range to pixel columns."""
        c0 = max(0, min(self.width, int(round((x0 - self.origin_x) / self.scale_x))))
        c1 = max(0, min(self.width, int(round((x1 - self.origin_x) / self.scale_x))))
        return c0, c1

    def _rows(self, y0: float, y1: float) -> Tuple[int, int]:
        """Convert point y-range to pixel rows."""
        r0 = max(0, min(self.height, int(round((y0 - self.origin_y) / self.scale_y))))
        r1 = max(0, min(self.height, int(round((y1 - self.origin_y) / self.scale_y))))
        return r0, r1

    def row_counts(self, x0: float, x1: float) -> List[int]:
        """Number of ink pixels per raster row inside ``[x0, x1]``."""
        c0, c1 = self._cols(x0, x1)
        if c1 <= c0:
            return [0] * self.height
        counts: List[int] = []
        for row in range(self.height):
            offset = row * self.stride + c0
            chunk = self.data[offset:offset + (c1 - c0)]
            masked = chunk.translate(_INK_TABLE)
            counts.append(len(masked) - masked.count(255))
        return counts

    def row_extent(self, row: int, c0: int, c1: int) -> Optional[Tuple[int, int]]:
        """First and last ink pixel columns in one row, or ``None``."""
        offset = row * self.stride + c0
        masked = self.data[offset:offset + (c1 - c0)].translate(_INK_TABLE)
        stripped = masked.lstrip(b"\xff")
        if not stripped:
            return None
        lead = len(masked) - len(stripped)
        trail = len(masked) - len(masked.rstrip(b"\xff"))
        return c0 + lead, c1 - trail

    def x_extent(self, y0: float, y1: float, x0: float, x1: float
                 ) -> Optional[Tuple[float, float]]:
        """Horizontal ink extent inside a rectangle, in points."""
        c0, c1 = self._cols(x0, x1)
        r0, r1 = self._rows(y0, y1)
        lo: Optional[int] = None
        hi: Optional[int] = None
        for row in range(r0, r1):
            extent = self.row_extent(row, c0, c1)
            if extent is None:
                continue
            lo = extent[0] if lo is None else min(lo, extent[0])
            hi = extent[1] if hi is None else max(hi, extent[1])
        if lo is None or hi is None:
            return None
        return (self.origin_x + lo * self.scale_x,
                self.origin_x + hi * self.scale_x)

    def edge_ink(self, rect: "fitz.Rect", margin: float = EDGE_TOLERANCE) -> bool:
        """True when ink touches any of the four edges of ``rect``."""
        top = self.x_extent(rect.y0, min(rect.y1, rect.y0 + margin),
                            rect.x0, rect.x1)
        if top is not None:
            return True
        bottom = self.x_extent(max(rect.y0, rect.y1 - margin), rect.y1,
                               rect.x0, rect.x1)
        if bottom is not None:
            return True

        c0, c1 = self._cols(rect.x0, rect.x1)
        r0, r1 = self._rows(rect.y0, rect.y1)
        for row in range(r0, r1):
            extent = self.row_extent(row, c0, c1)
            if extent is None:
                continue
            left = self.origin_x + extent[0] * self.scale_x
            right = self.origin_x + extent[1] * self.scale_x
            if left <= rect.x0 + margin or right >= rect.x1 - margin:
                return True
        return False


# ---------------------------------------------------------------------------
# PDF content extraction
# ---------------------------------------------------------------------------

def _text_lines(page: "fitz.Page", body: "fitz.Rect") -> List[Tuple["fitz.Rect", str]]:
    """Return (bbox, text) for every text line inside the body area."""
    lines: List[Tuple["fitz.Rect", str]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            rect = _to_display(fitz.Rect(line["bbox"]), page)
            text = "".join(span.get("text", "")
                           for span in line.get("spans", [])).strip()
            if not text or rect.width < 2 or rect.height < 2:
                continue
            if rect.y1 < body.y0 or rect.y0 > body.y1:
                continue
            lines.append((rect, text))
    return lines


def _caption_blocks(page: "fitz.Page", body: "fitz.Rect") -> List[Caption]:
    """Find true caption blocks (text starting with Figure/Table/Algorithm n:)."""
    captions: List[Caption] = []
    for block in page.get_text("blocks"):
        if len(block) < 7 or block[6] != 0:
            continue
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        match = CAPTION_RE.match(text)
        if not match:
            continue
        rect = _to_display(fitz.Rect(x0, y0, x1, y1), page)
        if rect.y1 <= body.y0 or rect.y0 >= body.y1:
            continue
        if rect.width < 10 or rect.height < 4:
            continue
        captions.append(Caption(
            kind=match.group(1).lower(),
            number=int(match.group(2)),
            rect=rect,
            text=" ".join(text.split()),
        ))
    captions.sort(key=lambda cap: (cap.rect.y0, cap.rect.x0))
    return captions


def _graphic_rects(page: "fitz.Page") -> List["fitz.Rect"]:
    """Bounding boxes of vector drawings and raster images on the page."""
    rects: List["fitz.Rect"] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for drawing in drawings:
        rect = fitz.Rect(drawing["rect"])
        if rect.width > 2 and rect.height > 2 and rect.width * rect.height > 1:
            rects.append(_to_display(rect, page))
    for image in page.get_images(full=True):
        try:
            image_rects = page.get_image_rects(image[0])
        except Exception:
            continue
        for rect in image_rects:
            rect = _to_display(fitz.Rect(rect), page)
            if rect.width > 2 and rect.height > 2:
                rects.append(rect)
    return rects


# ---------------------------------------------------------------------------
# Column model
# ---------------------------------------------------------------------------

def _column_band(caption: Caption, body: "fitz.Rect",
                 lines: Sequence[Tuple["fitz.Rect", str]],
                 gutter: Optional[Tuple[float, float]]
                 ) -> Tuple[str, "fitz.Rect"]:
    """Return ("left"|"right"|"full", column band) for a caption.

    A caption wider than 65% of the text area is always full width.  Otherwise
    a detected page gutter (or, failing that, the caption's position relative
    to the page centre) picks a side.  The exact band edge is taken from the
    nearest text line on the other side of the gutter; a detected gutter is
    used as a fallback.  If neither exists the caption is left full width
    rather than guessing a wrong crop.
    """
    full = ("full", fitz.Rect(body))
    if caption.rect.width > 0.65 * body.width:
        return full

    window0 = caption.rect.y0 - 70.0
    window1 = caption.rect.y1 + 70.0
    local = [(rect, text) for rect, text in lines
             if rect.y1 >= window0 and rect.y0 <= window1]
    center = body.x0 + 0.5 * body.width

    side: Optional[str] = None
    if gutter is not None:
        g0, g1 = gutter
        if caption.rect.x0 < g0 - 5.0 and caption.rect.x1 > g1 + 5.0:
            return full
        middle = 0.5 * (g0 + g1)
        if caption.rect.x1 <= middle:
            side = "left"
        elif caption.rect.x0 >= middle:
            side = "right"
    if side is None:
        if caption.rect.x0 >= center:
            side = "right"
        elif caption.rect.x1 <= center:
            side = "left"
        else:
            return full

    if side == "left":
        right = [rect for rect, _ in local if rect.x0 >= caption.rect.x1]
        if right:
            x1 = min(rect.x0 for rect in right) - 1.0
            if x1 > body.x0 + 0.25 * body.width:
                return "left", fitz.Rect(body.x0, body.y0, x1, body.y1)
        if gutter is not None and caption.rect.x1 <= gutter[0]:
            return "left", fitz.Rect(body.x0, body.y0, gutter[0] - 1.0, body.y1)
        return full

    left = [rect for rect, _ in local if rect.x1 <= caption.rect.x0]
    if left:
        x0 = max(rect.x1 for rect in left) + 1.0
        if x0 < body.x1 - 0.25 * body.width:
            return "right", fitz.Rect(x0, body.y0, body.x1, body.y1)
    if gutter is not None and caption.rect.x0 >= gutter[1]:
        return "right", fitz.Rect(gutter[1] + 1.0, body.y0, body.x1, body.y1)
    return full


def _page_gutter(lines: Sequence[Tuple["fitz.Rect", str]],
                 body: "fitz.Rect") -> Optional[Tuple[float, float]]:
    """Detect a two-column gutter, returning its (start, end) x range.

    The check looks for a >=6 pt vertical whitespace band in the central
    third of the text area that is crossed by very few text lines and has
    long lines on both sides.  This is conservative: single-column pages with
    figures/tables in the middle are normally rejected.
    """
    if len(lines) < 10:
        return None
    width = body.width
    lo = body.x0 + 0.35 * width
    hi = body.x0 + 0.65 * width
    step = 0.5
    positions = []
    x = lo
    while x <= hi:
        positions.append(x)
        x += step
    crossings = [
        sum(1 for rect, _ in lines if rect.x0 < pos < rect.x1)
        for pos in positions
    ]
    minimum = min(crossings)
    runs: List[Tuple[float, float]] = []
    start: Optional[float] = None
    for pos, crossing in zip(positions, crossings):
        if crossing <= minimum + 1:
            start = pos if start is None else start
            end = pos
        elif start is not None:
            runs.append((start, end))
            start = None
    if start is not None:
        runs.append((start, end))
    runs = [(a, b) for a, b in runs if b - a >= 6.0]
    if not runs:
        return None
    a, b = max(runs, key=lambda run: run[1] - run[0])

    long_line = max(60.0, 0.2 * width)
    left = [rect for rect, _ in lines
            if rect.x1 <= a + 1.0 and rect.width > long_line]
    right = [rect for rect, _ in lines
             if rect.x0 >= b - 1.0 and rect.width > long_line]
    if len(left) < 2 or len(right) < 2:
        return None
    return a, b


# ---------------------------------------------------------------------------
# Body discovery
# ---------------------------------------------------------------------------

def _row_y(ink: InkMap, row: int) -> Tuple[float, float]:
    """Top and bottom y of a raster row in points."""
    return (ink.origin_y + row * ink.scale_y,
            ink.origin_y + (row + 1) * ink.scale_y)


def _scan_rows(ink: InkMap, direction: str, edge: float, limit: float,
               guard: float = 1.2):
    """Yield (row, y0, y1) from a caption edge outwards to ``limit``."""
    if direction == "up":
        limit = min(limit, edge)
    else:
        limit = max(limit, edge)
    if direction == "up":
        row = min(ink.height - 1,
                  int(math.floor((edge - guard - ink.origin_y) / ink.scale_y)))
        stop = max(0, int(math.ceil((limit - ink.origin_y) / ink.scale_y)))
        while row >= stop:
            y0, y1 = _row_y(ink, row)
            yield row, y0, y1
            row -= 1
    else:
        row = max(0, int(math.ceil((edge + guard - ink.origin_y) / ink.scale_y)))
        stop = min(ink.height - 1,
                   int(math.ceil((limit - ink.origin_y) / ink.scale_y)))
        while row <= stop:
            y0, y1 = _row_y(ink, row)
            yield row, y0, y1
            row += 1


def _first_ink(ink: InkMap, counts: Sequence[int], edge: float,
               direction: str, limit: float, max_gap: float
               ) -> Optional[Tuple[int, float, float]]:
    """First ink row within ``max_gap`` of the caption edge."""
    for row, y0, y1 in _scan_rows(ink, direction, edge, limit):
        if counts[row] < 1:
            continue
        distance = (edge - y1) if direction == "up" else (y0 - edge)
        if distance <= max_gap:
            return row, y0, y1
        return None
    return None


def _row_has_prose(y0: float, y1: float, band: "fitz.Rect",
                   lines: Sequence[Tuple["fitz.Rect", str]]) -> bool:
    """True when a wide paragraph line overlaps this raster row."""
    for rect, _ in lines:
        if rect.y1 < y0 - 1.0 or rect.y0 > y1 + 1.0:
            continue
        if rect.x1 <= band.x0 + 5.0 or rect.x0 >= band.x1 - 5.0:
            continue
        if (rect.width > PROSE_STOP * band.width
                and rect.x0 < band.x0 + 0.30 * band.width):
            return True
    return False


def _analyse_side(ink: InkMap, counts: Sequence[int], band: "fitz.Rect",
                  caption: Caption, direction: str, limit: float,
                  initial_gap: float,
                  lines: Sequence[Tuple["fitz.Rect", str]],
                  graphics: Sequence["fitz.Rect"]) -> SideInfo:
    """Look at the content immediately on one side of a caption."""
    first = _first_ink(ink, counts, caption.rect.y0 if direction == "up"
                       else caption.rect.y1, direction, limit, initial_gap)
    if first is None:
        return SideInfo(found=False)

    _, y0, y1 = first
    if direction == "up":
        probe_top = max(band.y0, y1 - 45.0)
        probe_bottom = min(caption.rect.y0 - 0.5, y1 + 2.0)
    else:
        probe_top = max(caption.rect.y1 + 0.5, y0 - 2.0)
        probe_bottom = min(band.y1, y0 + 45.0)
    probe = fitz.Rect(band.x0, probe_top, band.x1, probe_bottom)
    if probe.height <= 0:
        return SideInfo(found=True, first=y0)

    nearby = [rect for rect, _ in lines
              if rect.intersects(probe)
              and rect.x1 > band.x0 + 2 and rect.x0 < band.x1 - 2
              and not rect.intersects(caption.rect)]
    prose = any(rect.width > PROSE_WIDTH * band.width for rect in nearby)
    graphics_near = sum(
        1 for rect in graphics
        if rect.intersects(probe) and rect.width > 2 and rect.height > 2
    )
    return SideInfo(found=True, first=y0, prose=prose,
                    strength=len(nearby) + graphics_near)


def _aggregate_body(ink: InkMap, counts: Sequence[int], band: "fitz.Rect",
                    caption: Caption, direction: str, limit: float,
                    initial_gap: float, gap: float, kind: str,
                    lines: Sequence[Tuple["fitz.Rect", str]]
                    ) -> Optional["fitz.Rect"]:
    """Grow a contiguous ink band outwards from the caption."""
    edge = caption.rect.y0 if direction == "up" else caption.rect.y1
    top: Optional[float] = None
    bottom: Optional[float] = None
    last_ink: Optional[float] = None

    for row, y0, y1 in _scan_rows(ink, direction, edge, limit):
        if counts[row] < 1:
            if top is None or last_ink is None:
                continue
            blank = (last_ink - y1) if direction == "up" else (y0 - last_ink)
            if blank > gap:
                break
            continue

        if (kind == "table" and top is not None and last_ink is not None
                and bottom - top >= MIN_PROSE_STOP_HEIGHT
                and _row_has_prose(y0, y1, band, lines)):
            break

        if top is None:
            distance = (edge - y1) if direction == "up" else (y0 - edge)
            if distance > initial_gap:
                break
            top, bottom = y0, y1
            last_ink = y0 if direction == "up" else y1
            continue

        blank = (last_ink - y1) if direction == "up" else (y0 - last_ink)
        if blank > gap:
            break
        top = min(top, y0)
        bottom = max(bottom, y1)
        last_ink = y0 if direction == "up" else y1

    if top is None or bottom is None or bottom - top < 1.0:
        return None
    return fitz.Rect(band.x0, top, band.x1, bottom)


# ---------------------------------------------------------------------------
# Per-page processing
# ---------------------------------------------------------------------------

def _caption_limits(caption: Caption, captions: Sequence[Caption],
                    band: "fitz.Rect", body: "fitz.Rect"
                    ) -> Tuple[float, float]:
    """Vertical scan limits set by neighbouring captions in the same band."""
    up, down = body.y0, body.y1
    for other in captions:
        if other is caption:
            continue
        if other.rect.x1 <= band.x0 + 2 or other.rect.x0 >= band.x1 - 2:
            continue
        if other.rect.y1 <= caption.rect.y0:
            up = max(up, other.rect.y1 + 1.0)
        elif other.rect.y0 >= caption.rect.y1:
            down = min(down, other.rect.y0 - 1.0)
    return up, down


def _process_page(page: "fitz.Page", page_index: int, margin: float,
                  gap: float, include_caption: bool) -> List[Crop]:
    """Locate every caption on one page and build its crop."""
    body = _body_rect(page, margin)
    if body.width < 20 or body.height < 20:
        return []

    captions = _caption_blocks(page, body)
    if not captions:
        return []

    lines = _text_lines(page, body)
    graphics = _graphic_rects(page)
    ink = InkMap(page, body)
    gutter = _page_gutter(lines, body)
    initial_gap = max(18.0, 1.5 * gap)

    crops: List[Crop] = []
    for caption in captions:
        mode, band = _column_band(caption, body, lines, gutter)
        if band.width < 10 or band.height < 10:
            band = fitz.Rect(body)
            mode = "full"

        up_limit, down_limit = _caption_limits(caption, captions, band, body)
        counts = ink.row_counts(band.x0, band.x1)

        primary = "up" if caption.kind in ("figure", "algorithm") else "down"
        secondary = "down" if primary == "up" else "up"

        first_limit = up_limit if primary == "up" else down_limit
        primary_info = _analyse_side(ink, counts, band, caption, primary,
                                     first_limit, initial_gap, lines, graphics)
        second_limit = up_limit if secondary == "up" else down_limit
        secondary_info = _analyse_side(ink, counts, band, caption, secondary,
                                       second_limit, initial_gap, lines, graphics)

        if not primary_info.found:
            if secondary_info.found:
                side, info = secondary, secondary_info
            else:
                side, info = None, None
        elif (primary_info.prose and secondary_info.found
              and not secondary_info.prose and secondary_info.strength >= 2):
            # Caption on the "wrong" side of a conventional layout (e.g. a
            # table caption below the table, or a figure caption above it).
            side, info = secondary, secondary_info
        else:
            side, info = primary, primary_info

        flags: List[str] = []
        body_band: Optional["fitz.Rect"] = None
        if side is not None:
            limit = up_limit if side == "up" else down_limit
            body_band = _aggregate_body(
                ink, counts, band, caption, side, limit,
                initial_gap, gap, caption.kind, lines,
            )
            if body_band is not None:
                extent = ink.x_extent(body_band.y0, body_band.y1,
                                      band.x0, band.x1)
                if extent is not None:
                    body_band.x0, body_band.x1 = extent
                else:
                    body_band = None

        if body_band is None:
            flags.append("no-body")
            rect = fitz.Rect(caption.rect)
        else:
            rect = fitz.Rect(body_band)
            if include_caption:
                rect = _union(rect, caption.rect)

        rect = fitz.Rect(rect.x0 - PADDING, rect.y0 - PADDING,
                         rect.x1 + PADDING, rect.y1 + PADDING)
        rect = _clamp(rect, body)
        rect = _round_rect(rect)
        if rect.width < 1 or rect.height < 1:
            flags.append("no-body")
            rect = _round_rect(_clamp(fitz.Rect(caption.rect), body))

        if include_caption and not _contains(rect, caption.rect):
            flags.append("cap-outside")
        if ink.edge_ink(rect):
            flags.append("edge-ink")
        if (mode in ("left", "right") and gutter is not None
                and (gutter[0] - rect.x0) > 8.0
                and (rect.x1 - gutter[1]) > 8.0):
            flags.append("wide-span")

        key = f"{caption.key_prefix}{caption.number}"
        crops.append(Crop(key=key, page_index=page_index,
                          caption=caption, rect=rect, flags=flags))

    return crops


# ---------------------------------------------------------------------------
# Report and JSON
# ---------------------------------------------------------------------------

def _snippet(text: str, length: int = 50) -> str:
    """First ``length`` characters of a whitespace-collapsed caption."""
    text = " ".join(text.split())
    if len(text) <= length:
        return text
    return text[:length] + "…"


def _print_crop(crop: Crop) -> None:
    """Print one report line plus its warning markers."""
    rect = crop.rect
    print(
        f"{crop.key:<7} p.{crop.page_index + 1:<3} "
        f"rect=[{rect.x0:6.1f}, {rect.y0:6.1f}, {rect.x1:6.1f}, {rect.y1:6.1f}]  "
        f"{_snippet(crop.caption.text)}"
    )
    for flag in crop.flags:
        print(f"        [warn] {flag}")


def _unique_key(key: str, used: set) -> str:
    """Return a unique crop key, suffixing duplicates."""
    if key not in used:
        return key
    index = 2
    while f"{key}_{index}" in used:
        index += 1
    return f"{key}_{index}"


def _write_crops(path: str, crops: Sequence[Crop]) -> None:
    """Write crops.json in the format expected by extract_figs.py."""
    payload = {
        crop.key: {
            "page": crop.page_index,
            "rect": [crop.rect.x0, crop.rect.y0, crop.rect.x1, crop.rect.y1],
        }
        for crop in crops
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="locate_figs.py",
        description="Locate figures/tables in a PDF and write crops.json "
                    "for extract_figs.py.",
    )
    parser.add_argument("pdf", help="input PDF")
    parser.add_argument("output", nargs="?",
                        help="output crops.json (omit to only print a report)")
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help=f"page margin excluded from detection in points "
                             f"(default: {DEFAULT_MARGIN:g})")
    parser.add_argument("--gap", type=float, default=DEFAULT_GAP,
                        help=f"blank gap in points that ends a figure/table "
                             f"body (default: {DEFAULT_GAP:g})")
    parser.add_argument("--no-caption", action="store_true",
                        help="crop only the body, excluding the caption")
    args = parser.parse_args(argv)
    if args.margin < 0:
        parser.error("--margin must be >= 0")
    if args.gap < 2:
        parser.error("--gap must be >= 2")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    args = _parse_args(argv)
    try:
        doc = fitz.open(args.pdf)
    except Exception as exc:
        print(f"error: cannot open {args.pdf}: {exc}", file=sys.stderr)
        return 1
    if getattr(doc, "needs_pass", False):
        print(f"error: {args.pdf} is password-protected", file=sys.stderr)
        doc.close()
        return 1

    crops: List[Crop] = []
    used_keys: set = set()
    try:
        for page_index in range(len(doc)):
            try:
                page_crops = _process_page(doc[page_index], page_index,
                                           args.margin, args.gap,
                                           not args.no_caption)
            except Exception as exc:  # keep going on a malformed page
                print(f"[warn] page {page_index + 1}: {exc}", file=sys.stderr)
                continue
            for crop in page_crops:
                crop.key = _unique_key(crop.key, used_keys)
                used_keys.add(crop.key)
                crops.append(crop)
    finally:
        doc.close()

    if not crops:
        print(f"no figure/table/algorithm captions found in {args.pdf}")
        if args.output:
            try:
                _write_crops(args.output, [])
            except OSError as exc:
                print(f"error: cannot write {args.output}: {exc}",
                      file=sys.stderr)
                return 1
            print(f"wrote {args.output}: 0 crops (figs=0, tables=0)")
        return 0

    for crop in crops:
        _print_crop(crop)

    figures = sum(1 for crop in crops if crop.caption.kind == "figure")
    tables = sum(1 for crop in crops if crop.caption.kind == "table")
    algorithms = sum(1 for crop in crops if crop.caption.kind == "algorithm")

    if args.output:
        try:
            _write_crops(args.output, crops)
        except OSError as exc:
            print(f"error: cannot write {args.output}: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.output}: {len(crops)} crops "
              f"(figs={figures}, tables={tables})")
        if algorithms:
            print(f"  (algorithms={algorithms})")
    else:
        print(f"{len(crops)} crops detected (figs={figures}, tables={tables})"
              f"{f', algorithms={algorithms}' if algorithms else ''}; "
              f"no output file written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
