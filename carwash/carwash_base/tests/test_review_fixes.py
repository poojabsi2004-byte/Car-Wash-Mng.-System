from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestReviewFixes(TransactionCase):
    """Regression tests for the QA review of 06 Oct 2026 (booking workflow, bays, vehicles, timezones)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Fix Branch"})
        cls.other_company = cls.env["res.company"].create({"name": "Fix Other Branch"})
        Bay = cls.env["carwash.bay"]
        cls.bay = Bay.create({"name": "Fix Bay 1", "company_id": cls.company.id})
        cls.bay_2 = Bay.create({"name": "Fix Bay 2", "company_id": cls.company.id})
        cls.foreign_bay = Bay.create({"name": "Fix Foreign Bay", "company_id": cls.other_company.id})
        cls.customer = cls.env["res.partner"].create({"name": "Fix Customer"})
        cls.vehicle = cls.env["carwash.vehicle"].create(
            {"license_plate": "FIX 1", "customer_id": cls.customer.id, "company_id": cls.company.id}
        )
        cls.wash = cls.env["product.product"].create(
            {"name": "Fix Wash", "type": "service", "is_carwash_service": True, "list_price": 100}
        )
        cls.Appointment = cls.env["carwash.appointment"].with_company(cls.company)

    def _booking(self, bay=None, **vals):
        return self.Appointment.create({
            "customer_id": self.customer.id, "vehicle_id": self.vehicle.id, "company_id": self.company.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=3), "bay_id": (bay or self.bay).id,
            "line_ids": [(0, 0, {"product_id": self.wash.id})], **vals,
        })

    def test_workflow_state_guards(self):
        booking = self._booking()
        with self.assertRaisesRegex(UserError, "can't be completed"):
            booking.action_done()
        self.assertFalse(booking.sale_order_id, "no sales order for a draft booking")
        with self.assertRaisesRegex(UserError, "can't be marked as arrived"):
            booking.action_arrive()
        booking.action_confirm()
        with self.assertRaisesRegex(UserError, "can't be confirmed"):
            booking.action_confirm()
        booking.action_arrive()
        booking.action_cancel()  # a customer who leaves before the wash
        self.assertEqual(booking.state, "cancelled")

    def test_maintenance_bay_is_not_bookable(self):
        self.bay_2.state = "maintenance"
        start = fields.Datetime.now() + timedelta(days=3)
        free = self.Appointment._carwash_free_bays(self.company, start, 0.5)
        self.assertEqual(free, self.bay)

    def test_bay_must_belong_to_the_branch(self):
        with self.assertRaisesRegex(ValidationError, "belongs to"):
            self._booking(bay=self.foreign_bay)

    def test_bay_occupied_only_by_a_service(self):
        with self.assertRaisesRegex(UserError, "becomes Occupied automatically"):
            self.bay.state = "occupied"
        self.bay.state = "maintenance"
        self.bay.state = "free"
        self.assertEqual(self.bay.state, "free")

    def test_licence_plate_is_normalized(self):
        vehicle = self.env["carwash.vehicle"].create(
            {"license_plate": "  gj01  ab 77 ", "customer_id": self.customer.id, "company_id": self.company.id}
        )
        self.assertEqual(vehicle.license_plate, "GJ01 AB 77")
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env["carwash.vehicle"].create(
                {"license_plate": "gj01 ab 77", "customer_id": self.customer.id, "company_id": self.company.id}
            )
            self.env.flush_all()

    def test_old_timezone_alias_is_normalized(self):
        partner = self.env["res.partner"].create({"name": "Fix TZ", "tz": "Asia/Calcutta"})
        self.assertEqual(partner.tz, "Asia/Kolkata")
        partner.tz = "Asia/Calcutta"
        self.assertEqual(partner.tz, "Asia/Kolkata")

    def test_consumption_recorded_without_stock(self):
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", self.company.id)], limit=1)
        if not warehouse:
            self.skipTest("branch has no warehouse")
        soap = self.env["product.product"].create({"name": "Fix Soap", "type": "consu", "is_storable": True})
        self.wash.product_tmpl_id.carwash_material_line_ids = [(0, 0, {"product_id": soap.id, "quantity": 0.5})]
        booking = self._booking()
        booking.action_confirm()
        booking.state = "ready"
        booking.action_done()
        move = booking.stock_move_ids
        self.assertEqual((move.state, move.quantity), ("done", 0.5), "usage recorded even with nothing on hand")

    def test_vehicle_types_are_configurable(self):
        """Vehicle Type is a list of records: standard ones with a code, own ones created on the fly."""
        VehicleType = self.env["carwash.vehicle.type"]
        self.assertEqual(VehicleType._by_code("bike"), self.env.ref("carwash_base.vehicle_type_bike"))
        self.assertEqual(self.vehicle.vehicle_type_id, self.env.ref("carwash_base.vehicle_type_sedan"), "Sedan by default")
        type_id, _name = VehicleType.name_create("Scooter")  # 'Create "Scooter"' from the dropdown
        scooter = VehicleType.browse(type_id)
        self.vehicle.vehicle_type_id = scooter
        self.assertEqual((scooter.vehicle_count, scooter.icon), (1, "fa-car"))
        self.assertIn(self.vehicle, self.env["carwash.vehicle"].search(scooter.action_view_vehicles()["domain"]))
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            VehicleType.create({"name": "Scooter"})
            self.env.flush_all()

