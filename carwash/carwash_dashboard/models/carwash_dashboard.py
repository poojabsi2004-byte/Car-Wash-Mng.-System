from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

PERIOD_DAYS = {"today": 0, "week": 6, "month": 29, "quarter": 89, "year": 364}
ACTIVE_STATES = ("confirmed", "arrived", "in_service", "ready")
VEHICLE_ICONS = {
    "hatchback": "fa-car",
    "sedan": "fa-car",
    "suv": "fa-car",
    "truck": "fa-truck",
    "van": "fa-bus",
    "bike": "fa-motorcycle",
    "other": "fa-car",
}
BAY_TYPE_ICONS = {"hand": "fa-hand-paper-o", "tunnel": "fa-road", "detail": "fa-diamond"}


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
        return local.strftime("%d %b, %H:%M") if local else ""

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
        # view. The owner-only business-overview section deliberately ignores this
        # and always aggregates every branch the owner can see (that's its point).
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
            "today_label": now_local.strftime("%A, %d %B %Y"),
            "today": fields.Date.to_string(today),
            "currency": {"symbol": currency.symbol or "", "position": currency.position or "before"},
            "has_washer_data": is_washer and not is_manager,
            "has_qc_data": is_qc,
            "has_manager_data": is_manager,
            "has_owner_data": is_owner,
        }
        data.update(self._get_live_data(company_ids, today_start, tomorrow_start))

        if self.env["carwash.jobcard"].has_access("read"):
            data["jobcards"] = self._get_jobcards(company_ids, only_mine=is_washer and not is_manager and not is_qc)
        else:
            data["jobcards"] = []

        if is_washer and not is_manager:
            data["my_jobcards"] = self._get_my_jobcard_counts(today_start)

        if is_qc:
            data["pending_qc"] = len([j for j in data["jobcards"] if j["stage"] == "qc"])

        if is_manager:
            period_from, period_to = self._get_period_range(today, period, date_from, date_to)
            data["period"] = period
            data["period_from"] = fields.Date.to_string(period_from)
            data["period_to"] = fields.Date.to_string(period_to)
            data.update(self._get_manager_data(company_ids, today_start, tomorrow_start, period_from, period_to))

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
            "vehicle_icon": VEHICLE_ICONS.get(vehicle.vehicle_type, "fa-car"),
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
            bay_types = dict(self.env["carwash.bay"]._fields["bay_type"].selection)
            for bay in self.env["carwash.bay"].search([("company_id", "in", company_ids)]):
                current = in_service.get(bay.id)
                nxt = upcoming.get(bay.id)
                bays.append(
                    {
                        "id": bay.id,
                        "name": bay.name,
                        "type": bay_types.get(bay.bay_type, ""),
                        "type_icon": BAY_TYPE_ICONS.get(bay.bay_type, "fa-tint"),
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
            bucket_days, date_fmt = 30, "%b %Y"

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
            stat = branch_stats.setdefault(appt.company_id.name, {"revenue": 0.0, "washes": 0})
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
                "mrr": sum(active_memberships.mapped("plan_id.product_id.list_price")),
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
                    "next_billing": m.next_billing_date.strftime("%d %b %Y") if m.next_billing_date else "",
                    "overdue": is_overdue(m),
                }
                for m in active_memberships[:40]
            ],
            "loyalty_totals": {"points_balance": sum(loyalty_cards.mapped("points")), "cards": len(loyalty_cards)},
        }
