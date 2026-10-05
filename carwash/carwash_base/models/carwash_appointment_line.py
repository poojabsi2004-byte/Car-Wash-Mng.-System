from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashAppointmentLine(models.Model):
    _name = "carwash.appointment.line"
    _description = "Car Wash Booking Service Line"

    appointment_id = fields.Many2one("carwash.appointment", string="Booking", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product", required=True, string="Service", domain=[("is_carwash_service", "=", True)]
    )
    description = fields.Char()
    quantity = fields.Float(default=1.0)
    price_unit = fields.Float(compute="_compute_price_unit", store=True, readonly=False)
    price_subtotal = fields.Float(compute="_compute_price_subtotal", store=True)
    duration = fields.Float(related="product_id.carwash_duration", readonly=True)
    is_discount_line = fields.Boolean(
        string="Discount Line", readonly=True, copy=False,
        help="A price adjustment (e.g. the membership discount), not a service to perform.",
    )

    # Each service on the appointment is started and ended on its own once the
    # main service is running; the main service can only end when all are done.
    service_state = fields.Selection(
        [("pending", "Pending"), ("in_progress", "In Progress"), ("done", "Done")],
        string="Service Status",
        default="pending",
        required=True,
        copy=False,
    )
    start_time = fields.Datetime(string="Started", readonly=True, copy=False)
    end_time = fields.Datetime(string="Ended", readonly=True, copy=False)
    actual_duration = fields.Float(
        string="Time Taken (min)", compute="_compute_actual_duration", store=True, digits=(16, 1)
    )

    _quantity_positive = models.Constraint("CHECK(quantity > 0)", "Quantity must be positive.")

    @api.depends("product_id")
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.product_id.list_price

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.depends("start_time", "end_time")
    def _compute_actual_duration(self):
        for line in self:
            if line.start_time and line.end_time:
                line.actual_duration = (line.end_time - line.start_time).total_seconds() / 60.0
            else:
                line.actual_duration = 0.0

    def _check_can_run_services(self):
        if not self.env["carwash.appointment"]._can_run_services():
            raise UserError(self.env._("You don't have permission to start or end services."))

    def action_start_line(self):
        self._check_can_run_services()
        for line in self:
            if line.appointment_id.state != "in_service":
                raise UserError(self.env._("Start the main service before starting %s.", line.product_id.display_name))
            if line.service_state != "pending":
                raise UserError(self.env._("%s has already been started.", line.product_id.display_name))
        # sudo: the role check above is the gate - washers start/end services but don't
        # get general write access to service lines (prices, quantities).
        self.sudo().write({"service_state": "in_progress", "start_time": fields.Datetime.now()})
        for line in self:
            line.appointment_id.message_post(body=self.env._("Service started: %s", line.product_id.display_name))
        return True

    def action_end_line(self):
        self._check_can_run_services()
        for line in self:
            if line.service_state != "in_progress":
                raise UserError(self.env._("%s hasn't been started yet.", line.product_id.display_name))
        self.sudo().write({"service_state": "done", "end_time": fields.Datetime.now()})
        for line in self:
            line.appointment_id.message_post(
                body=self.env._(
                    "Service finished: %(service)s (%(minutes)s min)",
                    service=line.product_id.display_name,
                    minutes=round(line.actual_duration),
                )
            )
        return True

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.display_name
