from odoo import api, fields, models

VEHICLE_ICONS = [
    ("fa-car", "Car"),
    ("fa-taxi", "Taxi / Cab"),
    ("fa-truck", "Truck / Pickup"),
    ("fa-bus", "Van / Bus"),
    ("fa-motorcycle", "Motorcycle / Scooter"),
    ("fa-bicycle", "Bicycle"),
]


class CarwashVehicleType(models.Model):
    """Kind of vehicle (Hatchback, SUV, Motorcycle...) - a configurable list instead of fixed choices."""

    _name = "carwash.vehicle.type"
    _description = "Car Wash Vehicle Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Technical key of a standard type (hatchback, sedan, suv, truck, van, bike, other); empty for your own types.",
    )
    sequence = fields.Integer(default=10)
    icon = fields.Selection(VEHICLE_ICONS, string="Dashboard Icon", default="fa-car", required=True)
    active = fields.Boolean(default=True)
    vehicle_ids = fields.One2many("carwash.vehicle", "vehicle_type_id", string="Vehicles")
    vehicle_count = fields.Integer(compute="_compute_vehicle_count", string="Vehicle Count")

    _name_uniq = models.Constraint("UNIQUE(name)", "A vehicle type with this name already exists.")
    _code_uniq = models.Constraint("UNIQUE(code)", "A vehicle type with this code already exists.")

    def _compute_vehicle_count(self):
        counts = dict(self.env["carwash.vehicle"]._read_group(
            [("vehicle_type_id", "in", self.ids)], ["vehicle_type_id"], ["__count"]
        ))
        for vehicle_type in self:
            vehicle_type.vehicle_count = counts.get(vehicle_type._origin, 0)

    @api.model
    def _by_code(self, code):
        """The type with this technical key (e.g. 'sedan'), or an empty recordset."""
        return self.search([("code", "=", code)], limit=1) if code else self.browse()

    @api.model
    def _default_type(self):
        return self.env.ref("carwash_base.vehicle_type_sedan", raise_if_not_found=False) or self.search([], limit=1)

    def action_view_vehicles(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_base.action_carwash_vehicle")
        action.update(domain=[("vehicle_type_id", "=", self.id)], context={"default_vehicle_type_id": self.id})
        return action
