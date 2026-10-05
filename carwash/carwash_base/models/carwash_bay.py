from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashBay(models.Model):
    _name = "carwash.bay"
    _description = "Car Wash Bay"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True)
    bay_type = fields.Selection(
        [("hand", "Hand Wash"), ("tunnel", "Tunnel"), ("detail", "Detailing")],
        default="hand",
        required=True,
    )
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

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    def write(self, vals):
        if "state" in vals and vals["state"] != "occupied" and not self.env.context.get("carwash_allow_bay_release"):
            still_busy = self.filtered(lambda bay: bay.state == "occupied")
            if still_busy:
                raise UserError(
                    self.env._(
                        "Bay %(bay)s is occupied by an active service and can't be freed manually. "
                        "Complete or cancel the vehicle's booking first.",
                        bay=still_busy[0].name,
                    )
                )
        return super().write(vals)

    _bay_name_company_uniq = models.Constraint(
        "UNIQUE(name, company_id)", "Bay name must be unique per company."
    )
