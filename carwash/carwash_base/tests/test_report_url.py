from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.carwash_base.models import ir_actions_report as report_module


@tagged("post_install", "-at_install")
class TestReportUrl(TransactionCase):
    """PDFs keep their design when web.base.url points to an address nothing answers on."""

    def test_unreachable_base_url_uses_running_server(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("report.url", False)
        ICP.set_param("web.base.url", "http://localhost:8088")  # server since moved to another port
        Report = self.env["ir.actions.report"]
        running = "http://localhost:8069"
        with patch.object(type(Report), "_carwash_report_url_fallbacks", return_value=[running]), \
                patch.object(report_module, "_url_reachable", side_effect=lambda url, timeout=1.5: url == running):
            self.assertEqual(Report._get_report_url(), running)
        # a base url that answers is used as before
        with patch.object(report_module, "_url_reachable", return_value=True):
            self.assertEqual(Report._get_report_url(), "http://localhost:8088")
        # an explicit report.url is always kept
        ICP.set_param("report.url", "http://reports.internal:8069")
        with patch.object(report_module, "_url_reachable", return_value=False):
            self.assertEqual(Report._get_report_url(), "http://reports.internal:8069")

    def test_url_reachable(self):
        self.assertFalse(report_module._url_reachable("http://127.0.0.1:1", timeout=0.5))
        self.assertFalse(report_module._url_reachable("not a url"))
