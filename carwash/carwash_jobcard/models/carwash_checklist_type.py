from odoo import api, fields, models
from odoo.exceptions import UserError

# the steps of the process where checklists are loaded (see carwash.checklist.mixin)
CHECKLIST_STEPS = [("jobcard", "Job Card"), ("booking", "Booking Check-in"), ("inspection", "Inspection")]
STANDARD_TYPES = {
    "jobcard": "carwash_jobcard.checklist_type_jobcard",
    "booking": "carwash_jobcard.checklist_type_booking",
    "inspection": "carwash_jobcard.checklist_type_inspection",
}


class CarwashChecklistType(models.Model):
    """Kind of checklist ("Used On" of a template) - a configurable list. Each type applies to one
    step of the process: the booking check-in, an inspection, or the crew's job card."""

    _name = "carwash.checklist.type"
    _description = "Car Wash Checklist Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    applies_to = fields.Selection(
        CHECKLIST_STEPS, string="Applies To", required=True, default="booking",
        help="Where checklists of this type are loaded: at the counter when the vehicle arrives (Booking Check-in), "
        "on a pre- or post-wash Inspection, or on the crew's Job Card.",
    )
    sequence = fields.Integer(default=10)
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    template_ids = fields.One2many("carwash.checklist.template", "checklist_type_id", string="Templates")
    template_count = fields.Integer(compute="_compute_template_count", string="Template Count")

    _name_uniq = models.Constraint("UNIQUE(name)", "A checklist type with this name already exists.")

    def _compute_template_count(self):
        counts = dict(self.env["carwash.checklist.template"]._read_group(
            [("checklist_type_id", "in", self.ids)], ["checklist_type_id"], ["__count"]
        ))
        for checklist_type in self:
            checklist_type.template_count = counts.get(checklist_type._origin, 0)

    def write(self, vals):
        if "applies_to" in vals:
            moved = self.filtered(lambda t: t.applies_to != vals["applies_to"])
            in_use = self.env["carwash.checklist.template"].with_context(active_test=False).search(
                [("checklist_type_id", "in", moved.ids)], limit=1
            ).checklist_type_id
            if in_use:
                raise UserError(self.env._(
                    "%s already has checklist templates - move them to another type before changing where it applies.",
                    in_use.name,
                ))
        return super().write(vals)

    @api.model
    def _default_for(self, applies_to):
        """The checklist type of a step: the standard one, else the first active one."""
        xmlid = STANDARD_TYPES.get(applies_to)
        standard = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        if standard and standard.active and standard.applies_to == applies_to:
            return standard
        return self.search([("applies_to", "=", applies_to)], limit=1)

    def action_view_templates(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_checklist_template")
        action.update(
            name=self.name, domain=[("checklist_type_id", "=", self.id)], context={"default_checklist_type_id": self.id},
        )
        return action
