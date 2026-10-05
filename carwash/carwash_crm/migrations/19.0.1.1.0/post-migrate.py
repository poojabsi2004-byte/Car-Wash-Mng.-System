from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Booking requests not confirmed yet get the default request-verification checklist."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    leads = env["crm.lead"].search(
        [("is_carwash_booking", "=", True), ("carwash_appointment_id", "=", False), ("checklist_line_ids", "=", False)]
    )
    leads._checklist_auto_apply()
