from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.carwash_dashboard.models.carwash_dashboard import _initials

FEATURE = "carwash_attendance.group_carwash_attendance"


class CarwashDashboard(models.AbstractModel):
    _inherit = "carwash.dashboard"

    @api.model
    def get_dashboard_data(self, period="week", date_from=None, date_to=None):
        data = super().get_dashboard_data(period=period, date_from=date_from, date_to=date_to)
        if self.env["carwash.feature"]._enabled(FEATURE):
            if data.get("has_manager_data"):
                data["attendance"] = self._get_attendance_data(self.env.companies.ids)
            # everyone (every role: washer, QC, front desk, manager, owner) checks in / out from the dashboard
            my_attendance = self._get_my_attendance_data()
            if my_attendance:
                data["my_attendance"] = my_attendance
        return data

    def _get_my_attendance_data(self):
        """The logged-in person's attendance: checked in or not, today's hours, the last shifts (every role)."""
        # sudo: staff only read their own attendances; the employee is the user's own
        employee = self.env.user.sudo().employee_id
        if not employee:
            # still shown: tells them why they can't check in
            return {"no_employee": True, "name": self.env.user.name, "checked_in": False, "since": "",
                    "today": "0h 00m", "recent": []}
        Attendance = self.env["hr.attendance"].sudo()
        now = fields.Datetime.now()
        today_start = self._day_start_utc(self._local_now().date())
        current = Attendance.search([("employee_id", "=", employee.id), ("check_out", "=", False)], limit=1)
        today = Attendance.search([
            ("employee_id", "=", employee.id), "|", ("check_in", ">=", today_start), ("check_out", "=", False),
        ])
        minutes = int(sum(((a.check_out or now) - max(a.check_in, today_start)).total_seconds() for a in today) // 60)
        recent = Attendance.search([("employee_id", "=", employee.id), ("check_out", "!=", False)],
                                   order="check_in desc", limit=4)
        return {
            "name": employee.name,
            "checked_in": bool(current),
            "since": self._fmt_time(current.check_in) if current else "",
            "today": f"{minutes // 60}h {minutes % 60:02d}m",
            "recent": [
                {
                    "id": attendance.id,
                    "day": self._to_local(attendance.check_in).strftime("%d %b"),
                    "check_in": self._fmt_time(attendance.check_in),
                    "check_out": self._fmt_time(attendance.check_out),
                    "hours": f"{int(attendance.worked_hours)}h {int(round(attendance.worked_hours % 1 * 60)):02d}m",
                }
                for attendance in recent
            ],
        }

    @api.model
    def action_carwash_check_in_out(self):
        """Dashboard button: check the logged-in staff member in, or out."""
        if not self.env["carwash.feature"]._enabled(FEATURE):
            raise UserError(self.env._("Staff Attendance is switched off in the Car Wash settings."))
        employee = self.env.user.sudo().employee_id
        if not employee:
            raise UserError(self.env._("Your user isn't linked to an employee - ask a manager to add you as staff."))
        employee._attendance_action_change({"mode": "systray"})
        return self._get_my_attendance_data()

    def _get_attendance_data(self, company_ids):
        """Today's staff attendance at the selected branch(es): who's in now and the day's counts."""
        today = self._local_now().date()
        today_start = self._day_start_utc(today)
        now = fields.Datetime.now()
        # sudo: managers see everyone's presence here; the full records stay behind attendance rights
        Employee = self.env["hr.employee"].sudo()
        staff = Employee.search([("company_id", "in", company_ids), ("carwash_role_ids", "!=", False)])
        attendances = self.env["hr.attendance"].sudo().search(
            [
                ("carwash_branch_id", "in", company_ids),
                "|", ("check_in", ">=", today_start), ("check_out", "=", False),
            ],
            order="check_in",
        )
        open_attendances = attendances.filtered(lambda a: not a.check_out)
        worked_today = attendances.employee_id
        present = []
        for attendance in open_attendances.sorted("check_in"):
            employee = attendance.employee_id
            minutes = max(0, int((now - attendance.check_in).total_seconds() // 60))
            present.append({
                "id": employee.id,
                "attendance_id": attendance.id,
                "name": employee.name,
                "initials": _initials(employee.name),
                "roles": ", ".join(employee.carwash_role_ids.mapped("name")) or (employee.job_title or ""),
                "branch": attendance.carwash_branch_id.name or "",
                "check_in": self._fmt_time(attendance.check_in),
                "since_yesterday": attendance.check_in < today_start,
                "duration": f"{minutes // 60}h {minutes % 60:02d}m",
            })
        checked_out = worked_today - open_attendances.employee_id
        return {
            "present": present,
            "counts": {
                "staff": len(staff | worked_today),
                "present": len(open_attendances.employee_id),
                "checked_out": len(checked_out),
                "absent": len(staff - worked_today),
            },
            "hours_today": round(sum(
                ((a.check_out or now) - max(a.check_in, today_start)).total_seconds() / 3600.0 for a in attendances
            ), 1),
        }
