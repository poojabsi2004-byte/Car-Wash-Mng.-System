from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashJobcard(models.Model):
    _name = "carwash.jobcard"
    _description = "Car Wash Job Card"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    appointment_id = fields.Many2one(
        "carwash.appointment", string="Booking", required=True, ondelete="cascade", tracking=True, index=True
    )
    customer_id = fields.Many2one(related="appointment_id.customer_id", store=True)
    vehicle_id = fields.Many2one(related="appointment_id.vehicle_id", store=True)
    bay_id = fields.Many2one(related="appointment_id.bay_id", store=True)

    assigned_employee_ids = fields.Many2many(
        "hr.employee",
        string="Assigned Staff",
        tracking=True,
        domain=lambda self: [("user_id.group_ids", "in", self._get_assignable_group_ids())],
    )
    checklist_template_id = fields.Many2one(
        "carwash.checklist.template", string="Task Checklist", tracking=True,
        domain=[("checklist_type", "=", "jobcard")],
    )
    checklist_line_ids = fields.One2many("carwash.jobcard.checklist.line", "jobcard_id", string="Tasks")
    task_id = fields.Many2one("project.task", readonly=True, copy=False, ondelete="set null")

    stages = fields.Selection(
        [
            ("draft", "New"),
            ("in_progress", "In Progress"),
            ("qc", "Quality Check"),
            ("done", "Completed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        group_expand="_expand_stages",
    )

    start_time = fields.Datetime(readonly=True)
    end_time = fields.Datetime(readonly=True)
    qc_inspector_id = fields.Many2one("hr.employee", readonly=True, tracking=True)
    qc_notes = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    checklist_progress = fields.Integer(compute="_compute_checklist_progress", string="Tasks Done")

    @api.depends("checklist_line_ids.is_check")
    def _compute_checklist_progress(self):
        for jobcard in self:
            lines = jobcard.checklist_line_ids
            jobcard.checklist_progress = round(100 * len(lines.filtered("is_check")) / len(lines)) if lines else 0

    @api.model
    def _expand_stages(self, stages, domain):
        return [key for key, _label in self._fields["stages"].selection]

    @api.model
    def _get_assignable_group_ids(self):
        groups = self.env["res.groups"]
        for xml_id in ("carwash_jobcard.group_carwash_washer", "carwash_base.group_carwash_manager"):
            group = self.env.ref(xml_id, raise_if_not_found=False)
            if group:
                groups |= group
        return groups.ids

    @api.onchange("checklist_template_id")
    def _onchange_checklist_template_id(self):
        for jobcard in self:
            if jobcard.checklist_template_id:
                jobcard.checklist_line_ids = [(5, 0, 0)] + [
                    (0, 0, {"name": item.name, "sequence": item.sequence})
                    for item in jobcard.checklist_template_id.item_ids
                ]

    @api.model_create_multi
    def create(self, vals_list):
        default_template = self.env["carwash.checklist.template"].search(
            [("checklist_type", "=", "jobcard"), ("is_default", "=", True)], limit=1
        )
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.jobcard") or "New"
            template = self.env["carwash.checklist.template"].browse(vals.get("checklist_template_id")) or default_template
            if template and not vals.get("checklist_line_ids"):
                vals["checklist_template_id"] = template.id
                vals["checklist_line_ids"] = [
                    (0, 0, {"name": item.name, "sequence": item.sequence}) for item in template.item_ids
                ]
        return super().create(vals_list)

    def action_start(self):
        for jobcard in self:
            if not jobcard.assigned_employee_ids:
                raise UserError(self.env._("Assign at least one staff member before starting the job card."))
            jobcard.write({"stages": "in_progress", "start_time": fields.Datetime.now()})
            if not jobcard.task_id:
                jobcard._create_task()

    def _create_task(self):
        self.ensure_one()
        project = self.env.ref("carwash_jobcard.project_carwash_jobs", raise_if_not_found=False)
        if not project:
            return
        task = self.env["project.task"].sudo().create(
            {
                "name": f"{self.name} - {self.vehicle_id.license_plate or ''}",
                "project_id": project.id,
                "company_id": self.company_id.id,
                "user_ids": [(6, 0, self.assigned_employee_ids.user_id.ids)],
            }
        )
        self.task_id = task.id

    def action_submit_qc(self):
        for jobcard in self:
            unchecked = jobcard.checklist_line_ids.filtered(lambda line: not line.is_check)
            if unchecked:
                raise UserError(self.env._("All checklist tasks must be checked before submitting for QC."))
            jobcard.stages = "qc"

    def action_qc_pass(self):
        for jobcard in self:
            jobcard.write(
                {
                    "stages": "done",
                    "end_time": fields.Datetime.now(),
                    "qc_inspector_id": self.env.user.employee_id.id,
                }
            )
            jobcard._log_timesheet()

    def _log_timesheet(self):
        self.ensure_one()
        if not (self.task_id and self.start_time and self.end_time and self.assigned_employee_ids):
            return
        # Assumption: the full duration is attributed to the first assigned employee rather
        # than split across a multi-person team - no attribution policy was specified.
        employee = self.assigned_employee_ids[0]
        hours = (self.end_time - self.start_time).total_seconds() / 3600.0
        self.env["account.analytic.line"].sudo().create(
            {
                "name": self.name,
                "task_id": self.task_id.id,
                "project_id": self.task_id.project_id.id,
                "employee_id": employee.id,
                "unit_amount": round(hours, 2),
            }
        )

    def action_qc_fail(self):
        for jobcard in self:
            jobcard.write({"stages": "in_progress", "qc_inspector_id": self.env.user.employee_id.id})
            jobcard.checklist_line_ids.write({"is_check": False})

    def action_cancel(self):
        for jobcard in self:
            jobcard.stages = "cancel"

    def action_view_task(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "form",
            "res_id": self.task_id.id,
        }


class CarwashJobcardChecklistLine(models.Model):
    _name = "carwash.jobcard.checklist.line"
    _description = "Car Wash Job Card Task"
    _order = "sequence, id"

    jobcard_id = fields.Many2one("carwash.jobcard", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    is_check = fields.Boolean(string="Done")
