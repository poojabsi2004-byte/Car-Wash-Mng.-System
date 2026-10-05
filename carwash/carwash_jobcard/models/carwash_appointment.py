from odoo import Command, api, fields, models
from odoo.exceptions import UserError

PACKAGE_EDITABLE_STATES = ("draft", "confirmed", "arrived")


class CarwashAppointmentLine(models.Model):
    _inherit = "carwash.appointment.line"

    package_id = fields.Many2one("carwash.service.package", string="Package", readonly=True, ondelete="set null")


class CarwashAppointment(models.Model):
    _name = "carwash.appointment"
    _inherit = ["carwash.appointment", "carwash.checklist.mixin"]
    _checklist_type = "booking"

    checklist_line_ids = fields.One2many("carwash.checklist.line", "appointment_id", string="Check-in Checklist")
    open_inspection_count = fields.Integer(compute="_compute_open_inspection_count", string="Open Inspections")
    jobcard_ids = fields.One2many("carwash.jobcard", "appointment_id")
    jobcard_count = fields.Integer(compute="_compute_jobcard_count")
    inspection_ids = fields.One2many("carwash.inspection", "appointment_id")
    inspection_count = fields.Integer(compute="_compute_inspection_count")
    service_package_id = fields.Many2one(
        "carwash.service.package",
        string="Package",
        tracking=True,
        help="Selecting a package adds its services to the booking at the package price. "
        "Services added on top of the package are billed at their normal price.",
    )
    package_amount = fields.Float(compute="_compute_package_amounts", string="Package Amount")
    package_saving = fields.Float(compute="_compute_package_amounts", string="Package Saving")
    extra_services_amount = fields.Float(compute="_compute_package_amounts", string="Extra Services")
    has_pre_inspection = fields.Boolean(compute="_compute_has_inspections")
    has_post_inspection = fields.Boolean(compute="_compute_has_inspections")

    @api.depends("line_ids.package_id", "line_ids.price_subtotal", "line_ids.quantity", "line_ids.product_id",
                 "line_ids.is_discount_line")
    def _compute_package_amounts(self):
        for appointment in self:
            package_lines = appointment.line_ids.filtered("package_id")
            appointment.package_amount = sum(package_lines.mapped("price_subtotal"))
            appointment.package_saving = max(
                sum(line.product_id.list_price * line.quantity for line in package_lines) - appointment.package_amount,
                0.0,
            )
            appointment.extra_services_amount = sum(
                (appointment._service_lines() - package_lines).mapped("price_subtotal")
            )

    def _package_line_commands(self, package):
        """Commands replacing the current package lines with `package`'s services (extras are kept)."""
        self.ensure_one()
        commands = [Command.delete(line.id) for line in self.line_ids.filtered("package_id")]
        if package:
            commands += [Command.create(vals) for vals in package._prepare_booking_line_vals()]
        return commands

    @api.onchange("service_package_id")
    def _onchange_service_package_id(self):
        Line = self.env["carwash.appointment.line"]
        for appointment in self:
            if appointment.state not in PACKAGE_EDITABLE_STATES:
                continue
            extras = appointment.line_ids.filtered(lambda line: not line.package_id)
            package_lines = Line
            if appointment.service_package_id:
                for vals in appointment.service_package_id._prepare_booking_line_vals():
                    package_lines |= Line.new(vals)
            appointment.line_ids = package_lines | extras

    def _apply_service_package(self, package):
        """Server-side equivalent of picking a package in the form (leads, website, buttons)."""
        for appointment in self:
            if appointment.state not in PACKAGE_EDITABLE_STATES:
                raise UserError(self.env._("The package can only be changed before the service starts."))
            appointment.write(
                {"service_package_id": package.id, "line_ids": appointment._package_line_commands(package)}
            )
            if package:
                appointment.message_post(
                    body=self.env._(
                        "Package applied: %(package)s (%(amount)s)",
                        package=package.name,
                        amount=appointment.package_amount,
                    )
                )

    @api.depends("jobcard_ids")
    def _compute_jobcard_count(self):
        for appointment in self:
            appointment.jobcard_count = len(appointment.jobcard_ids)

    @api.depends("inspection_ids")
    def _compute_inspection_count(self):
        for appointment in self:
            appointment.inspection_count = len(appointment.inspection_ids)

    @api.depends("inspection_ids.state")
    def _compute_open_inspection_count(self):
        for appointment in self:
            appointment.open_inspection_count = len(appointment.inspection_ids.filtered(lambda i: i.state != "done"))

    def _check_inspections_completed(self, step, inspection_type=None):
        """Raise if an inspection (of `inspection_type`, or any) on the booking is still in progress."""
        for appointment in self:
            open_inspections = appointment.inspection_ids.filtered(
                lambda i: i.state != "done" and (not inspection_type or i.inspection_type_id == inspection_type)
            )
            if open_inspections:
                raise UserError(
                    self.env._(
                        "Complete inspection %(inspection)s before you %(step)s.",
                        inspection=open_inspections[0].name,
                        step=step,
                    )
                )

    @api.depends("inspection_ids.inspection_type_id")
    def _compute_has_inspections(self):
        pre_type = self.env.ref("carwash_jobcard.inspection_type_pre", raise_if_not_found=False)
        post_type = self.env.ref("carwash_jobcard.inspection_type_post", raise_if_not_found=False)
        for appointment in self:
            types = appointment.inspection_ids.inspection_type_id
            appointment.has_pre_inspection = bool(pre_type and pre_type in types)
            appointment.has_post_inspection = bool(post_type and post_type in types)

    @api.model
    def _can_run_services(self):
        # Same people who start the main service (washer/manager) run its individual services.
        return self.env.user.has_group("carwash_jobcard.group_carwash_washer") or self.env.user.has_group(
            "carwash_base.group_carwash_manager"
        )

    _WASHER_LOCKED_FIELDS = {"customer_id", "vehicle_id", "bay_id", "line_ids", "notes", "cancel_reason", "service_package_id"}

    def write(self, vals):
        # Server-side enforcement to match the form's readonly attributes: the form's
        # readonly="not can_manage_details" only disables the input in the browser, it
        # doesn't stop a direct write() call - and Washer now holds model-level write
        # access to carwash.appointment so the Start Service button works. self.env.su
        # exempts system-triggered writes (e.g. the website booking controller's
        # sudo()-based appointment creation), which aren't a real user bypassing the UI.
        if (
            not self.env.su
            and self._WASHER_LOCKED_FIELDS & set(vals)
            and not (
                self.env.user.has_group("carwash_base.group_carwash_user")
                or self.env.user.has_group("carwash_base.group_carwash_manager")
            )
        ):
            raise UserError(self.env._("You don't have permission to edit these booking details."))
        return super().write(vals)

    def action_apply_service_package(self):
        """(Re)apply the selected package - resets its services and prices to the package's current ones."""
        for appointment in self:
            appointment._apply_service_package(appointment.service_package_id)

    def action_remove_service_package(self):
        for appointment in self:
            appointment._apply_service_package(self.env["carwash.service.package"])

    def action_start_service(self):
        # Server-side enforcement, not just the button's UI visibility: Front Desk keeps
        # write access to carwash.appointment for their own actions (confirm/arrive/ready/
        # done), which would otherwise let this method still be called directly even with
        # the button hidden from them.
        if not (
            self.env.user.has_group("carwash_jobcard.group_carwash_washer")
            or self.env.user.has_group("carwash_base.group_carwash_manager")
        ):
            raise UserError(self.env._("Only a Washer or Manager can start service on a booking."))
        step = self.env._("start the service")
        self._check_checklist_complete(step)
        self._check_inspections_completed(step, self.env.ref("carwash_jobcard.inspection_type_pre", raise_if_not_found=False))
        res = super().action_start_service()
        for appointment in self:
            if not appointment.jobcard_ids:
                # sudo: auto-created as a side effect of starting service, not a job card
                # the acting user (e.g. Front Desk) is expected to manage directly.
                self.env["carwash.jobcard"].sudo().create({"appointment_id": appointment.id})
        return res

    def action_ready(self):
        self._check_services_done()
        for appointment in self:
            open_jobcards = appointment.jobcard_ids.filtered(lambda j: j.stages not in ("done", "cancel"))
            if open_jobcards:
                raise UserError(
                    self.env._("Job card %s must be completed (QC passed) before the vehicle can be marked ready.",
                                open_jobcards[0].name)
                )
        return super().action_ready()

    def action_done(self):
        self._check_inspections_completed(self.env._("hand the vehicle back"))
        return super().action_done()

    def action_open_inspection(self):
        """Pre-wash inspection once the vehicle has arrived, post-wash once the main service has ended."""
        self.ensure_one()
        xmlid = "carwash_jobcard.inspection_type_pre" if self.state == "arrived" else "carwash_jobcard.inspection_type_post"
        inspection_type = self.env.ref(xmlid, raise_if_not_found=False)
        existing = self.inspection_ids.filtered(lambda i: inspection_type and i.inspection_type_id == inspection_type)[:1]
        action = {
            "type": "ir.actions.act_window",
            "name": inspection_type.name if inspection_type else self.env._("Inspection"),
            "res_model": "carwash.inspection",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_appointment_id": self.id,
                "default_inspection_type_id": inspection_type.id if inspection_type else False,
            },
        }
        if existing:
            action["res_id"] = existing.id
        return action

    def action_view_jobcards(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Job Cards",
            "res_model": "carwash.jobcard",
            "view_mode": "list,form",
            "domain": [("appointment_id", "=", self.id)],
            "context": {"default_appointment_id": self.id},
        }

    def action_view_inspections(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Inspections",
            "res_model": "carwash.inspection",
            "view_mode": "list,form",
            "domain": [("appointment_id", "=", self.id)],
            "context": {"default_appointment_id": self.id},
        }
