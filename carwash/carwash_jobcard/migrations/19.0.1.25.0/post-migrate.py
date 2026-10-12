# Job cards get a Consumption tab: existing job cards (not cancelled) are filled in from their
# services' consumables, so completing their booking keeps booking the same quantities out of stock.
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    jobcards = env["carwash.jobcard"].with_context(active_test=False).search([("stages", "!=", "cancel")])
    jobcards._fill_consumption()
