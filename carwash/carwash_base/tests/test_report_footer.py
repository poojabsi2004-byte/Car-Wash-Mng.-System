import io
from unittest.mock import patch

from reportlab.pdfgen import canvas

from odoo.tests import TransactionCase, tagged
from odoo.tools.pdf import PdfFileReader

from odoo.addons.carwash_base.models.carwash_report_footer import lift_signatures, stamp_pages


@tagged("post_install", "-at_install")
class TestReportFooter(TransactionCase):
    """Without page-footer support in wkhtmltopdf, the footer is drawn on every page of the PDF."""

    def _pdf(self, pages):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(595.28, 841.89))  # A4, like wkhtmltopdf's output
        for number in range(1, pages + 1):
            pdf.drawString(72, 720, f"Body page {number}")
            pdf.showPage()
        pdf.save()
        return stream

    def test_footer_on_every_page(self):
        footer = {
            "name": "Sparkle Car Wash", "phone": "+91 79 4000 1234", "email": "care@sparkle.test",
            "website": "sparkle.test", "note": "Thank you for washing with us", "doc_ref": "CW/26/0001",
            "printed": "Printed 07 Oct, 26 10:00 AM",
        }
        signatures = ["Washer / Detailer", "QC Inspector"]
        reader = PdfFileReader(stamp_pages(self._pdf(2), "Page %(page)s of %(total)s", footer=footer, signatures=signatures))
        self.assertEqual(len(reader.pages), 2)
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            for expected in (f"Body page {number}", f"Page {number} of 2", "CW/26/0001", "Sparkle Car Wash"):
                self.assertIn(expected, text)
        self.assertNotIn("QC Inspector", reader.pages[0].extract_text(), "signatures only on the last page")
        self.assertIn("Washer / Detailer", reader.pages[1].extract_text())
        self.assertIn("QC Inspector", reader.pages[1].extract_text())

    def test_signatures_lifted_from_the_page(self):
        html = """<html><body><main>
            <div class="article" data-oe-model="carwash.jobcard" data-oe-id="7"><div class="page o_cw_report">
                <p>Checklist</p>
                <table class="o_cw_signatures"><tr>
                    <td><div class="o_cw_sign_line"/>Washer / Detailer</td><td><div class="o_cw_sign_line"/>QC Inspector - Ravi</td>
                </tr></table>
                <p class="o_cw_thanks">Thank you</p>
            </div></div></main></body></html>"""
        collector = {}
        result = lift_signatures(html, collector)
        self.assertEqual(collector, {7: ["Washer / Detailer", "QC Inspector - Ravi"]})
        self.assertNotIn("o_cw_signatures\"", result)
        self.assertIn("Thank you", result)
        self.assertLess(result.index("Thank you"), result.index("o_cw_signatures_space"), "the space ends the content")
        self.assertEqual(lift_signatures("<html><body><p>No signatures</p></body></html>", {}),
                         "<html><body><p>No signatures</p></body></html>")

    def test_report_footer_only_when_needed(self):
        booking_report = self.env.ref("carwash_base.action_report_carwash_booking")
        report_class = type(booking_report)
        with patch.object(report_class, "_carwash_page_letterhead", return_value=True):
            self.assertFalse(booking_report._carwash_stamps_footer(), "patched wkhtmltopdf prints the footer itself")
        with patch.object(report_class, "_carwash_page_letterhead", return_value=False):
            self.assertTrue(booking_report._carwash_stamps_footer())
            other = self.env["ir.actions.report"].search([("paperformat_id", "=", False)], limit=1)
            self.assertFalse(other._carwash_stamps_footer(), "only Car Wash reports are stamped")
            # the branch's details and the document reference are printed
            company = self.env.company
            reader = PdfFileReader(booking_report._carwash_stamp_pages(self._pdf(1), company.partner_id, ["Customer"]))
            text = reader.pages[0].extract_text()
            self.assertIn(company.name, text)
            self.assertIn("Page 1 of 1", text)
            self.assertIn("Customer", text)
