from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Every branch gets its code (made from its name) - its own numbering starts from the next document."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env["res.company"].search([("carwash_code", "=", False)], order="id"):
        company._carwash_branch_code()
