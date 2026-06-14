"""Generate a synthetic receipt image so OCR/extraction can be tested offline.

Uses AppKit to draw black text on white — close enough to a printed receipt for
a Vision OCR smoke test without needing a real photo.
"""
from __future__ import annotations

from pathlib import Path

SAMPLE_RECEIPT_LINES = [
    "TRADER JOE'S #455",
    "1245 MARKET ST",
    "06/14/2026  17:32",
    "",
    "BANANAS              1.29",
    "WHOLE MILK 1GAL      3.49",
    "LARGE EGGS 12CT      4.19",
    "OLIVE OIL 500ML      8.99",
    "SOURDOUGH BREAD      4.50",
    "",
    "SUBTOTAL            22.46",
    "TAX                  0.00",
    "TOTAL               22.46",
    "VISA ************1234",
]


def render_receipt(path: Path, lines: list[str] | None = None) -> Path:
    """Render `lines` as a receipt image at `path` (PNG). Returns the path."""
    from AppKit import (
        NSBitmapImageRep,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSGraphicsContext,
        NSString,
    )
    from Foundation import NSMakeRect, NSMakePoint

    lines = lines or SAMPLE_RECEIPT_LINES
    width, line_h, pad = 360, 26, 20
    height = pad * 2 + line_h * len(lines)

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    NSColor.whiteColor().setFill()
    from AppKit import NSRectFill

    NSRectFill(NSMakeRect(0, 0, width, height))

    font = NSFont.fontWithName_size_("Menlo", 18) or NSFont.systemFontOfSize_(18)
    attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.blackColor()}
    for i, line in enumerate(lines):
        y = height - pad - line_h * (i + 1)
        NSString.stringWithString_(line).drawAtPoint_withAttributes_(
            NSMakePoint(pad, y), attrs
        )

    NSGraphicsContext.restoreGraphicsState()

    from AppKit import NSPNGFileType

    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    path = Path(path)
    png.writeToFile_atomically_(str(path), True)
    return path


if __name__ == "__main__":
    out = render_receipt(Path("/tmp/sample_receipt.png"))
    print(f"wrote {out}")
