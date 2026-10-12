"""Check in / out is for everyone now, decided by the Staff Attendance switch only (no per-branch flag): the
top-bar Check In / Check Out follows that switch for every branch (a database installed fresh had it off)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    on = env["carwash.feature"]._enabled("carwash_attendance.group_carwash_attendance")
    env["res.company"].with_context(active_test=False).search([]).write({"attendance_from_systray": on})
