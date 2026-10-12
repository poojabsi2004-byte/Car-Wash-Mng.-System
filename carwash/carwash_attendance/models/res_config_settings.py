from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_attendance = fields.Boolean(
        "Staff Attendance", implied_group="carwash_attendance.group_carwash_attendance",
        help="Everyone - every role, every branch - checks in / out (dashboard My Attendance and the top bar).",
    )

    def set_values(self):
        super().set_values()
        # the top-bar Check In / Check Out follows the switch, for every branch
        self.env["res.company"].sudo().with_context(active_test=False).search([]).write(
            {"attendance_from_systray": bool(self.group_carwash_attendance)}
        )
        # everyone with Car Wash access needs an employee to check in / out
        if self.group_carwash_attendance:
            self.env["res.users"].sudo().search([("share", "=", False)])._carwash_ensure_attendance_employee()
