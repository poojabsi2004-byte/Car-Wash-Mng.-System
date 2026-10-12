from odoo import api, fields, models

BAY_ICONS = [
    ("fa-hand-paper-o", "Hand Wash"),
    ("fa-road", "Tunnel / Conveyor"),
    ("fa-diamond", "Detailing"),
    ("fa-tint", "Water / Rinse"),
    ("fa-shower", "Pressure Wash"),
    ("fa-magic", "Polish / Coating"),
    ("fa-wrench", "Service / Repair"),
    ("fa-car", "General"),
]


class CarwashBayType(models.Model):
    """Kind of bay (Hand Wash, Tunnel, Detailing...) - a configurable list instead of fixed choices."""

    _name = "carwash.bay.type"
    _description = "Car Wash Bay Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Technical key of a standard type (hand, tunnel, detail); empty for your own types.",
    )
    sequence = fields.Integer(default=10)
    icon = fields.Selection(BAY_ICONS, string="Dashboard Icon", default="fa-tint", required=True)
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    bay_ids = fields.One2many("carwash.bay", "bay_type_id", string="Bays")
    bay_count = fields.Integer(compute="_compute_counts", string="Bay Count")
    service_count = fields.Integer(compute="_compute_counts", string="Service Count")

    _name_uniq = models.Constraint("UNIQUE(name)", "A bay type with this name already exists.")
    _code_uniq = models.Constraint("UNIQUE(code)", "A bay type with this code already exists.")

    def _compute_counts(self):
        bays = dict(self.env["carwash.bay"]._read_group(
            [("bay_type_id", "in", self.ids)], ["bay_type_id"], ["__count"]
        ))
        services = dict(self.env["product.template"]._read_group(
            [("carwash_bay_type_id", "in", self.ids)], ["carwash_bay_type_id"], ["__count"]
        ))
        for bay_type in self:
            bay_type.bay_count = bays.get(bay_type._origin, 0)
            bay_type.service_count = services.get(bay_type._origin, 0)

    @api.model
    def _by_code(self, code):
        """The type with this technical key (e.g. 'tunnel'), or an empty recordset."""
        return self.search([("code", "=", code)], limit=1) if code else self.browse()

    @api.model
    def _default_type(self):
        return self.env.ref("carwash_base.bay_type_hand", raise_if_not_found=False) or self.search([], limit=1)

    def action_view_bays(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_base.action_carwash_bay")
        action.update(domain=[("bay_type_id", "=", self.id)], context={"default_bay_type_id": self.id})
        return action

    def action_view_services(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_base.action_carwash_service")
        action.update(
            domain=[("is_carwash_service", "=", True), ("carwash_bay_type_id", "=", self.id)],
            context={"default_is_carwash_service": 1, "default_type": "service", "default_carwash_bay_type_id": self.id},
        )
        return action
