from odoo import api, fields, models


class CarwashServicePackage(models.Model):
    _name = "carwash.service.package"
    _description = "Car Wash Service Package"
    _inherit = ["mail.thread"]
    _order = "sequence, id"

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("carwash.service.package.line", "package_id", string="Services")
    price_type = fields.Selection(
        [("sum", "Sum of services"), ("fixed", "Fixed package price")],
        string="Pricing",
        default="sum",
        required=True,
        tracking=True,
        help="Sum of services: the package costs what its services cost.\n"
        "Fixed package price: one bundle price, spread across the services when applied to a booking.",
    )
    fixed_price = fields.Float(string="Package Price", tracking=True)
    services_total = fields.Float(compute="_compute_prices", string="Services Total")
    total_price = fields.Float(compute="_compute_prices", string="Package Amount")
    saving = fields.Float(compute="_compute_prices", string="Customer Saves")
    duration = fields.Float(compute="_compute_prices", string="Duration (hours)")
    service_count = fields.Integer(compute="_compute_prices", string="Number of Services")
    booking_count = fields.Integer(compute="_compute_booking_count", string="Bookings")
    website_highlights = fields.Html(
        string="What's Included (Website)",
        sanitize_attributes=False,
        help="Freeform, rich content shown under this package's tab on the website - "
        "e.g. one heading per stage of the wash with a checklist underneath. Falls back "
        "to a plain list of the services above if left empty.",
    )

    _fixed_price_positive = models.Constraint("CHECK(fixed_price >= 0)", "The package price can't be negative.")

    @api.depends("line_ids.quantity", "line_ids.product_id", "price_type", "fixed_price")
    def _compute_prices(self):
        for package in self:
            services_total = sum(line.product_id.list_price * line.quantity for line in package.line_ids)
            total = package.fixed_price if package.price_type == "fixed" else services_total
            package.services_total = services_total
            package.total_price = total
            package.saving = max(services_total - total, 0.0)
            package.duration = sum(line.product_id.carwash_duration * line.quantity for line in package.line_ids)
            package.service_count = len(package.line_ids)

    def _compute_booking_count(self):
        counts = dict(
            self.env["carwash.appointment"]._read_group(
                [("service_package_id", "in", self.ids)], ["service_package_id"], ["__count"]
            )
        )
        for package in self:
            package.booking_count = counts.get(package, 0)

    def _prepare_booking_line_vals(self):
        """Booking line values for this package's services, priced so they add up to the package amount."""
        self.ensure_one()
        lines = self.line_ids.filtered("product_id")
        if not lines:
            return []
        ratio = self.total_price / self.services_total if self.services_total else 0.0
        vals_list = [
            {
                "product_id": line.product_id.id,
                "description": f"{line.product_id.display_name} ({self.name})",
                "quantity": line.quantity or 1.0,
                "price_unit": round(line.product_id.list_price * ratio, 2),
                "package_id": self.id,
            }
            for line in lines
        ]
        # any rounding difference (or a fixed price on zero-priced services) goes on the last line
        allocated = sum(vals["price_unit"] * vals["quantity"] for vals in vals_list)
        difference = round(self.total_price - allocated, 2)
        if difference:
            last = vals_list[-1]
            last["price_unit"] = round(last["price_unit"] + difference / last["quantity"], 2)
        return vals_list

    def action_view_bookings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Bookings: %s", self.name),
            "res_model": "carwash.appointment",
            "view_mode": "list,kanban,form",
            "domain": [("service_package_id", "=", self.id)],
        }


class CarwashServicePackageLine(models.Model):
    _name = "carwash.service.package.line"
    _description = "Car Wash Service Package Line"
    _order = "sequence, id"

    package_id = fields.Many2one("carwash.service.package", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product", string="Service", required=True, domain=[("is_carwash_service", "=", True)]
    )
    quantity = fields.Float(default=1.0)
    list_price = fields.Float(related="product_id.list_price", string="Unit Price")
    subtotal = fields.Float(compute="_compute_subtotal", string="Subtotal")
    duration = fields.Float(related="product_id.carwash_duration", string="Duration (hours)")

    @api.depends("quantity", "product_id.list_price")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.product_id.list_price * line.quantity
