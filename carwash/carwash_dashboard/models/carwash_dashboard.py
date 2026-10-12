from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

PERIOD_DAYS = {"today": 0, "week": 6, "month": 29, "quarter": 89, "year": 364}
ACTIVE_STATES = ("confirmed", "arrived", "in_service", "ready")


def _initials(name):
    return "".join(part[0] for part in (name or "?").split()[:2]).upper()


class CarwashDashboard(models.AbstractModel):
    _name = "carwash.dashboard"
    _description = "Car Wash Dashboard Data Provider"

    # ------------------------------------------------------------------
    # Time helpers - every "today"/period boundary is the user's local day,
    # converted to the naive-UTC datetimes stored in the database.
    # ------------------------------------------------------------------
    def _tz(self):
        try:
            return pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _local_now(self):
        return pytz.utc.localize(fields.Datetime.now()).astimezone(self._tz())

    def _day_start_utc(self, day):
        local = self._tz().localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _to_local(self, dt):
        return pytz.utc.localize(dt).astimezone(self._tz()) if dt else None

    def _fmt_time(self, dt):
        local = self._to_local(dt)
        return local.strftime("%H:%M") if local else ""

    def _fmt_datetime(self, dt):
        local = self._to_local(dt)
        return local.strftime("%d %b, %y %H:%M") if local else ""

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, period="week", date_from=None, date_to=None):
        user = self.env.user
        is_owner = user.has_group("carwash_multibranch.group_carwash_owner")
        is_manager = user.has_group("carwash_base.group_carwash_manager")
        is_qc = user.has_group("carwash_jobcard.group_carwash_qc")
        is_washer = user.has_group("carwash_jobcard.group_carwash_washer")

        # The company switcher (top right) sets env.companies - scope the "what's
        # happening right now" sections to it, so switching branches updates the
        # view. The owner-only business-overview section covers the branches the owner
        # has ticked (all of them by default).
        company_ids = self.env.companies.ids
        now_local = self._local_now()
        today = now_local.date()
        today_start = self._day_start_utc(today)
        tomorrow_start = self._day_start_utc(today + timedelta(days=1))
        currency = self.env.company.currency_id

        data = {
            "role": "owner" if is_owner else "manager" if is_manager else "qc" if is_qc else "washer" if is_washer else "user",
            "user_name": user.name,
            "company_name": ", ".join(self.env.companies.mapped("name")),
            "today_label": now_local.strftime("%A, %d %b, %y"),
            "today": fields.Date.to_string(today),
            "currency": {"symbol": currency.symbol or "", "position": currency.position or "before"},
            "has_washer_data": is_washer and not is_manager,
            "has_qc_data": is_qc,
            "has_manager_data": is_manager,
            "has_owner_data": is_owner,
            # New Booking: front desk / managers - staff (washers) and QC inspectors don't create bookings
            "can_create_booking": self.env["carwash.appointment"].has_access("create"),
        }
        data.update(self._get_live_data(company_ids, today_start, tomorrow_start))
        requests = self._get_booking_requests(company_ids)
        if requests is not None:
            data["booking_requests"] = requests

        if self.env["carwash.jobcard"].has_access("read"):
            data["jobcards"] = self._get_jobcards(company_ids, only_mine=is_washer and not is_manager and not is_qc)
        else:
            data["jobcards"] = []

        if is_washer and not is_manager:
            data["my_jobcards"] = self._get_my_jobcard_counts(today_start)

        # staff / QC: what they earn on job cards (Settings > Staff Payable)
        if (is_washer or is_qc) and self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_commission"):
            earnings = self._get_my_earnings_data(today)
            if earnings:
                data["my_earnings"] = earnings

        if is_qc:
            data["pending_qc"] = len([j for j in data["jobcards"] if j["stage"] == "qc"])

        if is_manager:
            period_from, period_to = self._get_period_range(today, period, date_from, date_to)
            data["period"] = period
            data["period_from"] = fields.Date.to_string(period_from)
            data["period_to"] = fields.Date.to_string(period_to)
            data.update(self._get_manager_data(company_ids, today_start, tomorrow_start, period_from, period_to))
            data["payments"] = self._get_payments_data(company_ids, period_from, period_to)

        if is_owner:
            data.update(self._get_owner_data(today))

        return data

    def _get_period_range(self, today, period, date_from, date_to):
        if period == "custom" and date_from and date_to:
            start, end = fields.Date.from_string(date_from), fields.Date.from_string(date_to)
            return min(start, end), max(start, end)
        return today - timedelta(days=PERIOD_DAYS.get(period, 6)), today

    def _pct_change(self, current, previous):
        if not previous:
            return None if not current else 100.0
        return round((current - previous) / previous * 100, 1)

    # ------------------------------------------------------------------
    # Booking calendar (every role): one week of bookings + open requests
    # ------------------------------------------------------------------
    def _get_booking_requests(self, company_ids, limit=12):
        """New booking requests (leads of carwash_crm, which the dashboard doesn't depend on) not
        confirmed into a booking yet, whatever their requested date - newest first. None when
        CRM booking requests aren't installed or the user can't read them."""
        Lead = self.env["crm.lead"] if "crm.lead" in self.env else None
        if Lead is None or "carwash_appointment_id" not in Lead._fields or not Lead.has_access("read"):
            return None
        domain = [
            ("is_carwash_booking", "=", True),
            ("carwash_appointment_id", "=", False),
            ("company_id", "in", company_ids + [False]),
        ]
        leads = Lead.search(domain, order="create_date desc, id desc", limit=limit)
        action = self.env.ref("carwash_crm.action_carwash_booking_requests", raise_if_not_found=False)
        return {
            "count": Lead.search_count(domain),
            "action_id": action.id if action else False,
            "items": [
                {
                    "id": lead.id,
                    "name": lead.name or "",
                    "customer": lead.partner_id.name or lead.contact_name or "",
                    "phone": lead.phone or "",
                    "plate": lead.carwash_license_plate or lead.carwash_vehicle_id.license_plate or "",
                    "requested": self._fmt_datetime(lead.carwash_booking_date) if lead.carwash_booking_date else "",
                    "received": self._fmt_datetime(lead.create_date),
                    "services": ", ".join(filter(None, [lead.carwash_package_id.name or ""] + lead.carwash_service_ids.mapped("name"))),
                }
                for lead in leads
            ],
        }

    @api.model
    def get_calendar_data(self, start=None, days=7):
        """Bookings (and booking requests not confirmed yet) per local day, from `start`
        (ISO date, default: Monday of this week) for `days` days, in the ticked branches."""
        today = self._local_now().date()
        try:
            first = fields.Date.to_date(start) if start else None
        except ValueError:
            first = None
        first = first or today - timedelta(days=today.weekday())
        days = max(1, min(int(days or 7), 31))
        last = first + timedelta(days=days)
        range_start, range_end = self._day_start_utc(first), self._day_start_utc(last)
        company_ids = self.env.companies.ids

        by_day = {first + timedelta(days=i): {"bookings": [], "requests": []} for i in range(days)}
        state_labels = dict(self.env["carwash.appointment"]._fields["state"]._description_selection(self.env))
        bookings = self.env["carwash.appointment"].search([
            ("appointment_date", ">=", range_start),
            ("appointment_date", "<", range_end),
            ("company_id", "in", company_ids),
            ("state", "not in", ("cancelled", "no_show")),
        ], order="appointment_date")
        for appt in bookings:
            local = self._to_local(appt.appointment_date)
            by_day[local.date()]["bookings"].append({
                "id": appt.id,
                "name": appt.name,
                "time": local.strftime("%H:%M"),
                "end": (local + timedelta(hours=appt.duration or 0.5)).strftime("%H:%M"),
                "state": appt.state,
                "state_label": state_labels.get(appt.state, appt.state),
                "plate": appt.vehicle_id.license_plate or "",
                "vehicle_icon": appt.vehicle_id.vehicle_type_id.icon or "fa-car",
                "customer": appt.customer_id.name or "",
                "bay": appt.bay_id.name or "",
                "services": ", ".join(appt._service_lines().product_id.mapped("name")),
            })

        # booking requests come from carwash_crm, which the dashboard doesn't depend on
        Lead = self.env["crm.lead"] if "crm.lead" in self.env else None
        show_requests = bool(Lead is not None and "carwash_booking_date" in Lead._fields and Lead.has_access("read"))
        if show_requests:
            requests = Lead.search([
                ("is_carwash_booking", "=", True),
                ("carwash_appointment_id", "=", False),
                ("carwash_booking_date", ">=", range_start),
                ("carwash_booking_date", "<", range_end),
                ("company_id", "in", company_ids + [False]),
            ], order="carwash_booking_date")
            for lead in requests:
                local = self._to_local(lead.carwash_booking_date)
                by_day[local.date()]["requests"].append({
                    "id": lead.id,
                    "name": lead.name,
                    "time": local.strftime("%H:%M"),
                    "plate": lead.carwash_license_plate or "",
                    "customer": lead.partner_id.name or lead.contact_name or "",
                    "services": ", ".join(filter(None, [lead.carwash_package_id.name or ""]
                                                 + lead.carwash_service_ids.mapped("name"))),
                })

        return {
            "start": fields.Date.to_string(first),
            "end": fields.Date.to_string(last - timedelta(days=1)),
            "range_label": f"{first.strftime('%d %b')} - {(last - timedelta(days=1)).strftime('%d %b, %y')}",
            "is_current": first <= today < last,
            "show_requests": show_requests,
            "total_bookings": len(bookings),
            "total_requests": sum(len(d["requests"]) for d in by_day.values()),
            "days": [
                {
                    "date": fields.Date.to_string(day),
                    "weekday": day.strftime("%a"),
                    "label": day.strftime("%d %b"),
                    "is_today": day == today,
                    "is_past": day < today,
                    **entries,
                }
                for day, entries in sorted(by_day.items())
            ],
        }

    # ------------------------------------------------------------------
    # Live floor: pipeline, bays, hourly load (every role)
    # ------------------------------------------------------------------
    def _appointment_card(self, appt, now):
        vehicle = appt.vehicle_id
        progress = 0
        eta = None
        if appt.state == "in_service" and appt.service_started_at:
            planned = (appt.duration or 0.5) * 60
            elapsed = (now - appt.service_started_at).total_seconds() / 60
            progress = max(0, min(100, round(elapsed / planned * 100)))
            eta = round(planned - elapsed)
        return {
            "id": appt.id,
            "name": appt.name,
            "token": appt.token_no,
            "state": appt.state,
            "plate": vehicle.license_plate or "",
            "vehicle": " ".join(filter(None, [vehicle.make, vehicle.vehicle_model])),
            "vehicle_icon": vehicle.vehicle_type_id.icon or "fa-car",
            "customer": appt.customer_id.name or "",
            "bay": appt.bay_id.name or "",
            "time": self._fmt_time(appt.appointment_date),
            "waiting": round(appt.waiting_time) if appt.state == "arrived" else 0,
            "services": ", ".join(appt._service_lines().product_id.mapped("name")),
            "amount": appt.amount_total,
            "progress": progress,
            "eta": eta,
            "services_done": len(appt._service_lines().filtered(lambda line: line.service_state == "done")),
            "services_total": len(appt._service_lines()),
        }

    def _get_live_data(self, company_ids, today_start, tomorrow_start):
        Appointment = self.env["carwash.appointment"]
        now = fields.Datetime.now()

        active = Appointment.search(
            [
                ("state", "in", ACTIVE_STATES),
                ("appointment_date", "<", tomorrow_start),
                ("company_id", "in", company_ids),
            ],
            order="appointment_date, id",
            limit=200,
        )
        pipeline = {state: [] for state in ACTIVE_STATES}
        for appt in active:
            pipeline[appt.state].append(self._appointment_card(appt, now))

        today_appts = Appointment.search(
            [
                ("appointment_date", ">=", today_start),
                ("appointment_date", "<", tomorrow_start),
                ("company_id", "in", company_ids),
            ]
        )
        live_today = today_appts.filtered(lambda a: a.state not in ("cancelled", "no_show"))
        started_today = today_appts.filtered(lambda a: a.arrived_at and a.service_started_at)
        avg_wait = (
            sum((a.service_started_at - a.arrived_at).total_seconds() for a in started_today) / 60 / len(started_today)
            if started_today
            else 0.0
        )

        hourly = defaultdict(int)
        for appt in live_today:
            hourly[self._to_local(appt.appointment_date).hour] += 1
        hours = list(range(min([8, *hourly]), max([20, *hourly]) + 1))

        bays = []
        if self.env["carwash.bay"].has_access("read"):
            in_service = {a.bay_id.id: a for a in active if a.state == "in_service" and a.bay_id}
            upcoming = {}
            for appt in active.filtered(lambda a: a.state in ("confirmed", "arrived") and a.bay_id):
                upcoming.setdefault(appt.bay_id.id, appt)
            for bay in self.env["carwash.bay"].search([("company_id", "in", company_ids)]):
                current = in_service.get(bay.id)
                nxt = upcoming.get(bay.id)
                bays.append(
                    {
                        "id": bay.id,
                        "name": bay.name,
                        "type": bay.bay_type_id.name or "",
                        "type_icon": bay.bay_type_id.icon or "fa-tint",
                        "state": bay.state,
                        "current": self._appointment_card(current, now) if current else False,
                        "next": {"plate": nxt.vehicle_id.license_plate, "time": self._fmt_time(nxt.appointment_date)}
                        if nxt
                        else False,
                    }
                )

        bay_busy = len([b for b in bays if b["state"] == "occupied"])
        return {
            "pipeline": pipeline,
            "queue": {state: len(cards) for state, cards in pipeline.items()},
            "queue_total": len(active),
            "today_appointments": len(live_today),
            "today_done": len(today_appts.filtered(lambda a: a.state == "done")),
            "avg_wait": round(avg_wait, 1),
            "bays": bays,
            "bay_counts": {
                "free": len([b for b in bays if b["state"] == "free"]),
                "occupied": bay_busy,
                "maintenance": len([b for b in bays if b["state"] == "maintenance"]),
                "total": len(bays),
            },
            "bay_utilization": round(bay_busy / len(bays) * 100) if bays else 0,
            "hourly_load": {"labels": [f"{h:02d}:00" for h in hours], "values": [hourly.get(h, 0) for h in hours]},
        }

    # ------------------------------------------------------------------
    # Job cards
    # ------------------------------------------------------------------
    def _get_jobcards(self, company_ids, only_mine=False):
        domain = [("stages", "not in", ("done", "cancel")), ("company_id", "in", company_ids)]
        if only_mine:
            domain.append(("assigned_employee_ids", "in", self.env.user.employee_id.ids))
        stage_labels = dict(self.env["carwash.jobcard"]._fields["stages"].selection)
        now = fields.Datetime.now()
        result = []
        for jc in self.env["carwash.jobcard"].search(domain, order="id desc", limit=60):
            result.append(
                {
                    "id": jc.id,
                    "name": jc.name,
                    "appointment_id": jc.appointment_id.id,
                    "plate": jc.vehicle_id.license_plate or "",
                    "customer": jc.customer_id.name or "",
                    "bay": jc.bay_id.name or "",
                    "stage": jc.stages,
                    "stage_label": stage_labels.get(jc.stages, ""),
                    "staff": [{"name": e.name, "initials": _initials(e.name)} for e in jc.assigned_employee_ids],
                    # sudo: checklist lines are only readable by washer/qc/manager; this is
                    # a read-only progress figure, not exposure of the lines themselves.
                    "progress": jc.sudo().checklist_progress,
                    "minutes": round((now - jc.start_time).total_seconds() / 60) if jc.start_time else 0,
                }
            )
        return result

    def _get_my_earnings_data(self, today):
        """The logged-in staff member's / QC inspector's staff payables: still to receive, received, the latest
        ones (the full list is My Earnings)."""
        employee = self.env.user.sudo().employee_id
        if not employee:
            return None
        # sudo: their own payables only (the employee is the user's own)
        mine = self.env["carwash.staff.commission"].sudo().search(
            [("employee_id", "=", employee.id), ("state", "!=", "cancelled")], order="date desc, id desc",
        )
        month_start = today.replace(day=1)
        to_receive = mine.filtered(lambda p: p.state == "to_pay")
        received = mine.filtered(lambda p: p.state == "paid")
        return {
            "to_receive": sum(to_receive.mapped("amount")),
            "to_receive_count": len(to_receive),
            "received_month": sum(received.filtered(lambda p: p.paid_date and p.paid_date >= month_start).mapped("amount")),
            "earned_month": sum(mine.filtered(lambda p: p.date >= month_start).mapped("amount")),
            "received_total": sum(received.mapped("amount")),
            "form_view_id": self.env.ref("carwash_jobcard.view_carwash_my_earnings_form").id,
            "recent": [
                {
                    "id": payable.id,
                    "day": payable.date.strftime("%d %b"),
                    "jobcard": payable.jobcard_id.name or "",
                    "booking": payable.appointment_id.name or "",
                    "role": self.env._("QC") if payable.payable_role == "qc" else self.env._("Staff"),
                    "amount": payable.amount,
                    "received": payable.state == "paid",
                    "paid_day": payable.paid_date.strftime("%d %b") if payable.paid_date else "",
                }
                for payable in mine[:5]
            ],
        }

    def _get_my_jobcard_counts(self, today_start):
        jobcard = self.env["carwash.jobcard"]
        mine = [("assigned_employee_ids", "in", self.env.user.employee_id.ids)]
        return {
            "in_progress": jobcard.search_count(mine + [("stages", "=", "in_progress")]),
            "qc": jobcard.search_count(mine + [("stages", "=", "qc")]),
            "done_today": jobcard.search_count(mine + [("stages", "=", "done"), ("end_time", ">=", today_start)]),
        }

    # ------------------------------------------------------------------
    # Manager: money, services, consumables
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Manager: payments - money in from customers, out to staff and QC
    # ------------------------------------------------------------------
    def _get_payments_data(self, company_ids, period_from, period_to):
        """Customer payments received in the period and what is still to collect; staff / QC paid in the period and
        what they are still owed (per person); what the car wash keeps; the latest payments in and out."""
        # sudo: the manager's overview of every payment / payable of the branches
        Payment = self.env["account.payment"].sudo()
        received = Payment.search([
            ("company_id", "in", company_ids), ("payment_type", "=", "inbound"), ("partner_type", "=", "customer"),
            ("state", "not in", ("draft", "canceled", "rejected")),
            ("date", ">=", period_from), ("date", "<=", period_to),
        ], order="date desc, id desc")
        received_total = sum(received.mapped("amount_company_currency_signed"))

        # still to collect: bookings whose service ended (Ready) or done, not fully paid
        Appointment = self.env["carwash.appointment"].sudo()
        to_collect = Appointment.search([
            ("company_id", "in", company_ids), ("state", "in", ("ready", "done")), ("sale_order_id", "!=", False),
            "|", "|",
            ("sale_order_id.state", "in", ("draft", "sent")),
            ("sale_order_id.invoice_status", "=", "to invoice"),
            "&", ("sale_order_id.invoice_ids.state", "=", "posted"),
            ("sale_order_id.invoice_ids.payment_state", "in", ("not_paid", "partial")),
        ])
        due_by_booking = {}
        for booking in to_collect:
            due = booking.amount_due if booking.payment_state != "quotation" else booking.sale_order_id.amount_total
            if due > 0.005:
                due_by_booking[booking.id] = due

        data = {
            "received": received_total,
            "received_count": len(received),
            "received_ids": received.ids,
            "due": sum(due_by_booking.values()),
            "due_count": len(due_by_booking),
            "due_booking_ids": list(due_by_booking),
            "has_payables": self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_commission"),
            "staff_paid": 0.0, "qc_paid": 0.0, "staff_to_pay": 0.0, "qc_to_pay": 0.0,
            "owed": [],
        }
        events = [
            {
                "key": f"in-{payment.id}", "kind": "in", "model": "account.payment", "id": payment.id,
                "date": payment.date, "day": payment.date.strftime("%d %b"),
                "who": payment.partner_id.name or "", "what": payment.memo or payment.name or "",
                "amount": payment.amount_company_currency_signed,
            }
            for payment in received[:8]
        ]
        if data["has_payables"]:
            Payable = self.env["carwash.staff.commission"].sudo()
            to_pay = Payable.search([("company_id", "in", company_ids), ("state", "=", "to_pay")])
            paid = Payable.search([
                ("company_id", "in", company_ids), ("state", "=", "paid"),
                ("paid_date", ">=", period_from), ("paid_date", "<=", period_to),
            ], order="paid_date desc, id desc")
            for role in ("staff", "qc"):
                data[f"{role}_paid"] = sum(paid.filtered(lambda p: p.payable_role == role).mapped("amount"))
                data[f"{role}_to_pay"] = sum(to_pay.filtered(lambda p: p.payable_role == role).mapped("amount"))
            owed = {}
            for payable in to_pay:
                entry = owed.setdefault((payable.employee_id.id, payable.payable_role), {
                    "key": f"{payable.employee_id.id}-{payable.payable_role}", "employee_id": payable.employee_id.id,
                    "name": payable.employee_id.name, "initials": _initials(payable.employee_id.name),
                    "role": payable.payable_role, "role_label": self.env._("QC") if payable.payable_role == "qc" else self.env._("Staff"),
                    "amount": 0.0, "count": 0,
                })
                entry["amount"] += payable.amount
                entry["count"] += 1
            data["owed"] = sorted(owed.values(), key=lambda e: -e["amount"])[:6]
            events += [
                {
                    "key": f"out-{payable.id}", "kind": "out_qc" if payable.payable_role == "qc" else "out",
                    "model": "carwash.staff.commission", "id": payable.id,
                    "date": payable.paid_date, "day": payable.paid_date.strftime("%d %b"),
                    "who": payable.employee_id.name or "",
                    "what": f"{self.env._('QC') if payable.payable_role == 'qc' else self.env._('Staff')} · {payable.jobcard_id.name or ''}",
                    "amount": payable.amount,
                }
                for payable in paid[:8]
            ]
        paid_out = data["staff_paid"] + data["qc_paid"]
        data["paid_out"] = paid_out
        data["kept"] = received_total - paid_out
        base = max(received_total, paid_out) or 1.0
        data["split"] = {
            "staff": round(data["staff_paid"] / base * 100, 1),
            "qc": round(data["qc_paid"] / base * 100, 1),
            "kept": round(max(data["kept"], 0.0) / base * 100, 1),
        }
        events.sort(key=lambda e: (e["date"], e["kind"] == "in"), reverse=True)
        for event in events:
            del event["date"]
        data["recent"] = events[:7]
        return data

    def _get_manager_data(self, company_ids, today_start, tomorrow_start, period_from, period_to):
        Appointment = self.env["carwash.appointment"]
        start = self._day_start_utc(period_from)
        end = self._day_start_utc(period_to + timedelta(days=1))
        done_domain = [("state", "=", "done"), ("company_id", "in", company_ids)]

        done_in_period = Appointment.search(done_domain + [("done_at", ">=", start), ("done_at", "<", end)])
        today_done = Appointment.search(done_domain + [("done_at", ">=", today_start), ("done_at", "<", tomorrow_start)])

        # Same-length window immediately before the selected period, to show
        # "up/down vs previous period" on the KPI tiles.
        span = end - start
        done_in_prev_period = Appointment.search(done_domain + [("done_at", ">=", start - span), ("done_at", "<", start)])

        revenue_period = sum(done_in_period.mapped("amount_total"))
        revenue_prev = sum(done_in_prev_period.mapped("amount_total"))
        washes = len(done_in_period)
        washes_prev = len(done_in_prev_period)
        avg_ticket = revenue_period / washes if washes else 0.0
        avg_ticket_prev = revenue_prev / washes_prev if washes_prev else 0.0

        service_stats = {}
        for line in done_in_period.line_ids.filtered(lambda line: not line.is_discount_line):
            stat = service_stats.setdefault(line.product_id.id, {"name": line.product_id.name, "count": 0.0, "revenue": 0.0})
            stat["count"] += line.quantity
            stat["revenue"] += line.price_subtotal
        top_services = sorted(service_stats.values(), key=lambda s: -s["revenue"])[:8]

        recent = done_in_period.sorted(lambda a: a.done_at, reverse=True)[:12]
        return {
            "revenue_today": sum(today_done.mapped("amount_total")),
            "revenue_period": revenue_period,
            "revenue_period_change": self._pct_change(revenue_period, revenue_prev),
            "wash_count_period": washes,
            "wash_count_period_change": self._pct_change(washes, washes_prev),
            "avg_ticket": avg_ticket,
            "avg_ticket_change": self._pct_change(avg_ticket, avg_ticket_prev),
            "top_services": top_services,
            "revenue_trend": self._build_trend(done_in_period, period_from, period_to),
            "top_products": self._get_top_products(company_ids, start, end),
            "recent_done": [
                {
                    "id": a.id,
                    "name": a.name,
                    "plate": a.vehicle_id.license_plate or "",
                    "customer": a.customer_id.name or "",
                    "services": ", ".join(a._service_lines().product_id.mapped("name")),
                    "amount": a.amount_total,
                    "done_at": self._fmt_datetime(a.done_at),
                }
                for a in recent
            ],
        }

    def _build_trend(self, done_appointments, date_from, date_to):
        span_days = (date_to - date_from).days + 1
        if span_days <= 31:
            bucket_days, date_fmt = 1, "%d %b"
        elif span_days <= 180:
            bucket_days, date_fmt = 7, "%d %b"
        else:
            bucket_days, date_fmt = 30, "%b, %y"

        buckets = []
        cursor = date_from
        while cursor <= date_to:
            buckets.append(cursor)
            cursor += timedelta(days=bucket_days)
        revenue = [0.0] * len(buckets)
        washes = [0] * len(buckets)
        for appt in done_appointments:
            index = min((self._to_local(appt.done_at).date() - date_from).days // bucket_days, len(buckets) - 1)
            if index >= 0:
                revenue[index] += appt.amount_total
                washes[index] += 1
        return {"labels": [b.strftime(date_fmt) for b in buckets], "revenue": revenue, "washes": washes}

    def _get_top_products(self, company_ids, start, end):
        # sudo(): this is read-only aggregate reporting, not raw stock.move exposure -
        # front desk/washer/qc never had (or need) direct stock.move access.
        moves = self.env["stock.move"].sudo().search(
            [
                ("carwash_appointment_id", "!=", False),
                ("company_id", "in", company_ids),
                ("state", "=", "done"),
                ("date", ">=", start),
                ("date", "<", end),
            ]
        )
        stats = defaultdict(float)
        for move in moves:
            stats[move.product_id] += move.product_uom_qty
        result = []
        for product, qty_used in sorted(stats.items(), key=lambda kv: -kv[1])[:8]:
            on_hand = product.qty_available
            total = on_hand + qty_used
            result.append(
                {
                    "id": product.id,
                    "name": product.display_name,
                    "qty_used": round(qty_used, 2),
                    "uom": product.uom_id.name,
                    "stock_on_hand": round(on_hand, 2),
                    "stock_pct": max(0, min(100, round(on_hand / total * 100))) if total > 0 else 0,
                    "low": on_hand < max(5.0, qty_used),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Owner: every branch
    # ------------------------------------------------------------------
    def _get_owner_data(self, today):
        appointment = self.env["carwash.appointment"]
        jobcard = self.env["carwash.jobcard"]
        membership = self.env["carwash.membership"]

        branch_stats = {}
        for appt in appointment.search([("state", "=", "done")]):
            # sudo: a branch's name - the owner may not have every branch ticked in the switcher
            stat = branch_stats.setdefault(appt.company_id.sudo().name, {"revenue": 0.0, "washes": 0})
            stat["revenue"] += appt.amount_total
            stat["washes"] += 1
        branch_breakdown = sorted(
            ({"name": name, **stat} for name, stat in branch_stats.items()), key=lambda b: -b["revenue"]
        )

        staff_stats = {}
        for jc in jobcard.search([("stages", "=", "done")]):
            for employee in jc.assigned_employee_ids:
                stat = staff_stats.setdefault(
                    employee.id, {"name": employee.name, "initials": _initials(employee.name), "completed": 0}
                )
                stat["completed"] += 1
        staff_leaderboard = sorted(staff_stats.values(), key=lambda s: -s["completed"])[:10]

        active_memberships = membership.search([("state", "=", "active")], order="next_billing_date")
        loyalty_cards = self.env["loyalty.card"].sudo().search([])

        def is_overdue(m):
            return bool(m.next_billing_date and m.next_billing_date < today)

        return {
            "branch_breakdown": branch_breakdown,
            "staff_leaderboard": staff_leaderboard,
            "membership_totals": {
                "active": len(active_memberships),
                # monthly revenue: a yearly member counts 1/12 of the yearly amount
                "mrr": sum(m.amount / 12 if m.billing_period == "yearly" else m.amount for m in active_memberships),
            },
            "billing_overdue": len(active_memberships.filtered(is_overdue)),
            "memberships": [
                {
                    "id": m.id,
                    "name": m.name,
                    "customer": m.partner_id.name or "",
                    "plan": m.plan_id.name or "",
                    "used": m.washes_used,
                    "allowance": m.wash_allowance,
                    "next_billing": m.next_billing_date.strftime("%d %b, %y") if m.next_billing_date else "",
                    "overdue": is_overdue(m),
                }
                for m in active_memberships[:40]
            ],
            "loyalty_totals": {"points_balance": sum(loyalty_cards.mapped("points")), "cards": len(loyalty_cards)},
        }
