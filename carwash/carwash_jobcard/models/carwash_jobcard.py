from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CarwashJobcard(models.Model):
    _name = "carwash.jobcard"
    _description = "Car Wash Job Card"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    appointment_id = fields.Many2one(
        "carwash.appointment", string="Booking", required=True, ondelete="cascade", tracking=True, index=True
    )
    jobcard_service_ids = fields.One2many(
        "carwash.jobcard.service", "jobcard_id", string="Services",
        help="The booking's services this job card covers. A service is on one job card only - "
        "a second job card takes the services that are left.",
    )
    service_line_ids = fields.Many2many(
        "carwash.appointment.line", string="Service Lines",
        compute="_compute_service_line_ids", inverse="_inverse_service_line_ids",
        help="The booking services of the Services tab.",
    )
    taken_service_line_ids = fields.Many2many(
        "carwash.appointment.line", compute="_compute_taken_service_line_ids",
        help="Services of the booking already on another (not cancelled) job card.",
    )
    customer_id = fields.Many2one(related="appointment_id.customer_id", store=True)
    vehicle_id = fields.Many2one(related="appointment_id.vehicle_id", store=True)
    bay_id = fields.Many2one(related="appointment_id.bay_id", store=True)

    assigned_employee_ids = fields.Many2many(
        "hr.employee",
        string="Assigned Staff",
        tracking=True,
        domain="[('carwash_can_do_jobs', '=', True), ('company_id', '=', company_id)]",
        help="Staff doing the work: staff members of this branch whose role works on job cards "
        "(Washer, Detailer, Supervisor...).",
    )
    checklist_template_id = fields.Many2one(
        "carwash.checklist.template", string="Task Checklist", tracking=True,
        domain=[("checklist_type", "=", "jobcard")],
    )
    checklist_line_ids = fields.One2many("carwash.jobcard.checklist.line", "jobcard_id", string="Tasks")
    booking_state = fields.Selection(related="appointment_id.state", string="Booking Status")
    unassigned_service_count = fields.Integer(
        compute="_compute_unassigned_service_count", string="Services Without Job Card",
        help="Services of the booking that no job card covers yet - Create Job Card makes one for them.",
    )
    consumption_line_ids = fields.One2many(
        "carwash.jobcard.consumption", "jobcard_id", string="Consumption",
        help="Products used on this job card - booked out of stock when the booking is completed.",
    )
    consumption_extra_amount = fields.Float(
        compute="_compute_consumption_extra_amount", string="Extra Consumables Charged",
        help="Extra consumables used on this job card - added to the booking total.",
    )
    task_id = fields.Many2one("project.task", readonly=True, copy=False, ondelete="set null")
    timesheet_hours = fields.Float(
        related="task_id.effective_hours", string="Staff Timesheet",
        help="Staff time logged on this job card's timesheet (start to finish of the job).",
    )

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
    rework_count = fields.Integer(
        string="Reworks", readonly=True, copy=False,
        help="Times quality control sent the job card back for rework (QC Fail).",
    )
    qc_inspector_id = fields.Many2one(
        "hr.employee", string="QC Inspector", tracking=True,
        domain="[('carwash_can_do_qc', '=', True), ('company_id', '=', company_id)]",
        help="Who checks the work: staff members of this branch whose role does quality checks (QC Inspector, "
        "Supervisor...). Assign it when the job goes to quality check; if left empty, the person clicking "
        "QC Pass / Fail is recorded.",
    )
    commission_ids = fields.One2many("carwash.staff.commission", "jobcard_id", string="Staff Payables")
    commission_total = fields.Monetary(compute="_compute_commission_total", string="Staff Payable", currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id")
    qc_notes = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    checklist_progress = fields.Integer(compute="_compute_checklist_progress", string="Tasks Done")
    services_ended = fields.Boolean(
        compute="_compute_services_ended", help="Every service of the job card is ended: it can be submitted for QC.",
    )

    @api.depends("checklist_line_ids.is_check")
    def _compute_checklist_progress(self):
        for jobcard in self:
            lines = jobcard.checklist_line_ids
            jobcard.checklist_progress = round(100 * len(lines.filtered("is_check")) / len(lines)) if lines else 0

    @api.depends("jobcard_service_ids.service_state")
    def _compute_services_ended(self):
        for jobcard in self:
            services = jobcard.jobcard_service_ids
            jobcard.services_ended = bool(services) and all(state == "done" for state in services.mapped("service_state"))

    @api.depends("commission_ids.amount", "commission_ids.state")
    def _compute_commission_total(self):
        for jobcard in self:
            jobcard.commission_total = sum(jobcard.commission_ids.filtered(lambda c: c.state != "cancelled").mapped("amount"))

    @api.model
    def _expand_stages(self, stages, domain):
        return [key for key, _label in self._fields["stages"].selection]

    @api.onchange("checklist_template_id")
    def _onchange_checklist_template_id(self):
        for jobcard in self:
            if jobcard.checklist_template_id:
                jobcard.checklist_line_ids = [(5, 0, 0)] + [
                    (0, 0, {"name": item.name, "sequence": item.sequence})
                    for item in jobcard.checklist_template_id.item_ids
                ]

    @api.depends("jobcard_service_ids.appointment_line_id")
    def _compute_service_line_ids(self):
        for jobcard in self:
            jobcard.service_line_ids = jobcard.jobcard_service_ids.appointment_line_id

    def _inverse_service_line_ids(self):
        for jobcard in self:
            wanted = jobcard.service_line_ids
            rows = jobcard.jobcard_service_ids
            commands = [Command.delete(row.id) for row in rows if row.appointment_line_id not in wanted]
            commands += [Command.create({"appointment_line_id": line.id}) for line in wanted - rows.appointment_line_id]
            if commands:
                jobcard.jobcard_service_ids = commands

    @api.depends(
        "appointment_id", "appointment_id.jobcard_ids.jobcard_service_ids.appointment_line_id", "appointment_id.jobcard_ids.stages"
    )
    def _compute_taken_service_line_ids(self):
        for jobcard in self:
            # sudo: other staff's job cards too (a washer / QC only sees their own)
            others = jobcard.appointment_id.sudo().jobcard_ids.filtered(
                lambda other: other._origin != jobcard._origin and other.stages != "cancel"
            )
            jobcard.taken_service_line_ids = others.jobcard_service_ids.appointment_line_id

    def _carwash_unassigned_service_lines(self):
        """Services of this job card's booking that are on no (not cancelled) job card at all."""
        self.ensure_one()
        # sudo: other staff's job cards count too (a washer / QC only sees their own)
        appointment = self.appointment_id.sudo()
        covered = appointment.jobcard_ids.filtered(lambda jobcard: jobcard.stages != "cancel").jobcard_service_ids
        return appointment._service_lines() - covered.appointment_line_id

    @api.depends("appointment_id")
    def _compute_unassigned_service_count(self):
        for jobcard in self:
            open_booking = jobcard.appointment_id.state not in ("done", "cancelled", "no_show")
            jobcard.unassigned_service_count = (
                len(jobcard._carwash_unassigned_service_lines()) if jobcard._origin.id and open_booking else 0
            )

    # ------------------------------------------------------------------ payments once QC passed (admin)
    booking_payment_state = fields.Selection(related="appointment_id.payment_state", string="Customer Payment")
    staff_to_pay = fields.Monetary(compute="_compute_payables_to_pay", string="Staff To Pay", currency_field="currency_id")
    qc_to_pay = fields.Monetary(compute="_compute_payables_to_pay", string="QC To Pay", currency_field="currency_id")

    @api.depends("commission_ids.state", "commission_ids.amount", "commission_ids.payable_role")
    def _compute_payables_to_pay(self):
        for jobcard in self:
            to_pay = jobcard.sudo().commission_ids.filtered(lambda c: c.state == "to_pay")
            jobcard.staff_to_pay = sum(to_pay.filtered(lambda c: c.payable_role == "staff").mapped("amount"))
            jobcard.qc_to_pay = sum(to_pay.filtered(lambda c: c.payable_role == "qc").mapped("amount"))

    def action_customer_payment(self):
        """The customer's payment for the booking (invoiced first when needed) - after End Service."""
        self.ensure_one()
        return self.appointment_id.action_register_payment()

    def _carwash_pay_jobcard_payables(self, role):
        """Pay this job card's staff payables of `role`: bills (created when needed) + Register Payment."""
        self.appointment_id._carwash_check_billable()  # after the booking's End Service
        payables = self.sudo().commission_ids.filtered(lambda c: c.state == "to_pay" and c.payable_role == role)
        if not payables:
            raise UserError(self.env._("There is nothing left to pay on this job card."))
        return payables.with_env(self.env).action_pay()

    def action_pay_staff(self):
        """Pay the crew of this job card: a bill per staff member, validated and paid from Cash."""
        return self._carwash_pay_jobcard_payables("staff")

    def action_pay_qc(self):
        """Pay the QC inspector of this job card: a bill, validated and paid from Cash."""
        return self._carwash_pay_jobcard_payables("qc")

    def action_view_booking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Booking"),
            "res_model": "carwash.appointment",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.appointment_id.id,
        }

    def action_create_remaining_jobcard(self):
        """A new job card for the booking's services that no job card covers yet."""
        self.ensure_one()
        lines = self._carwash_unassigned_service_lines()
        if not lines:
            raise UserError(self.env._(
                "Every service of booking %s is already on a job card.", self.appointment_id.name))
        jobcard = self.create({
            "appointment_id": self.appointment_id.id,
            "company_id": self.appointment_id.company_id.id,
            "jobcard_service_ids": [Command.create({"appointment_line_id": line.id}) for line in lines],
        })
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Job Card"),
            "res_model": "carwash.jobcard",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": jobcard.id,
        }

    def _remaining_service_lines(self, appointment):
        """Services of the booking that no (other, not cancelled) job card covers yet."""
        others = appointment.sudo().jobcard_ids.filtered(
            lambda other: other._origin not in self._origin and other.stages != "cancel"
        )
        return appointment._service_lines() - others.jobcard_service_ids.appointment_line_id

    @api.onchange("appointment_id")
    def _onchange_appointment_services(self):
        """The first job card of a booking takes all its services; a further one starts empty
        and picks from the services that are left."""
        for jobcard in self:
            appointment = jobcard.appointment_id
            first = not appointment.sudo().jobcard_ids.filtered(
                lambda other: other._origin != jobcard._origin and other.stages != "cancel"
            )
            lines = jobcard._remaining_service_lines(appointment) if appointment and first else []
            jobcard.jobcard_service_ids = [Command.clear()] + [Command.create({"appointment_line_id": line.id}) for line in lines]

    @api.model
    def _default_checklist_template(self, appointment):
        """The task list applied automatically: the one for the vehicle's type, else the general one."""
        vehicle_type = appointment.vehicle_id.vehicle_type_id
        templates = self.env["carwash.checklist.template"].search([
            ("checklist_type", "=", "jobcard"), ("is_default", "=", True),
            "|", ("vehicle_type_ids", "=", False), ("vehicle_type_ids", "in", vehicle_type.ids),
        ])
        return templates.sorted(lambda t: (not t.vehicle_type_ids, t.sequence, t.id))[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            appointment = self.env["carwash.appointment"].browse(vals.get("appointment_id"))
            if appointment and not {"service_line_ids", "jobcard_service_ids"} & set(vals) and not appointment.sudo().jobcard_ids.filtered(
                lambda other: other.stages != "cancel"
            ):
                # the booking's first job card covers all its services
                vals["jobcard_service_ids"] = [
                    Command.create({"appointment_line_id": line.id}) for line in self._remaining_service_lines(appointment)
                ]
            if vals.get("name", "New") == "New":
                company = self.env["res.company"].browse(vals.get("company_id")) or appointment.company_id or self.env.company
                vals["name"] = self.env["ir.sequence"]._carwash_next_by_code("carwash.jobcard", company) or "New"
            template = (
                self.env["carwash.checklist.template"].browse(vals.get("checklist_template_id"))
                or self._default_checklist_template(appointment)
            )
            if template and not vals.get("checklist_line_ids"):
                vals["checklist_template_id"] = template.id
                vals["checklist_line_ids"] = [
                    (0, 0, {"name": item.name, "sequence": item.sequence}) for item in template.item_ids
                ]
        jobcards = super().create(vals_list)
        jobcards._fill_consumption()
        return jobcards

    @api.depends("consumption_line_ids.amount")
    def _compute_consumption_extra_amount(self):
        for jobcard in self:
            jobcard.consumption_extra_amount = sum(jobcard.consumption_line_ids.mapped("amount"))

    def _consumption_from_services(self, rows=None):
        """Consumption lines for the job card's services (or `rows` of them): each service's
        consumables x its quantity."""
        self.ensure_one()
        vals = []
        for row in self.jobcard_service_ids if rows is None else rows:
            line = row.appointment_line_id
            # sudo: the services' consumables are Manager-only configuration
            for mat in line.product_id.product_tmpl_id.sudo().carwash_material_line_ids:
                vals.append({
                    "product_id": mat.product_id.id,
                    "quantity": mat.quantity * (line.quantity or 1.0),
                    "service_id": line.product_id.id,
                })
        return vals

    def _fill_consumption(self):
        """An open job card without consumption gets its services' consumables."""
        for jobcard in self:
            if jobcard.consumption_line_ids or jobcard.stages == "cancel":
                continue
            vals = jobcard._consumption_from_services()
            if vals:
                jobcard.sudo().consumption_line_ids = [Command.create(v) for v in vals]

    def action_reload_consumption(self):
        """Consumption tab > Load from Services: list the services' consumables again."""
        for jobcard in self:
            if jobcard.stages == "cancel":
                raise UserError(self.env._("Job card %s is cancelled - its consumption can't be changed.", jobcard.name))
            if jobcard.consumption_line_ids.filtered("booked_out"):
                raise UserError(self.env._(
                    "The consumption of job card %s is already booked out of stock - add a line for anything else used.",
                    jobcard.name,
                ))
            # the extra lines (charged to the customer) stay
            jobcard.consumption_line_ids = [
                Command.unlink(line.id) for line in jobcard.consumption_line_ids.filtered(lambda l: not l.is_extra)
            ] + [Command.create(vals) for vals in jobcard._consumption_from_services()]
        return True

    @api.constrains("assigned_employee_ids", "qc_inspector_id")
    def _check_staff_have_users(self):
        """Only staff with a login can be put on a job card (as crew or QC inspector)."""
        for jobcard in self:
            without_user = (jobcard.assigned_employee_ids | jobcard.qc_inspector_id).filtered(lambda e: not e.user_id)
            if without_user:
                raise ValidationError(self.env._(
                    "%s has no user - only staff with a login can be assigned to a job card. "
                    "Create their user first (Staff > New Staff Member).",
                    ", ".join(without_user.mapped("name")),
                ))

    _OPEN_STAGES = ("draft", "in_progress", "qc")

    @api.constrains("assigned_employee_ids", "appointment_id")
    def _check_staff_not_double_booked(self):
        """A staff member can be on several job cards of the same booking, but not on a job card of another
        booking at the same time (its booking time overlaps) while they are on an open job card."""
        for jobcard in self.filtered(lambda j: j.stages in self._OPEN_STAGES and j.assigned_employee_ids):
            booking = jobcard.appointment_id
            start, end = booking._carwash_time_window()
            # sudo: the other job cards may be outside the user's view (washers see their own only)
            others = self.sudo().search([
                ("id", "!=", jobcard.id),
                ("appointment_id", "!=", booking.id),
                ("stages", "in", list(self._OPEN_STAGES)),
                ("assigned_employee_ids", "in", jobcard.assigned_employee_ids.ids),
            ])
            for other in others:
                other_start, other_end = other.appointment_id._carwash_time_window()
                if other_start < end and start < other_end:
                    busy = other.assigned_employee_ids & jobcard.assigned_employee_ids
                    local = other.appointment_id._slot_local
                    raise ValidationError(self.env._(
                        "%(staff)s is already working on job card %(jobcard)s (booking %(booking)s, %(start)s - %(end)s) "
                        "at that time - assign another staff member, or put them on this booking once that job is done.",
                        staff=", ".join(busy.mapped("name")), jobcard=other.name, booking=other.appointment_id.name,
                        start=local(other_start).strftime("%d %b %H:%M"), end=local(other_end).strftime("%H:%M"),
                    ))

    def _check_jobcard_step(self, stages, groups, step):
        """Server-side guard: right stage and right role (the buttons alone can be bypassed via RPC)."""
        labels = dict(self._fields["stages"]._description_selection(self.env))
        if not (self.env.su or any(self.env.user.has_group(g) for g in groups)):
            raise UserError(self.env._("You don't have the role needed to %s.", step))
        for jobcard in self:
            if jobcard.stages not in stages:
                raise UserError(self.env._(
                    "Job card %(jobcard)s is %(stage)s - you can't %(step)s now.",
                    jobcard=jobcard.name, stage=labels.get(jobcard.stages, jobcard.stages), step=step,
                ))

    _WORK_GROUPS = ("carwash_jobcard.group_carwash_washer", "carwash_base.group_carwash_manager")
    _QC_GROUPS = ("carwash_jobcard.group_carwash_qc", "carwash_base.group_carwash_manager")

    def action_start(self):
        self._check_jobcard_step(("draft",), self._WORK_GROUPS, self.env._("start the job card"))
        for jobcard in self:
            if not jobcard.assigned_employee_ids:
                raise UserError(self.env._("Assign at least one staff member before starting the job card."))
            if not jobcard.qc_inspector_id:
                raise UserError(self.env._("Assign the QC inspector before starting the job card."))
            jobcard.write({"stages": "in_progress", "start_time": fields.Datetime.now()})
            jobcard._fill_consumption()
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
        self._check_jobcard_step(("in_progress",), self._WORK_GROUPS, self.env._("submit it for QC"))
        states = dict(self.env["carwash.appointment.line"]._fields["service_state"]._description_selection(self.env))
        for jobcard in self:
            if not jobcard.jobcard_service_ids:
                raise UserError(self.env._(
                    "Job card %s has no services - add them on the Services tab and end them before submitting for QC.",
                    jobcard.name,
                ))
            open_services = jobcard.jobcard_service_ids.filtered(lambda service: service.service_state != "done")
            if open_services:
                raise UserError(self.env._(
                    "End every service before submitting for QC - still open: %s.",
                    ", ".join(f"{service.appointment_line_id.product_id.display_name} ({states.get(service.service_state)})"
                              for service in open_services),
                ))
            unchecked = jobcard.checklist_line_ids.filtered(lambda line: not line.is_check)
            if unchecked:
                raise UserError(self.env._("All checklist tasks must be checked before submitting for QC."))
            # someone has to check the work (it may have been cleared since the job card started)
            if not jobcard.qc_inspector_id:
                raise UserError(self.env._(
                    "Assign the QC inspector of job card %s (Crew > QC Inspector) before submitting it for QC.",
                    jobcard.name,
                ))
            jobcard.stages = "qc"

    def action_qc_pass(self):
        # only a QC inspector / manager approves - a washer can't pass their own work (and earn commission on it)
        self._check_jobcard_step(("qc",), self._QC_GROUPS, self.env._("pass quality control"))
        for jobcard in self:
            jobcard.write(
                {
                    "stages": "done",
                    "end_time": fields.Datetime.now(),
                    "qc_inspector_id": jobcard.qc_inspector_id.id or self.env.user.employee_id.id,
                }
            )
            jobcard._log_timesheet()
            jobcard._create_staff_commissions()

    def _commission_base_amount(self):
        """Service value the staff payable is calculated on: the job card's services (all the booking's
        services if none are linked). Price adjustments such as a membership discount aren't services,
        free member washes count as 0."""
        self.ensure_one()
        # the job card's own services (a booking split over several job cards pays each crew once)
        lines = self.service_line_ids or self.appointment_id._service_lines()
        return sum(lines.mapped("price_subtotal"))

    def _carwash_payable_vals(self, employee, role, base_amount):
        """The staff payable of `employee` on this job card (role staff / qc), from their staff payable rule."""
        commission_type, rate, fixed = employee._carwash_commission_rule()
        if commission_type == "percent":
            amount = base_amount * rate / 100.0
        elif commission_type == "fixed":
            amount = fixed
        else:
            return None
        amount = self.company_id.currency_id.round(amount)
        if amount <= 0:
            return None
        return {
            "employee_id": employee.id,
            "payable_role": role,
            "jobcard_id": self.id,
            "commission_type": commission_type,
            "base_amount": base_amount,
            "rate": rate if commission_type == "percent" else 0.0,
            "amount": amount,
            "company_id": self.company_id.id,
        }

    def _create_staff_commissions(self):
        """On QC pass: one staff payable per assigned staff member (a % is on their share of the service value)
        and one for the QC inspector (a % is on the job card's service value)."""
        self.ensure_one()
        if not self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_commission"):
            return
        active = self.commission_ids.filtered(lambda c: c.state != "cancelled")
        base = self._commission_base_amount()
        vals_list = []
        staff = self.assigned_employee_ids
        for employee in staff - active.filtered(lambda c: c.payable_role == "staff").employee_id:
            vals_list.append(self._carwash_payable_vals(employee, "staff", base / len(staff)))
        qc = self.qc_inspector_id
        if qc and qc not in active.filtered(lambda c: c.payable_role == "qc").employee_id:
            vals_list.append(self._carwash_payable_vals(qc, "qc", base))
        vals_list = [vals for vals in vals_list if vals]
        if vals_list:
            # sudo: earned automatically on QC pass - QC inspectors don't manage commissions
            commissions = self.env["carwash.staff.commission"].sudo().create(vals_list)
            self.message_post(body=self.env._(
                "Staff Payable recorded: %s",
                ", ".join(f"{c.employee_id.name}{' (QC)' if c.payable_role == 'qc' else ''} {c.amount:.2f}"
                          for c in commissions),
            ))

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
        self._check_jobcard_step(("qc",), self._QC_GROUPS, self.env._("send it back for rework"))
        for jobcard in self:
            jobcard.write({
                "stages": "in_progress",
                "qc_inspector_id": jobcard.qc_inspector_id.id or self.env.user.employee_id.id,
                "rework_count": jobcard.rework_count + 1,
            })
            jobcard.checklist_line_ids.write({"is_check": False})

    def action_cancel(self):
        self._check_jobcard_step(("draft", "in_progress", "qc"), ("carwash_base.group_carwash_manager",), self.env._("cancel it"))
        for jobcard in self:
            jobcard.stages = "cancel"
        self.commission_ids.sudo().action_cancel()
        self._carwash_close_task("1_canceled")

    def _carwash_close_task(self, state):
        """Close the staff timesheet task (Time Tracking) with its job / booking: 1_done or 1_canceled.
        sudo: the front desk completes bookings without Project rights."""
        tasks = self.sudo().task_id.filtered(lambda task: task.state not in ("1_done", "1_canceled"))
        if tasks:
            tasks.write({"state": state})

    def action_print_jobcard(self):
        return self.env.ref("carwash_jobcard.action_report_carwash_jobcard").report_action(self, config=False)

    def action_print_quality_check(self):
        return self.env.ref("carwash_jobcard.action_report_carwash_quality_check").report_action(self, config=False)

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


class CarwashJobcardService(models.Model):
    """One booking service on a job card (the job card's Services tab)."""

    _name = "carwash.jobcard.service"
    _description = "Car Wash Job Card Service"
    _order = "sequence, id"

    jobcard_id = fields.Many2one("carwash.jobcard", string="Job Card", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    appointment_line_id = fields.Many2one(
        "carwash.appointment.line", string="Service", required=True, ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(related="appointment_line_id.product_id", string="Product")
    package_id = fields.Many2one(related="appointment_line_id.package_id")
    quantity = fields.Float(related="appointment_line_id.quantity")
    service_state = fields.Selection(related="appointment_line_id.service_state", string="Status")
    start_time = fields.Datetime(related="appointment_line_id.start_time", string="Started")
    end_time = fields.Datetime(related="appointment_line_id.end_time", string="Ended")
    actual_duration = fields.Float(related="appointment_line_id.actual_duration", string="Time (min)")
    appointment_state = fields.Selection(related="appointment_line_id.appointment_id.state", string="Booking Status")

    _jobcard_line_uniq = models.Constraint(
        "UNIQUE(jobcard_id, appointment_line_id)", "This service is already on the job card."
    )

    @api.constrains("appointment_line_id", "jobcard_id")
    def _check_service(self):
        for row in self:
            jobcard, line = row.jobcard_id, row.appointment_line_id
            if line.appointment_id != jobcard.appointment_id or line.is_discount_line or line.jobcard_consumption_id:
                raise ValidationError(self.env._(
                    "%(service)s isn't a service of booking %(booking)s.",
                    service=line.product_id.display_name, booking=jobcard.appointment_id.name,
                ))
            if jobcard.stages == "cancel":
                continue
            # sudo: a washer only sees their own job cards, the rule is about all of the booking's
            other = self.sudo().search([
                ("appointment_line_id", "=", line.id), ("id", "!=", row.id), ("jobcard_id.stages", "!=", "cancel"),
            ], limit=1)
            if other:
                raise ValidationError(self.env._(
                    "%(service)s is already on job card %(other)s - a service can be on one job card only.",
                    service=line.product_id.display_name, other=other.jobcard_id.name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        rows = super().create(vals_list)
        # a service added to an open job card brings its consumables to the Consumption tab
        for jobcard in rows.jobcard_id:
            if jobcard.stages in ("done", "cancel"):
                continue
            vals = jobcard._consumption_from_services(rows.filtered(lambda row: row.jobcard_id == jobcard))
            if vals:
                jobcard.sudo().consumption_line_ids = [Command.create(v) for v in vals]
        return rows

    def unlink(self):
        removed = [(row.jobcard_id, row.appointment_line_id.product_id) for row in self]
        res = super().unlink()
        # ... and takes them away when it leaves (moved to another job card / removed)
        for jobcard, service in removed:
            if not jobcard.exists() or jobcard.stages in ("done", "cancel"):
                continue
            if service not in jobcard.jobcard_service_ids.appointment_line_id.product_id:
                jobcard.sudo().consumption_line_ids.filtered(
                    lambda line: line.service_id == service and not line.booked_out
                ).unlink()
        return res

    def action_start_line(self):
        return self.appointment_line_id.action_start_line()

    def action_end_line(self):
        return self.appointment_line_id.action_end_line()


class CarwashJobcardConsumption(models.Model):
    """A product used on a job card (Consumption tab): filled in from the services' consumables,
    adjusted by the crew - booked out of stock when the booking is completed."""

    _name = "carwash.jobcard.consumption"
    _description = "Car Wash Job Card Consumption"
    _order = "sequence, id"

    jobcard_id = fields.Many2one("carwash.jobcard", string="Job Card", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product", string="Product", required=True, domain=[("is_storable", "=", True)],
        help="Consumable used (shampoo, wax, cloth...).",
    )
    quantity = fields.Float(string="Quantity Used", required=True, default=1.0)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Unit")
    # extra: used on top of the services' own consumables - charged to the customer on the booking
    is_extra = fields.Boolean(
        string="Extra (Charged)", default=False,
        help="Used on top of the services' consumables: its amount is charged to the customer - added to the "
        "booking total (an 'Extra Consumables' line).",
    )
    price_unit = fields.Float(
        string="Unit Price", compute="_compute_price_unit", store=True, readonly=False, digits="Product Price",
        help="Price charged per unit (the product's sales price to start with).",
    )
    amount = fields.Float(string="Amount", compute="_compute_amount", store=True)
    appointment_line_id = fields.Many2one(
        "carwash.appointment.line", string="Booking Line", readonly=True, copy=False, ondelete="set null",
        help="The booking line charging this extra consumable.",
    )
    service_id = fields.Many2one(
        "product.product", string="For Service", domain=[("is_carwash_service", "=", True)],
        help="The service it was used for.",
    )
    company_id = fields.Many2one(related="jobcard_id.company_id", store=True)

    _quantity_positive = models.Constraint("CHECK(quantity > 0)", "The quantity used must be positive.")

    @api.depends("product_id", "is_extra")
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.product_id.lst_price if line.is_extra else 0.0

    @api.depends("quantity", "price_unit", "is_extra")
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.price_unit if line.is_extra else 0.0

    booked_out = fields.Boolean(
        string="Booked Out", readonly=True, copy=False,
        help="Already taken out of stock: the booking is completed. Such a line can't be changed any more - "
        "add a new line for anything else used (it is booked out at once).",
    )

    def _check_editable(self, jobcards, lines=None):
        """Consumption can be added to and changed until it is booked out of stock (booking completed),
        also on a completed job card; a cancelled job card's consumption is final. (The system itself
        - filling in, booking out - works as superuser.)"""
        if self.env.su:
            return
        cancelled = jobcards.filtered(lambda jobcard: jobcard.stages == "cancel")
        if cancelled:
            raise UserError(self.env._("Job card %s is cancelled - its consumption can't be changed.", cancelled[0].name))
        booked = lines.filtered("booked_out") if lines else lines
        if booked:
            raise UserError(self.env._(
                "%(product)s is already booked out of stock (booking %(booking)s is completed) - it can't be "
                "changed any more. Add a new line for anything else used.",
                product=booked[0].product_id.display_name, booking=booked[0].jobcard_id.appointment_id.name,
            ))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_editable(self.env["carwash.jobcard"].browse([vals.get("jobcard_id") for vals in vals_list]))
        lines = super().create(vals_list)
        lines._carwash_sync_charge()
        lines._book_out_if_booking_completed()
        return lines

    def write(self, vals):
        changed = set(vals) - {"sequence", "booked_out", "appointment_line_id"}
        self._check_editable(
            self.jobcard_id | self.env["carwash.jobcard"].browse(vals.get("jobcard_id")), self if changed else None
        )
        res = super().write(vals)
        if {"product_id", "quantity", "price_unit", "is_extra"} & set(vals):
            self._carwash_sync_charge()
        return res

    def unlink(self):
        self._check_editable(self.jobcard_id, self)
        charges = self.sudo().appointment_line_id
        res = super().unlink()
        charges.with_context(carwash_consumption_sync=True).unlink()
        return res

    # ------------------------------------------------------------------
    # Extra consumables: charged on the booking
    # ------------------------------------------------------------------
    def _carwash_charge_vals(self):
        self.ensure_one()
        return {
            "description": self.env._(
                "Extra consumables: %(product)s (%(qty)s %(uom)s)",
                product=self.product_id.display_name, qty=f"{self.quantity:g}", uom=self.uom_id.name or "",
            ),
            "quantity": 1.0,
            "price_unit": self.amount,
        }

    def _carwash_sync_charge(self):
        """An extra line is charged on its booking (one 'Extra Consumables' line, kept up to date); a line that
        isn't extra any more takes its charge away. Done as superuser: the crew records what they used, the
        booking is updated for them."""
        product = self.env.ref("carwash_jobcard.product_extra_consumables", raise_if_not_found=False)
        Line = self.env["carwash.appointment.line"].sudo().with_context(carwash_consumption_sync=True)
        for line in self.sudo():
            booking = line.jobcard_id.appointment_id
            charge = line.appointment_line_id
            if not line.is_extra or not product or booking.state in ("cancelled", "no_show") or not line.amount:
                if charge:
                    line.appointment_line_id = False
                    charge.with_context(carwash_consumption_sync=True).unlink()
                continue
            vals = line._carwash_charge_vals()
            if charge:
                if (charge.description, charge.price_unit) != (vals["description"], vals["price_unit"]):
                    charge.with_context(carwash_consumption_sync=True).write(vals)
                continue
            # once the booking's order is confirmed, the new booking line goes on it by itself (carwash_base)
            line.appointment_line_id = Line.create({
                **vals,
                "appointment_id": booking.id,
                "product_id": product.id,
                "service_state": "done",  # nothing to perform: it only charges what was used
                "jobcard_consumption_id": line.id,
            })

    def _book_out_if_booking_completed(self):
        """A line added once the booking is completed (its consumption already booked out of stock)
        is booked out at once."""
        lines = self.filtered(
            lambda line: not line.booked_out and line.jobcard_id.stages != "cancel"
            and line.jobcard_id.appointment_id.state == "done"
        )
        for booking in lines.jobcard_id.appointment_id:
            extra = lines.filtered(lambda line: line.jobcard_id.appointment_id == booking)
            booking._carwash_book_out([(line.product_id, line.quantity) for line in extra])
            extra.sudo().write({"booked_out": True})
            # sudo: the crew may not be allowed to post on the booking itself
            booking.sudo().message_post(body=self.env._(
                "Extra consumption booked out of stock (job card %(jobcard)s): %(products)s",
                jobcard=", ".join(extra.jobcard_id.mapped("name")),
                products=", ".join(f"{line.product_id.display_name} {line.quantity:g} {line.uom_id.name}" for line in extra),
            ))
