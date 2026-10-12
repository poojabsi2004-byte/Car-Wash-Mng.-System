from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    carwash_unit_cost = fields.Float(
        string="Unit Cost", digits="Product Price", readonly=True, copy=False,
        help="Cost of the consumable when it was used (average purchase cost).",
    )
    carwash_cost = fields.Float(
        string="Cost", compute="_compute_carwash_cost", store=True, digits="Product Price",
        help="Quantity used x unit cost.",
    )

    @api.depends("quantity", "carwash_unit_cost")
    def _compute_carwash_cost(self):
        for move in self:
            move.carwash_cost = move.quantity * move.carwash_unit_cost

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        # what a wash / a consumable request used is costed at the time it is used
        for move in moves.filtered(lambda m: m.state == "done" and (m.carwash_appointment_id or m.carwash_consumable_request_id)):
            move.carwash_unit_cost = move.product_id.with_company(move.company_id).standard_price
        return moves
