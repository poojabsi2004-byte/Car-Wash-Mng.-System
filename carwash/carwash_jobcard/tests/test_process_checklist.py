from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProcessChecklist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Checklist Manager",
                "login": "checklist_manager",
                "group_ids": [(6, 0, [cls.env.ref("carwash_base.group_carwash_manager").id])],
            }
        )
        cls.env = cls.env(user=cls.manager)
        cls.customer = cls.env["res.partner"].sudo().create({"name": "Checklist Customer"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "CHK-1", "customer_id": cls.customer.id})
        cls.wash = cls.env["product.product"].sudo().create(
            {"name": "Checklist Wash", "type": "service", "is_carwash_service": True, "list_price": 100}
        )
        cls.bay = cls.env["carwash.bay"].create({"name": "Checklist Bay"})
        cls.pre_type = cls.env.ref("carwash_jobcard.inspection_type_pre")

    def _booking(self):
        return self.env["carwash.appointment"].create(
            {
                "customer_id": self.customer.id,
                "vehicle_id": self.vehicle.id,
                "bay_id": self.bay.id,
                "appointment_date": fields.Datetime.now() + timedelta(days=3),
                "line_ids": [(0, 0, {"product_id": self.wash.id})],
            }
        )

    def test_default_templates_are_loaded(self):
        booking = self._booking()
        checkin = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        self.assertEqual(booking.checklist_template_id, checkin)
        self.assertEqual(booking.checklist_line_ids.mapped("name"), checkin.item_ids.mapped("name"))
        self.assertFalse(booking.checklist_complete)

        inspection = self.env["carwash.inspection"].create(
            {"appointment_id": booking.id, "inspection_type_id": self.pre_type.id}
        )
        self.assertEqual(inspection.checklist_template_id, self.env.ref("carwash_jobcard.checklist_template_inspection_pre"))
        self.assertEqual(inspection.state, "draft")

    def test_checkin_checklist_gates_start_service(self):
        booking = self._booking()
        booking.action_confirm()
        booking.action_arrive()
        with self.assertRaisesRegex(UserError, "mandatory checklist"):
            booking.action_start_service()

        # optional tasks don't block; ticking stamps who did it
        booking.checklist_line_ids.filtered("is_required").write({"is_done": True})
        line = booking.checklist_line_ids.filtered("is_done")[:1]
        self.assertEqual(line.done_by_id, self.manager)
        self.assertTrue(line.done_date)
        self.assertTrue(booking.checklist_complete)
        self.assertLess(booking.checklist_progress, 100)

        # an unfinished pre-wash inspection still blocks the start
        inspection = self.env["carwash.inspection"].create(
            {"appointment_id": booking.id, "inspection_type_id": self.pre_type.id}
        )
        with self.assertRaisesRegex(UserError, "Complete inspection"):
            booking.action_start_service()
        with self.assertRaisesRegex(UserError, "mandatory checklist"):
            inspection.action_complete()
        inspection.checklist_line_ids.write({"is_done": True})
        inspection.action_complete()
        self.assertEqual(inspection.state, "done")

        booking.action_start_service()
        self.assertEqual(booking.state, "in_service")

    def test_unticking_clears_stamp_and_no_template_means_no_gate(self):
        self.env["carwash.checklist.template"].search([("checklist_type", "=", "booking")]).is_default = False
        booking = self._booking()
        self.assertFalse(booking.checklist_line_ids)
        self.assertTrue(booking.checklist_complete)

        booking.checklist_template_id = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        booking.action_reload_checklist()
        line = booking.checklist_line_ids[:1]
        line.is_done = True
        line.is_done = False
        self.assertFalse(line.done_by_id)
        self.assertFalse(line.done_date)

    def test_mandatory_flag_comes_from_the_template(self):
        template = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        optional_item = template.item_ids.filtered(lambda item: not item.is_required)[:1]
        mandatory_item = template.item_ids.filtered("is_required")[:1]
        booking = self._booking()
        # a client that only sends the task name (e.g. a stale cached view) can't make it mandatory
        booking.write({"checklist_line_ids": [(5, 0, 0)] + [
            (0, 0, {"name": item.name, "template_item_id": item.id}) for item in optional_item | mandatory_item
        ]})
        line_by_item = {line.template_item_id: line for line in booking.checklist_line_ids}
        self.assertFalse(line_by_item[optional_item].is_required)
        self.assertTrue(line_by_item[mandatory_item].is_required)

        # a mandatory template task can't be switched off; a task added by hand can be set either way
        line_by_item[mandatory_item].is_required = False
        self.assertTrue(line_by_item[mandatory_item].is_required)
        booking.write({"checklist_line_ids": [(0, 0, {"name": "Extra: check roof box"})]})
        manual = booking.checklist_line_ids.filtered(lambda line: not line.template_item_id)
        self.assertFalse(manual.is_required, "hand-added tasks are optional by default")
        manual.is_required = True
        self.assertTrue(manual.is_required)
