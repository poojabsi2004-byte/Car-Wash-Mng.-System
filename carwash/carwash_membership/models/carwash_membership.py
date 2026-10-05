from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

BILLING_PERIOD_DELTA = {
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
    "yearly": relativedelta(years=1),
}
# Renewal orders are raised this many days before the paid period ends.
RENEWAL_LEAD_DAYS = 3


class CarwashMembership(models.Model):
    """A customer's subscription to a plan.

    Lifecycle: Pending (waiting for the first payment) -> Active (a paid billing period is
    running) -> Expired (the period ended without the renewal being paid) / Cancelled.
    Every billing period is a standard Sales Order; the membership activates/extends only
    once that order is paid - online (portal "Pay Now" -> payment.transaction) or in the
    backend (invoice registered as paid).
    """

    _name = "carwash.membership"
    _description = "Car Wash Membership"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, tracking=True, index=True)
    plan_id = fields.Many2one("carwash.membership.plan", string="Plan", required=True, tracking=True)
    state = fields.Selection(
        [("pending", "Pending Payment"), ("active", "Active"), ("expired", "Expired"), ("cancelled", "Cancelled")],
        default="pending",
        tracking=True,
        group_expand="_expand_states",
    )
    start_date = fields.Date(tracking=True, readonly=True, help="Day the first payment activated the membership.")
    period_start = fields.Date(readonly=True, help="First day of the current billing period.")
    valid_until = fields.Date(tracking=True, readonly=True, help="Last day of the current billing period.")
    paid_until = fields.Date(readonly=True, help="Last day covered by payments (later than Valid Until when a renewal was paid early).")
    next_billing_date = fields.Date(tracking=True, readonly=True)
    washes_used = fields.Integer(default=0, help="Covered (free) washes used in the current billing period.")
    wash_allowance = fields.Integer(related="plan_id.wash_allowance", readonly=True)
    washes_reserved = fields.Integer(compute="_compute_washes", string="Washes Booked",
                                     help="Upcoming bookings that already use a free wash.")
    washes_remaining = fields.Integer(compute="_compute_washes", string="Free Washes Left",
                                      help="-1 means unlimited.")
    discount_percent = fields.Float(related="plan_id.discount_percent")
    sale_order_ids = fields.One2many("sale.order", "carwash_membership_id", string="Billing History")
    sale_order_count = fields.Integer(compute="_compute_sale_order_count")
    pending_order_id = fields.Many2one("sale.order", compute="_compute_pending_order_id", string="Awaiting Payment")
    auto_renew = fields.Boolean(
        default=True, tracking=True,
        help="Raise and send the renewal order before the paid period ends. When off, the "
        "membership simply runs until its paid period ends and then expires.",
    )
    appointment_ids = fields.One2many("carwash.appointment", "membership_id", string="Bookings")
    appointment_count = fields.Integer(compute="_compute_appointment_count", string="Bookings")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    @api.depends("washes_used", "wash_allowance")
    def _compute_washes(self):
        reserved = dict(
            self.env["carwash.appointment"]._read_group(
                [
                    ("membership_id", "in", self.ids),
                    ("state", "not in", ("done", "cancelled", "no_show")),
                    ("line_ids.membership_covered", "=", True),
                ],
                ["membership_id"],
                ["__count"],
            )
        )
        for membership in self:
            membership.washes_reserved = reserved.get(membership, 0)
            if not membership.wash_allowance:
                membership.washes_remaining = -1
            else:
                membership.washes_remaining = max(
                    membership.wash_allowance - membership.washes_used - membership.washes_reserved, 0
                )

    @api.depends("appointment_ids")
    def _compute_appointment_count(self):
        for membership in self:
            membership.appointment_count = len(membership.appointment_ids)

    @api.depends("sale_order_ids")
    def _compute_sale_order_count(self):
        for membership in self:
            membership.sale_order_count = len(membership.sale_order_ids)

    @api.depends("sale_order_ids.carwash_membership_paid", "sale_order_ids.state")
    def _compute_pending_order_id(self):
        for membership in self:
            membership.pending_order_id = membership.sale_order_ids.filtered(
                lambda o: not o.carwash_membership_paid and o.state != "cancel"
            ).sorted("id", reverse=True)[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.membership") or "New"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Billing - every period is a Sales Order that has to be paid
    # ------------------------------------------------------------------
    def _get_or_create_billing_order(self):
        """The open (unpaid) billing order of this membership, created if needed."""
        self.ensure_one()
        if self.state == "cancelled":
            raise UserError(self.env._("This membership is cancelled."))
        if self.pending_order_id:
            return self.pending_order_id
        product = self.plan_id.product_id
        order = self.env["sale.order"].sudo().create(
            {
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "carwash_membership_id": self.id,
                "require_payment": True,
                "prepayment_percent": 1.0,
                "order_line": [
                    (0, 0, {
                        "product_id": product.id,
                        "name": self.env._("%(plan)s membership (%(period)s)", plan=self.plan_id.name,
                                           period=dict(self.plan_id._fields["billing_period"].selection)[self.plan_id.billing_period]),
                        "product_uom_qty": 1,
                        "price_unit": product.list_price,
                    })
                ],
            }
        )
        self.message_post(body=self.env._("Billing order %s created - waiting for payment.", order._get_html_link()))
        return order

    def action_request_payment(self):
        """Send the customer the billing order by email; they pay it online from the portal."""
        self.ensure_one()
        order = self._get_or_create_billing_order()
        if order.state == "draft":
            order.with_context(tracking_disable=True).action_quotation_sent()
        template = self.env.ref("carwash_membership.mail_template_membership_payment_request", raise_if_not_found=False)
        if template and self.partner_id.email:
            template.send_mail(self.id, force_send=False)
        self.message_post(body=self.env._("Payment request sent for %s.", order._get_html_link()))
        return True

    def action_create_invoice(self):
        """Backend payment: confirm + invoice the billing order; registering the payment activates it."""
        self.ensure_one()
        order = self._get_or_create_billing_order()
        if order.state in ("draft", "sent"):
            order.action_confirm()
        invoice = order.invoice_ids.filtered(lambda m: m.state != "cancel")[:1]
        if not invoice:
            invoice = order._create_invoices()
        if invoice.state == "draft":
            invoice.action_post()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": invoice.id,
        }

    def action_view_pending_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.pending_order_id.id,
        }

    def _register_paid_order(self, order):
        """`order` (one of this membership's billing orders) has been paid: start / extend the period."""
        self.ensure_one()
        if order.carwash_membership_paid or self.state == "cancelled":
            return
        order.sudo().carwash_membership_paid = True
        today = fields.Date.context_today(self)
        period = BILLING_PERIOD_DELTA[self.plan_id.billing_period]
        renewing = self.state == "active" and self.paid_until and self.paid_until >= today
        if renewing:
            # paid ahead: the current period (and its free-wash count) runs on, the next one is secured
            paid_until = self.paid_until + period
            vals = {"paid_until": paid_until}
        else:
            paid_until = today + period - relativedelta(days=1)
            vals = {
                "state": "active",
                "start_date": self.start_date or today,
                "period_start": today,
                "valid_until": paid_until,
                "paid_until": paid_until,
                "washes_used": 0,
            }
        vals["next_billing_date"] = paid_until + relativedelta(days=1)
        self.write(vals)
        valid_until = paid_until
        self.partner_id._carwash_sync_member_level()
        self.message_post(
            body=self.env._(
                "Payment received for %(order)s - membership active until %(date)s.",
                order=order._get_html_link(),
                date=valid_until,
            )
        )
        template = self.env.ref("carwash_membership.mail_template_membership_renewed", raise_if_not_found=False)
        if template and self.partner_id.email:
            template.send_mail(self.id, force_send=False)

    def action_cancel(self):
        for membership in self:
            membership.state = "cancelled"
            membership.pending_order_id.filtered(lambda o: o.state in ("draft", "sent")).sudo()._action_cancel()
        self.partner_id._carwash_sync_member_level()

    # kept for the existing "Bill Now" button / external callers
    def action_renew_now(self):
        for membership in self.filtered(lambda m: m.state in ("active", "expired", "pending")):
            membership.action_request_payment()

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Billing History",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("carwash_membership_id", "=", self.id)],
        }

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Bookings: %s", self.name),
            "res_model": "carwash.appointment",
            "view_mode": "list,form",
            "domain": [("membership_id", "=", self.id)],
        }

    def action_toggle_auto_renew(self):
        for membership in self:
            membership.auto_renew = not membership.auto_renew
            membership.message_post(
                body=self.env._("Auto-renewal turned on.") if membership.auto_renew
                else self.env._("Auto-renewal turned off - the membership ends with its paid period.")
            )
        return True

    # ------------------------------------------------------------------
    # Member prices - used to apply the membership on a booking and to
    # preview the member price before booking (website, booking requests)
    # ------------------------------------------------------------------
    def _member_discount_price(self, product, price_unit, quantity=1.0):
        """Member price of a non-free service: Odoo's member-level pricelist for catalogue-priced
        lines, the same % on lines with a special price (e.g. package prices)."""
        self.ensure_one()
        pricelist = self.plan_id.pricelist_id
        if pricelist and price_unit == product.list_price:
            return pricelist._get_product_price(product, quantity or 1.0)
        return price_unit * (1 - self.plan_id.discount_percent / 100.0)

    def _compute_member_prices(self, lines):
        """Member pricing of `lines` - (product, price_unit, quantity) tuples of one booking.

        Covered services are free while the wash allowance lasts (the booking counts as one
        wash), every other service gets the member discount. Returns one dict of booking-line
        values per line, or None where the plan gives no benefit.
        """
        self.ensure_one()
        plan = self.plan_id
        free_wash = self.washes_remaining != 0 and bool(plan.plan_service_ids)
        result = []
        for product, price_unit, quantity in lines:
            if free_wash and product in plan.plan_service_ids:
                result.append({"membership_covered": True, "price_unit": 0.0})
            elif plan.discount_percent:
                result.append({
                    "membership_discount": plan.discount_percent,
                    "price_unit": round(self._member_discount_price(product, price_unit, quantity), 2),
                })
            else:
                result.append(None)
        return result

    def _preview_member_total(self, lines):
        """Normal vs member total of a booking that isn't created yet (same rules as applying it)."""
        self.ensure_one()
        lines = list(lines)
        prices = self._compute_member_prices(lines)
        normal = sum(price_unit * quantity for _product, price_unit, quantity in lines)
        member = sum(
            (vals["price_unit"] if vals else price_unit) * quantity
            for (_product, price_unit, quantity), vals in zip(lines, prices)
        )
        return {
            "normal": round(normal, 2),
            "member": round(member, 2),
            "saving": round(normal - member, 2),
            "has_benefit": any(prices),
            "free_wash": any(vals and vals.get("membership_covered") for vals in prices),
        }

    def _check_usable(self):
        """Raise unless this membership can be used on a booking right now."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.state != "active" or (self.paid_until and self.paid_until < today):
            raise UserError(self.env._("Membership %s isn't active - it can't be used on a booking.", self.name))

    @api.model
    def _cron_process_membership_billing(self):
        today = fields.Date.context_today(self)
        # 1. raise the renewal order a few days before the paid period ends
        due = self.search(
            [("state", "=", "active"), ("next_billing_date", "<=", today + relativedelta(days=RENEWAL_LEAD_DAYS))]
        )
        for membership in due.filtered(lambda m: m.auto_renew and not m.pending_order_id):
            membership.action_request_payment()
        # 2. period over and the next one already paid -> roll over (free washes reset)
        for membership in self.search([("state", "=", "active"), ("valid_until", "<", today), ("paid_until", ">=", today)]):
            period = BILLING_PERIOD_DELTA[membership.plan_id.billing_period]
            start = membership.valid_until + relativedelta(days=1)
            membership.write({"period_start": start, "valid_until": start + period - relativedelta(days=1), "washes_used": 0})
            membership.message_post(body=self.env._("New billing period started - free washes reset."))
        # 3. period over and the renewal wasn't paid -> expired
        lapsed = self.search([("state", "=", "active"), ("paid_until", "<", today)])
        if lapsed:
            lapsed.write({"state": "expired"})
            lapsed.partner_id._carwash_sync_member_level()
            for membership in lapsed:
                membership.message_post(body=self.env._("Membership expired - the renewal wasn't paid in time."))
