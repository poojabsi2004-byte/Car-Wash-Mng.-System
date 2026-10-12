from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.branch_a = cls.env["res.company"].create({"name": "Dash Branch A"})
        cls.branch_b = cls.env["res.company"].create({"name": "Dash Branch B"})
        cls.owner = cls.env["res.users"].create({
            "name": "Dash Owner", "login": "dash_owner",
            "company_id": cls.branch_a.id, "company_ids": [(6, 0, (cls.branch_a | cls.branch_b).ids)],
            "group_ids": [(6, 0, [cls.env.ref("carwash_multibranch.group_carwash_owner").id])],
        })
        customer = cls.env["res.partner"].create({"name": "Dash Customer"})
        wash = cls.env["product.product"].create({"name": "Dash Wash", "type": "service", "is_carwash_service": True, "list_price": 250})
        vehicle = cls.env["carwash.vehicle"].create({"license_plate": "DASH 1", "customer_id": customer.id, "company_id": cls.branch_b.id})
        booking = cls.env["carwash.appointment"].with_company(cls.branch_b).create({
            "customer_id": customer.id, "vehicle_id": vehicle.id, "company_id": cls.branch_b.id,
            "appointment_date": fields.Datetime.now() - timedelta(hours=2),
            "line_ids": [(0, 0, {"product_id": wash.id})],
        })
        booking.write({"state": "done", "done_at": fields.Datetime.now()})
        cls.booking = booking

    def _data(self, companies):
        self.env.invalidate_all()  # like a fresh request: nothing read before as another user
        env = self.env(user=self.owner, context={"allowed_company_ids": companies.ids})
        return env["carwash.dashboard"].get_dashboard_data()

    def test_owner_with_one_branch_ticked(self):
        """Branch B has revenue - an owner looking at branch A only must not hit an access error."""
        data = self._data(self.branch_a)
        self.assertTrue(data["has_owner_data"])
        self.assertNotIn("Dash Branch B", [b["name"] for b in data["branch_breakdown"]],
                         "the overview follows the branches ticked in the switcher")
        data = self._data(self.branch_a | self.branch_b)
        self.assertIn("Dash Branch B", [b["name"] for b in data["branch_breakdown"]])

    def test_owner_lists_follow_the_switcher(self):
        env = self.env(user=self.owner, context={"allowed_company_ids": self.branch_a.ids})
        self.assertFalse(env["carwash.appointment"].search([("company_id", "=", self.branch_b.id)]))

    def test_booking_calendar_week(self):
        """The dashboard calendar shows a week of bookings per local day, in the ticked branches only."""
        env = self.env(user=self.owner, context={"allowed_company_ids": self.branch_b.ids, "tz": "UTC"})
        today = fields.Date.context_today(env["carwash.dashboard"])
        monday = today - timedelta(days=today.weekday())
        data = env["carwash.dashboard"].get_calendar_data()
        self.assertEqual((data["start"], len(data["days"])), (fields.Date.to_string(monday), 7))
        self.assertTrue(data["is_current"])
        booked = [b for day in data["days"] for b in day["bookings"]]
        if self.booking.appointment_date.date() >= monday:
            self.assertIn(self.booking.id, [b["id"] for b in booked], "this week's booking of the branch is shown")
        next_week = env["carwash.dashboard"].get_calendar_data(fields.Date.to_string(monday + timedelta(days=7)))
        self.assertFalse(next_week["is_current"])
        other_branch = self.env(user=self.owner, context={"allowed_company_ids": self.branch_a.ids, "tz": "UTC"})
        booked_a = [b["id"] for day in other_branch["carwash.dashboard"].get_calendar_data()["days"] for b in day["bookings"]]
        self.assertNotIn(self.booking.id, booked_a, "other branches' bookings are not shown")
