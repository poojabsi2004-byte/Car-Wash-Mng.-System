from datetime import datetime, timedelta

import pytz

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request


class CarwashBookingController(http.Controller):

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _branch_tz(company):
        """Timezone of the branch's working hours - website slots are local times of the branch."""
        try:
            return pytz.timezone(company.sudo().resource_calendar_id.tz or "UTC")
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _to_local(self, company, utc_dt):
        return pytz.utc.localize(utc_dt).astimezone(self._branch_tz(company)).replace(tzinfo=None)

    def _parse_slot_start(self, company, value):
        """The posted slot (UTC, as rendered by the slot page) as a naive UTC datetime, or None.
        A value with a timezone offset is converted to UTC."""
        try:
            start = datetime.fromisoformat(value or "")
        except ValueError:
            return None
        if start.tzinfo:
            start = start.astimezone(pytz.utc).replace(tzinfo=None)
        return start

    def _bookable_slots(self, company, booking_date, service, package):
        """Free slots of `booking_date` at the branch (branch-local hours, UTC `start`), future ones only."""
        now = fields.Datetime.now()
        slots = request.env["carwash.appointment"].sudo()._get_available_slots(
            company, booking_date, service, duration=self._selection_duration(service, package),
            tz=self._branch_tz(company),
        )
        for slot in slots:
            slot["label"] = self._to_local(company, slot["start"]).strftime("%I:%M %p")
        return [slot for slot in slots if slot["start"] > now]

    def _vehicle_type(self, vehicle_type_id=None, code=None):
        """The vehicle type picked on the website (by id, or by its standard code), else the default one."""
        VehicleType = request.env["carwash.vehicle.type"].sudo()
        vehicle_type = VehicleType.browse(self._to_int(vehicle_type_id) or []).exists().filtered("active")
        return vehicle_type or VehicleType._by_code(code) or VehicleType._default_type()

    def _get_branches(self):
        bay_company_ids = request.env["carwash.bay"].sudo().search([]).company_id.ids
        return request.env["res.company"].sudo().browse(set(bay_company_ids))

    def _get_services(self):
        return request.env["product.product"].sudo().search([("is_carwash_service", "=", True)])

    def _get_packages(self):
        if not request.env["carwash.feature"].sudo()._enabled("carwash_jobcard.group_carwash_package"):
            return request.env["carwash.service.package"]
        return request.env["carwash.service.package"].sudo().search([("active", "=", True)])

    def _get_selection(self, product_id=None, package_id=None):
        """Validated (service, package) picked on the website - either may be empty, not both."""
        product_id = self._to_int(product_id)
        package_id = self._to_int(package_id)
        service = self._get_services().filtered(lambda p: p.id == product_id) if product_id else request.env["product.product"]
        package = self._get_packages().filtered(lambda p: p.id == package_id) if package_id else request.env["carwash.service.package"]
        return service, package

    def _get_usable_membership(self, partner):
        return partner._carwash_get_usable_membership()

    @staticmethod
    def _booking_price_lines(service, package):
        """(product, price_unit, quantity) of the booking a website selection would create."""
        lines = [
            (request.env["product.product"].sudo().browse(vals["product_id"]), vals["price_unit"], vals["quantity"])
            for vals in package._prepare_booking_line_vals()
        ] if package else []
        extra = service - package.line_ids.product_id
        if extra:
            lines.append((extra, extra.list_price, 1.0))
        return lines

    def _membership_preview(self, membership, service, package):
        """Normal vs member price of the selection, or None when the membership gives nothing on it."""
        if not membership or not (service or package):
            return None
        preview = membership._preview_member_total(self._booking_price_lines(service, package))
        return preview if preview["has_benefit"] else None

    @staticmethod
    def _selection_duration(service, package):
        return (package.duration + (service.carwash_duration if service else 0.0)) or 0.5

    def _lock_and_pick_bay(self, company, start, end):
        """Lock candidate bay rows and return the first bay still free for [start, end).

        Row-locking (SELECT ... FOR UPDATE) serializes concurrent bookings of the same
        slot: a second request blocks here until the first commits, then re-reads
        appointments and sees the first booking - so it correctly picks a different bay
        or reports the slot full instead of double-booking.
        """
        bays = request.env["carwash.appointment"].sudo()._carwash_bookable_bays(company)
        if not bays:
            return None
        request.env.cr.execute(
            "SELECT id FROM carwash_bay WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(bays.ids),)
        )
        existing = request.env["carwash.appointment"].sudo().search(
            [
                ("company_id", "=", company.id),
                ("bay_id", "in", bays.ids),
                ("state", "in", ("confirmed", "arrived", "in_service")),
            ]
        )
        busy_ids = set()
        for appt in existing:
            o_start, o_end = appt._get_bay_window()
            if start < o_end and o_start < end:
                busy_ids.add(appt.bay_id.id)
        free = bays.filtered(lambda b: b.id not in busy_ids)
        return free[:1]

    @http.route("/car-wash/home", type="http", auth="public", website=True, sitemap=True)
    def book_home(self, **kwargs):
        website = request.website
        values = {
            "branches": self._get_branches(),
            "services": self._get_services(),
            "show_packages": website.carwash_show_packages,
            "packages": self._get_packages() if website.carwash_show_packages else request.env["carwash.service.package"],
        }
        return request.render("carwash_website.book_home_page", values)

    @http.route("/car-wash/book", type="http", auth="public", website=True, sitemap=False)
    def book_start(self, package_id=None, **kwargs):
        if request.env.user._is_public():
            return request.render("carwash_website.book_auth_required", {})
        _service, package = self._get_selection(package_id=package_id)
        values = {
            "branches": self._get_branches(),
            "services": self._get_services(),
            "packages": self._get_packages(),
            "package": package,
            "service": request.env["product.product"],
            "today": datetime.now().date(),
            "membership": self._get_usable_membership(request.env.user.partner_id),
        }
        return request.render("carwash_website.book_start_page", values)

    @http.route("/car-wash/book/slots", type="http", auth="user", website=True, sitemap=False)
    def book_slots(self, company_id=None, product_id=None, date=None, error=None, package_id=None, **kwargs):
        branches = self._get_branches()
        services = self._get_services()
        company_id = self._to_int(company_id)
        company = branches.filtered(lambda c: c.id == company_id) if company_id else request.env["res.company"]
        service, package = self._get_selection(product_id, package_id)
        booking_date = None
        if date:
            try:
                booking_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                booking_date = None

        values = {
            "branches": branches,
            "services": services,
            "packages": self._get_packages(),
            "today": datetime.now().date(),
            "company": company,
            "service": service,
            "package": package,
            "date": date,
            "error": error,
            "membership": self._get_usable_membership(request.env.user.partner_id),
        }
        if not (company and (service or package) and booking_date):
            values["error"] = values["error"] or "Please choose a branch, a package or service, and a date."
            return request.render("carwash_website.book_start_page", values)

        partner = request.env.user.partner_id
        slots = self._bookable_slots(company, booking_date, service, package)
        vehicles = request.env["carwash.vehicle"].sudo().search(
            [("customer_id", "=", partner.id), ("company_id", "=", company.id)]
        )
        values.update(
            {
                "slots": slots,
                "vehicles": vehicles,
                "vehicle_types": request.env["carwash.vehicle.type"].sudo().search([]),
                "default_vehicle_type": request.env["carwash.vehicle.type"].sudo()._default_type(),
                "normal_amount": round(sum(price * qty for _p, price, qty in self._booking_price_lines(service, package)), 2),
                "membership_preview": self._membership_preview(values["membership"], service, package),
            }
        )
        return request.render("carwash_website.book_slots_page", values)

    @http.route("/car-wash/book/confirm", type="http", auth="user", website=True, methods=["POST"], sitemap=False)
    def book_confirm(self, company_id=None, slot_start=None, product_id=None, vehicle_id=None, license_plate=None,
                      make=None, vehicle_model=None, vehicle_type=None, package_id=None, use_membership=None,
                      vehicle_type_id=None, **kwargs):
        company_id = self._to_int(company_id)
        service, package = self._get_selection(product_id, package_id)
        if not (company_id and (service or package)):
            return request.redirect("/car-wash/book")
        company = request.env["res.company"].sudo().browse(company_id)
        if company not in self._get_branches():
            return request.redirect("/car-wash/book")
        product_id = service.id or None
        retry = {"package_id": package.id or None}

        start = self._parse_slot_start(company, slot_start)
        if not start:
            return request.redirect("/car-wash/book")
        local_date = self._to_local(company, start).date()
        end = start + timedelta(hours=self._selection_duration(service, package))
        # only a slot the page offered can be booked (no past / closed / lunch / odd times)
        if start not in {slot["start"] for slot in self._bookable_slots(company, local_date, service, package)}:
            return self.book_slots(
                company_id=company_id, product_id=product_id, date=local_date.isoformat(), **retry,
                error="That time can't be booked any more. Please pick one of the available times.",
            )

        partner = request.env.user.partner_id
        Vehicle = request.env["carwash.vehicle"].sudo()
        vehicle_id = self._to_int(vehicle_id)
        if vehicle_id:
            vehicle = Vehicle.search(
                [("id", "=", vehicle_id), ("customer_id", "=", partner.id), ("company_id", "=", company.id)]
            )
            if not vehicle:
                return self.book_slots(
                    company_id=company_id, product_id=product_id, date=local_date.isoformat(), **retry,
                    error="That vehicle is no longer available. Please pick another.",
                )
        elif license_plate:
            vehicle = Vehicle.create(
                {
                    "license_plate": license_plate,
                    "customer_id": partner.id,
                    "company_id": company.id,
                    "make": make or "",
                    "vehicle_model": vehicle_model or "",
                    "vehicle_type_id": self._vehicle_type(vehicle_type_id, vehicle_type).id,
                }
            )
        else:
            return self.book_slots(
                company_id=company_id, product_id=product_id, date=local_date.isoformat(), **retry,
                error="Please select an existing vehicle or register a new one.",
            )

        bay = self._lock_and_pick_bay(company, start, end)
        if not bay:
            return self.book_slots(
                company_id=company_id, product_id=product_id, date=local_date.isoformat(), **retry,
                error="Sorry, that slot was just taken. Please pick another time.",
            )

        return self._carwash_finalize_booking(
            partner, vehicle, company, service, start, bay, package=package,
            use_membership=bool(use_membership and self._get_usable_membership(partner)),
        )

    def _carwash_finalize_booking(self, partner, vehicle, company, service, start, bay, package=None,
                                  use_membership=False):
        """Turn a validated website request (free slot + bay found) into the booking."""
        package = package or request.env["carwash.service.package"]
        Appointment = request.env["carwash.appointment"].sudo()
        extra = service - package.line_ids.product_id
        # the package's services are added right after creating the booking
        appointment = Appointment.with_context(carwash_services_pending=True).create(
            {
                "customer_id": partner.id,
                "vehicle_id": vehicle.id,
                "company_id": company.id,
                "appointment_date": start,
                "line_ids": [(0, 0, {"product_id": extra.id, "quantity": 1})] if extra else [],
            }
        ).with_context(carwash_services_pending=False)
        try:
            if package:
                appointment._apply_service_package(package)
            if use_membership:
                try:
                    appointment.action_apply_membership()
                except UserError:
                    pass  # no benefit on these services - book at the normal price
            appointment.bay_id = bay.id
            appointment.action_confirm()
        except UserError:
            return self.book_slots(
                company_id=company.id, product_id=service.id or None, package_id=package.id or None,
                date=self._to_local(company, start).date().isoformat(),
                error="Sorry, that slot was just taken. Please pick another time.",
            )
        return request.redirect(f"/car-wash/book/success/{appointment.id}")

    @http.route("/car-wash/book/success/<int:appointment_id>", type="http", auth="user", website=True, sitemap=False)
    def book_success(self, appointment_id, **kwargs):
        appointment = request.env["carwash.appointment"].sudo().browse(appointment_id)
        if not appointment.exists() or appointment.customer_id != request.env.user.partner_id:
            return request.redirect("/car-wash/book")
        return request.render("carwash_website.book_success_page", {"appointment": appointment})
