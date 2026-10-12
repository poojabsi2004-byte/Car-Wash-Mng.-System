from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Car Wash users without an employee (e.g. created in Settings > Users) get one, to check in / out."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["res.users"].search([("share", "=", False)])._carwash_ensure_attendance_employee()
