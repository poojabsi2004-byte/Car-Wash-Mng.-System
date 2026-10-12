"""Drawn onto Car Wash PDFs after wkhtmltopdf:

- the page footer, at the bottom of every page. A wkhtmltopdf build without "patched qt" (e.g.
  Ubuntu's own package) can't print page footers: the pages are then rendered with an empty bottom
  margin and the footer is drawn into it, with the same content and look as the HTML footer
  (report/carwash_report_layout.xml);
- the signature lines (the report's ``table.o_cw_signatures``), at the bottom of the last page just
  above the footer instead of right after the content. The table is taken out of the HTML before
  printing and an empty space is left at the end of the content, so they never overlap it.
"""
import io
import logging

import lxml.html
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from odoo.tools.misc import file_path
from odoo.tools.pdf import PdfFileReader, PdfFileWriter

_logger = logging.getLogger(__name__)

BRAND = HexColor("#0e7490")
INK = HexColor("#0b1f33")
MUTED = HexColor("#5b7085")
SEPARATOR = HexColor("#b9ccd6")

SIDE = 3.4 * mm         # aligned with the left / right edge of the page content
SIGN_LABEL_Y = 3 * mm   # signatures, above the bottom of the page content: label baseline
SIGN_LINE_Y = 7.5 * mm  # ... and signature line (about 12 mm above it are left for signing)
LINE_Y = 16 * mm        # rule above the footer (the page's bottom margin is 20 mm)
FIRST_Y = 12.6 * mm     # baseline of the first footer line
LINE_GAP = 3.3 * mm

FONT_FILES = {
    "CarwashLato": ("web/static/fonts/lato/Lato-Reg-webfont.ttf", "Helvetica"),
    "CarwashLato-Bold": ("web/static/fonts/lato/Lato-Bol-webfont.ttf", "Helvetica-Bold"),
    "CarwashLato-Italic": ("web/static/fonts/lato/Lato-RegIta-webfont.ttf", "Helvetica-Oblique"),
    "CarwashIcons": ("web/static/src/libs/fontawesome/fonts/fontawesome-webfont.ttf", None),
}
ICONS = {"phone": "\uf095", "email": "\uf0e0", "website": "\uf0ac"}  # Font Awesome phone / envelope / globe
_fonts = {}


def _font(name):
    """The registered font to use for `name` (Lato / Font Awesome; built-in fallback if unavailable)."""
    if name not in _fonts:
        path, fallback = FONT_FILES[name]
        try:
            pdfmetrics.registerFont(TTFont(name, file_path(path)))
            _fonts[name] = name
        except Exception:  # missing or unreadable font file: never block printing
            _logger.info("Car Wash report footer: font %s unavailable, using %s", path, fallback)
            _fonts[name] = fallback
    return _fonts[name]


def _draw_footer(pdf, width, footer, page_label):
    left, right = SIDE, width - SIDE
    regular, bold, italic, icons = (
        _font("CarwashLato"), _font("CarwashLato-Bold"), _font("CarwashLato-Italic"), _font("CarwashIcons"),
    )
    pdf.setStrokeColor(BRAND)
    pdf.setLineWidth(1.5)
    pdf.line(left, LINE_Y, right, LINE_Y)

    # right: document reference, page number, printed time
    right_lines = [(footer["doc_ref"], bold, 7.5, INK), (page_label, regular, 7, MUTED), (footer["printed"], regular, 6.5, MUTED)]
    right_lines = [line for line in right_lines if line[0]]
    y = FIRST_Y
    for text, font, size, color in right_lines:
        pdf.setFont(font, size)
        pdf.setFillColor(color)
        pdf.drawRightString(right, y, text)
        y -= LINE_GAP
    right_width = max((pdfmetrics.stringWidth(t, f, s) for t, f, s, _c in right_lines), default=0)
    left_limit = right - right_width - 6 * mm

    # left: company name | phone | email | website, then the footer note
    pieces = [(footer["name"], bold, 8, BRAND)]
    for key in ("phone", "email", "website"):
        if footer.get(key):
            pieces.append(("   |   ", regular, 7, SEPARATOR))
            if icons:
                pieces.append((ICONS[key] + " ", icons, 6.5, BRAND))
            pieces.append((footer[key], regular, 7, MUTED))
    total = sum(pdfmetrics.stringWidth(t, f, s) for t, f, s, _c in pieces)
    scale = min(1.0, (left_limit - left) / total) if total else 1.0
    x = left
    for text, font, size, color in pieces:
        pdf.setFont(font, size * scale)
        pdf.setFillColor(color)
        pdf.drawString(x, FIRST_Y, text)
        x += pdfmetrics.stringWidth(text, font, size * scale)
    pdf.setFont(italic, 6.8)
    pdf.setFillColor(MUTED)
    y = FIRST_Y - LINE_GAP
    for line in simpleSplit(footer["note"], italic, 6.8, left_limit - left)[:3]:
        pdf.drawString(left, y, line)
        y -= LINE_GAP * 0.85


def _draw_signatures(pdf, width, labels, content_bottom):
    """One signature line per label, side by side, like the HTML ``table.o_cw_signatures``."""
    regular = _font("CarwashLato")
    left, right = SIDE, width - SIDE
    gap = 12 * mm
    column = (right - left - gap * (len(labels) - 1)) / len(labels)
    for index, label in enumerate(labels):
        start = left + index * (column + gap)
        pdf.setStrokeColor(INK)
        pdf.setLineWidth(0.7)
        pdf.line(start + 2 * mm, content_bottom + SIGN_LINE_Y, start + column - 2 * mm, content_bottom + SIGN_LINE_Y)
        pdf.setFont(regular, 7.5)
        pdf.setFillColor(MUTED)
        for number, line in enumerate(simpleSplit(label, regular, 7.5, column)[:2]):
            pdf.drawCentredString(start + column / 2, content_bottom + SIGN_LABEL_Y - number * 2.8 * mm, line)


def stamp_pages(pdf_stream, page_label, footer=None, signatures=None, content_bottom=20 * mm):
    """Return a new stream: `pdf_stream` with the footer at the bottom of every page and the
    signature lines above it on the last page.

    :param str page_label: e.g. "Page %(page)s of %(total)s"
    :param dict footer: name, phone, email, website, note, doc_ref, printed (None: no footer)
    :param list signatures: one label per signature line (None: no signatures)
    :param float content_bottom: bottom edge of the page content, in points from the page bottom
    """
    pdf_stream.seek(0)
    reader = PdfFileReader(pdf_stream)
    pages = list(reader.pages)
    overlay_stream = io.BytesIO()
    overlay = canvas.Canvas(overlay_stream)
    for number, page in enumerate(pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay.setPageSize((width, height))
        if footer:
            _draw_footer(overlay, width, footer, page_label % {"page": number, "total": len(pages)})
        if signatures and number == len(pages):
            _draw_signatures(overlay, width, signatures, content_bottom)
        overlay.showPage()
    overlay.save()
    overlay_pages = PdfFileReader(overlay_stream).pages

    writer = PdfFileWriter()
    for page, footer_page in zip(pages, overlay_pages):
        page.merge_page(footer_page)
        writer.add_page(page)
    result = io.BytesIO()
    writer.write(result)
    result.seek(0)
    return result


def _has_class(name):
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


def lift_signatures(html, collector):
    """Take the signature table out of every printed record of the report `html`, leave an empty
    space of its height at the end of the record's content, and store the labels in
    `collector[record id]`. Returns the html to print."""
    root = lxml.html.fromstring(html, parser=lxml.html.HTMLParser(encoding="utf-8"))
    lifted = False
    for article in root.xpath(f"//div[{_has_class('article')}]"):
        tables = article.xpath(f".//table[{_has_class('o_cw_signatures')}]")
        if not tables:
            continue
        labels = [" ".join(cell.text_content().split()) for cell in tables[-1].xpath(".//td")]
        for table in tables:
            table.drop_tree()
        content = (article.xpath(f".//div[{_has_class('page')}]") or [article])[0]
        content.append(lxml.html.Element("div", {"class": "o_cw_signatures_space"}))
        collector[int(article.get("data-oe-id") or 0)] = [label for label in labels if label]
        lifted = True
    return lxml.html.tostring(root, encoding="unicode") if lifted else html
