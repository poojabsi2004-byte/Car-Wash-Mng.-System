from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPortalBookings(HttpCase):
    def test_my_bookings_lists_own_bookings(self):
        portal = new_test_user(self.env, login="cw_portal_test", groups="base.group_portal", name="Portal Customer")
        vehicle = self.env["carwash.vehicle"].create({"license_plate": "PORTAL 1", "customer_id": portal.partner_id.id})
        wash = self.env["product.product"].create(
            {"name": "Portal Wash", "type": "service", "is_carwash_service": True, "list_price": 300}
        )
        booking = self.env["carwash.appointment"].create({
            "customer_id": portal.partner_id.id, "vehicle_id": vehicle.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=1),
            "line_ids": [(0, 0, {"product_id": wash.id})],
        })
        # dates are shown in the branch's timezone, whose working hours a portal user can't read
        self.assertTrue(booking.with_user(portal)._slot_local(booking.appointment_date))
        self.authenticate("cw_portal_test", "cw_portal_test")
        response = self.url_open("/my/bookings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(booking.name, response.text)
        response = self.url_open(f"/my/bookings/{booking.id}")
        self.assertEqual(response.status_code, 200)
