from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

PACKAGE_EDITABLE_STATES = ("draft", "confirmed", "arrived")


class CarwashAppointmentLine(models.Model):
    _inherit = "carwash.appointment.line"

    package_id = fields.Many2one("carwash.service.package", string="Package", readonly=True, ondelete="set null")
    jobcard_service_ids = fields.One2many("carwash.jobcard.service", "appointment_line_id", string="Job Card Services")
    jobcard_id = fields.Many2one("carwash.jobcard", compute="_compute_jobcard_id", string="Job Card")
    jobcard_consumption_id = fields.Many2one(
        "carwash.jobcard.consumption", string="Extra Consumable", readonly=True, copy=False, index="btree_not_null",
        ondelete="set null", help="This line charges extra consumables used on a job card (Consumption tab).",
    )

    def unlink(self):
        charges = self.filtered("jobcard_consumption_id")
        if charges and not self.env.context.get("carwash_consumption_sync"):
            raise UserError(self.env._(
                "%(line)s comes from job card %(jobcard)s - change or remove it on the job card's Consumption tab.",
                line=charges[0].description, jobcard=charges[0].jobcard_consumption_id.jobcard_id.name,
            ))
        return super().unlink()

    def write(self, vals):
        charges = self.filtered("jobcard_consumption_id")
        if charges and {"product_id", "quantity", "price_unit"} & set(vals) and not self.env.context.get("carwash_consumption_sync"):
            raise UserError(self.env._(
                "%(line)s comes from job card %(jobcard)s - change it on the job card's Consumption tab.",
                line=charges[0].description, jobcard=charges[0].jobcard_consumption_id.jobcard_id.name,
            ))
        return super().write(vals)

    _rec_names_search = ["product_id", "description"]

    @api.depends("jobcard_service_ids.jobcard_id.stages")
    def _compute_jobcard_id(self):
        for line in self:
            line.jobcard_id = line.jobcard_service_ids.jobcard_id.filtered(lambda jobcard: jobcard.stages != "cancel")[:1]

    def action_start_line(self):
        self._check_staff_assigned()
        self._check_staff_free()
        return super().action_start_line()

    def _check_staff_assigned(self):
        """A service starts only once its job card has its staff (crew) assigned."""
        for line in self:
            jobcard = line.sudo().jobcard_id
            if not jobcard:
                raise UserError(self.env._(
                    "%(service)s isn't on a job card yet - put it on a job card and assign its staff before starting it.",
                    service=line.product_id.display_name,
                ))
            if not jobcard.assigned_employee_ids or not jobcard.qc_inspector_id:
                raise UserError(self.env._(
                    "Assign the staff and the QC inspector on job card %(jobcard)s before starting %(service)s.",
                    jobcard=jobcard.name, service=line.product_id.display_name,
                ))

    def _check_staff_free(self):
        """Staff on several job cards finish one service before starting one on another job card."""
        Row = self.env["carwash.jobcard.service"].sudo()  # sudo: the other job cards may be outside the user's view
        for line in self:
            jobcard = line.jobcard_id
            staff = jobcard.assigned_employee_ids
            if not staff:
                continue
            busy = Row.search([
                ("service_state", "=", "in_progress"), ("jobcard_id", "!=", jobcard.id),
                ("jobcard_id.stages", "!=", "cancel"), ("jobcard_id.assigned_employee_ids", "in", staff.ids),
            ], limit=1)
            if busy:
                raise UserError(self.env._(
                    "%(staff)s is still working on %(service)s (job card %(jobcard)s). End that service before "
                    "starting %(new)s on job card %(this)s.",
                    staff=", ".join((busy.jobcard_id.assigned_employee_ids & staff).mapped("name")),
                    service=busy.product_id.display_name, jobcard=busy.jobcard_id.name,
                    new=line.product_id.display_name, this=jobcard.name,
                ))

    @api.depends("product_id", "quantity")
    def _compute_display_name(self):
        for line in self:
            name = line.product_id.display_name or line.description or ""
            line.display_name = f"{name} × {line.quantity:g}" if line.quantity and line.quantity != 1 else name


class CarwashAppointment(models.Model):
    _name = "carwash.appointment"
    _inherit = ["carwash.appointment", "carwash.checklist.mixin"]
    _checklist_type = "booking"

    checklist_line_ids = fields.One2many("carwash.checklist.line", "appointment_id", string="Check-in Checklist")
    inspection_feature_enabled = fields.Boolean(compute="_compute_feature_flags")
    rating_feature_enabled = fields.Boolean(compute="_compute_feature_flags")
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

    def _service_lines(self):
        """The extra consumables charged from the job cards aren't services to perform."""
        return super()._service_lines().filtered(lambda line: not line.jobcard_consumption_id)

    def _create_consumption_moves(self):
        moves = super()._create_consumption_moves()
        # the job cards' consumption is booked out of stock now: it can't be changed any more
        self.sudo().jobcard_ids.filtered(lambda jobcard: jobcard.stages != "cancel").consumption_line_ids.write(
            {"booked_out": True}
        )
        return moves

    def _carwash_consumption_items(self):
        """What the job cards list on their Consumption tab; services no job card covers use their
        consumables."""
        self.ensure_one()
        jobcards = self.sudo().jobcard_ids.filtered(lambda jobcard: jobcard.stages != "cancel")
        covered = jobcards.jobcard_service_ids.appointment_line_id
        items = [(line.product_id, line.quantity) for line in jobcards.consumption_line_ids]
        items += [
            (mat.product_id, mat.quantity * line.quantity)
            for line in self.sudo().line_ids - covered
            for mat in line.product_id.product_tmpl_id.carwash_material_line_ids
        ]
        return items

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

    def _compute_feature_flags(self):
        Feature = self.env["carwash.feature"]
        inspection = Feature._enabled("carwash_jobcard.group_carwash_inspection")
        rating = Feature._enabled("carwash_jobcard.group_carwash_rating")
        for appointment in self:
            appointment.inspection_feature_enabled = inspection
            appointment.rating_feature_enabled = rating

    def _checklist_vehicle_type(self):
        return self.vehicle_id.vehicle_type_id

    def _checklist_needs_auto_apply(self):
        # the check-in checklist belongs to the vehicle's arrival, not to the booking itself
        return self.state not in ("draft", "confirmed", "cancelled", "no_show")

    def action_arrive(self):
        res = super().action_arrive()
        self._checklist_auto_apply()
        return res

    @api.depends("inspection_ids.state")
    def _compute_open_inspection_count(self):
        for appointment in self:
            appointment.open_inspection_count = len(appointment.inspection_ids.filtered(lambda i: i.state != "done"))

    def _check_inspections_completed(self, step, inspection_type=None):
        """Raise if an inspection (of `inspection_type`, or any) on the booking is still in progress."""
        if not self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_inspection"):
            return
        for appointment in self:
            # sudo: every inspection of the booking counts, not only the ones the user may see (washer / QC)
            open_inspections = appointment.sudo().inspection_ids.filtered(
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
            types = appointment.sudo().inspection_ids.inspection_type_id
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
        Jobcard = self.env["carwash.jobcard"]
        for appointment in self:
            # sudo: the booking's job cards of every staff member (a washer only sees their own)
            active = appointment.sudo().jobcard_ids.filtered(lambda jobcard: jobcard.stages != "cancel")
            remaining = Jobcard._remaining_service_lines(appointment)
            if not active or remaining:
                # sudo: auto-created as a side effect of starting service, not a job card the acting
                # user (e.g. Front Desk) is expected to manage directly. It covers the services that
                # no job card has yet (all of them for the first one).
                Jobcard.sudo().create({
                    "appointment_id": appointment.id,
                    "jobcard_service_ids": [Command.create({"appointment_line_id": line.id}) for line in remaining],
                })
        return res

    def action_ready(self):
        self._check_services_done()
        for appointment in self:
            open_jobcards = appointment.sudo().jobcard_ids.filtered(lambda j: j.stages not in ("done", "cancel"))
            if open_jobcards:
                raise UserError(
                    self.env._("Job card %s must be completed (QC passed) before the vehicle can be marked ready.",
                                open_jobcards[0].name)
                )
        return super().action_ready()

    def action_done(self):
        self._check_inspections_completed(self.env._("hand the vehicle back"))
        res = super().action_done()
        # the job cards' staff timesheet tasks are done with the booking
        self.sudo().jobcard_ids.filtered(lambda jobcard: jobcard.stages != "cancel")._carwash_close_task("1_done")
        return res

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

    # ------------------------------------------------------------------ staff payables of the booking
    staff_payable_ids = fields.Many2many(
        "carwash.staff.commission", compute="_compute_staff_payables", compute_sudo=True, string="Staff Payables",
        help="What the staff earned on this booking's job cards (recorded when the job card passes QC).",
    )
    staff_payable_total = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="Goes to Staff", currency_field="currency_id",
        help="Staff payables of the crew (Assigned Staff) of this booking's job cards.",
    )
    qc_payable_total = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="Goes to QC", currency_field="currency_id",
        help="Staff payables of the QC inspectors of this booking's job cards.",
    )
    staff_paid = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="Paid to Staff & QC", currency_field="currency_id",
    )
    staff_to_pay = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="Staff To Pay", currency_field="currency_id",
    )
    qc_to_pay = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="QC To Pay", currency_field="currency_id",
    )
    staff_bill_ids = fields.Many2many(
        "account.move", compute="_compute_staff_payables", compute_sudo=True, string="Staff Bills",
    )
    staff_bill_count = fields.Integer(compute="_compute_staff_payables", compute_sudo=True, string="Staff Bill Count")
    amount_kept = fields.Monetary(
        compute="_compute_staff_payables", compute_sudo=True, string="Kept by the Car Wash", currency_field="currency_id",
        help="Customer paid minus what goes to the staff and the QC.",
    )

    # compute_sudo: worked out from every staff payable and staff bill of the booking (washers / QC can read only
    # their own payables and no bills) - they can still open the booking
    @api.depends("jobcard_ids.commission_ids.state", "jobcard_ids.commission_ids.amount")
    def _compute_staff_payables(self):
        for booking in self:
            # sudo: the front desk sees the booking's staff payables (washers / QC only their own records)
            payables = booking.sudo().jobcard_ids.commission_ids.filtered(lambda c: c.state != "cancelled")
            staff = payables.filtered(lambda c: c.payable_role == "staff")
            qc = payables - staff
            bills = payables.bill_id.filtered(lambda m: m.state != "cancel")
            booking.staff_payable_ids = payables
            booking.staff_payable_total = sum(staff.mapped("amount"))
            booking.qc_payable_total = sum(qc.mapped("amount"))
            booking.staff_paid = sum(payables.filtered(lambda c: c.state == "paid").mapped("amount"))
            booking.staff_to_pay = sum(staff.filtered(lambda c: c.state == "to_pay").mapped("amount"))
            booking.qc_to_pay = sum(qc.filtered(lambda c: c.state == "to_pay").mapped("amount"))
            booking.staff_bill_ids = bills
            booking.staff_bill_count = len(bills)
            booking.amount_kept = booking.amount_paid - sum(payables.mapped("amount"))

    def _carwash_time_window(self):
        """(start, end) of the booking in UTC: its date and time + its estimated service time."""
        self.ensure_one()
        start = self.appointment_date
        return start, start + timedelta(hours=self.duration or 0.5)

    def _carwash_can_bill(self):
        """Also billable once the service has ended (Ready): End Service needs every job card QC-passed. Not while
        the booking is still In Service, even when its job cards have passed QC."""
        if super()._carwash_can_bill():
            return True
        jobcards = self.sudo().jobcard_ids.filtered(lambda j: j.stages != "cancel")
        return self.state == "ready" and all(j.stages == "done" for j in jobcards)

    def _carwash_pay_payables(self, role):
        """Pay the booking's staff payables of `role` (staff / qc): their bills (created when needed), then Odoo's
        Register Payment (Cash by default); they are Paid once the payment is registered."""
        self._carwash_check_billable()  # after End Service, like the customer's payment
        payables = self.sudo().jobcard_ids.commission_ids.filtered(lambda c: c.state == "to_pay" and c.payable_role == role)
        if not payables:
            raise UserError(self.env._("There is nothing left to pay to the %s on this booking.",
                                       self.env._("QC") if role == "qc" else self.env._("staff")))
        return payables.with_env(self.env).action_pay()

    def action_pay_staff(self):
        """Pay what the crew earned on this booking: a bill per staff member, validated and paid from Cash."""
        return self._carwash_pay_payables("staff")

    def action_pay_qc(self):
        """Pay what the QC inspectors earned on this booking: a bill per inspector, validated and paid from Cash."""
        return self._carwash_pay_payables("qc")

    def action_view_staff_bills(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_move_in_invoice_type")
        action.update({"domain": [("id", "in", self.staff_bill_ids.ids)], "context": {"default_move_type": "in_invoice"}})
        if len(self.staff_bill_ids) == 1:
            action.update({"views": [(False, "form")], "view_mode": "form", "res_id": self.staff_bill_ids.id})
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
