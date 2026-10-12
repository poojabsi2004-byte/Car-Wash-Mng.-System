from odoo import models

from .hr_employee import FEATURE


class CarwashStaffPerformanceReport(models.TransientModel):
    _inherit = "carwash.staff.performance.report"

    def _carwash_performance_hours(self, employees, start, end):
        """Hours worked from the attendances (check-ins in the period), when Staff Attendance is on."""
        hours = super()._carwash_performance_hours(employees, start, end)
        if not employees or not self.env["carwash.feature"]._enabled(FEATURE):
            return hours
        worked = dict.fromkeys(employees.ids, 0.0)
        for employee, total in self.env["hr.attendance"].sudo()._read_group(
            [("employee_id", "in", employees.ids), ("check_in", ">=", start), ("check_in", "<", end)],
            ["employee_id"], ["worked_hours:sum"],
        ):
            worked[employee.id] = total or 0.0
        hours.update(worked)
        return hours
