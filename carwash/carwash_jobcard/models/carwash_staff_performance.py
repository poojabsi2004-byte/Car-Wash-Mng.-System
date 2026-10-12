from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, tools
from odoo.exceptions import UserError

PERIODS = [
    ("today", "Today"),
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("custom", "Custom"),
]


class CarwashStaffPerformance(models.Model):
    """One line per staff member and completed job card: what they did, how fast, how well
    (Reporting > Staff Performance Analysis, and the Staff Performance report)."""

    _name = "carwash.staff.performance"
    _description = "Car Wash Staff Performance"
    _auto = False
    _order = "date desc"
    _rec_name = "employee_id"
    # pending changes of these are saved before the view is read
    _depends = {
        "carwash.jobcard": [
            "stages", "start_time", "end_time", "rework_count", "appointment_id", "company_id", "assigned_employee_ids",
        ],
        "carwash.jobcard.service": ["jobcard_id", "appointment_line_id"],
        "carwash.appointment.line": ["service_state", "actual_duration", "quantity", "product_id"],
        "product.template": ["carwash_duration"],
        "rating.rating": ["rating", "consumed", "res_model", "res_id"],
        "carwash.staff.commission": ["amount", "state", "jobcard_id", "employee_id"],
    }

    employee_id = fields.Many2one("hr.employee", string="Staff", readonly=True)
    jobcard_id = fields.Many2one("carwash.jobcard", string="Job Card", readonly=True)
    appointment_id = fields.Many2one("carwash.appointment", string="Booking", readonly=True)
    company_id = fields.Many2one("res.company", string="Branch", readonly=True)
    date = fields.Datetime(string="Completed On", readonly=True)
    job_count = fields.Integer(string="Jobs Completed", readonly=True)
    service_count = fields.Integer(string="Services Done", readonly=True)
    service_minutes = fields.Float(string="Service Time (min)", readonly=True, digits=(16, 1))
    standard_minutes = fields.Float(
        string="Standard Time (min)", readonly=True, digits=(16, 1),
        help="The services' estimated duration - the time the work should take.",
    )
    job_minutes = fields.Float(string="Job Card Time (min)", readonly=True, digits=(16, 1))
    rework_count = fields.Integer(string="Reworks", readonly=True)
    first_time_pass = fields.Integer(
        string="Passed QC First Time", readonly=True, help="1 when quality control passed the job card without rework."
    )
    rating = fields.Float(string="Customer Rating", readonly=True, aggregator="avg", digits=(16, 1))
    rated_count = fields.Integer(string="Ratings", readonly=True)
    rating_sum = fields.Float(string="Rating Points", readonly=True)
    commission = fields.Float(string="Staff Payable", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY jobcard.id, rel.hr_employee_id) AS id,
                    rel.hr_employee_id AS employee_id,
                    jobcard.id AS jobcard_id,
                    jobcard.appointment_id AS appointment_id,
                    jobcard.company_id AS company_id,
                    COALESCE(jobcard.end_time, jobcard.write_date) AS date,
                    1 AS job_count,
                    COALESCE(service.service_count, 0) AS service_count,
                    COALESCE(service.service_minutes, 0) AS service_minutes,
                    COALESCE(service.standard_minutes, 0) AS standard_minutes,
                    COALESCE(EXTRACT(EPOCH FROM (jobcard.end_time - jobcard.start_time)) / 60.0, 0) AS job_minutes,
                    COALESCE(jobcard.rework_count, 0) AS rework_count,
                    CASE WHEN COALESCE(jobcard.rework_count, 0) = 0 THEN 1 ELSE 0 END AS first_time_pass,
                    review.rating AS rating,
                    CASE WHEN review.rating IS NULL THEN 0 ELSE 1 END AS rated_count,
                    COALESCE(review.rating, 0) AS rating_sum,
                    COALESCE(commission.amount, 0) AS commission
                FROM carwash_jobcard jobcard
                JOIN carwash_jobcard_hr_employee_rel rel ON rel.carwash_jobcard_id = jobcard.id
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS service_count,
                           SUM(line.actual_duration) AS service_minutes,
                           SUM(COALESCE(template.carwash_duration, 0) * line.quantity * 60.0) AS standard_minutes
                      FROM carwash_jobcard_service row_
                      JOIN carwash_appointment_line line ON line.id = row_.appointment_line_id
                      JOIN product_product product ON product.id = line.product_id
                      JOIN product_template template ON template.id = product.product_tmpl_id
                     WHERE row_.jobcard_id = jobcard.id AND line.service_state = 'done'
                ) service ON TRUE
                LEFT JOIN LATERAL (
                    SELECT AVG(rating.rating) AS rating
                      FROM rating_rating rating
                     WHERE rating.res_model = 'carwash.appointment' AND rating.res_id = jobcard.appointment_id
                       AND rating.consumed AND rating.rating >= 1
                ) review ON TRUE
                LEFT JOIN LATERAL (
                    SELECT SUM(staff_commission.amount) AS amount
                      FROM carwash_staff_commission staff_commission
                     WHERE staff_commission.jobcard_id = jobcard.id
                       AND staff_commission.employee_id = rel.hr_employee_id
                       AND staff_commission.state != 'cancelled'
                ) commission ON TRUE
                WHERE jobcard.stages = 'done'
            )
        """)


class CarwashStaffPerformanceReport(models.TransientModel):
    """Reporting > Staff Performance: choose the period, branches and staff, then print the report or
    analyse it on screen."""

    _name = "carwash.staff.performance.report"
    _description = "Car Wash Staff Performance Report"

    period = fields.Selection(PERIODS, default="this_month", required=True)
    date_from = fields.Date(string="From", compute="_compute_dates", store=True, readonly=False, required=True, precompute=True)
    date_to = fields.Date(string="To", compute="_compute_dates", store=True, readonly=False, required=True, precompute=True)
    company_ids = fields.Many2many(
        "res.company", string="Branches", default=lambda self: self.env.companies,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    employee_ids = fields.Many2many(
        "hr.employee", string="Staff", domain="[('carwash_role_ids', '!=', False)]",
        help="Leave empty for the whole team (everyone with a car wash role at the branches).",
    )
    detailed = fields.Boolean(
        string="Page per Staff Member",
        help="Add a page for each staff member: day by day, reworks, customer reviews and staff payable.",
    )

    @api.depends("date_from", "date_to")
    def _compute_display_name(self):
        for report in self:
            report.display_name = (
                self.env._("Staff Performance %s", report._period_label()) if report.date_from and report.date_to
                else self.env._("Staff Performance")
            )

    @api.depends("period")
    def _compute_dates(self):
        today = fields.Date.context_today(self)
        for report in self:
            if report.period == "today":
                start, end = today, today
            elif report.period == "this_week":
                start = today - timedelta(days=today.weekday())
                end = start + timedelta(days=6)
            elif report.period == "last_week":
                start = today - timedelta(days=today.weekday() + 7)
                end = start + timedelta(days=6)
            elif report.period == "last_month":
                start = today.replace(day=1) - relativedelta(months=1)
                end = today.replace(day=1) - timedelta(days=1)
            elif report.period == "this_month" or not (report.date_from and report.date_to):
                start = today.replace(day=1)
                end = start + relativedelta(months=1, days=-1)
            else:
                continue  # custom: keep the dates typed in
            report.date_from, report.date_to = start, end

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for report in self:
            if report.date_from and report.date_to and report.date_from > report.date_to:
                raise UserError(self.env._("The start date must be before the end date."))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _carwash_check_manager(self):
        if not self.env.user.has_group("carwash_base.group_carwash_manager"):
            raise UserError(self.env._("Only a Car Wash Manager can see the staff performance."))

    def action_print(self):
        self.ensure_one()
        self._carwash_check_manager()
        return self.env.ref("carwash_jobcard.action_report_carwash_staff_performance").report_action(self)

    def action_view_analysis(self):
        self.ensure_one()
        self._carwash_check_manager()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_staff_performance_analysis")
        action["domain"] = self._performance_domain()
        action["context"] = {"group_by": ["employee_id"]}
        action["display_name"] = self.env._("Staff Performance: %s", self._period_label())
        return action

    # ------------------------------------------------------------------
    # Report data
    # ------------------------------------------------------------------
    def _utc_bounds(self):
        """[start, end) of the period in UTC, from the user's local days."""
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")

        def utc(day):
            return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        return utc(self.date_from), utc(self.date_to + timedelta(days=1))

    def _companies(self):
        return self.company_ids or self.env.companies

    def _performance_domain(self):
        start, end = self._utc_bounds()
        domain = [("date", ">=", start), ("date", "<", end), ("company_id", "in", self._companies().ids)]
        if self.employee_ids:
            domain.append(("employee_id", "in", self.employee_ids.ids))
        return domain

    def _period_label(self):
        if self.date_from == self.date_to:
            return self.date_from.strftime("%d %b, %y")
        return f"{self.date_from.strftime('%d %b, %y')} - {self.date_to.strftime('%d %b, %y')}"

    def _team(self):
        """Who the report is about: the chosen staff, else everyone with a car wash role at the branches."""
        if self.employee_ids:
            return self.employee_ids
        return self.env["hr.employee"].search([
            ("carwash_role_ids", "!=", False), ("company_id", "in", self._companies().ids),
        ])

    def _carwash_performance_hours(self, employees, start, end):
        """{employee id: hours worked} in [start, end) - filled in by Staff Attendance when it's installed."""
        return {}

    def _carwash_report_data(self):
        """Everything the Staff Performance report prints."""
        self.ensure_one()
        Performance = self.env["carwash.staff.performance"].sudo()
        start, end = self._utc_bounds()
        domain = self._performance_domain()
        lines = Performance.search(domain)
        team = self._team() | lines.employee_id
        if not self.employee_ids:
            team = team.filtered(lambda e: e.company_id in self._companies() or e in lines.employee_id)
        hours = self._carwash_performance_hours(team, start, end)

        # QC inspections done by the team (QC inspectors)
        Jobcard = self.env["carwash.jobcard"].sudo()
        qc_counts = dict(Jobcard._read_group(
            [("qc_inspector_id", "in", team.ids), ("stages", "=", "done"), ("end_time", ">=", start),
             ("end_time", "<", end), ("company_id", "in", self._companies().ids)],
            ["qc_inspector_id"], ["__count"],
        ))
        commissions = defaultdict(lambda: {"to_pay": 0.0, "paid": 0.0})
        for commission in self.env["carwash.staff.commission"].sudo().search([
            ("employee_id", "in", team.ids), ("jobcard_id", "in", lines.jobcard_id.ids), ("state", "!=", "cancelled"),
        ]):
            commissions[commission.employee_id.id]["paid" if commission.state == "paid" else "to_pay"] += commission.amount

        by_employee = defaultdict(lambda: Performance.browse())
        for line in lines:
            by_employee[line.employee_id.id] |= line

        rows = []
        for employee in team:
            mine = by_employee[employee.id]
            jobs = len(mine)
            services = sum(mine.mapped("service_count"))
            service_minutes = sum(mine.mapped("service_minutes"))
            standard_minutes = sum(mine.mapped("standard_minutes"))
            first_time = sum(mine.mapped("first_time_pass"))
            rated = sum(mine.mapped("rated_count"))
            worked = hours.get(employee.id)
            rows.append({
                "employee": employee,
                "roles": ", ".join(employee.carwash_role_ids.mapped("name")),
                "jobs": jobs,
                "services": services,
                "avg_minutes": service_minutes / services if services else 0.0,
                "standard_minutes": standard_minutes / services if services else 0.0,
                # > 100: faster than the services' standard time
                "speed": round(standard_minutes / service_minutes * 100) if service_minutes and standard_minutes else 0,
                "reworks": sum(mine.mapped("rework_count")),
                "pass_rate": round(first_time / jobs * 100) if jobs else 0,
                "rating": round(sum(mine.mapped("rating_sum")) / rated, 1) if rated else 0.0,
                "rated": rated,
                "commission": sum(mine.mapped("commission")),
                "commission_to_pay": commissions[employee.id]["to_pay"],
                "commission_paid": commissions[employee.id]["paid"],
                "qc_checks": qc_counts.get(employee, 0),
                "hours": worked,
                "jobs_per_hour": round(jobs / worked, 2) if worked else 0.0,
                "lines": mine,
            })
        rows.sort(key=lambda r: (-r["jobs"], -r["pass_rate"], -r["rating"], r["employee"].name or ""))
        top_jobs = max((r["jobs"] for r in rows), default=0)
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            row["bar"] = round(row["jobs"] / top_jobs * 100) if top_jobs else 0

        # the team (job cards counted once even with a crew of several)
        jobcards = {}
        for line in lines:
            jobcards[line.jobcard_id.id] = line
        unique = list(jobcards.values())
        team_services = sum(line.service_count for line in unique)
        team_service_minutes = sum(line.service_minutes for line in unique)
        team_rated = [line.rating for line in unique if line.rated_count]
        summary = {
            "jobs": len(unique),
            "services": team_services,
            "avg_minutes": team_service_minutes / team_services if team_services else 0.0,
            "pass_rate": round(sum(line.first_time_pass for line in unique) / len(unique) * 100) if unique else 0,
            "reworks": sum(line.rework_count for line in unique),
            "rating": round(sum(team_rated) / len(team_rated), 1) if team_rated else 0.0,
            "rated": len(team_rated),
            "commission": sum(r["commission"] for r in rows),
            "staff": len([r for r in rows if r["jobs"]]),
            "hours": sum(r["hours"] or 0.0 for r in rows),
        }

        def best(key, minimum_key, minimum=1):
            candidates = [r for r in rows if r[minimum_key] >= minimum and r[key]]
            return max(candidates, key=lambda r: r[key]) if candidates else None
        highlights = [
            (self.env._("Most jobs"), best("jobs", "jobs"), "jobs", ""),
            (self.env._("Fastest vs standard"), best("speed", "services"), "speed", "%"),
            (self.env._("Best QC first-time pass"), best("pass_rate", "jobs"), "pass_rate", "%"),
            (self.env._("Best customer rating"), best("rating", "rated"), "rating", " / 5"),
        ]
        return {
            "period": self._period_label(),
            "branches": ", ".join(self._companies().mapped("name")),
            "currency": self._companies()[:1].currency_id or self.env.company.currency_id,
            "rows": rows,
            "summary": summary,
            "highlights": [h for h in highlights if h[1]],
            "show_hours": any(r["hours"] for r in rows),  # only when hours were recorded
            "show_qc": any(r["qc_checks"] for r in rows),
        }

    def _carwash_staff_details(self, row):
        """The staff member's page: day by day, reworks, customer reviews."""
        lines = row["lines"]
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        days = defaultdict(lambda: {"jobs": 0, "services": 0, "minutes": 0.0, "reworks": 0})
        for line in lines:
            day = pytz.utc.localize(line.date).astimezone(tz).date()
            days[day]["jobs"] += 1
            days[day]["services"] += line.service_count
            days[day]["minutes"] += line.service_minutes
            days[day]["reworks"] += line.rework_count
        reviews = self.env["rating.rating"].sudo().search([
            ("res_model", "=", "carwash.appointment"), ("res_id", "in", lines.appointment_id.ids),
            ("consumed", "=", True), ("rating", ">=", 1),
        ], order="write_date desc", limit=10)
        return {
            "days": [
                {"date": day, **values, "avg": values["minutes"] / values["services"] if values["services"] else 0.0}
                for day, values in sorted(days.items())
            ],
            "reworks": lines.filtered("rework_count").jobcard_id,
            "reviews": reviews,
        }


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def action_carwash_performance_report(self):
        """Performance Report button: the staff member's report for this month (with their own page)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Staff Performance"),
            "res_model": "carwash.staff.performance.report",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_employee_ids": [self.id],
                "default_detailed": True,
                "default_company_ids": (self.company_id or self.env.company).ids,
            },
        }
