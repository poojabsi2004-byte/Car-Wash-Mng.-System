from odoo import Command, api, fields, models
from odoo.exceptions import UserError

# how far the customer's billing of a booking is
CARWASH_PAYMENT_STATES = [
    ("no_order", "Not Billed"),
    ("quotation", "Quotation"),
    ("to_invoice", "To Invoice"),
    ("not_paid", "Not Paid"),
    ("partial", "Partially Paid"),
    ("paid", "Paid"),
]
# booking line fields that change what the customer is charged
CARWASH_BILLED_LINE_FIELDS = {"product_id", "quantity", "price_unit", "description"}


class CarwashAppointment(models.Model):
    """Customer billing of a booking, the standard Sales / Invoicing way:

    Confirmed      -> a quotation for its services (kept in line with the Services tab while it's a quotation)
    Work passed QC -> (all its job cards, see carwash_jobcard) or Done: Create Invoice / Register Payment on the
                      booking (Register Payment confirms the order and invoices first when needed). The customer
                      can also pay the invoice online from its Pay Now link (payment providers, e.g. Demo).
    Services added / changed once the order is confirmed go on the order (not invoiced yet: updated).
    """

    _inherit = "carwash.appointment"

    currency_id = fields.Many2one(related="company_id.currency_id", string="Booking Currency")
    invoice_ids = fields.Many2many(
        "account.move", compute="_compute_carwash_billing", compute_sudo=True, string="Invoices",
    )
    invoice_count = fields.Integer(compute="_compute_carwash_billing", compute_sudo=True, string="Invoice Count")
    customer_payment_ids = fields.Many2many(
        "account.payment", compute="_compute_carwash_billing", compute_sudo=True, string="Customer Payments",
        help="Payments received for this booking's invoices (cash at the counter, online...).",
    )
    amount_billed = fields.Monetary(
        compute="_compute_carwash_billing", compute_sudo=True, string="Customer Total", currency_field="currency_id",
        help="What the customer is charged, taxes included: the invoices plus what is still to invoice.",
    )
    amount_paid = fields.Monetary(
        compute="_compute_carwash_billing", compute_sudo=True, string="Customer Paid", currency_field="currency_id",
    )
    amount_due = fields.Monetary(
        compute="_compute_carwash_billing", compute_sudo=True, string="Amount Due", currency_field="currency_id",
        help="Still to be paid by the customer (open invoices + what is still to invoice).",
    )
    amount_to_invoice = fields.Monetary(
        compute="_compute_carwash_billing", compute_sudo=True, string="To Invoice", currency_field="currency_id",
    )
    payment_state = fields.Selection(
        CARWASH_PAYMENT_STATES, compute="_compute_carwash_billing", compute_sudo=True, string="Payment",
        help="Quotation while the booking runs; once done: To Invoice, Not Paid, Partially Paid or Paid.",
    )
    can_bill = fields.Boolean(
        compute="_compute_can_bill", string="Can Be Billed",
        help="The customer can be invoiced and take the payment: the booking is done (or its work passed QC).",
    )

    def _compute_can_bill(self):
        for booking in self:
            booking.can_bill = booking._carwash_can_bill()

    def _carwash_can_bill(self):
        """Invoice / payment allowed (carwash_jobcard: also once every job card passed QC)."""
        self.ensure_one()
        return self.state == "done"

    # compute_sudo: the billing is worked out from the booking's quotation / invoices / payments, which washers and
    # QC inspectors can't read - they open the booking (its header checks the payment status) and only see the
    # status; the Payments tab with the invoices is for the front desk and managers.
    @api.depends("sale_order_id.state", "sale_order_id.invoice_ids.state", "sale_order_id.invoice_ids.amount_residual",
                 "sale_order_id.amount_to_invoice")
    def _compute_carwash_billing(self):
        for booking in self:
            # sudo: the front desk sees the booking's billing without Sales rights
            order = booking.sudo().sale_order_id
            invoices = order.invoice_ids.filtered(lambda m: m.state == "posted")
            to_invoice = order.amount_to_invoice if order.state == "sale" else 0.0
            billed = sum(invoices.mapped("amount_total_signed")) + to_invoice
            due = sum(invoices.mapped("amount_residual_signed")) + to_invoice
            currency = booking.company_id.currency_id
            booking.invoice_ids = invoices
            booking.invoice_count = len(invoices)
            booking.customer_payment_ids = invoices._get_reconciled_payments()
            booking.amount_to_invoice = to_invoice
            booking.amount_billed = billed
            booking.amount_due = due
            booking.amount_paid = billed - due
            if not order or order.state == "cancel":
                state = "no_order"
            elif order.state in ("draft", "sent"):
                state = "quotation"
            elif not invoices:
                state = "to_invoice" if not currency.is_zero(to_invoice) else "paid"
            elif currency.is_zero(due) or due < 0:
                state = "paid"
            elif currency.is_zero(billed - due):
                state = "not_paid"
            else:
                state = "partial"
            booking.payment_state = state

    # ------------------------------------------------------------------ quotation -> sales order
    def _carwash_order_line_vals(self):
        self.ensure_one()
        return [line._carwash_sale_line_vals() for line in self.line_ids.filtered("product_id")]

    def _carwash_create_quotation(self):
        """The booking's quotation (draft sales order), created once."""
        for booking in self.filtered(lambda b: not b.sale_order_id):
            # sudo: front desk / website bookings create it without Sales rights
            order = self.env["sale.order"].sudo().create({
                "partner_id": booking.customer_id.id,
                "company_id": booking.company_id.id,
                # the booking already has its prices (membership, packages): no pricelist, so the order is
                # in the branch's currency whatever the customer's pricelist currency is
                "pricelist_id": False,
                "origin": booking.name,
                "order_line": [Command.create(vals) for vals in booking._carwash_order_line_vals()],
            })
            booking.sale_order_id = order.id

    def _carwash_sync_quotation(self):
        """While it's a quotation, the order follows the Services tab (services, quantities, prices)."""
        for booking in self:
            order = booking.sudo().sale_order_id
            if order and order.state in ("draft", "sent"):
                order.order_line = [Command.clear()] + [
                    Command.create(vals) for vals in booking._carwash_order_line_vals()
                ]

    def _carwash_confirm_sale_order(self):
        """Booking done: its quotation (created now for older bookings) becomes the sales order."""
        for booking in self:
            if not booking.sale_order_id:
                booking._carwash_create_quotation()
            else:
                booking._carwash_sync_quotation()
            order = booking.sudo().sale_order_id
            if order.state in ("draft", "sent"):
                order.action_confirm()

    def _create_and_confirm_sale_order(self):
        # kept for callers of the former name
        self._carwash_confirm_sale_order()

    def action_confirm(self):
        res = super().action_confirm()
        self.filtered(lambda b: b.state == "confirmed")._carwash_create_quotation()
        return res

    def _carwash_cancel_quotation(self):
        orders = self.sudo().sale_order_id.filtered(lambda o: o.state in ("draft", "sent"))
        if orders:
            orders._action_cancel()

    def action_cancel(self):
        res = super().action_cancel()
        self._carwash_cancel_quotation()
        return res

    def action_no_show(self):
        res = super().action_no_show()
        self._carwash_cancel_quotation()
        return res

    # ------------------------------------------------------------------ invoice + payment
    def _carwash_check_billable(self):
        for booking in self:
            if not booking._carwash_can_bill():
                raise UserError(self.env._(
                    "Booking %s is invoiced and paid once its service has ended (End Service) or the booking is done.",
                    booking.name))

    def _carwash_create_invoices(self):
        """Invoice (and post) what the booking's sales order still has to invoice."""
        self._carwash_check_billable()
        invoices = self.env["account.move"]
        for booking in self:
            booking._carwash_confirm_sale_order()
            order = booking.sudo().sale_order_id
            if order.invoice_status == "to invoice":
                new = order._create_invoices()
                new.action_post()
                invoices |= new
        return invoices

    def action_create_invoice(self):
        invoices = self._carwash_create_invoices()
        if not invoices:
            raise UserError(self.env._("There is nothing left to invoice on this booking."))
        for booking in self:
            booking.message_post(body=self.env._(
                "Invoice %s created.", ", ".join(invoices.filtered(lambda m: m in booking.invoice_ids).mapped("name"))
                or invoices[:1].name,
            ))
        return True

    @api.model
    def _carwash_cash_journal(self, company):
        """The company's Cash journal (created when there is none)."""
        Journal = self.env["account.journal"].sudo()
        journal = Journal.search([("type", "=", "cash"), *Journal._check_company_domain(company)], limit=1)
        if not journal:
            root = company.root_id
            code = "CSH"
            number = 1
            while Journal.search_count([("code", "=", code), ("company_id", "=", root.id)]):
                number += 1
                code = f"CSH{number}"
            journal = Journal.create({"name": self.env._("Cash"), "type": "cash", "code": code, "company_id": root.id})
        return journal

    def action_register_payment(self):
        """Take the customer's payment: invoices first if needed, then Odoo's Register Payment (Cash by default)."""
        self.ensure_one()
        self._carwash_create_invoices()
        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type == "out_invoice" and m.payment_state not in ("paid", "in_payment", "reversed")
        )
        if not invoices:
            raise UserError(self.env._("Booking %s is already paid.", self.name))
        action = invoices.action_register_payment()
        action["context"] = dict(
            action.get("context", {}),
            default_journal_id=self._carwash_cash_journal(self.company_id).id,
        )
        return action

    def action_send_invoice(self):
        """Email the invoice to the customer - its Pay Now link lets them pay online."""
        self.ensure_one()
        self._carwash_create_invoices()
        invoices = self.invoice_ids.filtered(lambda m: m.move_type == "out_invoice")
        if not invoices:
            raise UserError(self.env._("There is no invoice to send."))
        return invoices[-1:].action_send_and_print()

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_move_out_invoice_type")
        action.update({"domain": [("id", "in", self.invoice_ids.ids)], "context": {"default_move_type": "out_invoice"}})
        if len(self.invoice_ids) == 1:
            action.update({"views": [(False, "form")], "view_mode": "form", "res_id": self.invoice_ids.id})
        return action


class CarwashAppointmentLine(models.Model):
    _inherit = "carwash.appointment.line"

    def _carwash_sale_line_vals(self):
        self.ensure_one()
        return dict(
            {
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity,
                "price_unit": self.price_unit,
                "carwash_appointment_line_id": self.id,
            },
            # keep the booking line's wording (e.g. which package it belongs to)
            **({"name": self.description} if self.description else {}),
        )

    def _carwash_sale_lines(self, states=("sale",)):
        return self.env["sale.order.line"].sudo().search([
            ("carwash_appointment_line_id", "in", self.ids), ("order_id.state", "in", list(states)),
        ])

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.appointment_id._carwash_sync_quotation()
        # a service added once the order is confirmed (e.g. paid already, extras) goes on the order too
        for line in lines.filtered("product_id"):
            order = line.appointment_id.sudo().sale_order_id
            if order.state == "sale":
                order.order_line = [Command.create(line._carwash_sale_line_vals())]
        return lines

    def write(self, vals):
        res = super().write(vals)
        if CARWASH_BILLED_LINE_FIELDS & set(vals):
            self.appointment_id._carwash_sync_quotation()
            for sale_line in self._carwash_sale_lines().filtered(lambda sl: not sl.qty_invoiced):
                line = sale_line.carwash_appointment_line_id
                vals_sale = {"product_uom_qty": line.quantity, "price_unit": line.price_unit}
                if line.description:
                    vals_sale["name"] = line.description
                sale_line.write(vals_sale)
        return res

    def unlink(self):
        bookings = self.appointment_id
        confirmed = self._carwash_sale_lines()
        res = super().unlink()
        bookings.exists()._carwash_sync_quotation()
        # a removed service that wasn't invoiced yet isn't charged any more
        confirmed.exists().filtered(lambda sl: not sl.qty_invoiced).write({"product_uom_qty": 0.0})
        return res


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    carwash_appointment_line_id = fields.Many2one(
        "carwash.appointment.line", string="Booking Service", ondelete="set null", copy=False, index="btree_not_null",
    )
