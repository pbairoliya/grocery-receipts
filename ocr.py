"""ocr.py — local receipt OCR via Apple's Vision framework (no cloud, no model download).

Vision's VNRecognizeTextRequest is the best on-device OCR on macOS and, unlike a
vision-LLM, it transcribes digits faithfully — which matters for prices. Images
(JPEG/PNG/HEIC) are fed straight to Vision; PDFs (from the iOS document scanner)
are rasterized page-by-page with Quartz first.
"""
from __future__ import annotations

import errno
import re
import subprocess
import time
from pathlib import Path

import Quartz
import Vision
from Foundation import NSData

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

# Render scanned PDF pages at 2x so small receipt print stays legible to OCR.
_PDF_RENDER_SCALE = 2.0


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


# Two observations whose vertical centers sit within this fraction of image
# height are treated as the same printed row (so an item and its price, which
# Vision returns as separate observations, get rejoined left-to-right).
_ROW_TOLERANCE = 0.012


def _recognize(handler) -> str:
    """Run accurate, language-corrected OCR and reconstruct printed rows.

    Vision returns each text run as its own observation with a normalized
    bounding box (origin bottom-left). Naively joining them column-orders a
    two-column receipt ("BANANAS\\nMILK\\n...\\n1.29\\n3.49"). We instead group
    observations by vertical position into rows, then sort each row by x, so
    "BANANAS   1.29" stays on one line — far easier to parse downstream.
    """
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")

    tokens: list[tuple[float, float, str]] = []  # (center_y, x, text)
    for obs in request.results() or []:
        candidate = obs.topCandidates_(1)
        if not candidate:
            continue
        box = obs.boundingBox()  # normalized, origin bottom-left
        center_y = box.origin.y + box.size.height / 2
        tokens.append((center_y, box.origin.x, candidate[0].string()))

    # Top-to-bottom: higher normalized y is higher on the page.
    tokens.sort(key=lambda t: -t[0])
    rows: list[list[tuple[float, float, str]]] = []
    for tok in tokens:
        if rows and abs(rows[-1][0][0] - tok[0]) <= _ROW_TOLERANCE:
            rows[-1].append(tok)
        else:
            rows.append([tok])

    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda t: t[1])  # left-to-right
        lines.append("   ".join(_merge_price_fragments([t[2] for t in row])))
    return "\n".join(lines)


def _merge_price_fragments(tokens: list[str]) -> list[str]:
    """Rejoin a dollar amount Vision split across two observations.

    Faded receipts often OCR "$3.99" as two runs "$3" and ".99". When a token is
    a bare integer (optionally $-prefixed) and the next is ".dd", glue them.
    """
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        cur = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if re.fullmatch(r"\$?\d+", cur) and re.fullmatch(r"\.\d{2}", nxt):
            merged.append(cur + nxt)
            i += 2
        else:
            merged.append(cur)
            i += 1
    return merged


def _materialize_icloud(path: Path, timeout: float = 60.0) -> None:
    """Force iCloud to download a dataless placeholder and wait for the bytes.

    Reading an undownloaded iCloud file raises OSError EDEADLK ("Resource
    deadlock avoided") rather than transparently materializing it, so we ask
    `brctl` to pull it down and poll until the on-disk size matches.
    """
    try:
        subprocess.run(
            ["brctl", "download", str(path)],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # brctl missing (non-iCloud path) or slow — fall through to polling.
        pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path, "rb") as f:
                f.read(1)
            return
        except OSError as e:
            if e.errno != errno.EDEADLK:
                raise
            time.sleep(0.5)
    raise TimeoutError(f"iCloud file never materialized within {timeout:.0f}s: {path}")


def _read_nsdata(path: Path) -> NSData:
    # Reading via Python first also sidesteps URL-encoding issues with names
    # that contain exotic spaces (iOS uses U+202F before AM/PM).
    try:
        raw = path.read_bytes()
    except OSError as e:
        if e.errno != errno.EDEADLK:
            raise
        # Dataless iCloud placeholder — download it, then retry.
        _materialize_icloud(path)
        raw = path.read_bytes()
    return NSData.dataWithBytes_length_(raw, len(raw))


def _ocr_image_file(path: Path) -> str:
    data = _read_nsdata(path)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    return _recognize(handler)


def _ocr_pdf(path: Path) -> str:
    data = _read_nsdata(path)
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    doc = Quartz.CGPDFDocumentCreateWithProvider(provider)
    if doc is None:
        raise RuntimeError(f"Could not open PDF: {path}")
    n_pages = Quartz.CGPDFDocumentGetNumberOfPages(doc)
    page_texts: list[str] = []
    for i in range(1, n_pages + 1):
        cg_image = _render_pdf_page(doc, i, _PDF_RENDER_SCALE)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        page_texts.append(_recognize(handler))
    return "\n".join(page_texts)


def _render_pdf_page(doc, page_number: int, scale: float):
    page = Quartz.CGPDFDocumentGetPage(doc, page_number)
    rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    width = int(rect.size.width * scale)
    height = int(rect.size.height * scale)
    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, width, height, 8, 0, color_space,
        Quartz.kCGImageAlphaPremultipliedLast,
    )
    # White background so scans with transparency don't OCR as black-on-black.
    Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))
    Quartz.CGContextScaleCTM(ctx, scale, scale)
    Quartz.CGContextDrawPDFPage(ctx, page)
    return Quartz.CGBitmapContextCreateImage(ctx)


def ocr_file(path: Path) -> str:
    """OCR a receipt image or PDF → raw text (one observation per line)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _ocr_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return _ocr_image_file(path)
    raise ValueError(f"Unsupported file type for OCR: {path.suffix} ({path})")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("usage: uv run python ocr.py <receipt.jpg|receipt.pdf>")
    print(ocr_file(Path(sys.argv[1])))
