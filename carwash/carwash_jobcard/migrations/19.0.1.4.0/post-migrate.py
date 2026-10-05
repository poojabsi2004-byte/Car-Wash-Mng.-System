from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Inspections gained a state (In Progress / Completed) and bookings a check-in checklist.

    Inspections recorded before that existed were finished in practice - mark them
    Completed so they don't block bookings already under way. Upcoming bookings (not
    arrived yet) get the default check-in checklist.
    """
    cr.execute("UPDATE carwash_inspection SET state = 'done' WHERE state IS DISTINCT FROM 'done'")
    env = api.Environment(cr, SUPERUSER_ID, {})
    upcoming = env["carwash.appointment"].search([("state", "in", ("draft", "confirmed")), ("checklist_line_ids", "=", False)])
    upcoming._checklist_auto_apply()
