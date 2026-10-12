from odoo import SUPERUSER_ID, api, models


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    @api.model_create_multi
    def create(self, vals_list):
        orderpoints = super().create(vals_list)
        orderpoints.filtered(lambda op: op.product_id.is_carwash_consumable)._carwash_sync()
        return orderpoints

    def _carwash_sync(self):
        """A consumable's minimum-stock rule buys from the supplier: Buy route, manual trigger (Create RFQs
        button) or automatic (branch setting), and a reorder-up-to quantity no lower than the minimum."""
        buy = self.env.ref("purchase_stock.route_warehouse0_buy", raise_if_not_found=False)
        for orderpoint in self.sudo():
            vals = {}
            trigger = "auto" if orderpoint.company_id.carwash_auto_rfq else "manual"
            if orderpoint.trigger != trigger:
                vals["trigger"] = trigger
            if buy and orderpoint.route_id != buy:
                vals["route_id"] = buy.id
            if orderpoint.product_max_qty < orderpoint.product_min_qty:
                vals["product_max_qty"] = orderpoint.product_min_qty
            if vals:
                orderpoint.write(vals)

    def _unlink_processed_orderpoints(self):
        """Odoo removes the manual reordering rules made by the system once nothing is to order (one-off
        suggestions of the replenishment report). A car wash consumable's minimum stock is a standing rule:
        it is kept."""
        candidates = self if self.ids else self.with_context(active_test=False).search(
            [("create_uid", "=", SUPERUSER_ID), ("trigger", "=", "manual")]
        )
        others = candidates.filtered(lambda op: not op.product_id.is_carwash_consumable)
        if not others:
            return self.browse()
        return super(StockWarehouseOrderpoint, others)._unlink_processed_orderpoints()

