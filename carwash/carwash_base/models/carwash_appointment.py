from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class CarwashAppointment(models.Model):
    _name = "carwash.appointment"
    _description = "Car Wash Booking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "appointment_date desc, id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    customer_id = fields.Many2one("res.partner", required=True, tracking=True, index=True)
    vehicle_id = fields.Many2one(
        "carwash.vehicle", required=True, tracking=True, domain="[('customer_id', '=', customer_id)]"
    )
    appointment_date = fields.Datetime(string="Booking Date", required=True, default=fields.Datetime.now, tracking=True)
    line_ids = fields.One2many("carwash.appointment.line", "appointment_id", string="Services")
    bay_id = fields.Many2one("carwash.bay", tracking=True)
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
        self.ensure_one()
        start = self.service_started_at if (self.state == "in_service" and self.service_started_at) else self.appointment_date
        return start, start + timedelta(hours=self.duration or 0.5)

    @api.constrains("bay_id", "appointment_date", "duration", "state", "service_started_at")
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
                            "Bay %(bay)s is already booked by booking %(other)s in that time window.",
                            bay=appointment.bay_id.name,
                            other=other.name,
                        )
                    )

    @api.model
    def _get_available_slots(self, company, date, service, duration=None):
        """Return time slots on `date` with free-bay counts for `service` at `company`.

        `date` is a naive date (local to the company); `service` is a product.product
        with is_carwash_service=True. Returns a list of
        {'start': datetime, 'bay_count': int, 'bay_ids': [ids]} in company timezone-naive
        (server) datetimes, one entry per half-hour slot within business hours that has
        at least one free bay.
        """
        calendar = company.resource_calendar_id
        bays = self.env["carwash.bay"].search([("company_id", "=", company.id), ("active", "=", True)])
        if not calendar or not bays:
            return []
        duration = duration or service.carwash_duration or 0.5
        weekday = date.weekday()
        attendances = calendar.attendance_ids.filtered(lambda a: int(a.dayofweek) == weekday)
        if not attendances:
            return []
        day_start = fields.Datetime.to_datetime(date)
        existing = self.search(
            [
                ("company_id", "=", company.id),
                ("bay_id", "!=", False),
                ("state", "in", self._BAY_BLOCKING_STATES),
                ("appointment_date", ">=", day_start),
                ("appointment_date", "<", day_start + timedelta(days=1)),
            ]
        )
        slots = []
        for attendance in attendances:
            hour = float(attendance.hour_from)
            hour_to = float(attendance.hour_to)
            while hour + duration <= hour_to:
                slot_start = day_start + timedelta(hours=hour)
                slot_end = slot_start + timedelta(hours=duration)
                busy_bay_ids = set()
                for appt in existing:
                    o_start, o_end = appt._get_bay_window()
                    if slot_start < o_end and o_start < slot_end:
                        busy_bay_ids.add(appt.bay_id.id)
                free_bays = bays.filtered(lambda b: b.id not in busy_bay_ids)
                if free_bays:
                    slots.append({"start": slot_start, "bay_count": len(free_bays), "bay_ids": free_bays.ids})
                hour += 0.5
        return slots

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.appointment") or "New"
            if not vals.get("token_no"):
                today_start = fields.Datetime.to_string(fields.Date.context_today(self))
                tomorrow_start = fields.Datetime.to_string(fields.Date.context_today(self) + timedelta(days=1))
                count_today = self.search_count(
                    [("create_date", ">=", today_start), ("create_date", "<", tomorrow_start)]
                )
                vals["token_no"] = count_today + 1
        return super().create(vals_list)

    def action_confirm(self):
        for appointment in self:
            if not appointment._service_lines():
                raise UserError(self.env._("Add at least one service line before confirming."))
            appointment.state = "confirmed"

    def action_arrive(self):
        for appointment in self:
            appointment.write({"state": "arrived", "arrived_at": fields.Datetime.now()})

    def action_start_service(self):
        for appointment in self:
            if not appointment.bay_id:
                raise UserError(self.env._("Assign a bay before starting the service."))
            if appointment.bay_id.state != "free":
                raise UserError(self.env._("Bay %s is not free.", appointment.bay_id.name))
            appointment.bay_id.state = "occupied"
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
        self._check_services_done()
        for appointment in self:
            if appointment.bay_id:
                appointment.bay_id.with_context(carwash_allow_bay_release=True).state = "free"
            appointment.write({"state": "ready", "ready_at": fields.Datetime.now()})

    def action_done(self):
        for appointment in self:
            appointment.write({"state": "done", "done_at": fields.Datetime.now()})
            # sudo: reading stock_move_ids requires Inventory-app read access the acting
            # user (e.g. Front Desk) isn't expected to have just to check idempotency here.
            if not appointment.sudo().stock_move_ids:
                appointment._create_consumption_moves()
            if not appointment.sale_order_id:
                appointment._create_and_confirm_sale_order()

    def action_cancel(self):
        for appointment in self:
            if appointment.bay_id and appointment.bay_id.state == "occupied":
                appointment.bay_id.with_context(carwash_allow_bay_release=True).state = "free"
            appointment.state = "cancelled"

    def action_no_show(self):
        for appointment in self:
            appointment.state = "no_show"

    def _create_consumption_moves(self):
        # sudo: computing and creating consumable stock moves touches the service's
        # material recipe (Manager-only) and Inventory-app models the acting user (e.g.
        # Front Desk, completing an appointment) isn't expected to have direct access to -
        # this whole flow is a system-triggered side effect, not a manual stock operation.
        self.ensure_one()
        appointment = self.sudo()
        warehouse = self.env["stock.warehouse"].sudo().search([("company_id", "=", appointment.company_id.id)], limit=1)
        if not warehouse:
            return
        move_vals = []
        for line in appointment.line_ids:
            for mat in line.product_id.product_tmpl_id.carwash_material_line_ids:
                qty = mat.quantity * line.quantity
                move_vals.append(
                    {
                        "product_id": mat.product_id.id,
                        "product_uom_qty": qty,
                        "product_uom": mat.product_id.uom_id.id,
                        "location_id": warehouse.lot_stock_id.id,
                        "location_dest_id": mat.product_id.property_stock_production.id,
                        "origin": appointment.name,
                        "carwash_appointment_id": appointment.id,
                    }
                )
        if move_vals:
            moves = self.env["stock.move"].sudo().create(move_vals)
            moves._action_confirm()
            moves._action_assign()
            moves.picked = True
            moves._action_done()

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
