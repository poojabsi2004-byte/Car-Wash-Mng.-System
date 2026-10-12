from odoo import fields, models

RETURN_REASONS = [
    ("damaged", "Damaged"),
    ("expired", "Expired"),
    ("wrong", "Wrong Item"),
    ("quality", "Poor Quality"),
    ("excess", "Excess Quantity"),
    ("other", "Other"),
]


class StockPicking(models.Model):
    _inherit = "stock.picking"

    carwash_return_reason = fields.Selection(RETURN_REASONS, string="Return Reason", readonly=True, copy=False)
    carwash_return_note = fields.Char(string="Return Note", readonly=True, copy=False)

    def _action_done(self):
        res = super()._action_done()
        # goods ordered for a consumable request arrived: the request can be issued now
        for picking in self.filtered(lambda p: p.picking_type_code == "incoming" and p.purchase_id.carwash_request_id):
            picking.purchase_id.carwash_request_id._carwash_goods_received(picking)
        return res


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    carwash_return_reason = fields.Selection(RETURN_REASONS, string="Reason")
    carwash_return_note = fields.Char(string="Details")

    def _create_return(self):
        new_picking = super()._create_return()
        if self.carwash_return_reason:
            new_picking.write({
                "carwash_return_reason": self.carwash_return_reason,
                "carwash_return_note": self.carwash_return_note,
            })
            reason = dict(RETURN_REASONS)[self.carwash_return_reason]
            lines = ", ".join(
                f"{line.product_id.display_name} {line.quantity:g} {line.uom_id.name}"
                for line in self.product_return_moves if line.quantity
            )
            body = self.env._("Returned to the supplier (%(reason)s%(note)s): %(lines)s", reason=reason,
                              note=f" - {self.carwash_return_note}" if self.carwash_return_note else "", lines=lines)
            new_picking.message_post(body=body)
            if self.picking_id.purchase_id:
                self.picking_id.purchase_id.message_post(body=body)
        return new_picking
