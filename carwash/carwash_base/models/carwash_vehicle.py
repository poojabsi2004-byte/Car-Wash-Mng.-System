from odoo import api, fields, models


class CarwashVehicle(models.Model):
    _name = "carwash.vehicle"
    _description = "Car Wash Vehicle"
    _inherit = ["mail.thread"]
    _rec_name = "license_plate"

    license_plate = fields.Char(required=True, index=True, tracking=True)
    customer_id = fields.Many2one("res.partner", required=True, tracking=True, index=True, ondelete="restrict")
    make = fields.Char()
    vehicle_model = fields.Char(string="Model")
    vehicle_type_id = fields.Many2one(
        "carwash.vehicle.type", string="Vehicle Type", ondelete="restrict", index=True,
        default=lambda self: self.env["carwash.vehicle.type"]._default_type(),
    )
    vehicle_type_icon = fields.Selection(related="vehicle_type_id.icon", string="Type Icon")
    color = fields.Char()
    year = fields.Char()
    vin = fields.Char(string="VIN / Chassis No.")
    image_1920 = fields.Image(string="Photo")
    image_128 = fields.Image(related="image_1920", max_width=128, max_height=128, store=True, string="Photo (small)")
    notes = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    appointment_ids = fields.One2many("carwash.appointment", "vehicle_id", string="Bookings")
    appointment_count = fields.Integer(compute="_compute_appointment_count", string="Booking Count")
    visit_count = fields.Integer(compute="_compute_service_history", store=True)
    last_service_date = fields.Datetime(compute="_compute_service_history", store=True)

    @staticmethod
    def _normalize_plate(plate):
        """'  gj01 ab 1234 ' -> 'GJ01 AB 1234' - so the same plate typed differently is one vehicle."""
        return " ".join(plate.split()).upper() if isinstance(plate, str) else plate

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("license_plate"):
                vals["license_plate"] = self._normalize_plate(vals["license_plate"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("license_plate"):
            vals["license_plate"] = self._normalize_plate(vals["license_plate"])
        return super().write(vals)

    _license_plate_company_uniq = models.Constraint(
        "UNIQUE(license_plate, company_id)",
        "This license plate is already registered. If ownership changed, "
        "edit the existing vehicle's Customer instead of creating a duplicate.",
    )

    @api.depends("appointment_ids")
    def _compute_appointment_count(self):
        for vehicle in self:
            vehicle.appointment_count = len(vehicle.appointment_ids)

    @api.depends("appointment_ids.state", "appointment_ids.done_at")
    def _compute_service_history(self):
        for vehicle in self:
            done = vehicle.appointment_ids.filtered(lambda a: a.state == "done")
            vehicle.visit_count = len(done)
            vehicle.last_service_date = max(done.mapped("done_at"), default=False)

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Bookings",
            "res_model": "carwash.appointment",
            "view_mode": "list,form",
            "domain": [("vehicle_id", "=", self.id)],
            "context": {"default_vehicle_id": self.id, "default_customer_id": self.customer_id.id},
        }
