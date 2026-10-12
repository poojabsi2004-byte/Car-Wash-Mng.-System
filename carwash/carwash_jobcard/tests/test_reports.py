from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashReports(TransactionCase):
    """The printed documents render with the booking's real data (no template errors)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Report Customer", "phone": "+91 90000 00000"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "RPT 1", "customer_id": cls.customer.id, "make": "Maruti"})
        cls.wash = cls.env["product.product"].create(
            {"name": "Report Wash", "type": "service", "is_carwash_service": True, "list_price": 450}
        )
        # staff must have a job-card role to be listed on a job card
        washer_user = cls.env["res.users"].create({"name": "Report Washer", "login": "report_washer"})
        cls.staff = cls.env["hr.employee"].create({
            "name": "Report Washer", "user_id": washer_user.id,
            "carwash_role_ids": [(6, 0, cls.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        # no document layout chosen: the Car Wash letterhead doesn't need Odoo's layout configurator
        cls.env.company.external_report_layout_id = False
        cls.booking = cls.env["carwash.appointment"].create({
            "customer_id": cls.customer.id, "vehicle_id": cls.vehicle.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=2),
            "bay_id": cls.env["carwash.bay"].create({"name": "Report Bay"}).id,
            "line_ids": [(0, 0, {"product_id": cls.wash.id})],
        })
        cls.booking.action_confirm()
        cls.inspection = cls.env["carwash.inspection"].create({
            "appointment_id": cls.booking.id, "inspection_type_id": cls.env.ref("carwash_jobcard.inspection_type_pre").id,
            "has_damage": True, "condition_notes": "Scratch on the rear bumper",
        })
        cls.jobcard = cls.env["carwash.jobcard"].create(
            {"appointment_id": cls.booking.id, "assigned_employee_ids": [(6, 0, cls.staff.ids)],
             "checklist_line_ids": [(0, 0, {"name": "Rinse"})]}
        )

    def _html(self, xmlid, records):
        report = self.env.ref(xmlid)
        return self.env["ir.actions.report"]._render_qweb_html(report.report_name, records.ids)[0].decode()

    def test_booking_confirmation_and_receipt(self):
        html = self._html("carwash_base.action_report_carwash_booking", self.booking)
        self.assertIn("Booking Confirmation", html)
        self.assertIn("RPT 1", html)
        self.assertIn("Report Wash", html)
        self.booking.state = "done"
        html = self._html("carwash_base.action_report_carwash_booking", self.booking)
        self.assertIn("Service Receipt", html)
        self.assertIn("Vehicle Inspections", html)
        self.assertIn("Scratch on the rear bumper", html)
        action = self.booking.action_print_booking()
        self.assertEqual(action["report_name"], "carwash_base.report_carwash_booking")

    def test_job_card_quality_check_and_inspection(self):
        html = self._html("carwash_jobcard.action_report_carwash_jobcard", self.jobcard)
        self.assertIn("Job Card", html)
        self.assertIn("Report Washer", html)
        self.assertIn("Rinse", html)
        html = self._html("carwash_jobcard.action_report_carwash_quality_check", self.jobcard)
        self.assertIn("Quality Check Report", html)
        self.assertIn("Damage found", html)
        html = self._html("carwash_jobcard.action_report_carwash_inspection", self.inspection)
        self.assertIn("Scratch on the rear bumper", html)
        for action in (self.jobcard.action_print_jobcard(), self.jobcard.action_print_quality_check(),
                       self.inspection.action_print_inspection()):
            self.assertEqual(action["type"], "ir.actions.report")

    def test_letterhead_branding(self):
        company = self.booking.company_id
        company.partner_id.write({
            "street": "12 Ring Road", "street2": False, "city": "Ahmedabad", "zip": "380015",
            "state_id": False, "country_id": self.env.ref("base.in").id,
            "phone": "+91 79 1234 5678", "email": "hello@carwash.test", "website": "https://carwash.test",
        })
        company.vat = "24ABCDE1234F1Z5"
        company.logo = company._get_logo()  # Odoo's "Your logo" placeholder
        details = company._carwash_report_details()
        self.assertTrue(details["is_emblem"], "the placeholder logo is replaced by the Car Wash emblem")
        html = self._html("carwash_base.action_report_carwash_booking", self.booking)
        self.assertEqual(details["vat_label"], "GSTIN")
        for text in (company.name, "12 Ring Road", "Ahmedabad, 380015, India", "+91 79 1234 5678",
                     "hello@carwash.test", "carwash.test", "24ABCDE1234F1Z5", "o_cw_letterhead", "o_cw_letterfoot"):
            self.assertIn(text, html)
        # a real logo is printed as is; a branch without its own logo uses the parent company's
        company.logo = company._carwash_report_logo()[0]  # any image other than the placeholder
        logo, is_emblem = company._carwash_report_logo()
        self.assertFalse(is_emblem)
        branch = self.env["res.company"].create({"name": "Report Branch", "parent_id": company.id})
        branch.logo = False
        self.assertEqual(branch._carwash_report_logo(), (logo, False))
        self.assertEqual(branch._carwash_report_details()["phone"], "+91 79 1234 5678")
        # every Car Wash report prints on the Car Wash paper format
        for xmlid in ("carwash_base.action_report_carwash_booking", "carwash_jobcard.action_report_carwash_jobcard",
                      "carwash_jobcard.action_report_carwash_quality_check", "carwash_jobcard.action_report_carwash_inspection"):
            report = self.env.ref(xmlid)
            self.assertEqual(report.paperformat_id, self.env.ref("carwash_base.paperformat_carwash_a4"))
            # without page-header support (unpatched wkhtmltopdf) the letterhead goes inside the page
            expected = "carwash_base.paperformat_carwash_a4" if report._carwash_page_letterhead() else "carwash_base.paperformat_carwash_a4_inline"
            self.assertEqual(report.get_paperformat(), self.env.ref(expected))
