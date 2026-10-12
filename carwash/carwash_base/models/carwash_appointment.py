from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CarwashAppointment(models.Model):
    _name = "carwash.appointment"
    _description = "Car Wash Booking"
    _inherit = ["mail.thread", "mail.activity.mixin", "carwash.booking.slot.mixin"]
    _order = "appointment_date desc, id desc"
    _slot_datetime_field = "appointment_date"
    _slot_bay_field = "bay_id"

    name = fields.Char(default="New", copy=False, readonly=True)
    customer_id = fields.Many2one("res.partner", required=True, tracking=True, index=True)
    vehicle_id = fields.Many2one(
        "carwash.vehicle", required=True, tracking=True, domain="[('customer_id', '=', customer_id)]"
    )
    # display only: the number plate chip in the booking form's header
    carwash_vehicle_plate = fields.Char(related="vehicle_id.license_plate", string="Plate")
    appointment_date = fields.Datetime(string="Booking Date", required=True, default=fields.Datetime.now, tracking=True)
    line_ids = fields.One2many("carwash.appointment.line", "appointment_id", string="Services")
    bay_id = fields.Many2one("carwash.bay", tracking=True, domain="[('company_id', 'in', [company_id, False])]")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("arrived", "Arrived"),
            ("in_service", "In Service"),
            ("ready", "Ready for Pickup"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("no_show", "No-Show"),
        ],
        default="draft",
        tracking=True,
        group_expand="_expand_states",
    )

    arrived_at = fields.Datetime(readonly=True)
    service_started_at = fields.Datetime(readonly=True)
    ready_at = fields.Datetime(readonly=True)
    done_at = fields.Datetime(readonly=True)
    cancel_reason = fields.Text()
    notes = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    sale_order_id = fields.Many2one("sale.order", readonly=True, copy=False, tracking=True)
    sale_order_state = fields.Selection(related="sale_order_id.state", string="Sales Order Status", readonly=True)
    amount_total = fields.Float(compute="_compute_amount_total", store=True)
    token_no = fields.Integer(readonly=True, copy=False)
    waiting_time = fields.Float(compute="_compute_waiting_time", string="Waiting Time (min)")

    stock_move_ids = fields.One2many("stock.move", "carwash_appointment_id")
    duration = fields.Float(compute="_compute_duration", store=True, help="Estimated duration in hours.")
    can_manage_details = fields.Boolean(compute="_compute_can_manage_details")
    can_run_services = fields.Boolean(compute="_compute_can_run_services")
    services_total = fields.Integer(compute="_compute_services_progress")
    services_done = fields.Integer(compute="_compute_services_progress")
    services_progress = fields.Float(compute="_compute_services_progress", string="Services Progress")
    all_services_done = fields.Boolean(compute="_compute_services_progress")

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in self._fields["state"].selection]

    def _compute_can_manage_details(self):
        can_manage = self.env.user.has_group("carwash_base.group_carwash_user") or self.env.user.has_group(
            "carwash_base.group_carwash_manager"
        )
        for appointment in self:
            appointment.can_manage_details = can_manage

    @api.model
    def _can_run_services(self):
        """Who may start/end the individual services of a running booking."""
        return self.env.user.has_group("carwash_base.group_carwash_user")

    def _compute_can_run_services(self):
        allowed = self._can_run_services()
        for appointment in self:
            appointment.can_run_services = allowed

    @api.depends("line_ids.service_state", "line_ids.is_discount_line")
    def _compute_services_progress(self):
        for appointment in self:
            states = appointment._service_lines().mapped("service_state")
            done = states.count("done")
            appointment.services_total = len(states)
            appointment.services_done = done
            appointment.services_progress = 100.0 * done / len(states) if states else 0.0
            appointment.all_services_done = done == len(states)

    def _slot_duration(self):
        return self.duration or 0.5

    def _slot_extra_depends(self):
        return ["line_ids.duration"]

    def _slot_exclude_booking_ids(self):
        return self._origin.ids

    def _service_lines(self):
        """Lines that are services to perform (discount lines are only price adjustments)."""
        return self.line_ids.filtered(lambda line: not line.is_discount_line)

    @api.depends("line_ids.duration")
    def _compute_duration(self):
        for appointment in self:
            appointment.duration = sum(appointment.line_ids.mapped("duration")) or 0.5

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        for appointment in self:
            appointment.amount_total = sum(appointment.line_ids.mapped("price_subtotal"))

    @api.depends("arrived_at", "service_started_at", "state")
    def _compute_waiting_time(self):
        now = fields.Datetime.now()
        for appointment in self:
            if not appointment.arrived_at:
                appointment.waiting_time = 0.0
                continue
            end = appointment.service_started_at or now
            appointment.waiting_time = (end - appointment.arrived_at).total_seconds() / 60.0

    _BAY_BLOCKING_STATES = ("confirmed", "arrived", "in_service")

    def _get_bay_window(self):
        """The time the booking holds its bay: its booked date / time + duration. Bookings on a bay
        clash only when these overlap - a vehicle in service doesn't stretch it (a late or early
        start doesn't block another booking's own time)."""
        self.ensure_one()
        return self.appointment_date, self.appointment_date + timedelta(hours=self.duration or 0.5)

    @api.constrains("state", "line_ids")
    def _check_services_required(self):
        """Services are required: a booking can't be saved (or confirmed) without one.
        Code that adds the services right after creating the booking (a package from the
        website or a booking request) sets the ``carwash_services_pending`` context."""
        if self.env.context.get("carwash_services_pending"):
            return
        for appointment in self:
            if appointment.state not in ("cancelled", "no_show") and not appointment._service_lines():
                raise ValidationError(self.env._(
                    "Add at least one service to the booking (Services tab) - a booking can't be saved without one."
                ))

    @api.constrains("bay_id", "company_id")
    def _check_bay_company(self):
        for appointment in self:
            bay_company = appointment.bay_id.company_id
            if bay_company and appointment.company_id and bay_company != appointment.company_id:
                raise ValidationError(self.env._(
                    "Bay %(bay)s belongs to %(bay_branch)s - pick a bay of %(branch)s for this booking.",
                    bay=appointment.bay_id.name, bay_branch=bay_company.name, branch=appointment.company_id.name,
                ))

    @api.constrains("bay_id", "appointment_date", "duration", "state")
    def _check_bay_time_conflict(self):
        for appointment in self:
            if not appointment.bay_id or appointment.state not in self._BAY_BLOCKING_STATES:
                continue
            start, end = appointment._get_bay_window()
            others = self.search(
                [
                    ("id", "!=", appointment.id),
                    ("bay_id", "=", appointment.bay_id.id),
                    ("state", "in", self._BAY_BLOCKING_STATES),
                ]
            )
            for other in others:
                o_start, o_end = other._get_bay_window()
                if start < o_end and o_start < end:
                    raise UserError(
                        self.env._(
                            "Bay %(bay)s is already booked by booking %(other)s in that time window "
                            "(%(start)s - %(end)s). Pick another bay or time.",
                            bay=appointment.bay_id.name,
                            other=other.name,
                            start=other._carwash_report_datetime(o_start),
                            end=other._slot_local(o_end).strftime("%I:%M %p"),
                        )
                    )

    @api.model
    def _get_available_slots(self, company, date, service, duration=None, tz=None, exclude_ids=None):
        """Return time slots on `date` with free-bay counts for `service` at `company`.

        `date` is a naive date (local to the company); `service` is a product.product
        with is_carwash_service=True. Returns a list of
        {'start': datetime, 'hour': float, 'bay_count': int, 'bay_ids': [ids]}, one entry
        per half-hour slot within business hours that has at least one free bay; `hour`
        is the slot's time of day as on the calendar.

        Without `tz`, calendar hours are used as server (UTC) times - the website booking
        flow relies on that. With `tz` (a pytz timezone), they're local times of that zone
        and `start` is the matching UTC datetime. `exclude_ids` are bookings to ignore when
        checking bays (e.g. the booking being rescheduled).
        """
        duration = duration or service.carwash_duration or 0.5
        hours = []
        for attendance in self._carwash_working_attendances(company, date):
            hour = float(attendance.hour_from)
            while hour + duration <= float(attendance.hour_to):
                hours.append(hour)
                hour += 0.5
        free = self._carwash_slot_availability(company, date, hours, duration, tz=tz, exclude_ids=exclude_ids)
        day_start = self._carwash_day_start(date, tz)
        return [
            {"start": day_start + timedelta(hours=hour), "hour": hour, "bay_count": len(bays), "bay_ids": bays.ids}
            for hour, bays in free.items()
        ]

    @api.model
    def _carwash_working_attendances(self, company, date):
        """Working periods of `company` on `date` - the lunch break (day_period "lunch") isn't bookable."""
        calendar = company.resource_calendar_id
        if not calendar:
            return self.env["resource.calendar.attendance"]
        weekday = date.weekday()
        return calendar.attendance_ids.filtered(
            lambda a: int(a.dayofweek) == weekday and a.day_period != "lunch"
        ).sorted("hour_from")

    @api.model
    def _carwash_day_start(self, date, tz=None):
        day_start = fields.Datetime.to_datetime(date)
        if tz:
            day_start = tz.localize(day_start).astimezone(pytz.utc).replace(tzinfo=None)
        return day_start

    @api.model
    def _carwash_slot_availability(self, company, date, hours, duration, tz=None, exclude_ids=None,
                                   anytime_hours=(), require_bay=True):
        """{start hour: free bays} for the `hours` of `date` that fit a working period for `duration`
        and have at least one free bay (see _get_available_slots for `tz` / `exclude_ids`).

        `anytime_hours` are offered outside the working hours too (slots set up for the branch itself).
        Without `require_bay`, a branch that has no bays yet gets its hours anyway (no bays: empty
        recordset) - its bay is then chosen when the vehicle arrives."""
        bays = self._carwash_bookable_bays(company)
        attendances = self._carwash_working_attendances(company, date)
        no_bays_ok = not require_bay and not self.env["carwash.bay"].search_count(
            [("company_id", "=", company.id), ("active", "=", True)])
        if (not bays and not no_bays_ok) or (not attendances and not anytime_hours):
            return {}
        duration = duration or 0.5
        day_start = self._carwash_day_start(date, tz)
        existing = self.search(
            [
                ("id", "not in", list(exclude_ids or [])),
                ("company_id", "=", company.id),
                ("bay_id", "!=", False),
                ("state", "in", self._BAY_BLOCKING_STATES),
                ("appointment_date", ">=", day_start - timedelta(days=1)),
                ("appointment_date", "<", day_start + timedelta(days=1)),
            ]
        )
        windows = [(appt._get_bay_window(), appt.bay_id.id) for appt in existing]
        result = {}
        anytime = {round(hour, 4) for hour in anytime_hours}
        for hour in sorted(hours):
            in_hours = any(a.hour_from <= hour and hour + duration <= a.hour_to for a in attendances)
            if not in_hours and round(hour, 4) not in anytime:
                continue
            start = day_start + timedelta(hours=hour)
            end = start + timedelta(hours=duration)
            busy = {bay_id for (o_start, o_end), bay_id in windows if start < o_end and o_start < end}
            free = bays.filtered(lambda b: b.id not in busy)
            if free or no_bays_ok:
                result[hour] = free
        return result

    @api.model
    def _carwash_bookable_bays(self, company):
        """Active bays of `company` that can take bookings - a bay under maintenance can't."""
        return self.env["carwash.bay"].search(
            [("company_id", "=", company.id), ("active", "=", True), ("state", "!=", "maintenance")]
        )

    @api.model
    def _carwash_free_bays(self, company, start, duration, exclude_ids=None):
        """Active bays of `company` with no blocking booking overlapping [start, start + duration)."""
        end = start + timedelta(hours=duration or 0.5)
        bays = self._carwash_bookable_bays(company)
        busy = self.search(
            [
                ("id", "not in", list(exclude_ids or [])),
                ("company_id", "=", company.id),
                ("bay_id", "in", bays.ids),
                ("state", "in", self._BAY_BLOCKING_STATES),
            ]
        )
        busy_bay_ids = set()
        for appointment in busy:
            o_start, o_end = appointment._get_bay_window()
            if start < o_end and o_start < end:
                busy_bay_ids.add(appointment.bay_id.id)
        return bays.filtered(lambda bay: bay.id not in busy_bay_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"]._carwash_next_by_code("carwash.appointment", company) or "New"
            if not vals.get("token_no"):
                # the day's tokens count per branch
                today_start = fields.Datetime.to_string(fields.Date.context_today(self))
                tomorrow_start = fields.Datetime.to_string(fields.Date.context_today(self) + timedelta(days=1))
                count_today = self.sudo().search_count([
                    ("company_id", "=", company.id),
                    ("create_date", ">=", today_start), ("create_date", "<", tomorrow_start),
                ])
                vals["token_no"] = count_today + 1
        return super().create(vals_list)

    def _carwash_report_datetime(self, value):
        """`value` (UTC datetime) as printed on car wash documents - in the branch's timezone."""
        return self._slot_local(value).strftime("%d %b, %y %I:%M %p") if value else ""

    def action_print_booking(self):
        """Booking Confirmation, or Service Receipt once the booking is Done."""
        return self.env.ref("carwash_base.action_report_carwash_booking").report_action(self, config=False)

    def _check_workflow_state(self, allowed, step):
        """Server-side guard of the booking workflow (buttons are only shown in the right state,
        but actions can also be called through RPC / automations)."""
        labels = dict(self._fields["state"]._description_selection(self.env))
        for appointment in self:
            if appointment.state not in allowed:
                raise UserError(self.env._(
                    "Booking %(booking)s is %(state)s - it can't be %(step)s.",
                    booking=appointment.name, state=labels.get(appointment.state, appointment.state), step=step,
                ))

    def action_confirm(self):
        self._check_workflow_state(("draft",), self.env._("confirmed"))
        for appointment in self:
            if not appointment._service_lines():
                raise UserError(self.env._("Add at least one service in the Services tab before confirming the booking."))
            appointment.state = "confirmed"

    @api.model
    def _carwash_bay_busy_reason(self, bay):
        """Why `bay` can't take a vehicle now (under maintenance), or False. Another vehicle in
        service on it doesn't block: bookings on a bay clash only when their booked times
        overlap (_check_bay_time_conflict)."""
        if bay and bay.state == "maintenance":
            return self.env._("Bay %s is under maintenance.", bay.name)
        return False

    def _check_bay_free_now(self, todo):
        """The booking's bay must not be under maintenance. Checked when the vehicle arrives and
        when its service starts; `todo` says what to do instead."""
        for appointment in self:
            reason = self._carwash_bay_busy_reason(appointment.bay_id)
            if reason:
                raise UserError(f"{reason} {todo}")

    def action_arrive(self):
        self._check_workflow_state(("confirmed",), self.env._("marked as arrived"))
        self._check_bay_free_now(self.env._(
            "Pick a free bay on the booking before marking the vehicle arrived, or clear the Bay and assign one when a bay is free."
        ))
        for appointment in self:
            appointment.write({"state": "arrived", "arrived_at": fields.Datetime.now()})

    def action_start_service(self):
        self._check_workflow_state(("arrived",), self.env._("started"))
        for appointment in self:
            if not appointment.bay_id:
                raise UserError(self.env._("Assign a bay before starting the service."))
        self._check_bay_free_now(self.env._("Pick a free bay on the booking before starting the service."))
        for appointment in self:
            appointment.bay_id.with_context(carwash_bay_by_service=True).state = "occupied"
            appointment.write({"state": "in_service", "service_started_at": fields.Datetime.now()})

    def _check_services_done(self):
        for appointment in self:
            unfinished = appointment._service_lines().filtered(lambda line: line.service_state != "done")
            if unfinished:
                raise UserError(
                    self.env._(
                        "Finish every service before ending the main service. Still open: %s",
                        ", ".join(unfinished.product_id.mapped("display_name")),
                    )
                )

    def action_ready(self):
        self._check_workflow_state(("in_service",), self.env._("ended"))
        self._check_services_done()
        for appointment in self:
            appointment.write({"state": "ready", "ready_at": fields.Datetime.now()})
            bay = appointment.bay_id
            # the bay is free once every vehicle in service on it has ended
            if bay and bay.state == "occupied" and not bay._carwash_running_booking():
                bay.with_context(carwash_allow_bay_release=True).state = "free"

    def action_done(self):
        self._check_workflow_state(("ready",), self.env._("completed"))
        for appointment in self:
            appointment.write({"state": "done", "done_at": fields.Datetime.now()})
            # sudo: reading stock_move_ids requires Inventory-app read access the acting
            # user (e.g. Front Desk) isn't expected to have just to check idempotency here.
            if not appointment.sudo().stock_move_ids:
                appointment._create_consumption_moves()
            # its quotation becomes the sales order (invoice + payment on the booking)
            appointment._carwash_confirm_sale_order()

    def action_cancel(self):
        # an arrived customer may still leave before the wash starts
        self._check_workflow_state(("draft", "confirmed", "arrived"), self.env._("cancelled"))
        for appointment in self:
            bay = appointment.bay_id
            # a booking that never started doesn't hold its bay: free it only if no other vehicle is on it
            if bay and bay.state == "occupied" and not bay._carwash_running_booking():
                bay.with_context(carwash_allow_bay_release=True).state = "free"
            appointment.state = "cancelled"

    def action_no_show(self):
        self._check_workflow_state(("confirmed",), self.env._("marked as no-show"))
        for appointment in self:
            appointment.state = "no_show"

    def _carwash_consumption_items(self):
        """(consumable, quantity) the booking used: each service's consumables x its quantity."""
        self.ensure_one()
        return [
            (mat.product_id, mat.quantity * line.quantity)
            for line in self.sudo().line_ids
            for mat in line.product_id.product_tmpl_id.carwash_material_line_ids
        ]

    def _create_consumption_moves(self):
        """Completing the booking: book what it used out of the branch's stock."""
        self.ensure_one()
        return self._carwash_book_out(self._carwash_consumption_items())

    def _carwash_book_out(self, items):
        """Book (consumable, quantity) `items` out of the branch's stock for this booking; returns the moves."""
        # sudo: computing and creating consumable stock moves touches the service's
        # material recipe (Manager-only) and Inventory-app models the acting user (e.g.
        # Front Desk, completing an appointment) isn't expected to have direct access to -
        # this whole flow is a system-triggered side effect, not a manual stock operation.
        self.ensure_one()
        appointment = self.sudo()
        Move = self.env["stock.move"].sudo()
        warehouse = self.env["stock.warehouse"].sudo().search([("company_id", "=", appointment.company_id.id)], limit=1)
        if not warehouse:
            return Move
        move_vals = [
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom": product.uom_id.id,
                "location_id": warehouse.lot_stock_id.id,
                "location_dest_id": product.property_stock_production.id,
                "origin": appointment.name,
                "carwash_appointment_id": appointment.id,
            }
            for product, qty in items
            if qty > 0
        ]
        if not move_vals:
            return Move
        moves = Move.create(move_vals)
        moves._action_confirm()
        moves._action_assign()
        # record the full usage even when the branch is short of stock (stock goes negative and
        # shows up in the low-stock alerts) - otherwise the move would stay waiting with 0 done
        for move in moves:
            move.quantity = move.product_uom_qty
        moves.picked = True
        moves._action_done()
        return moves

    def _create_and_confirm_sale_order(self):
        self.ensure_one()
        order = self.env["sale.order"].sudo().create(
            {
                "partner_id": self.customer_id.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "order_line": [
                    (
                        0,
                        0,
                        dict(
                            {
                                "product_id": line.product_id.id,
                                "product_uom_qty": line.quantity,
                                "price_unit": line.price_unit,
                            },
                            # keep the booking line's wording (e.g. which package it belongs to)
                            **({"name": line.description} if line.description else {}),
                        ),
                    )
                    for line in self.line_ids
                ],
            }
        )
        order.sudo().action_confirm()
        self.sale_order_id = order.id

    def action_view_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }
