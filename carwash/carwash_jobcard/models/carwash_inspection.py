from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashInspectionType(models.Model):
    _name = "carwash.inspection.type"
    _description = "Car Wash Inspection Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(translate=True, help="What the inspector should check for this type of inspection.")
    active = fields.Boolean(default=True)
    inspection_count = fields.Integer(compute="_compute_inspection_count", string="Inspections")

    _name_uniq = models.Constraint("UNIQUE(name)", "An inspection type with this name already exists.")

    def _compute_inspection_count(self):
        counts = dict(
            self.env["carwash.inspection"]._read_group(
                [("inspection_type_id", "in", self.ids)], ["inspection_type_id"], ["__count"]
            )
        )
        for inspection_type in self:
            inspection_type.inspection_count = counts.get(inspection_type, 0)

    def action_view_inspections(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "carwash.inspection",
            "view_mode": "list,form",
            "domain": [("inspection_type_id", "=", self.id)],
            "context": {"default_inspection_type_id": self.id},
        }


class CarwashInspection(models.Model):
    _name = "carwash.inspection"
    _description = "Car Wash Vehicle Inspection"
    _inherit = ["carwash.checklist.mixin"]
    _order = "inspection_date desc, id desc"
    _checklist_type = "inspection"

    name = fields.Char(default="New", copy=False, readonly=True)
    appointment_id = fields.Many2one("carwash.appointment", string="Booking", required=True, ondelete="cascade", index=True)
    vehicle_id = fields.Many2one(related="appointment_id.vehicle_id", store=True)
    inspection_type_id = fields.Many2one(
        "carwash.inspection.type",
        string="Inspection Type",
        required=True,
        index=True,
        ondelete="restrict",
        default=lambda self: self.env["carwash.inspection.type"].search([], limit=1),
    )
    inspector_id = fields.Many2one("hr.employee", default=lambda self: self.env.user.employee_id)
    inspection_date = fields.Datetime(default=fields.Datetime.now)
    condition_notes = fields.Text()
    has_damage = fields.Boolean(string="Damage Found")
    photo_ids = fields.One2many("carwash.inspection.photo", "inspection_id", string="Photos")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    state = fields.Selection(
        [("draft", "In Progress"), ("done", "Completed")],
        default="draft",
        required=True,
        help="An inspection must be completed (mandatory checklist tasks ticked) before the booking moves on.",
    )
    checklist_line_ids = fields.One2many("carwash.checklist.line", "inspection_id", string="Checklist")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.inspection") or "New"
        return super().create(vals_list)

    def _checklist_template_domain(self):
        return super()._checklist_template_domain() + [
            ("inspection_type_id", "in", [False, self.inspection_type_id.id])
        ]

    @api.onchange("inspection_type_id")
    def _onchange_inspection_type_id(self):
        """New inspection: load the default checklist of the picked inspection type."""
        for inspection in self.filtered(lambda i: i.state == "draft" and not i.checklist_line_ids.filtered("is_done")):
            template = inspection._checklist_default_template()
            if template and template != inspection.checklist_template_id:
                inspection.checklist_template_id = template
                inspection._onchange_checklist_template_id()

    def action_complete(self):
        self._check_checklist_complete(self.env._("complete the inspection"))
        for inspection in self:
            inspection.write({"state": "done", "inspector_id": inspection.inspector_id.id or self.env.user.employee_id.id})
            # sudo: QC inspectors only read bookings; logging the result on it isn't an edit
            inspection.appointment_id.sudo().message_post(
                body=self.env._(
                    "%(type)s inspection %(name)s completed%(damage)s.",
                    type=inspection.inspection_type_id.name,
                    name=inspection.name,
                    damage=self.env._(" - damage recorded") if inspection.has_damage else "",
                )
            )
        return True

    def action_reopen(self):
        if any(i.appointment_id.state in ("done", "cancelled", "no_show") for i in self):
            raise UserError(self.env._("The booking is closed - its inspections can't be reopened."))
        self.write({"state": "draft"})
        return True


class CarwashInspectionPhoto(models.Model):
    _name = "carwash.inspection.photo"
    _description = "Car Wash Inspection Photo"

    inspection_id = fields.Many2one("carwash.inspection", required=True, ondelete="cascade")
    image = fields.Image(required=True, max_width=1920, max_height=1920)
    note = fields.Char()
