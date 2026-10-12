from datetime import datetime

import pytz

from odoo import api, fields, models

CARWASH_SHIFT_STATUS = [
    ("on_shift", "On Shift"),
    ("done", "Checked Out"),
    ("no_checkout", "No Check-out"),
]


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    carwash_branch_id = fields.Many2one(
        "res.company", string="Branch", compute="_compute_carwash_branch_id", store=True, readonly=False,
        index=True, help="Branch the staff member worked at (their branch when they checked in).",
    )
    # shown on the Car Wash attendance list / form (the times of day in the staff member's timezone)
    carwash_status = fields.Selection(
        CARWASH_SHIFT_STATUS, string="Status", compute="_compute_carwash_shift",
        help="On Shift: checked in, not out yet. Checked Out: shift ended. "
        "No Check-out: checked in on an earlier day and never checked out.",
    )
    carwash_in_time = fields.Char(string="In", compute="_compute_carwash_shift")
    carwash_out_time = fields.Char(string="Out", compute="_compute_carwash_shift")

    @api.depends("employee_id")
    def _compute_carwash_branch_id(self):
        # only follows the employee picked on the attendance - moving the employee to another
        # branch later doesn't rewrite where past shifts were worked
        for attendance in self:
            attendance.carwash_branch_id = attendance.employee_id.company_id

    def _carwash_tz(self):
        self.ensure_one()
        # sudo: the employee / branch hours aren't readable by every user
        name = (
            self.employee_id.sudo().tz
            or self.carwash_branch_id.sudo().resource_calendar_id.tz
            or self.env.user.tz
            or "UTC"
        )
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    @api.depends("check_in", "check_out", "employee_id", "carwash_branch_id")
    @api.depends_context("tz")
    def _compute_carwash_shift(self):
        for attendance in self:
            tz = attendance._carwash_tz()
            local_in = attendance.check_in and pytz.utc.localize(attendance.check_in).astimezone(tz)
            local_out = attendance.check_out and pytz.utc.localize(attendance.check_out).astimezone(tz)
            attendance.carwash_in_time = local_in.strftime("%I:%M %p") if local_in else False
            out_time = local_out.strftime("%I:%M %p") if local_out else False
            if out_time and local_in and local_out.date() > local_in.date():
                out_time += " (+%s)" % (local_out.date() - local_in.date()).days  # ended on a later day
            attendance.carwash_out_time = out_time
            if attendance.check_out:
                attendance.carwash_status = "done"
            elif local_in and local_in.date() < datetime.now(tz).date():
                attendance.carwash_status = "no_checkout"
            else:
                attendance.carwash_status = "on_shift"
