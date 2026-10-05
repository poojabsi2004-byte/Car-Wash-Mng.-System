from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    carwash_show_packages = fields.Boolean(
        related="website_id.carwash_show_packages", readonly=False,
        string="Show Service Packages on Homepage",
    )
