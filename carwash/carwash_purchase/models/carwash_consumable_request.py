from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class CarwashConsumableRequest(models.Model):
    _inherit = "carwash.consumable.request"

    carwash_purchase_ids = fields.One2many("purchase.order", "carwash_request_id", string="Purchases")
    carwash_purchase_count = fields.Integer(compute="_compute_carwash_purchase_count", string="Purchases Count")

    def _compute_carwash_purchase_count(self):
        for request in self:
            request.carwash_purchase_count = len(request.sudo().carwash_purchase_ids)

    def _carwash_shortage(self):
        """[(product, quantity missing at the branch)] for a floor issue that is short of stock."""
        self.ensure_one()
        warehouse = self.company_id._carwash_warehouse()
        shortage = []
        for line in self.line_ids:
            product = line.product_id
            available = product.sudo().with_context(warehouse_id=warehouse.id).qty_available if warehouse else 0.0
            needed = line.uom_id._compute_quantity(line.quantity, product.uom_id)
            if float_compare(needed, available, precision_rounding=product.uom_id.rounding) > 0:
                shortage.append((product, needed - max(available, 0.0)))
        return shortage

    def action_carwash_request_purchase(self):
        """Request Purchase: RFQs (one per vendor) for what the branch is missing to issue this request. Products
        without a vendor price open a new RFQ prefilled with them, where the vendor is chosen."""
        if not self.env.user.has_group("purchase.group_purchase_user"):
            raise UserError(self.env._("You aren't allowed to create purchases."))
        PurchaseOrder = self.env["purchase.order"]
        orders = PurchaseOrder
        no_vendor = {}  # request -> [(product, quantity)] without a vendor price
        for request in self:
            if request.request_type != "issue" or request.state not in ("submitted", "approved"):
                raise UserError(self.env._("Only a submitted or approved floor issue can request a purchase."))
            shortage = request._carwash_shortage()
            if not shortage:
                raise UserError(self.env._("%s: everything is in stock - it can be issued.", request.name))
            by_supplier = {}
            for product, quantity in shortage:
                seller = product._carwash_seller(request.company_id)
                if not seller:
                    no_vendor.setdefault(request, []).append((product, quantity))
                    continue
                by_supplier.setdefault(seller.partner_id, []).append((product, max(quantity, seller.min_qty)))
            if len(no_vendor) > 1:
                raise UserError(self.env._(
                    "Several requests have products without a vendor price - request their purchase one by one."))
            for supplier, lines in by_supplier.items():
                orders |= self.env["purchase.order"].with_company(request.company_id).create({
                    "partner_id": supplier.id,
                    "company_id": request.company_id.id,
                    "origin": request.name,
                    "carwash_request_id": request.id,
                    "order_line": [(0, 0, {"product_id": product.id, "product_qty": qty}) for product, qty in lines],
                })
            mine = orders.filtered(lambda o: o.carwash_request_id == request)
            if mine:
                request.message_post(body=self.env._(
                    "Purchase requested for the missing stock: %s", ", ".join(mine.mapped("name"))))
        if not no_vendor:
            return PurchaseOrder._carwash_rfq_result_action(orders)
        # the products without a vendor price: a new RFQ with them, the vendor is picked on it
        request, lines = next(iter(no_vendor.items()))
        new_rfq = PurchaseOrder._carwash_new_rfq_action(request.company_id, lines, origin=request.name, request=request)
        if not orders:
            return new_rfq
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Purchase requested"),
                "message": self.env._(
                    "RFQ %(orders)s created. No vendor price yet for %(products)s - choose the vendor on the new RFQ.",
                    orders=", ".join(orders.mapped("name")),
                    products=", ".join(product.display_name for product, _qty in lines),
                ),
                "type": "info",
                "sticky": False,
                "next": new_rfq,
            },
        }

    def action_carwash_view_purchases(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_purchase.action_carwash_purchase_all")
        action["domain"] = [("carwash_request_id", "=", self.id)]
        action["context"] = {}
        return action

    def _carwash_goods_received(self, picking):
        """Goods ordered for this request arrived: tell the requester and the managers it can be issued."""
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for request in self.sudo():
            request.message_post(body=self.env._(
                "Goods received (%(receipt)s from %(supplier)s) - the request can be issued now.",
                receipt=picking.name, supplier=picking.partner_id.display_name,
            ))
            if request.state in ("submitted", "approved"):
                request.activity_schedule(
                    activity_type_id=todo.id if todo else False,
                    summary=self.env._("Goods received - issue the request"),
                    user_id=request.requested_by_id.id,
                )

    def action_issue(self):
        res = super().action_issue()
        self.company_id._carwash_auto_replenish()
        return res
