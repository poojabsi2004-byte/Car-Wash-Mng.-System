from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_consumable = fields.Boolean(
        "Consumable Management", implied_group="carwash_consumable.group_carwash_consumable",
        help="Branch stock of consumables, requests with approval, low-stock alerts and consumption analysis.",
    )
