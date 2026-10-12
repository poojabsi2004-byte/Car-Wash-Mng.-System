from odoo import fields, models


class CarwashBay(models.Model):
    _inherit = "carwash.bay"

    carwash_purchase_ids = fields.One2many("purchase.order", "carwash_bay_id", string="Purchases")
    carwash_purchase_count = fields.Integer(compute="_compute_carwash_maintenance", string="Purchases Count")
    carwash_maintenance_cost = fields.Monetary(
        compute="_compute_carwash_maintenance", string="Maintenance Cost", currency_field="carwash_currency_id",
        help="Confirmed purchases for this bay (repairs, spare parts, equipment), without taxes.",
    )
    carwash_currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")

    def _compute_carwash_maintenance(self):
        for bay in self:
            orders = bay.sudo().carwash_purchase_ids.filtered(lambda o: o.state != "cancel")
            bay.carwash_purchase_count = len(orders)
            bay.carwash_maintenance_cost = sum(orders.filtered(lambda o: o.state in ("purchase", "done")).mapped("amount_untaxed"))

    def action_carwash_order_repair(self):
        """Order Repair / Parts: a new RFQ for this bay (a maintenance service to start with)."""
        self.ensure_one()
        service = self.env.ref("carwash_purchase.product_bay_maintenance", raise_if_not_found=False)
        context = {
            "default_carwash_bay_id": self.id,
            "default_company_id": (self.company_id or self.env.company).id,
            "default_origin": self.name,
        }
        if service:
            context["default_order_line"] = [
                (0, 0, {"product_id": service.id, "product_qty": 1, "product_uom_id": service.uom_id.id})
            ]
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Order Repair / Parts"),
            "res_model": "purchase.order",
            "view_mode": "form",
            "views": [(False, "form")],
            "context": context,
        }

    def action_carwash_view_purchases(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_purchase.action_carwash_purchase_all")
        action["domain"] = [("carwash_bay_id", "=", self.id)]
        action["context"] = {"default_carwash_bay_id": self.id}
        return action
