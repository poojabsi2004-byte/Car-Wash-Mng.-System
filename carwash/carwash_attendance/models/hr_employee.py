from odoo import api, fields, models
from odoo.exceptions import UserError

FEATURE = "carwash_attendance.group_carwash_attendance"


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    carwash_attendance_enabled = fields.Boolean(compute="_compute_carwash_attendance_enabled")
    carwash_today_hours = fields.Float(compute="_compute_carwash_today_hours", string="Worked Today")

    def _compute_carwash_attendance_enabled(self):
        enabled = self.env["carwash.feature"]._enabled(FEATURE)
        for employee in self:
            employee.carwash_attendance_enabled = enabled

    def _compute_carwash_today_hours(self):
        start = self.env["carwash.dashboard"]._day_start_utc(self.env["carwash.dashboard"]._local_now().date())
        now = fields.Datetime.now()
        attendances = self.env["hr.attendance"].sudo().search(
            [("employee_id", "in", self.ids), ("check_in", ">=", start)]
        )
        for employee in self:
            hours = 0.0
            for attendance in attendances.filtered(lambda a: a.employee_id == employee):
                hours += ((attendance.check_out or now) - attendance.check_in).total_seconds() / 3600.0
            employee.carwash_today_hours = hours

    def action_carwash_check_in_out(self):
        """Check the staff member in (or out) from their employee form - like the kiosk does."""
        self.ensure_one()
        if not self.env["carwash.feature"]._enabled(FEATURE):
            raise UserError(self.env._("Staff attendance is switched off (Car Wash > Configuration > Settings)."))
        if not self.env.user.has_group("hr_attendance.group_hr_attendance_officer"):
            raise UserError(self.env._("Only attendance officers can check staff in or out."))
        self.sudo()._attendance_action_change()
        return True

    def action_carwash_view_attendances(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_attendance.action_carwash_attendance")
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {"default_employee_id": self.id}
        action["display_name"] = self.env._("Attendances: %s", self.name)
        return action
