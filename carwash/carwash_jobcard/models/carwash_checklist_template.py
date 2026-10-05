from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashChecklistTemplate(models.Model):
    _name = "carwash.checklist.template"
    _description = "Car Wash Checklist Template"
    _order = "checklist_type, sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    checklist_type = fields.Selection(
        [("jobcard", "Job Card"), ("booking", "Booking Check-in"), ("inspection", "Inspection")],
        string="Used On",
        default="jobcard",
        required=True,
        help="Which step of the process this checklist belongs to.",
    )
    inspection_type_id = fields.Many2one(
        "carwash.inspection.type",
        string="Inspection Type",
        help="Only offer this checklist on inspections of this type (empty = any inspection).",
    )
    is_default = fields.Boolean(
        string="Apply Automatically",
        help="Loaded automatically on every new record of this step. Mandatory tasks must be "
        "ticked before the process can move on.",
    )
    description = fields.Text()
    item_ids = fields.One2many("carwash.checklist.template.item", "template_id", string="Tasks")

    def _prepare_checklist_line_vals(self):
        self.ensure_one()
        return [
            {"name": item.name, "sequence": item.sequence, "is_required": item.is_required, "template_item_id": item.id}
            for item in self.item_ids
        ]


class CarwashChecklistTemplateItem(models.Model):
    _name = "carwash.checklist.template.item"
    _description = "Car Wash Checklist Template Task"
    _order = "sequence, id"

    template_id = fields.Many2one("carwash.checklist.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    is_required = fields.Boolean(
        string="Mandatory", default=True, help="Must be ticked before the next step of the process."
    )


class CarwashChecklistLine(models.Model):
    """One task of a process checklist (booking check-in, inspection, booking request).

    Each owner model points here through its own many2one, so a line always belongs to
    exactly one record and is deleted with it.
    """

    _name = "carwash.checklist.line"
    _description = "Car Wash Process Checklist Task"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Task", required=True)
    template_item_id = fields.Many2one(
        "carwash.checklist.template.item", string="Template Task", ondelete="set null", readonly=True,
        help="Task of the checklist template this line was loaded from - it decides whether the task is mandatory.",
    )
    is_required = fields.Boolean(
        string="Mandatory", help="Template tasks take this from the template; tasks added by hand are optional unless ticked here."
    )
    is_done = fields.Boolean(string="Done")
    done_by_id = fields.Many2one("res.users", string="Done By", readonly=True)
    done_date = fields.Datetime(string="Done On", readonly=True)
    note = fields.Char()
    appointment_id = fields.Many2one("carwash.appointment", string="Booking", ondelete="cascade", index="btree_not_null")
    inspection_id = fields.Many2one("carwash.inspection", string="Inspection", ondelete="cascade", index="btree_not_null")

    @api.model_create_multi
    def create(self, vals_list):
        items = self.env["carwash.checklist.template.item"].browse(
            [vals["template_item_id"] for vals in vals_list if vals.get("template_item_id")]
        )
        mandatory = {item.id: item.is_required for item in items.sudo()}
        for vals in vals_list:
            # a template task is mandatory exactly when the template says so, whatever the client sent
            if vals.get("template_item_id") in mandatory:
                vals["is_required"] = mandatory[vals["template_item_id"]]
            if vals.get("is_done"):
                vals.setdefault("done_by_id", self.env.uid)
                vals.setdefault("done_date", fields.Datetime.now())
        return super().create(vals_list)

    def write(self, vals):
        template_lines = self.filtered("template_item_id")
        if "is_required" in vals and template_lines:
            # template tasks keep the template's "mandatory" flag - it can't be switched off on a record
            vals = dict(vals)
            is_required = vals.pop("is_required")
            (self - template_lines).write({"is_required": is_required})
            if not vals:
                return True
        if "is_done" in vals:
            if vals["is_done"]:
                vals = dict(vals, done_by_id=self.env.uid, done_date=fields.Datetime.now())
            else:
                vals = dict(vals, done_by_id=False, done_date=False)
        return super().write(vals)


class CarwashChecklistMixin(models.AbstractModel):
    """Process checklist on a record: loaded from a template, mandatory tasks gate a step.

    Inheriting models set ``_checklist_type`` and define ``checklist_line_ids`` as a
    one2many to ``carwash.checklist.line`` through their own many2one.
    """

    _name = "carwash.checklist.mixin"
    _description = "Car Wash Process Checklist Mixin"
    _checklist_type = None

    checklist_template_id = fields.Many2one(
        "carwash.checklist.template",
        string="Checklist",
        domain=lambda self: [("checklist_type", "=", self._checklist_type)],
        help="Picking a checklist loads its tasks.",
    )
    checklist_progress = fields.Integer(compute="_compute_checklist_status", string="Checklist Done (%)")
    checklist_pending_count = fields.Integer(compute="_compute_checklist_status", string="Mandatory Tasks Left")
    checklist_complete = fields.Boolean(compute="_compute_checklist_status", string="Checklist Complete")

    @api.depends("checklist_line_ids.is_done", "checklist_line_ids.is_required")
    def _compute_checklist_status(self):
        for record in self:
            lines = record.checklist_line_ids
            record.checklist_progress = round(100 * len(lines.filtered("is_done")) / len(lines)) if lines else 0
            record.checklist_pending_count = len(lines.filtered(lambda line: line.is_required and not line.is_done))
            record.checklist_complete = not record.checklist_pending_count

    def _checklist_template_domain(self):
        return [("checklist_type", "=", self._checklist_type)]

    def _checklist_default_template(self):
        self.ensure_one()
        return self.env["carwash.checklist.template"].search(
            self._checklist_template_domain() + [("is_default", "=", True)], limit=1
        )

    def _checklist_needs_auto_apply(self):
        """Whether this record should get the default checklist when it's created."""
        self.ensure_one()
        return True

    @api.onchange("checklist_template_id")
    def _onchange_checklist_template_id(self):
        for record in self:
            if record.checklist_template_id:
                record.checklist_line_ids = [(5, 0, 0)] + [
                    (0, 0, vals) for vals in record.checklist_template_id._prepare_checklist_line_vals()
                ]

    def _checklist_load(self, template):
        """Replace the checklist with `template`'s tasks."""
        for record in self:
            record.write(
                {
                    "checklist_template_id": template.id,
                    "checklist_line_ids": [(5, 0, 0)] + [(0, 0, vals) for vals in template._prepare_checklist_line_vals()],
                }
            )

    def _checklist_auto_apply(self):
        for record in self:
            if record.checklist_line_ids or not record._checklist_needs_auto_apply():
                continue
            template = record.checklist_template_id or record._checklist_default_template()
            if template:
                record._checklist_load(template)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._checklist_auto_apply()
        return records

    def action_reload_checklist(self):
        """Reload the tasks from the selected (or default) checklist - ticks are reset."""
        for record in self:
            template = record.checklist_template_id or record._checklist_default_template()
            if not template:
                raise UserError(self.env._("Select a checklist first."))
            record._checklist_load(template)

    def _check_checklist_complete(self, step):
        """Raise unless every mandatory task is ticked; `step` names what's being blocked."""
        for record in self:
            pending = record.checklist_line_ids.filtered(lambda line: line.is_required and not line.is_done)
            if pending:
                raise UserError(
                    self.env._(
                        "%(record)s: tick every mandatory checklist task before you %(step)s.\nStill open: %(tasks)s",
                        record=record.display_name,
                        step=step,
                        tasks=", ".join(pending.mapped("name")),
                    )
                )
