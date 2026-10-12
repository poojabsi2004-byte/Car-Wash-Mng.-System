from odoo import api, fields, models
from odoo.exceptions import UserError

MEMBERSHIP_EDITABLE_STATES = ("draft", "confirmed", "arrived")
# a membership can still be taken off until the booking is completed - e.g. it lapsed during the wash
MEMBERSHIP_REMOVABLE_STATES = MEMBERSHIP_EDITABLE_STATES + ("in_service", "ready")


class CarwashAppointmentLine(models.Model):
    _inherit = "carwash.appointment.line"

    membership_covered = fields.Boolean(string="Free with Membership", readonly=True, copy=False)
    membership_discount = fields.Float(string="Member Discount (%)", readonly=True, copy=False)
    price_before_membership = fields.Float(readonly=True, copy=False)


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    membership_id = fields.Many2one(
        "carwash.membership", string="Membership Applied", readonly=True, copy=False, tracking=True, index=True
    )
    customer_membership_id = fields.Many2one(
        "carwash.membership", compute="_compute_customer_membership", string="Customer Membership"
    )
    membership_washes_left = fields.Integer(compute="_compute_customer_membership", string="Free Washes Left")
    membership_benefit = fields.Char(compute="_compute_customer_membership", string="Membership Benefit")
    membership_saving = fields.Float(compute="_compute_membership_saving", string="Membership Saving")

    @api.depends("customer_id", "membership_id")
    def _compute_customer_membership(self):
        for appointment in self:
            # sudo: a display summary - staff (washer / QC) open the booking without access to memberships / plans
            membership = appointment.membership_id.sudo() or appointment.customer_id.sudo().carwash_active_membership_id
            appointment.customer_membership_id = membership
            appointment.membership_washes_left = membership.washes_remaining if membership else 0
            appointment.membership_benefit = membership.plan_id._benefit_summary() if membership else False

    @api.depends("line_ids.price_before_membership", "line_ids.price_unit", "line_ids.quantity",
                 "line_ids.is_discount_line", "membership_id")
    def _compute_membership_saving(self):
        for appointment in self:
            free = appointment.line_ids.filtered("membership_covered")
            discount = appointment.line_ids.filtered(lambda line: line.is_discount_line and appointment.membership_id)
            appointment.membership_saving = sum(
                (line.price_before_membership - line.price_unit) * line.quantity for line in free
            ) - sum(discount.mapped("price_subtotal"))

    def _membership_pricelist_price(self, membership, line):
        return membership._member_discount_price(line.product_id, line.price_unit, line.quantity)

    def _membership_discount_line_vals(self, membership, amount, discounted_lines):
        """The single booking line carrying the member discount (a negative price)."""
        product = self.env.ref("carwash_membership.product_membership_discount")
        plan = membership.plan_id
        return {
            "product_id": product.id,
            "description": self.env._(
                "Membership discount - %(plan)s, %(percent)s%% off %(services)s",
                plan=plan.name,
                percent=f"{plan.discount_percent:g}",
                services=", ".join(discounted_lines.product_id.mapped("name")),
            ),
            "quantity": 1.0,
            "price_unit": -amount,
            "is_discount_line": True,
            "service_state": "done",
        }

    def action_apply_membership(self):
        """Free covered services go to 0 on their own line; the member discount on the other
        services is one separate "Membership Discount" line, so the services keep their price."""
        if not self.env["carwash.feature"]._enabled("carwash_membership.group_carwash_membership"):
            raise UserError(self.env._("Memberships are switched off (Car Wash > Configuration > Settings)."))
        for appointment in self:
            membership = appointment.customer_id.sudo().carwash_active_membership_id
            if not membership:
                raise UserError(self.env._("%s has no active membership.", appointment.customer_id.display_name))
            if appointment.state not in MEMBERSHIP_EDITABLE_STATES:
                raise UserError(self.env._("A membership can only be applied before the service starts."))
            membership._check_usable()
            appointment._reset_membership_prices()
            membership.invalidate_recordset(["washes_reserved", "washes_remaining"])
            plan = membership.plan_id
            # a free wash is available unless the allowance is used up (this booking's own
            # reservation was released by the reset above)
            lines = appointment._service_lines()
            member_prices = membership._compute_member_prices(
                [(line.product_id, line.price_unit, line.quantity) for line in lines]
            )
            if not any(member_prices):
                raise UserError(
                    self.env._("The %s plan gives no benefit on these services (and no free washes are left).", plan.name)
                )
            discount_amount = 0.0
            discounted = self.env["carwash.appointment.line"]
            for line, vals in zip(lines, member_prices):
                if not vals:
                    continue
                if vals.get("membership_covered"):
                    line.write({
                        "membership_covered": True,
                        "price_before_membership": line.price_unit,
                        "price_unit": 0.0,
                        "description": self.env._("%s (free with membership)", line.description or line.product_id.display_name),
                    })
                else:
                    discount_amount += (line.price_unit - vals["price_unit"]) * line.quantity
                    discounted |= line
                    line.write({"membership_discount": vals["membership_discount"], "price_before_membership": line.price_unit})
            discount_amount = round(discount_amount, 2)
            if discount_amount > 0:
                appointment.line_ids = [(0, 0, appointment._membership_discount_line_vals(membership, discount_amount, discounted))]
            appointment.membership_id = membership
            membership.invalidate_recordset(["washes_reserved", "washes_remaining"])
            appointment.message_post(
                body=self.env._(
                    "Membership %(membership)s applied - saving %(saving)s.",
                    membership=membership.name,
                    saving=round(appointment.membership_saving, 2),
                )
            )
        return True

    def _reset_membership_prices(self):
        suffix = " (free with membership)"
        for appointment in self:
            appointment.line_ids.filtered("is_discount_line").unlink()
            for line in appointment.line_ids.filtered(lambda l: l.membership_covered or l.membership_discount):
                vals = {"price_unit": line.price_before_membership, "membership_covered": False, "membership_discount": 0.0}
                if line.membership_covered and line.description and line.description.endswith(suffix):
                    vals["description"] = line.description[: -len(suffix)]
                line.write(vals)
            appointment.membership_id.invalidate_recordset(["washes_reserved", "washes_remaining"])
            appointment.membership_id = False

    def action_remove_membership(self):
        for appointment in self:
            if appointment.state not in MEMBERSHIP_REMOVABLE_STATES:
                raise UserError(self.env._("The membership can only be removed before the booking is completed."))
        self._reset_membership_prices()
        return True

    # ------------------------------------------------------------------
    # Workflow hooks
    # ------------------------------------------------------------------
    def _send_carwash_template(self, xml_id):
        template = self.env.ref(xml_id, raise_if_not_found=False)
        if not template:
            return
        for appointment in self:
            if appointment.customer_id.email:
                self.env["carwash.mail"]._send_now([template.send_mail(appointment.id, force_send=False)])

    def action_confirm(self):
        res = super().action_confirm()
        self._send_carwash_template("carwash_membership.mail_template_appointment_confirmed")
        return res

    def action_ready(self):
        res = super().action_ready()
        self._send_carwash_template("carwash_membership.mail_template_appointment_ready")
        return res

    def action_done(self):
        for appointment in self.filtered("membership_id"):
            try:
                appointment.membership_id._check_usable()
            except UserError as error:
                raise UserError(self.env._(
                    "%(error)s\nClick Remove on the membership banner to complete the booking at normal prices.",
                    error=error.args[0],
                )) from error
        res = super().action_done()
        for appointment in self:
            appointment._apply_membership_usage()
        return res

    def _apply_membership_usage(self):
        """A completed booking that used a free wash consumes it from the current period."""
        self.ensure_one()
        if self.membership_id and self.line_ids.filtered("membership_covered"):
            self.membership_id.sudo().washes_used += 1
