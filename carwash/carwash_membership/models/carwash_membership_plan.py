from odoo import api, fields, models


class CarwashMembershipPlan(models.Model):
    _name = "carwash.membership.plan"
    _description = "Car Wash Membership Plan"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(help="Short pitch shown on the website membership page.")
    product_id = fields.Many2one(
        "product.product",
        string="Billing Product",
        required=True,
        domain=[("type", "=", "service")],
        help="Service product invoiced to the customer on each billing cycle.",
    )
    price = fields.Float(related="product_id.list_price", readonly=True)
    billing_period = fields.Selection(
        [("monthly", "Monthly"), ("quarterly", "Quarterly"), ("yearly", "Yearly")],
        default="monthly",
        required=True,
    )
    # Benefit 1 - covered services are free, up to the wash allowance per billing cycle
    wash_allowance = fields.Integer(
        string="Washes per Cycle", default=4, help="Maximum free (covered) washes per billing cycle. 0 = unlimited."
    )
    plan_service_ids = fields.Many2many(
        "product.product",
        string="Covered Services",
        domain=[("is_carwash_service", "=", True)],
        help="Free for members (one wash per booking counts against the allowance).",
    )
    # Benefit 2 - member discount on every other car wash service, via Odoo's member level + pricelist
    discount_percent = fields.Float(
        string="Member Discount (%)",
        help="Discount on car wash services that aren't covered (or once the free washes are used up). "
        "Applied through the plan's member level pricelist.",
    )
    grade_id = fields.Many2one(
        "res.partner.grade", string="Member Level", readonly=True, copy=False,
        help="Odoo Partnership level given to customers while their membership is active.",
    )
    pricelist_id = fields.Many2one(
        "product.pricelist", string="Member Pricelist", readonly=True, copy=False,
        help="Pricelist of the member level - holds the member discount on car wash services.",
    )
    website_published = fields.Boolean(string="Available Online", default=True,
                                        help="Customers can join this plan from the website.")
    active = fields.Boolean(default=True)
    member_count = fields.Integer(compute="_compute_member_count", string="Active Members")

    _discount_range = models.Constraint(
        "CHECK(discount_percent >= 0 AND discount_percent <= 100)", "The member discount must be between 0 and 100%."
    )

    def _compute_member_count(self):
        counts = dict(
            self.env["carwash.membership"]._read_group(
                [("plan_id", "in", self.ids), ("state", "=", "active")], ["plan_id"], ["__count"]
            )
        )
        for plan in self:
            plan.member_count = counts.get(plan, 0)

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._sync_member_level()
        return plans

    def write(self, vals):
        res = super().write(vals)
        if {"name", "discount_percent", "active"} & set(vals):
            self._sync_member_level()
        return res

    def _sync_member_level(self):
        """Keep the plan's Odoo member level (res.partner.grade) and its pricelist in sync."""
        services = self.env["product.product"].with_context(active_test=False).search([("is_carwash_service", "=", True)])
        for plan in self.sudo():
            if not plan.pricelist_id:
                plan.pricelist_id = self.env["product.pricelist"].create(
                    {"name": f"Membership: {plan.name}", "company_id": False}
                )
            if not plan.grade_id:
                plan.grade_id = self.env["res.partner.grade"].create(
                    {"name": plan.name, "default_pricelist_id": plan.pricelist_id.id, "company_id": False}
                )
            plan.pricelist_id.name = f"Membership: {plan.name}"
            plan.grade_id.write({"name": plan.name, "active": plan.active})
            items = [(5, 0, 0)]
            if plan.discount_percent:
                items += [
                    (0, 0, {
                        "applied_on": "0_product_variant",
                        "product_id": service.id,
                        "product_tmpl_id": service.product_tmpl_id.id,
                        "compute_price": "percentage",
                        "percent_price": plan.discount_percent,
                    })
                    for service in services
                ]
            plan.pricelist_id.item_ids = items

    def _benefit_summary(self):
        self.ensure_one()
        parts = []
        if self.plan_service_ids:
            allowance = f"{self.wash_allowance} free washes" if self.wash_allowance else "unlimited free washes"
            parts.append(f"{allowance} ({', '.join(self.plan_service_ids.mapped('name'))})")
        if self.discount_percent:
            parts.append(f"{self.discount_percent:g}% off other services")
        return "; ".join(parts)

    def action_view_members(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Members: %s", self.name),
            "res_model": "carwash.membership",
            "view_mode": "list,kanban,form",
            "domain": [("plan_id", "=", self.id)],
            "context": {"default_plan_id": self.id},
        }
