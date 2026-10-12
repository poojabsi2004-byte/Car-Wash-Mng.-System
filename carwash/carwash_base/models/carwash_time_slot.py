import re
from datetime import datetime, time, timedelta

import pytz

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

SLOT_MODES = [("slot", "Time Slot"), ("custom", "Custom Time")]

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*([ap])?\.?\s*m?\.?\s*$", re.IGNORECASE)


def parse_time_of_day(text):
    """'10:15', '4:15 PM', '16.30', '9 am' -> 10.25, 16.25, 16.5, 9.0 (None if it isn't a time)."""
    match = _TIME_RE.match(text or "")
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").lower()
    if minute > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "p" else 0)
    if hour > 23:
        return None
    return hour + minute / 60.0


class CarwashTimeSlot(models.Model):
    """A bookable start time offered in the backend booking forms (Configuration > Time Slots).

    A slot is offered on a day when it fits the branch's working hours (calendar, lunch
    break excluded) for the booking's duration and at least one bay is free.
    """

    _name = "carwash.time.slot"
    _description = "Car Wash Time Slot"
    _order = "hour, id"

    name = fields.Char(compute="_compute_name", store=True, string="Slot")
    hour = fields.Float(string="Start Time", required=True, default=9.0, help="Time of day in the branch's timezone, e.g. 09:30.")
    # the start time as it is entered: 12-hour clock + AM / PM
    hour_12 = fields.Float(
        string="Time", compute="_compute_hour_12", readonly=False,
        help="Start time on the 12-hour clock (1:00 - 12:59); choose AM or PM next to it.",
    )
    meridiem = fields.Selection([("am", "AM"), ("pm", "PM")], string="AM/PM", compute="_compute_hour_12", readonly=False)
    active = fields.Boolean(default=True, help="Archive a slot to stop offering it.")
    company_ids = fields.Many2many(
        "res.company", "carwash_time_slot_company_rel", "slot_id", "company_id", string="Branches",
        help="Only offer this slot at these branches. Empty = every branch.",
    )

    _hour_range = models.Constraint("CHECK(hour >= 0 AND hour < 24)", "A time slot must be between 00:00 and 23:59.")

    @api.depends("hour")
    def _compute_hour_12(self):
        for slot in self:
            hour = slot.hour or 0.0
            slot.meridiem = "pm" if hour >= 12 else "am"
            hour_12 = hour % 12
            slot.hour_12 = hour_12 + 12 if hour_12 < 1 else hour_12  # 0:30 -> 12:30 AM, 12:30 -> 12:30 PM

    @staticmethod
    def _hour_from_12(hour_12, meridiem):
        """12-hour clock + AM / PM -> hour of the day (12:30 AM = 0.5, 12:30 PM = 12.5, 4:15 PM = 16.25)."""
        return (hour_12 or 0.0) % 12 + (12 if meridiem == "pm" else 0)

    @api.onchange("hour_12", "meridiem")
    def _onchange_hour_12(self):
        for slot in self:
            if slot.hour_12 and slot.meridiem:
                slot.hour = slot._hour_from_12(slot.hour_12, slot.meridiem)

    def _vals_hour_from_12(self, vals):
        """Write the 12-hour time + AM / PM as the stored start time."""
        if "hour_12" not in vals and "meridiem" not in vals:
            return vals
        vals = dict(vals)
        hour_12 = vals.pop("hour_12", None)
        meridiem = vals.pop("meridiem", None)
        if hour_12 and not 0 <= hour_12 < 13:
            raise ValidationError(self.env._("Enter the time on the 12-hour clock (1:00 - 12:59) and choose AM or PM."))
        # the half that isn't given comes from the start time saved with it, else the slot's own
        if "hour" in vals:
            base = vals["hour"] or 0.0
        elif self:
            base = self[:1].hour
        else:
            base = self.default_get(["hour"]).get("hour") or 0.0
        if hour_12 is None:
            hour_12 = base % 12
        if not meridiem:
            meridiem = "pm" if base >= 12 else "am"
        vals["hour"] = self._hour_from_12(hour_12, meridiem)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._vals_hour_from_12(vals) for vals in vals_list])

    def write(self, vals):
        if len(self) > 1 and ("hour_12" in vals) != ("meridiem" in vals):
            # one half of the time on several slots: apply it slot by slot
            for slot in self:
                slot.write(vals)
            return True
        return super().write(self._vals_hour_from_12(vals))

    @api.depends("hour")
    def _compute_name(self):
        for slot in self:
            minutes = round(slot.hour * 60)
            hour, minute = divmod(minutes, 60)
            slot.name = f"{(hour % 12) or 12:02d}:{minute:02d} {'AM' if hour < 12 else 'PM'}"

    @api.constrains("hour", "company_ids")
    def _check_unique_time(self):
        """One slot per time and branch: two slots at the same time can't share a branch, and only
        one of them can be for every branch (a branch's own slot may sit next to an every-branch one)."""
        for slot in self:
            twins = self.search([
                ("id", "!=", slot.id),
                ("hour", ">=", slot.hour - 1 / 120),
                ("hour", "<=", slot.hour + 1 / 120),
            ])
            for twin in twins:
                if not slot.company_ids and not twin.company_ids:
                    raise ValidationError(self.env._("There's already a %s time slot for every branch.", slot.name))
                shared = slot.company_ids & twin.company_ids
                if shared:
                    raise ValidationError(self.env._(
                        "There's already a %(slot)s time slot for %(branches)s.",
                        slot=slot.name, branches=", ".join(shared.mapped("name")),
                    ))

    @api.model
    def default_get(self, fields):
        """A slot created from a booking's slot field is for that booking's branch: the booking
        forms pass it as default_company_id."""
        defaults = super().default_get(fields)
        company_id = self.env.context.get("default_company_id")
        if "company_ids" in fields and "company_ids" not in defaults and company_id:
            defaults["company_ids"] = [Command.set([company_id])]
        return defaults

    @api.model
    def name_create(self, name):
        """Typing a time in a slot field ("10:15", "4:15 PM") creates that slot - for the booking's
        branch when the form passes it (default_company_id)."""
        hour = parse_time_of_day(name)
        if hour is None:
            raise UserError(self.env._("Type a time like 10:15, 4:15 PM or 16:15."))
        slot = self.create({"hour": hour})
        return slot.id, slot.display_name

    def _search_display_name(self, operator, value):
        """Find a slot by its label ("04:15 PM") or by the time typed any way ("16:15", "4:15pm")."""
        domain = super()._search_display_name(operator, value)
        if isinstance(value, str) and operator in ("ilike", "=ilike", "like", "="):
            hour = parse_time_of_day(value)
            if hour is not None:
                domain = Domain.OR([domain, [("hour", ">=", hour - 1 / 120), ("hour", "<=", hour + 1 / 120)]])
        return domain

    @api.model
    def _by_hour(self, company=None):
        """{rounded hour: slot} of the active slots offered at `company` (a branch's own slot wins)."""
        domain = ["|", ("company_ids", "=", False), ("company_ids", "in", company.ids)] if company else []
        result = {}
        for slot in self.search(domain).sorted(lambda s: bool(s.company_ids)):
            result[round(slot.hour, 4)] = slot
        return result


class CarwashBookingSlotMixin(models.AbstractModel):
    """Pick a booking's date and time from the branch's free time slots, or type a custom time.

    The models keep their own datetime field (``_slot_datetime_field``) as the stored value;
    the date / slot / custom time shown in the form are derived from it in the branch's
    timezone and write back to it when changed.
    """

    _name = "carwash.booking.slot.mixin"
    _description = "Car Wash Booking Time Slot Picker"
    _slot_datetime_field = None
    _slot_bay_field = None

    booking_slot_date = fields.Date(
        string="Date", compute="_compute_booking_slot_date", store=True, readonly=False,
        help="Booking day in the branch's timezone.",
    )
    booking_time_mode = fields.Selection(
        SLOT_MODES, string="Time", default="slot",
        help="Time Slot: pick one of the free slots of the branch. Custom Time: any time you type.",
    )
    booking_slot_id = fields.Many2one(
        "carwash.time.slot", string="Time Slot", compute="_compute_booking_slot",
        inverse="_inverse_booking_slot", readonly=False, domain="[('id', 'in', available_slot_ids)]",
        search="_search_booking_slot_id",
    )
    booking_slot_hour = fields.Float(
        string="Time of Day", compute="_compute_booking_slot_hour", store=True,
        help="Booking time in the branch's timezone (hours) - lets bookings be searched by time slot.",
    )
    booking_custom_time = fields.Float(
        string="Custom Time", compute="_compute_booking_slot", inverse="_inverse_booking_slot", readonly=False
    )
    available_slot_ids = fields.Many2many(
        "carwash.time.slot", compute="_compute_available_slot_ids", string="Free Time Slots"
    )
    booking_slot_info = fields.Char(compute="_compute_available_slot_ids", string="Availability")

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _slot_company(self):
        return self.company_id or self.env.company

    def _slot_duration(self):
        return 0.5

    def _slot_exclude_booking_ids(self):
        return []

    def _slot_extra_depends(self):
        """Fields the booking duration depends on (they change which slots are free)."""
        return []

    def _slot_tz(self):
        # the branch's working hours aren't readable by every user (e.g. portal customers)
        name = self._slot_company().sudo().resource_calendar_id.tz or self.env.user.tz or "UTC"
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    # ------------------------------------------------------------------
    # datetime <-> date + time of day (branch timezone)
    # ------------------------------------------------------------------
    def _slot_local(self, value):
        return pytz.utc.localize(value).astimezone(self._slot_tz()).replace(tzinfo=None)

    def _slot_utc(self, date, hour):
        local = datetime.combine(date, time()) + timedelta(minutes=round(hour * 60))
        return self._slot_tz().localize(local).astimezone(pytz.utc).replace(tzinfo=None)

    @api.depends(lambda self: [self._slot_datetime_field, "company_id"])
    def _compute_booking_slot_date(self):
        for record in self:
            value = record[record._slot_datetime_field]
            # a day picked before any time is chosen stays as it is
            if value:
                record.booking_slot_date = record._slot_local(value).date()
            elif not record.booking_slot_date:
                record.booking_slot_date = False

    @api.depends(lambda self: [self._slot_datetime_field, "company_id"])
    def _compute_booking_slot(self):
        for record in self:
            slots = self.env["carwash.time.slot"]._by_hour(record._slot_company())
            value = record[record._slot_datetime_field]
            if not value:
                record.booking_slot_id = False
                record.booking_custom_time = 0.0
                continue
            local = record._slot_local(value)
            hour = local.hour + local.minute / 60.0
            record.booking_slot_id = slots.get(round(hour, 4), False)
            record.booking_custom_time = hour

    @api.depends(lambda self: [self._slot_datetime_field, "company_id"])
    def _compute_booking_slot_hour(self):
        for record in self:
            value = record[record._slot_datetime_field]
            local = record._slot_local(value) if value else None
            record.booking_slot_hour = local.hour + local.minute / 60.0 if local else 0.0

    def _search_booking_slot_id(self, operator, value):
        """Find bookings by time slot: a time typed any way ("10:30 AM", "16:30") or the slots picked."""
        Slot = self.env["carwash.time.slot"].with_context(active_test=False)
        if operator == "any":
            # a typed text arrives as a domain on the slot ("display_name ilike '2:36 pm'"): a time
            # is matched as such (also a custom time no slot has), anything else by the slots' names
            texts = [
                condition.value for condition in Domain(value).iter_conditions()
                if condition.field_expr in ("display_name", "name") and isinstance(condition.value, str)
            ]
            typed = [parse_time_of_day(text) for text in texts]
            if typed and all(hour is not None for hour in typed):
                hours = typed
            else:
                hours = Slot.search(value).mapped("hour")
        elif isinstance(value, str):
            hour = parse_time_of_day(value)
            hours = [hour] if hour is not None else Slot.search([("name", "ilike", value)]).mapped("hour")
        else:
            ids = [value] if isinstance(value, int) else list(value or [])
            hours = Slot.browse([i for i in ids if isinstance(i, int)]).exists().mapped("hour")
        if operator not in ("any", "ilike", "=ilike", "like", "=like", "=", "in") or not hours:
            return Domain.FALSE
        return Domain.OR([
            [("booking_slot_hour", ">=", hour - 1 / 120), ("booking_slot_hour", "<=", hour + 1 / 120)] for hour in hours
        ])

    def _inverse_booking_slot(self):
        """Nothing to store: the onchange already wrote the booking datetime."""

    def _slot_hour(self):
        self.ensure_one()
        if self.booking_time_mode == "custom":
            return self.booking_custom_time
        return self.booking_slot_id.hour if self.booking_slot_id else None

    @api.onchange("booking_slot_date", "booking_time_mode", "booking_slot_id", "booking_custom_time")
    def _onchange_booking_slot(self):
        for record in self:
            hour = record._slot_hour()
            if not record.booking_slot_date or hour is None:
                continue
            start = record._slot_utc(record.booking_slot_date, hour)
            record[record._slot_datetime_field] = start
            warning = record._slot_assign_free_bay(start)
            if warning:
                return {"warning": {"title": self.env._("Bay changed"), "message": warning, "type": "notification"}}

    def _slot_assign_free_bay(self, start):
        """If the chosen bay is busy at the new time, switch to a free one (returns a notice)."""
        if not self._slot_bay_field or not self[self._slot_bay_field]:
            return False
        free = self.env["carwash.appointment"]._carwash_free_bays(
            self._slot_company(), start, self._slot_duration(), self._slot_exclude_booking_ids()
        )
        bay = self[self._slot_bay_field]
        if bay._origin in free or bay in free:
            return False
        self[self._slot_bay_field] = free[:1]
        if free:
            return self.env._("%(old)s is busy at that time - switched to %(new)s.", old=bay.name, new=free[0].name)
        return self.env._("%s is busy at that time and no other bay is free.", bay.name)

    @api.depends(lambda self: [
        "booking_slot_date", "booking_time_mode", "booking_slot_id", "booking_custom_time", "company_id",
        self._slot_datetime_field, *self._slot_extra_depends(),
    ])
    def _compute_available_slot_ids(self):
        Appointment = self.env["carwash.appointment"]
        for record in self:
            company = record._slot_company()
            if not record.booking_slot_date or not company:
                record.available_slot_ids = False
                record.booking_slot_info = False
                continue
            duration = record._slot_duration()
            exclude = record._slot_exclude_booking_ids()
            slot_by_hour = self.env["carwash.time.slot"]._by_hour(company)
            # a slot set up for this branch is its own opening time: offered even outside the working hours
            branch_hours = [hour for hour, slot in slot_by_hour.items() if company in slot.company_ids]
            free = Appointment._carwash_slot_availability(
                company, record.booking_slot_date, list(slot_by_hour), duration, tz=record._slot_tz(),
                exclude_ids=exclude, anytime_hours=branch_hours, require_bay=False,
            )
            # a saved booking's own slot stays selectable even if it's no longer listed as free
            own = record.booking_slot_id.ids if record._origin.id else []
            record.available_slot_ids = [slot_by_hour[hour].id for hour in free] + own
            total_bays = self.env["carwash.bay"].search_count([("company_id", "=", company.id), ("active", "=", True)])
            hour = record._slot_hour()
            if not total_bays:
                record.booking_slot_info = self.env._(
                    "%s has no bays yet (Configuration > Bays) - the bay is given when the vehicle arrives.", company.name)
            elif hour is not None:
                bays = Appointment._carwash_free_bays(company, record._slot_utc(record.booking_slot_date, hour), duration, exclude)
                record.booking_slot_info = (
                    self.env._("%(free)s of %(total)s bays free at this time", free=len(bays), total=total_bays)
                    if bays else self.env._("No bay is free at this time")
                )
            elif free:
                record.booking_slot_info = self.env._("%s free time slots on this day", len(free))
            else:
                record.booking_slot_info = self.env._("No free time slot on this day (closed or fully booked) - use a custom time")

    # ------------------------------------------------------------------
    # keep the Time Slot / Custom Time choice right when the datetime is set elsewhere
    # (website, booking request, import...)
    # ------------------------------------------------------------------
    def _slot_sync_time_mode(self):
        for record in self:
            mode = "slot" if record.booking_slot_id else "custom"
            if record[record._slot_datetime_field] and record.booking_time_mode != mode:
                record.write({"booking_time_mode": mode})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            if "booking_time_mode" not in vals:
                record._slot_sync_time_mode()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self._slot_datetime_field in vals and "booking_time_mode" not in vals:
            self._slot_sync_time_mode()
        return res
