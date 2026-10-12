from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_membership = fields.Boolean(
        "Memberships", implied_group="carwash_membership.group_carwash_membership",
        help="Membership plans with free washes and member prices, billed monthly or yearly.",
    )
