from odoo import api, fields, models

USAGE_TYPES = [
    ("service", "Service (booking)"),
    ("issue", "Floor Issue"),
    ("wastage", "Wastage / Damage"),
    ("return", "Return to Store"),
]


class StockMove(models.Model):
    _inherit = "stock.move"

    carwash_consumable_request_id = fields.Many2one(
        "carwash.consumable.request", string="Consumable Request", ondelete="set null", index="btree_not_null"
    )
    carwash_usage_type = fields.Selection(
        USAGE_TYPES, string="Car Wash Usage", compute="_compute_carwash_usage_type", store=True, index="btree_not_null"
    )

    @api.depends("carwash_appointment_id", "carwash_consumable_request_id.request_type")
    def _compute_carwash_usage_type(self):
        for move in self:
            if move.carwash_appointment_id:
                move.carwash_usage_type = "service"
            else:
                move.carwash_usage_type = move.carwash_consumable_request_id.request_type or False
