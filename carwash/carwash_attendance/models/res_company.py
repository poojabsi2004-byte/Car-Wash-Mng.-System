from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # car wash staff / QC check in and out themselves (top bar, and the dashboard's My Attendance)
    attendance_from_systray = fields.Boolean(default=True)
