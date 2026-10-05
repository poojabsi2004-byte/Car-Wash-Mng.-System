from datetime import datetime, timedelta

from odoo import http
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteBookingLead(HttpCase):

    def _confirm(self, lead):
        """Staff tick the request-verification checklist, then confirm the lead into a booking."""
        self.assertTrue(lead.checklist_line_ids, "website requests get the default request checklist")
        lead.checklist_line_ids.write({"is_done": True})
        lead.with_user(self.env.ref("base.user_admin")).action_confirm_carwash_booking()

    def test_website_booking_creates_lead_then_confirm_creates_booking(self):
        portal = self.env["res.users"].create(
            {
                "name": "Portal Booker",
                "login": "portal_booker",
                "password": "portal_booker_pw",
                "email": "portal.booker@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        company = self.env["carwash.bay"].search([("active", "=", True)], limit=1).company_id
        service = self.env["product.product"].search([("is_carwash_service", "=", True)], limit=1)
        start = (datetime.now() + timedelta(days=30)).replace(hour=5, minute=0, second=0, microsecond=0)

        self.authenticate("portal_booker", "portal_booker_pw")
        response = self.url_open(
            "/car-wash/book/confirm",
            data={
                "company_id": company.id,
                "product_id": service.id,
                "slot_start": start.isoformat(),
                "license_plate": "TEST 1234",
                "make": "Test",
                "vehicle_model": "Car",
                "vehicle_type": "sedan",
                "csrf_token": http.Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/car-wash/book/requested/", response.headers["Location"])

        lead = self.env["crm.lead"].search([("partner_id", "=", portal.partner_id.id)])
        self.assertEqual(len(lead), 1)
        self.assertTrue(lead.is_carwash_booking)
        self.assertEqual(lead.carwash_service_ids, service)
        self.assertEqual(lead.carwash_license_plate, "TEST 1234")
        self.assertEqual(lead.team_id, self.env.ref("carwash_crm.crm_team_carwash_bookings"))
        self.assertFalse(
            self.env["carwash.appointment"].search([("customer_id", "=", portal.partner_id.id)]),
            "A website request must not create a booking before staff confirm the lead",
        )

        page = self.url_open(response.headers["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("Booking Request Received", page.text)

        self._confirm(lead)
        booking = lead.carwash_appointment_id
        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(booking.customer_id, portal.partner_id)
        self.assertEqual(booking.lead_id, lead)
        self.assertEqual(lead.won_status, "won")

    def test_website_package_booking_flows_into_lead_and_booking(self):
        portal = self.env["res.users"].create(
            {
                "name": "Package Booker",
                "login": "package_booker",
                "password": "package_booker_pw",
                "email": "package.booker@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        services = self.env["product.product"].search([("is_carwash_service", "=", True), ("list_price", ">", 0)], limit=3)
        self.assertGreaterEqual(len(services), 3, "test needs 3 priced car wash services")
        package = self.env["carwash.service.package"].create(
            {
                "name": "Test Combo",
                "price_type": "fixed",
                "fixed_price": round(sum(services[:2].mapped("list_price")) * 0.8, 2),
                "line_ids": [(0, 0, {"product_id": p.id}) for p in services[:2]],
            }
        )
        extra = services[2]
        company = self.env["carwash.bay"].search([("active", "=", True)], limit=1).company_id
        start = (datetime.now() + timedelta(days=31)).replace(hour=6, minute=0, second=0, microsecond=0)

        self.authenticate("package_booker", "package_booker_pw")
        start_page = self.url_open(f"/car-wash/book?package_id={package.id}")
        self.assertIn(f'value="{package.id}" selected', start_page.text.replace("selected=\"selected\"", "selected"))

        response = self.url_open(
            "/car-wash/book/confirm",
            data={
                "company_id": company.id,
                "package_id": package.id,
                "product_id": extra.id,
                "slot_start": start.isoformat(),
                "license_plate": "PKG 777",
                "csrf_token": http.Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        lead = self.env["crm.lead"].search([("partner_id", "=", portal.partner_id.id)])
        self.assertEqual(lead.carwash_package_id, package)
        self.assertEqual(lead.carwash_package_service_ids, services[:2])
        self.assertEqual(lead.carwash_service_ids, extra, "only the extra service is listed as an extra")
        self.assertAlmostEqual(lead.expected_revenue, package.total_price + extra.list_price, places=2)

        self._confirm(lead)
        booking = lead.carwash_appointment_id
        self.assertEqual(booking.service_package_id, package)
        self.assertAlmostEqual(booking.package_amount, package.total_price, places=2)
        self.assertAlmostEqual(booking.extra_services_amount, extra.list_price, places=2)
        self.assertAlmostEqual(booking.amount_total, package.total_price + extra.list_price, places=2)
        self.assertEqual(booking.line_ids.filtered("package_id").product_id, services[:2])

    def test_website_membership_join_pay_and_use(self):
        portal = self.env["res.users"].create(
            {
                "name": "Member Booker",
                "login": "member_booker",
                "password": "member_booker_pw",
                "email": "member.booker@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        wash = self.env["product.product"].create(
            {"name": "Member Wash", "type": "service", "is_carwash_service": True, "list_price": 300, "carwash_duration": 0.5}
        )
        fee = self.env["product.product"].create({"name": "Member Fee", "type": "service", "list_price": 999})
        plan = self.env["carwash.membership.plan"].create(
            {"name": "Web Gold", "product_id": fee.id, "wash_allowance": 2,
             "plan_service_ids": [(6, 0, wash.ids)], "discount_percent": 10}
        )

        # public visitors see the plan and are asked to log in
        page = self.url_open("/car-wash/membership")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Web Gold", page.text)
        self.assertIn("Log in to join", page.text)

        # join -> pending membership + billing order, redirected to the order's payment page
        self.authenticate("member_booker", "member_booker_pw")
        response = self.url_open(
            "/car-wash/membership/join",
            data={"plan_id": plan.id, "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/my/orders/", response.headers["Location"])
        membership = self.env["carwash.membership"].search([("partner_id", "=", portal.partner_id.id)])
        self.assertEqual(membership.state, "pending")
        self.assertIn("Pay now", self.url_open("/my/membership").text)

        # online payment completes -> active
        provider = self.env.ref("payment.payment_provider_demo")
        provider.state = "test"
        order = membership.pending_order_id
        tx = self.env["payment.transaction"].create(
            {
                "provider_id": provider.id,
                "payment_method_id": provider.payment_method_ids[:1].id,
                "amount": order.amount_total,
                "currency_id": order.currency_id.id,
                "partner_id": portal.partner_id.id,
                "reference": f"WEB-{order.name}",
                "sale_order_ids": [(6, 0, order.ids)],
            }
        )
        tx._set_done()
        tx._post_process()
        self.assertEqual(membership.state, "active")
        self.assertIn("Active", self.url_open("/my/membership").text)

        # booking online offers the membership; the request carries it to the lead and the booking
        company = self.env["carwash.bay"].search([("active", "=", True)], limit=1).company_id
        date = (datetime.now() + timedelta(days=32)).date().isoformat()
        slots_page = self.url_open(f"/car-wash/book/slots?company_id={company.id}&product_id={wash.id}&date={date}")
        self.assertIn("Use my Web Gold membership", slots_page.text)
        start = (datetime.now() + timedelta(days=32)).replace(hour=7, minute=0, second=0, microsecond=0)
        response = self.url_open(
            "/car-wash/book/confirm",
            data={
                "company_id": company.id, "product_id": wash.id, "slot_start": start.isoformat(),
                "license_plate": "MEM 1", "use_membership": "1", "csrf_token": http.Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        lead = self.env["crm.lead"].search([("partner_id", "=", portal.partner_id.id)])
        self.assertTrue(lead.carwash_use_membership)
        self._confirm(lead)
        booking = lead.carwash_appointment_id
        self.assertEqual(booking.membership_id, membership)
        self.assertEqual(booking.amount_total, 0.0, "the covered wash is free")

    def test_request_checklist_gates_confirmation(self):
        partner = self.env["res.partner"].create({"name": "Phone Caller", "phone": "123"})
        service = self.env["product.product"].search([("is_carwash_service", "=", True)], limit=1)
        lead = self.env["crm.lead"].create(
            {
                "name": "Phone request",
                "type": "opportunity",
                "is_carwash_booking": True,
                "partner_id": partner.id,
                "carwash_booking_date": datetime.now() + timedelta(days=40),
                "carwash_service_ids": [(6, 0, service.ids)],
                "carwash_license_plate": "CALL 1",
            }
        )
        template = self.env.ref("carwash_crm.checklist_template_lead_verification")
        self.assertEqual(lead.checklist_template_id, template)
        with self.assertRaisesRegex(UserError, "mandatory checklist"):
            lead.action_confirm_carwash_booking()
        self.assertFalse(lead.carwash_appointment_id)
        lead.checklist_line_ids.filtered("is_required").write({"is_done": True})
        lead.action_confirm_carwash_booking()
        self.assertTrue(lead.carwash_appointment_id)

        # leads that aren't car wash requests get no checklist
        other = self.env["crm.lead"].create({"name": "Fleet deal", "type": "opportunity"})
        self.assertFalse(other.checklist_line_ids)

    def test_member_portal_apply_remove_renew(self):
        portal = self.env["res.users"].create(
            {
                "name": "Portal Member",
                "login": "portal_member",
                "password": "portal_member_pw",
                "email": "portal.member@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        wash = self.env["product.product"].create(
            {"name": "Portal Wash", "type": "service", "is_carwash_service": True, "list_price": 200, "carwash_duration": 0.5}
        )
        wax = self.env["product.product"].create(
            {"name": "Portal Wax", "type": "service", "is_carwash_service": True, "list_price": 100, "carwash_duration": 0.5}
        )
        fee = self.env["product.product"].create({"name": "Portal Fee", "type": "service", "list_price": 500})
        plan = self.env["carwash.membership.plan"].create(
            {"name": "Portal Gold", "product_id": fee.id, "wash_allowance": 3,
             "plan_service_ids": [(6, 0, wash.ids)], "discount_percent": 10}
        )
        membership = self.env["carwash.membership"].create({"partner_id": portal.partner_id.id, "plan_id": plan.id})
        membership._register_paid_order(membership._get_or_create_billing_order())
        self.assertEqual(membership.state, "active")
        company = self.env["carwash.bay"].search([("active", "=", True)], limit=1).company_id
        vehicle = self.env["carwash.vehicle"].create(
            {"license_plate": "PM 1", "customer_id": portal.partner_id.id, "company_id": company.id}
        )
        booking = self.env["carwash.appointment"].create(
            {
                "customer_id": portal.partner_id.id,
                "vehicle_id": vehicle.id,
                "company_id": company.id,
                "appointment_date": datetime.now() + timedelta(days=41),
                "line_ids": [(0, 0, {"product_id": wash.id}), (0, 0, {"product_id": wax.id})],
            }
        )
        booking.action_confirm()

        self.authenticate("portal_member", "portal_member_pw")
        # the booking flow shows the member price before booking
        day = (datetime.now() + timedelta(days=42)).date()
        while day.weekday() >= 5:  # a working day, so the branch has open slots
            day += timedelta(days=1)
        date = day.isoformat()
        slots = self.url_open(f"/car-wash/book/slots?company_id={company.id}&product_id={wash.id}&date={date}")
        self.assertIn("Use my Portal Gold membership", slots.text)
        self.assertIn("Free with membership", slots.text)
        self.assertIn("free with your membership", self.url_open("/car-wash/book").text)

        # apply the membership on an existing booking from the portal
        page = self.url_open(f"/my/bookings/{booking.id}")
        self.assertIn("Apply my membership", page.text)
        response = self.url_open(
            f"/my/bookings/{booking.id}/membership",
            data={"apply": "1", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(booking.membership_id, membership)
        self.assertAlmostEqual(booking.amount_total, 90.0, msg="wash free, wax -10%")
        self.assertIn("Free with membership", self.url_open(response.headers["Location"]).text)

        # ... and remove it again
        self.url_open(
            f"/my/bookings/{booking.id}/membership",
            data={"apply": "0", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertFalse(booking.membership_id)
        self.assertAlmostEqual(booking.amount_total, 300.0)

        # someone else's booking is out of reach
        other = self.env["carwash.appointment"].create(
            {
                "customer_id": self.env["res.partner"].create({"name": "Someone Else"}).id,
                "vehicle_id": vehicle.id,
                "company_id": company.id,
                "appointment_date": datetime.now() + timedelta(days=41),
                "line_ids": [(0, 0, {"product_id": wash.id})],
            }
        )
        response = self.url_open(
            f"/my/bookings/{other.id}/membership",
            data={"apply": "1", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertEqual(response.headers["Location"].rsplit("/", 1)[-1], "bookings")
        self.assertFalse(other.membership_id)

        # auto-renewal off/on and paying the next period early
        self.url_open(
            f"/my/membership/{membership.id}/auto-renew",
            data={"auto_renew": "0", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertFalse(membership.auto_renew)
        self.assertIn("Auto-renewal", self.url_open("/my/membership").text)
        response = self.url_open(
            f"/my/membership/{membership.id}/renew",
            data={"csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertIn("/my/orders/", response.headers["Location"])
        self.assertTrue(membership.pending_order_id)

    def test_member_request_membership_toggle(self):
        portal = self.env["res.users"].create(
            {
                "name": "Request Member",
                "login": "request_member",
                "password": "request_member_pw",
                "email": "request.member@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        wash = self.env["product.product"].create(
            {"name": "Req Wash", "type": "service", "is_carwash_service": True, "list_price": 150}
        )
        fee = self.env["product.product"].create({"name": "Req Fee", "type": "service", "list_price": 500})
        plan = self.env["carwash.membership.plan"].create(
            {"name": "Req Plan", "product_id": fee.id, "wash_allowance": 2, "plan_service_ids": [(6, 0, wash.ids)]}
        )
        membership = self.env["carwash.membership"].create({"partner_id": portal.partner_id.id, "plan_id": plan.id})
        membership._register_paid_order(membership._get_or_create_billing_order())
        lead = self.env["crm.lead"].create(
            {
                "name": "Member request",
                "type": "opportunity",
                "is_carwash_booking": True,
                "partner_id": portal.partner_id.id,
                "carwash_booking_date": datetime.now() + timedelta(days=43),
                "carwash_service_ids": [(6, 0, wash.ids)],
                "carwash_license_plate": "REQ 1",
            }
        )
        self.assertEqual(lead.carwash_member_amount, 150.0, "membership not switched on yet")

        self.authenticate("request_member", "request_member_pw")
        page = self.url_open("/my/bookings")
        self.assertIn("Awaiting confirmation", page.text)
        self.assertIn("Apply my membership", page.text)
        self.url_open(
            f"/my/booking-requests/{lead.id}/membership",
            data={"use_membership": "1", "csrf_token": http.Request.csrf_token(self)},
            allow_redirects=False,
        )
        self.assertTrue(lead.carwash_use_membership)
        self.assertEqual(lead.carwash_member_amount, 0.0)
        self.assertEqual(lead.expected_revenue, 0.0)

        self._confirm(lead)
        self.assertEqual(lead.carwash_appointment_id.membership_id, membership)
