from odoo import fields, models


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    carwash_consumable_cost = fields.Monetary(
        compute="_compute_carwash_consumable_cost", string="Consumables Cost", currency_field="carwash_currency_id",
        help="Cost of the consumables this booking used (quantity x average purchase cost when used).",
    )

    carwash_currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")

    def _compute_carwash_consumable_cost(self):
        for appointment in self:
            moves = appointment.sudo().stock_move_ids.filtered(lambda m: m.state == "done")
            appointment.carwash_consumable_cost = sum(moves.mapped("carwash_cost"))

    def _carwash_book_out(self, items):
        moves = super()._carwash_book_out(items)
        self.company_id._carwash_auto_replenish()
        return moves
