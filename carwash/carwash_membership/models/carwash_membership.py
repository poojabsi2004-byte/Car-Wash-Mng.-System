from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import consteq, format_date
from odoo.tools.misc import hmac

from .carwash_membership_plan import BILLING_CYCLES

BILLING_PERIOD_DELTA = {
    "monthly": relativedelta(months=1),
    "yearly": relativedelta(years=1),
}
ONE_MONTH = relativedelta(months=1)
ONE_DAY = relativedelta(days=1)


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
    billing_period = fields.Selection(
        BILLING_CYCLES, string="Billing", default="monthly", required=True, tracking=True,
        help="Chosen when joining: the membership runs one month or one year per payment, for the plan's monthly / "
        "yearly amount. Fixed once the membership has been paid.",
    )
    amount = fields.Float(compute="_compute_amount", string="Amount", digits="Product Price",
                          help="Charged for each month / year (from the plan).")
    currency_id = fields.Many2one(related="plan_id.currency_id", string="Currency")
    start_date = fields.Date(string="Start Date", tracking=True, readonly=True,
                             help="Day the membership was activated (its payment received).")
    period_start = fields.Date(readonly=True, help="First day of the current paid month / year.")
    valid_until = fields.Date(string="End Date", tracking=True, readonly=True,
                              help="Last day the membership runs: the start date + 1 month (monthly) or + 1 year (yearly), "
                              "moved on by every renewal paid. The next day it expires unless renewed.")
    paid_until = fields.Date(readonly=True, help="Last day covered by payments (same as the End Date).")
    expiry_date = fields.Date(compute="_compute_expiry_date", string="Expires On",
                              help="The day after the End Date: the membership expires automatically then, unless renewed.")
    next_billing_date = fields.Date(string="Renewal Due", tracking=True, readonly=True)
    wash_period_start = fields.Date(readonly=True, help="First day of the current month of free washes.")
    washes_used = fields.Integer(default=0, help="Covered (free) washes used this month.")
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
        default=False, tracking=True,
        help="Off for a new membership: the customer turns it on with the Auto Renew button of the reminder email "
        "(sent before the end date), on the website, or a manager here. On: the day after the end date the renewal "
        "is invoiced and paid automatically and the membership carries on for another month / year (logged on the "
        "membership). Off: it runs until its end date and then expires.",
    )
    appointment_ids = fields.One2many("carwash.appointment", "membership_id", string="Bookings")
    appointment_count = fields.Integer(compute="_compute_appointment_count", string="Booking Count")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    @api.depends("plan_id.monthly_price", "plan_id.yearly_price", "billing_period")
    def _compute_amount(self):
        for membership in self:
            membership.amount = membership.plan_id._carwash_cycle_price(membership.billing_period) if membership.plan_id else 0.0

    @api.depends("valid_until")
    def _compute_expiry_date(self):
        for membership in self:
            membership.expiry_date = membership.valid_until + relativedelta(days=1) if membership.valid_until else False

    @api.constrains("plan_id", "billing_period")
    def _check_billing_period(self):
        for membership in self.filtered("plan_id"):
            if not membership.plan_id._carwash_cycle_price(membership.billing_period):
                raise ValidationError(self.env._(
                    "The %(plan)s plan isn't offered %(cycle)s - choose another billing.",
                    plan=membership.plan_id.name,
                    cycle=dict(BILLING_CYCLES)[membership.billing_period].lower(),
                ))

    @api.onchange("plan_id")
    def _onchange_plan_billing(self):
        """A plan offered yearly only starts on yearly billing (and vice versa)."""
        for membership in self.filtered("plan_id"):
            cycles = [cycle for cycle, _label, _amount in membership.plan_id._carwash_cycles()]
            if cycles and membership.billing_period not in cycles:
                membership.billing_period = cycles[0]

    def write(self, vals):
        if {"billing_period", "plan_id"} & set(vals) and not self.env.su:
            # fixed once paid (the form shows them read-only); the customer's own website renewal runs as sudo
            paid = self.filtered(lambda m: m.state != "pending")
            if paid:
                raise UserError(self.env._(
                    "The plan and billing of membership %s can't be changed once it has been paid.", paid[0].name
                ))
        res = super().write(vals)
        if {"billing_period", "plan_id"} & set(vals):
            # a payment not made yet follows the new choice
            self._carwash_update_pending_order()
        return res

    def _carwash_update_pending_order(self):
        for membership in self:
            order = membership.sudo().pending_order_id
            if not order or order.state not in ("draft", "sent"):
                continue
            # an order already confirmed / invoiced keeps its own amount and cycle (that's what gets paid)
            line = order.order_line.filtered(lambda l: not l.display_type)[:1]
            if line:
                vals = {"price_unit": membership.amount, "name": membership._carwash_billing_line_name()}
                if line.product_id != membership.plan_id.product_id:
                    vals["product_id"] = membership.plan_id.product_id.id  # the plan was changed
                line.write(vals)
                order.carwash_billing_period = membership.billing_period

    def _carwash_billing_line_name(self):
        self.ensure_one()
        return self.env._("%(plan)s membership (%(period)s)", plan=self.plan_id.name,
                          period=dict(BILLING_CYCLES)[self.billing_period])

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
            if not vals.get("billing_period") and vals.get("plan_id"):
                # the plan's first offered cycle (a plan sold yearly only starts yearly)
                cycles = self.env["carwash.membership.plan"].browse(vals["plan_id"])._carwash_cycles()
                if cycles:
                    vals["billing_period"] = cycles[0][0]
        return super().create(vals_list)

    @api.constrains("partner_id", "state")
    def _check_one_open_membership(self):
        """One running membership per customer: renew / change the existing one instead of adding another."""
        for membership in self.filtered(lambda m: m.state in ("pending", "active")):
            other = self.sudo().search([
                ("id", "!=", membership.id),
                ("partner_id", "=", membership.partner_id.id),
                ("state", "in", ("pending", "active")),
            ], limit=1)
            if other:
                raise ValidationError(self.env._(
                    "%(customer)s already has membership %(other)s (%(state)s) - renew or cancel it instead of adding another one.",
                    customer=membership.partner_id.display_name, other=other.name,
                    state=dict(other._fields["state"]._description_selection(self.env))[other.state],
                ))

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
                "carwash_billing_period": self.billing_period,
                "require_payment": True,
                "prepayment_percent": 1.0,
                "order_line": [
                    (0, 0, {
                        "product_id": product.id,
                        "name": self._carwash_billing_line_name(),
                        "product_uom_qty": 1,
                        "price_unit": self.amount,
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
        self._carwash_notify_membership("payment_request")
        self.message_post(body=self.env._("Payment request sent for %s.", order._get_html_link()))
        return True

    def action_create_invoice(self):
        """Backend payment: confirm + invoice the billing order; registering the payment activates it. For a new
        membership (pending), an expired one, or the renewal raised near the end of an active one."""
        self.ensure_one()
        if not (self.state in ("pending", "expired") or (self.state == "active" and self.pending_order_id)):
            raise UserError(self.env._(
                "Membership %s is already paid until %s - an invoice is made when its renewal is due or it has "
                "expired.", self.name, format_date(self.env, self.valid_until),
            ))
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
        if order.carwash_membership_paid:
            return
        if self.state == "cancelled":
            # money received for a membership that was cancelled meanwhile - someone has to refund or reactivate it
            self.message_post(body=self.env._(
                "Payment received for %s, but this membership is cancelled - refund the customer or reactivate the membership.",
                order._get_html_link(),
            ))
            self.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=self.env._("Refund or reactivate cancelled membership"),
                note=self.env._("Payment received for %s after the membership was cancelled.", order.name),
                user_id=self.create_uid.id or self.env.uid,
            )
            return
        order.sudo().carwash_membership_paid = True
        today = fields.Date.context_today(self)
        # one month or one year: what this order was raised for
        period = BILLING_PERIOD_DELTA[order.carwash_billing_period or self.billing_period]
        # paid by the end date or on the day after it (Expires On, when auto-renewal pays): it carries on without a gap
        renewing = self.state == "active" and self.valid_until and self.valid_until >= today - ONE_DAY
        first_activation = not self.start_date
        if renewing:
            # renewed before it ended: it carries on one more month / year from its end date
            end_date = self.valid_until + period
            vals = {"period_start": self.valid_until, "valid_until": end_date, "paid_until": end_date}
        else:
            # (re)activated today: starts today, ends the same day next month / next year, expires the day after
            end_date = today + period
            vals = {
                "state": "active",
                "start_date": today,
                "period_start": today,
                "valid_until": end_date,
                "paid_until": end_date,
                "wash_period_start": today,
                "washes_used": 0,
            }
        # the renewal is due on the end date (its order is raised a few days before)
        vals["next_billing_date"] = end_date
        self.write(vals)
        valid_until = end_date
        self.partner_id._carwash_sync_member_level()
        self.message_post(
            body=self.env._(
                "Payment received for %(order)s - membership active until %(date)s.",
                order=order._get_html_link(),
                date=format_date(self.env, valid_until),
            )
        )
        self._carwash_notify_membership("activated" if first_activation else "renewed")

    # Customer emails of the membership life cycle. carwash_notification overrides this to add
    # the Settings switches, more events (ending soon, expired...) and chatter logging.
    _CARWASH_MEMBERSHIP_TEMPLATES = {
        "payment_request": "carwash_membership.mail_template_membership_payment_request",
        "activated": "carwash_membership.mail_template_membership_renewed",
        "renewed": "carwash_membership.mail_template_membership_renewed",
    }

    def _carwash_notify_membership(self, kind):
        """Email the members about `kind` (payment_request, activated, renewed, expiring, expired, cancelled)."""
        xmlid = self._CARWASH_MEMBERSHIP_TEMPLATES.get(kind)
        template = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
        if not template:
            return
        for membership in self.filtered(lambda m: m.partner_id.email):
            self.env["carwash.mail"]._send_now([template.send_mail(membership.id, force_send=False)])

    def action_cancel(self):
        for membership in self:
            membership.state = "cancelled"
            unpaid = membership.sale_order_ids.filtered(lambda o: not o.carwash_membership_paid and o.state != "cancel").sudo()
            # an unpaid invoice of a cancelled membership must not be paid any more - cancel it with its order
            invoices = unpaid.invoice_ids.filtered(lambda m: m.state == "posted" and m.payment_state == "not_paid")
            invoices.button_draft()
            invoices.button_cancel()
            unpaid.invoice_ids.filtered(lambda m: m.state == "draft").button_cancel()
            unpaid.filtered(lambda o: not o.invoice_ids.filtered(lambda m: m.state != "cancel"))._action_cancel()
        self.partner_id._carwash_sync_member_level()
        self._carwash_notify_membership("cancelled")

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
        if self.state != "active" or (self.valid_until and self.valid_until < today):
            raise UserError(self.env._("Membership %s isn't active - it can't be used on a booking.", self.name))

    # ------------------------------------------------------------------
    # Auto-renewal: the customer turns it on from the reminder email (or the website / a manager); the day
    # after the end date the renewal is then paid automatically
    # ------------------------------------------------------------------
    def _carwash_auto_renew_token(self):
        self.ensure_one()
        return hmac(self.env(su=True), "carwash-membership-auto-renew", self.id)

    def _carwash_check_auto_renew_token(self, token):
        self.ensure_one()
        return bool(token) and consteq(token, self._carwash_auto_renew_token())

    def _carwash_auto_renew_url(self):
        """The Auto Renew button of the reminder email: a page where the customer confirms it."""
        self.ensure_one()
        return f"{self.get_base_url()}/car-wash/membership/{self.id}/auto-renew/{self._carwash_auto_renew_token()}"

    def _carwash_turn_on_auto_renew(self, by_customer=False):
        """Turn auto-renewal on (Auto Renew button of the reminder email, when `by_customer`) - logged."""
        for membership in self.filtered(lambda m: m.state == "active" and not m.auto_renew):
            membership.auto_renew = True
            membership.message_post(
                body=self.env._(
                    "Auto-renewal turned on %(by)s - on %(date)s (the day after the end date) the renewal is paid "
                    "automatically and the membership carries on.",
                    by=self.env._("by the customer (Auto Renew button of the reminder email)") if by_customer
                    else self.env._("by %s", self.env.user.name),
                    date=format_date(self.env, membership.expiry_date),
                ),
                subtype_xmlid="mail.mt_note",
            )

    def _carwash_auto_renew(self):
        """Renew automatically (the day after the end date): the renewal order is confirmed and invoiced, and
        its payment registered (the default payment journal) - the paid invoice renews the membership one more
        month / year from its end date, like a payment taken at the counter. Logged on the membership; if it
        can't be done, the customer gets the renewal order to pay instead."""
        for membership in self:
            try:
                with self.env.cr.savepoint():
                    # sudo: run by the daily job - sales / invoicing / payments of the customer
                    order = membership._get_or_create_billing_order().sudo()
                    if order.state in ("draft", "sent"):
                        order.action_confirm()
                    invoice = order.invoice_ids.filtered(lambda m: m.state != "cancel")[:1] or order._create_invoices()
                    if invoice.state == "draft":
                        invoice.action_post()
                    payment = self.env["account.payment"]
                    if invoice.payment_state not in ("paid", "in_payment"):
                        payment = self.env["account.payment.register"].sudo().with_context(
                            active_model="account.move", active_ids=invoice.ids,
                        ).create({})._create_payments()
                    membership.message_post(
                        body=self.env._(
                            "Auto-renewal: %(order)s invoiced (%(invoice)s) and paid automatically%(journal)s - "
                            "membership renewed until %(date)s.",
                            order=order._get_html_link(), invoice=invoice._get_html_link(),
                            journal=f" ({payment.journal_id.name})" if payment else "",
                            date=format_date(self.env, membership.valid_until),
                        ),
                        subtype_xmlid="mail.mt_note",
                    )
            except Exception as error:  # noqa: BLE001 - one membership must not stop the others' renewal
                membership.message_post(
                    body=self.env._(
                        "Auto-renewal couldn't take the payment automatically (%s) - the renewal order was sent to "
                        "the customer to pay.", error,
                    ),
                    subtype_xmlid="mail.mt_note",
                )
                if not membership.pending_order_id.invoice_ids:
                    membership.action_request_payment()

    @api.model
    def _cron_process_membership_billing(self):
        today = fields.Date.context_today(self)
        # 1. auto-renewal: the day after the end date (Expires On) the renewal is paid automatically - before 3.
        #    expires the memberships that weren't renewed
        self.search([
            ("state", "=", "active"), ("auto_renew", "=", True), ("valid_until", "<", today),
        ])._carwash_auto_renew()
        # 2. a new month of free washes (monthly and yearly members alike)
        for membership in self.search([("state", "=", "active"), ("wash_period_start", "!=", False),
                                       ("wash_period_start", "<=", today - ONE_MONTH)]):
            start = membership.wash_period_start
            while start + ONE_MONTH <= today:
                start += ONE_MONTH
            membership.write({"wash_period_start": start, "washes_used": 0})
            membership.message_post(body=self.env._("New month - free washes reset."))
        # 3. the day after the end date, not renewed -> expired
        lapsed = self.search([("state", "=", "active"), ("valid_until", "<", today)])
        if lapsed:
            lapsed.write({"state": "expired"})
            lapsed.partner_id._carwash_sync_member_level()
            for membership in lapsed:
                membership.message_post(body=self.env._("Membership expired - the renewal wasn't paid in time."))
            lapsed._carwash_notify_membership("expired")
