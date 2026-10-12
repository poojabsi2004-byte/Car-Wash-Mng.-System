from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashBay(models.Model):
    _name = "carwash.bay"
    _description = "Car Wash Bay"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True)
    bay_type_id = fields.Many2one(
        "carwash.bay.type", string="Bay Type", required=True, ondelete="restrict", index=True, tracking=True,
        default=lambda self: self.env["carwash.bay.type"]._default_type(),
    )
    bay_type_icon = fields.Selection(related="bay_type_id.icon", string="Type Icon")
    state = fields.Selection(
        [("free", "Free"), ("occupied", "Occupied"), ("maintenance", "Maintenance")],
        default="free",
        tracking=True,
        group_expand="_expand_states",
    )
    active = fields.Boolean(default=True)
    notes = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    appointment_ids = fields.One2many("carwash.appointment", "bay_id", string="Bookings")
    appointment_count = fields.Integer(compute="_compute_appointment_count", string="Booking Count")

    def _compute_appointment_count(self):
        counts = dict(self.env["carwash.appointment"]._read_group(
            [("bay_id", "in", self.ids)], ["bay_id"], ["__count"]
        ))
        for bay in self:
            bay.appointment_count = counts.get(bay._origin, 0)

    def action_view_appointments(self):
        """Smart button: every booking of this bay (upcoming and past)."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_base.action_carwash_appointment_all")
        title = self.env._("Bookings - %s", self.name)
        action.update(
            name=title,
            display_name=title,
            domain=[("bay_id", "=", self.id)],
            view_mode="list,kanban,form",
            views=[(False, "list"), (False, "kanban"), (False, "form")],
            context={"default_bay_id": self.id, "default_company_id": self.company_id.id},
        )
        return action

    def action_set_maintenance(self):
        """Take the bay out of use: no bookings are scheduled on a bay under maintenance."""
        self.write({"state": "maintenance"})

    def action_set_free(self):
        """End maintenance, or release a bay left Occupied without a running service."""
        self.write({"state": "free"})

    def _carwash_time(self, value):
        return fields.Datetime.context_timestamp(self, value).strftime("%I:%M %p")

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    def write(self, vals):
        if vals.get("state") == "occupied" and not self.env.context.get("carwash_bay_by_service"):
            # Occupied is set by Start Service only - set by hand it could never be released again
            raise UserError(self.env._(
                "A bay becomes Occupied automatically when a service starts on it - set it to Free or Maintenance instead."
            ))
        if "state" in vals and vals["state"] != "occupied" and not self.env.context.get("carwash_allow_bay_release"):
            still_busy = self.filtered(lambda bay: bay.state == "occupied" and bay._carwash_running_booking())
            if still_busy:
                raise UserError(
                    self.env._(
                        "Bay %(bay)s is occupied by an active service and can't be freed manually. "
                        "Complete or cancel the vehicle's booking first.",
                        bay=still_busy[0].name,
                    )
                )
        return super().write(vals)

    def _carwash_running_booking(self):
        self.ensure_one()
        return self.env["carwash.appointment"].sudo().search_count([("bay_id", "=", self.id), ("state", "=", "in_service")])

    _bay_name_company_uniq = models.Constraint(
        "UNIQUE(name, company_id)", "Bay name must be unique per company."
    )
