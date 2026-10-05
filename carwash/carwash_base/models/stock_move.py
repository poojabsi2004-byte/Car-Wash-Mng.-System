from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    carwash_appointment_id = fields.Many2one(
        "carwash.appointment", string="Car Wash Booking", ondelete="set null", index=True
    )
