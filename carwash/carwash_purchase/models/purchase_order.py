from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .product import SUPPLY_TYPES

PAYMENT_STATES = [
    ("not_billed", "Not Billed"),
    ("to_pay", "To Pay"),
    ("partial", "Partially Paid"),
    ("paid", "Paid"),
]


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    carwash_bay_id = fields.Many2one(
        "carwash.bay", string="For Bay", tracking=True, index="btree_not_null",
        domain="[('company_id', 'in', (company_id, False))]",
        help="Bay this purchase is for: a repair, spare parts or equipment of that bay (its maintenance cost).",
    )
    carwash_request_id = fields.Many2one(
        "carwash.consumable.request", string="Consumable Request", readonly=True, copy=False, index="btree_not_null",
        help="Consumable request that was short of stock - its requester is told when the goods arrive.",
    )
    carwash_supply_type = fields.Selection(
        SUPPLY_TYPES + [("mixed", "Mixed")], string="Purchase For", compute="_compute_carwash_supply_type", store=True,
    )
    carwash_payment_state = fields.Selection(
        PAYMENT_STATES, string="Payment Status", compute="_compute_carwash_payment_state",
    )

    @api.depends("order_line.product_id.product_tmpl_id.carwash_supply_type")
    def _compute_carwash_supply_type(self):
        for order in self:
            types = set(order.order_line.product_id.product_tmpl_id.mapped("carwash_supply_type")) - {False}
            order.carwash_supply_type = (types.pop() if len(types) == 1 else "mixed") if types else False

    @api.depends("invoice_ids.payment_state", "invoice_ids.state")
    def _compute_carwash_payment_state(self):
        for order in self:
            bills = order.invoice_ids.filtered(lambda m: m.state == "posted" and m.move_type == "in_invoice")
            if not bills:
                order.carwash_payment_state = "not_billed"
            elif all(b.payment_state in ("paid", "in_payment", "reversed") for b in bills):
                order.carwash_payment_state = "paid"
            elif any(b.payment_state in ("partial", "paid", "in_payment") for b in bills):
                order.carwash_payment_state = "partial"
            else:
                order.carwash_payment_state = "to_pay"

    # ------------------------------------------------------------------
    # Approval: above the branch's amount a Manager / Owner approves
    # ------------------------------------------------------------------
    def _carwash_needs_approval(self):
        """Above the branch's approval amount (Settings > Purchase Approval)."""
        self.ensure_one()
        company = self.company_id
        if company.po_double_validation != "two_step":
            return False
        limit = self.env.company.currency_id._convert(
            company.po_double_validation_amount, self.currency_id, company, self.date_order or fields.Date.today())
        return self.amount_total >= limit

    def _approval_allowed(self):
        """Above the approval amount every order waits in To Approve when it is confirmed - also one raised by a
        Manager (Odoo would let a purchase manager skip it) - until a Car Wash Manager / Owner approves it."""
        self.ensure_one()
        if not self._carwash_needs_approval():
            return True
        if self.env.context.get("carwash_confirming"):
            return False
        return self.env.su or self.env.user.has_group("purchase.group_purchase_manager")

    def button_confirm(self):
        res = super(PurchaseOrder, self.with_context(carwash_confirming=True)).button_confirm()
        self.filtered(lambda o: o.state == "to approve")._carwash_ask_approval()
        return res

    def _carwash_approvers(self):
        """Car Wash Managers / Owners of the order's branch (they approve purchase orders)."""
        self.ensure_one()
        group = self.env.ref("purchase.group_purchase_manager")
        return group.sudo().all_user_ids.filtered(
            lambda u: self.company_id in u.company_ids and not u.share and u.active
            and u.has_group("carwash_base.group_carwash_manager")
        )

    def _carwash_ask_approval(self):
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for order in self:
            for approver in order._carwash_approvers()[:3]:
                if approver == self.env.user:
                    continue
                order.sudo().activity_schedule(
                    activity_type_id=todo.id if todo else False,
                    summary=self.env._("Approve purchase order"),
                    note=self.env._(
                        "%(order)s for %(supplier)s: %(amount)s - above the approval amount of %(branch)s.",
                        order=order.name, supplier=order.partner_id.display_name,
                        amount=order.currency_id.format(order.amount_total), branch=order.company_id.name,
                    ),
                    user_id=approver.id,
                )

    def button_approve(self, force=False):
        refused = self.filtered(lambda o: o.state == "to approve" and not o._approval_allowed())
        if refused:
            raise UserError(self.env._(
                "Only a Car Wash Manager or the Owner can approve %s.", ", ".join(refused.mapped("name"))))
        res = super().button_approve(force=force)
        summary = self.env._("Approve purchase order")
        for order in self:
            order.sudo().activity_ids.filtered(lambda a: a.summary == summary).action_feedback(
                feedback=self.env._("Approved by %s", self.env.user.name)
            )
        return res

    # ------------------------------------------------------------------
    # Printouts (car wash letterhead)
    # ------------------------------------------------------------------
    def print_quotation(self):
        self.filtered(lambda o: o.state == "draft").write({"state": "sent"})
        return self.env.ref("carwash_purchase.action_report_carwash_rfq").report_action(self)

    def _carwash_report_lines(self):
        return self.order_line.filtered(lambda l: not l.display_type)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    @api.model
    def _carwash_new_rfq_action(self, company, lines, origin=False, request=False):
        """A new RFQ (not saved yet) with these [(product, quantity)] lines - for products without a vendor price:
        the user picks the vendor and saves. Confirming it adds the vendor to the product's vendor prices, so the
        next time it is ordered automatically."""
        order_lines = []
        for product, quantity in lines:
            vals = {"product_id": product.id, "product_qty": quantity, "product_uom_id": product.uom_id.id}
            if product.standard_price:
                vals["price_unit"] = product.standard_price  # lines given as defaults aren't priced by the form
            order_lines.append((0, 0, vals))
        context = {"default_company_id": company.id, "default_order_line": order_lines}
        if origin:
            context["default_origin"] = origin
        if request:
            context["default_carwash_request_id"] = request.id
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Request for Quotation"),
            "res_model": "purchase.order",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
            "context": context,
        }

    @api.model
    def _carwash_low_stock_lines(self, products, company):
        """[(product, quantity to order)] to bring low-stock products back up (to Reorder Up To, else the minimum)."""
        warehouse = company._carwash_warehouse()
        lines = []
        for product in products:
            orderpoint = product._carwash_orderpoint(warehouse) if warehouse else False
            target = max(orderpoint.product_max_qty, orderpoint.product_min_qty) if orderpoint else 0.0
            on_hand = product.sudo().with_context(warehouse_id=warehouse.id).qty_available if warehouse else 0.0
            lines.append((product, max(target - on_hand, 1.0)))
        return lines

    def _carwash_rfq_result_action(self, orders, missing_products=None):
        """Open the RFQs just created (or say there was nothing to order); products without a vendor price get a
        new RFQ prefilled with them, where the vendor is chosen."""
        missing_products = missing_products or self.env["product.product"]
        if orders:
            action = self.env["ir.actions.act_window"]._for_xml_id("carwash_purchase.action_carwash_rfq")
            action["domain"] = [("id", "in", orders.ids)]
            action["context"] = {}
            if len(orders) == 1:
                action.update(res_id=orders.id, view_mode="form", views=[(False, "form")])
        else:
            action = False
        if missing_products:
            company = self.env.company
            action = self._carwash_new_rfq_action(company, self._carwash_low_stock_lines(missing_products, company))
        if missing_products or not orders:
            message = (
                self.env._("No vendor price yet for: %s - choose the vendor on the new RFQ (confirming it remembers "
                           "the vendor for next time).", ", ".join(missing_products.mapped("display_name")))
                if missing_products else self.env._("Nothing to order: no consumable is below its minimum stock.")
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Low stock"),
                    "message": message,
                    "type": "warning" if missing_products else "info",
                    "sticky": bool(missing_products),
                    "next": action or {"type": "ir.actions.act_window_close"},
                },
            }
        return action

    @api.model
    def _cron_carwash_purchase_followup(self):
        """Daily: To-Dos for late deliveries (to the buyer / branch managers) and for vendor bills due within
        3 days or overdue (to the branch managers)."""
        if not self.env["carwash.feature"]._enabled("carwash_purchase.group_carwash_purchase"):
            return
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        today = fields.Date.context_today(self)
        late_summary = self.env._("Delivery late")
        late_orders = self.search([
            ("state", "=", "purchase"), ("receipt_status", "in", ("pending", "partial")),
            ("date_planned", "<", fields.Datetime.to_datetime(today)),
        ])
        for order in late_orders:
            if order.activity_ids.filtered(lambda a: a.summary == late_summary):
                continue
            users = order.user_id or order._carwash_approvers()[:1]
            for user in users:
                order.activity_schedule(
                    activity_type_id=todo.id if todo else False, summary=late_summary, user_id=user.id,
                    note=self.env._("%(supplier)s was expected to deliver on %(date)s - follow up or receive the goods.",
                                    supplier=order.partner_id.display_name, date=order.date_planned.date()),
                )
        due_summary = self.env._("Pay supplier bill")
        bills = self.env["account.move"].search([
            ("move_type", "=", "in_invoice"), ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")), ("invoice_date_due", "<=", today + timedelta(days=3)),
            ("invoice_line_ids.purchase_line_id", "!=", False),
        ])
        manager_group = self.env.ref("carwash_base.group_carwash_manager")
        for bill in bills:
            if bill.activity_ids.filtered(lambda a: a.summary == due_summary):
                continue
            managers = manager_group.all_user_ids.filtered(
                lambda u: bill.company_id in u.company_ids and not u.share and u.active
            )
            for manager in managers[:1]:
                bill.activity_schedule(
                    activity_type_id=todo.id if todo else False, summary=due_summary, user_id=manager.id,
                    date_deadline=bill.invoice_date_due,
                    note=self.env._("%(supplier)s: %(amount)s due on %(date)s.", supplier=bill.partner_id.display_name,
                                    amount=bill.currency_id.format(bill.amount_residual), date=bill.invoice_date_due),
                )
