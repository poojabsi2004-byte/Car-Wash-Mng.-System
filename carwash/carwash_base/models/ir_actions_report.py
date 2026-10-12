import logging
import socket
from urllib.parse import urlsplit

from reportlab.lib.units import mm

from odoo import models
from odoo.addons.base.models.ir_actions_report import _wkhtml
from odoo.http import request
from odoo.tools import config

from .carwash_report_footer import lift_signatures, stamp_pages

_logger = logging.getLogger(__name__)


def _url_reachable(url, timeout=1.5):
    """Whether something accepts connections at the url's host and port."""
    parts = urlsplit(url or "")
    if not parts.hostname:
        return False
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        with socket.create_connection((parts.hostname, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _carwash_page_letterhead(self):
        """Whether wkhtmltopdf can repeat the Car Wash letterhead / footer on every page.
        Only the "with patched qt" build supports page headers and footers."""
        return _wkhtml().is_patched_qt

    def get_paperformat(self):
        paperformat = super().get_paperformat()
        if not self._carwash_page_letterhead() and paperformat == self.env.ref(
            "carwash_base.paperformat_carwash_a4", raise_if_not_found=False
        ):
            # the letterhead is printed inside the page: no space reserved for a page header
            return self.env.ref("carwash_base.paperformat_carwash_a4_inline", raise_if_not_found=False) or paperformat
        return paperformat

    def _carwash_is_report(self):
        """A Car Wash report (printed with the Car Wash letterhead and paper format)."""
        self.ensure_one()
        return self.paperformat_id == self.env.ref("carwash_base.paperformat_carwash_a4", raise_if_not_found=False)

    def _carwash_stamps_footer(self):
        """Car Wash reports printed by a wkhtmltopdf that can't print page footers get their
        footer drawn at the bottom of every page afterwards (see carwash_report_footer)."""
        return self._carwash_is_report() and not self._carwash_page_letterhead()

    def _prepare_html(self, html, report_model=False):
        # Car Wash reports: the signature lines are drawn at the bottom of the last page
        signatures = self.env.context.get("carwash_signatures")
        if signatures is not None and self._carwash_is_report():
            html = lift_signatures(html, signatures)
        return super()._prepare_html(html, report_model=report_model)

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        report = self._get_report(report_ref)
        if not report._carwash_is_report():
            return super()._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)
        signatures = {}  # record id: signature labels, filled while the html is prepared
        streams = super(IrActionsReport, self.with_context(carwash_signatures=signatures))._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids=res_ids
        )
        model = self.env[report.model]
        for res_id, stream_data in streams.items():
            if not stream_data.get("stream") or stream_data.get("attachment"):
                continue  # a stored PDF was completed when it was printed the first time
            labels = signatures.get(res_id) if res_id else next(reversed(signatures.values()), None)
            record = model.browse(res_id) if res_id else model.browse((res_ids or [])[:1])
            stream_data["stream"] = report._carwash_stamp_pages(stream_data["stream"], record, labels)
        return streams

    def _carwash_stamp_pages(self, stream, record, signatures):
        """`stream` with the signature lines at the bottom of its last page and, when wkhtmltopdf
        can't print it, the Car Wash footer (branch contacts, document reference, page x of y) on
        every page. Unchanged if that fails - printing is never blocked by it."""
        footer = None
        if self._carwash_stamps_footer():
            company = record.company_id if record and "company_id" in record and record.company_id else self.env.company
            brand = company.sudo()._carwash_report_details()
            footer = {
                "name": brand["name"],
                "phone": brand["phone"],
                "email": brand["email"],
                "website": brand["website"],
                "note": brand["footer_note"] or self.env._("This is a computer-generated document."),
                "doc_ref": record.display_name if record else "",
                "printed": self.env._("Printed %s", brand["printed_at"]),
            }
        if not footer and not signatures:
            return stream
        try:
            return stamp_pages(
                stream, self.env._("Page %(page)s of %(total)s"), footer=footer, signatures=signatures,
                content_bottom=self.get_paperformat().margin_bottom * mm,
            )
        except Exception:
            _logger.exception("Car Wash report %s: could not add the footer / signatures", self.report_name)
            stream.seek(0)
            return stream

    def _get_report_url(self, layout=None):
        """wkhtmltopdf downloads the report's styles (CSS, fonts) from this address.
        Odoo uses the "web.base.url" system parameter, which keeps the address the server had
        when an administrator last logged in (e.g. another port); if nothing answers there the
        PDF comes out without any design. Then use the address of the running server instead.
        An explicit "report.url" system parameter is always kept."""
        url = super()._get_report_url(layout=layout)
        if self.env["ir.config_parameter"].sudo().get_param("report.url") or _url_reachable(url):
            return url
        for fallback in self._carwash_report_url_fallbacks():
            if fallback != url and _url_reachable(fallback):
                return fallback
        return url

    def _carwash_report_url_fallbacks(self):
        """The address the user is printing from, then this server's own HTTP port."""
        urls = []
        if request and getattr(request, "httprequest", None):
            urls.append(request.httprequest.url_root.rstrip("/"))
        if config.get("http_enable", True) and config.get("http_port"):
            host = config.get("http_interface") or "127.0.0.1"
            if host in ("0.0.0.0", "::"):
                host = "127.0.0.1"
            elif ":" in host:
                host = f"[{host}]"
            urls.append(f"http://{host}:{config['http_port']}")
        return urls
