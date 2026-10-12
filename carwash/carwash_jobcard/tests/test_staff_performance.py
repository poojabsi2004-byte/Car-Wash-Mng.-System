from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStaffPerformance(TransactionCase):
    """Staff Performance: jobs, service time against the standard, QC first-time pass / reworks, rating,
    commission - per staff member, ranked, printed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["carwash.checklist.template"].search([]).is_default = False  # no checklist gates here
        # Perf Ravi is paid his own 10% (Settings > Individual Staff Pay)
        cls.env["res.config.settings"].create({"group_carwash_individual_pay": True}).execute()
        washer_role = cls.env.ref("carwash_jobcard.staff_role_washer")

        def staff(name, login, rate=0.0):
            user = cls.env["res.users"].create({
                "name": name, "login": login,
                "group_ids": [Command.set([cls.env.ref("carwash_jobcard.group_carwash_washer").id])],
            })
            return cls.env["hr.employee"].create({
                "name": name, "user_id": user.id, "carwash_role_ids": [Command.set(washer_role.ids)],
                "carwash_commission_type": "percent" if rate else "none", "carwash_commission_rate": rate,
            })
        cls.ravi = staff("Perf Ravi", "perf_ravi", rate=10)
        cls.asha = staff("Perf Asha", "perf_asha")
        qc_user = cls.env["res.users"].create({"name": "Perf QC", "login": "perf_qc"})
        cls.inspector = cls.env["hr.employee"].create({
            "name": "Perf QC", "user_id": qc_user.id,
            "carwash_role_ids": [Command.set(cls.env.ref("carwash_jobcard.staff_role_qc").ids)],
        })
        cls.customer = cls.env["res.partner"].create({"name": "Perf Customer"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "PERF 1", "customer_id": cls.customer.id})
        Product = cls.env["product.product"]
        cls.wash = Product.create({"name": "Perf Wash", "type": "service", "is_carwash_service": True,
                                   "list_price": 500, "carwash_duration": 0.5})  # standard 30 min
        cls.wax = Product.create({"name": "Perf Wax", "type": "service", "is_carwash_service": True,
                                  "list_price": 300, "carwash_duration": 0.25})  # standard 15 min
        cls.manager = cls.env["res.users"].create({
            "name": "Perf Manager", "login": "perf_manager",
            "group_ids": [Command.set([cls.env.ref("carwash_base.group_carwash_manager").id])],
        })

    def _job(self, crew, services, rework=False, rating=None):
        """A completed job card: services done in the given minutes, optionally failed QC once and rated."""
        booking = self.env["carwash.appointment"].create({
            "customer_id": self.customer.id, "vehicle_id": self.vehicle.id,
            "appointment_date": fields.Datetime.now() - timedelta(hours=2),
            "line_ids": [Command.create({"product_id": product.id}) for product, _minutes in services],
        })
        booking.action_confirm()
        jobcard = self.env["carwash.jobcard"].create({
            "appointment_id": booking.id, "assigned_employee_ids": [Command.set(crew.ids)],
            "qc_inspector_id": self.inspector.id,
        })
        jobcard.action_start()
        start = fields.Datetime.now() - timedelta(hours=1)
        for line, (_product, minutes) in zip(booking.line_ids, services):
            line.sudo().write({"service_state": "done", "start_time": start, "end_time": start + timedelta(minutes=minutes)})
        jobcard.stages = "qc"
        if rework:
            jobcard.action_qc_fail()
            jobcard.stages = "qc"
        jobcard.action_qc_pass()
        if rating:
            self.env["rating.rating"].create({
                "res_model_id": self.env["ir.model"]._get_id("carwash.appointment"), "res_id": booking.id,
                "partner_id": self.customer.id, "rating": rating, "consumed": True, "feedback": "Shiny!",
            })
        return jobcard

    def _report(self, **vals):
        return self.env["carwash.staff.performance.report"].with_user(self.manager).create({
            "period": "this_month", "company_ids": [Command.set(self.env.company.ids)], **vals,
        })

    def test_ranking_and_figures(self):
        team_job = self._job(self.ravi | self.asha, [(self.wash, 25), (self.wax, 15)], rework=True, rating=4)
        self.assertEqual(team_job.rework_count, 1, "QC Fail counts a rework")
        self._job(self.ravi, [(self.wash, 30)], rating=5)

        lines = self.env["carwash.staff.performance"].search([("jobcard_id", "in", team_job.ids)])
        self.assertEqual(lines.employee_id, self.ravi | self.asha, "a crew job counts for each member")
        self.assertEqual(set(lines.mapped("service_count")), {2})
        self.assertEqual(set(lines.mapped("standard_minutes")), {45.0})

        report = self._report(employee_ids=[Command.set((self.ravi | self.asha).ids)])
        data = report._carwash_report_data()
        ravi, asha = data["rows"]
        self.assertEqual((ravi["employee"], ravi["rank"], asha["employee"], asha["rank"]), (self.ravi, 1, self.asha, 2),
                         "ranked by jobs completed")
        self.assertEqual((ravi["jobs"], ravi["services"], ravi["reworks"], ravi["pass_rate"]), (2, 3, 1, 50))
        self.assertAlmostEqual(ravi["avg_minutes"], 70 / 3, places=1)
        self.assertEqual(ravi["speed"], round(75 / 70 * 100), "standard 75 min / taken 70 min")
        self.assertEqual((ravi["rating"], ravi["rated"]), (4.5, 2))
        self.assertEqual((asha["jobs"], asha["pass_rate"], asha["rating"]), (1, 0, 4.0))
        self.assertAlmostEqual(ravi["commission"], 10 / 100 * (800 / 2 + 500), msg="10% of his share")
        self.assertEqual(ravi["commission_to_pay"], ravi["commission"])
        self.assertEqual(asha["commission"], 0)
        summary = data["summary"]
        self.assertEqual((summary["jobs"], summary["services"], summary["reworks"], summary["pass_rate"]), (2, 3, 1, 50),
                         "the team counts each job card once")
        self.assertEqual(summary["rating"], 4.5)
        self.assertEqual({h[0] for h in data["highlights"]} >= {"Most jobs", "Best customer rating"}, True)

        details = report._carwash_staff_details(ravi)
        self.assertEqual(sum(day["jobs"] for day in details["days"]), 2)
        self.assertEqual(details["reworks"], team_job)
        self.assertEqual(len(details["reviews"]), 2)

    def test_whole_team_and_hours_hook(self):
        self._job(self.asha, [(self.wash, 35)])
        report = self._report()
        data = report._carwash_report_data()
        mine = [row for row in data["rows"] if row["employee"] in self.ravi | self.asha]
        self.assertEqual([row["employee"] for row in mine], [self.asha, self.ravi],
                         "the whole team, staff without jobs in the period too (ranked last)")
        self.assertEqual((mine[1]["jobs"], mine[1]["pass_rate"], mine[1]["avg_minutes"]), (0, 0, 0.0))

    def test_print_and_analyse(self):
        self._job(self.ravi | self.asha, [(self.wash, 25), (self.wax, 10)], rework=True, rating=4)
        report = self._report(detailed=True, employee_ids=[Command.set((self.ravi | self.asha).ids)])
        html = self.env["ir.actions.report"]._render_qweb_html(
            "carwash_jobcard.action_report_carwash_staff_performance", report.ids
        )[0].decode()
        for text in ("Staff Performance", "Ranking", "Perf Ravi", "Perf Asha", "Day by Day", "Customer Reviews", "Shiny!"):
            self.assertIn(text, html)
        self.assertEqual(report.action_print()["report_name"], "carwash_jobcard.report_carwash_staff_performance")
        action = report.action_view_analysis()
        self.assertEqual(action["res_model"], "carwash.staff.performance")
        self.assertEqual(self.env["carwash.staff.performance"].search_count(action["domain"]), 2)

        button = self.ravi.action_carwash_performance_report()
        self.assertEqual((button["res_model"], button["context"]["default_employee_ids"]),
                         ("carwash.staff.performance.report", [self.ravi.id]))
        washer = self.ravi.user_id
        with self.assertRaises(UserError):
            report.with_user(washer).action_print()

    def test_periods(self):
        report = self._report()
        today = fields.Date.context_today(report)
        self.assertEqual((report.date_from, report.date_to.month), (today.replace(day=1), today.month))
        report.period = "last_week"
        self.assertEqual((report.date_to - report.date_from).days, 6)
        self.assertEqual(report.date_from.weekday(), 0)
        with self.assertRaises(UserError):
            report.write({"period": "custom", "date_from": today, "date_to": today - timedelta(days=1)})


@tagged("post_install", "-at_install")
class TestStaffPerformancePdf(HttpCase):
    """The Staff Performance report prints as a real PDF (wkhtmltopdf). An HttpCase: wkhtmltopdf fetches the report
    styles from the server, which shares the test's cursor here."""

    def test_pdf(self):
        user = self.env["res.users"].create({"name": "Pdf Washer", "login": "pdf_washer"})
        employee = self.env["hr.employee"].create({
            "name": "Pdf Washer", "user_id": user.id,
            "carwash_role_ids": [Command.set(self.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        report = self.env["carwash.staff.performance.report"].create({
            "period": "this_month", "detailed": True, "employee_ids": [Command.set(employee.ids)],
        })
        pdf, kind = self.env["ir.actions.report"].with_context(force_report_rendering=True)._render_qweb_pdf(
            "carwash_jobcard.action_report_carwash_staff_performance", report.ids
        )
        self.assertEqual(kind, "pdf")
        self.assertTrue(pdf.startswith(b"%PDF"))

