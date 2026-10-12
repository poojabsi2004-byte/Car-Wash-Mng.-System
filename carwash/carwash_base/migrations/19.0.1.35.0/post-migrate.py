"""Bookings now get a quotation when they are confirmed: give one to the bookings already confirmed / running."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["carwash.appointment"].with_context(active_test=False).search([
        ("state", "in", ("confirmed", "arrived", "in_service", "ready")),
        ("sale_order_id", "=", False),
    ])._carwash_create_quotation()
