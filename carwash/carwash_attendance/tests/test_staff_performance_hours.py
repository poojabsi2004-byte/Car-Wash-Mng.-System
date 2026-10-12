from datetime import datetime, time, timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStaffPerformanceHours(TransactionCase):
    """With Staff Attendance on, the Staff Performance report shows the hours worked and jobs per hour."""

    def test_hours_worked_from_attendances(self):
        self.env.ref("base.group_user").write({"implied_ids": [Command.link(self.env.ref("carwash_attendance.group_carwash_attendance").id)]})
        user = self.env["res.users"].create({"name": "Hours Washer", "login": "hours_washer"})
        employee = self.env["hr.employee"].create({
            "name": "Hours Washer", "user_id": user.id,
            "carwash_role_ids": [Command.set(self.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        # a fixed early-morning shift yesterday (02:00-04:00 UTC): never overlaps a lunch break, whatever the time
        # the test runs (Odoo deducts the calendar's lunch from worked hours)
        start = datetime.combine(fields.Date.today() - timedelta(days=1), time(2, 0))
        self.env["hr.attendance"].create({"employee_id": employee.id, "check_in": start,
                                          "check_out": start + timedelta(hours=2)})
        today = fields.Date.context_today(employee)
        report = self.env["carwash.staff.performance.report"].create({
            "period": "custom", "date_from": today - timedelta(days=3), "date_to": today,
            "employee_ids": [Command.set(employee.ids)],
        })
        data = report._carwash_report_data()
        self.assertTrue(data["show_hours"])
        self.assertAlmostEqual(data["rows"][0]["hours"], 2.0, places=2)
        self.assertEqual(data["rows"][0]["jobs_per_hour"], 0.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "carwash_jobcard.action_report_carwash_staff_performance", report.ids
        )[0].decode()
        self.assertIn("Hours worked", html)
