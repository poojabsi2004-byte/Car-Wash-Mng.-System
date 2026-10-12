from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProcessChecklist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # these tests are about the features below - make sure they are switched on
        cls.env.ref("base.group_user").write({"implied_ids": [(4, cls.env.ref(x).id) for x in ['carwash_jobcard.group_carwash_checklist', 'carwash_jobcard.group_carwash_inspection']]})
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
        booking.action_confirm()
        self.assertFalse(booking.checklist_line_ids, "no check-in checklist while it's only a booking")
        booking.action_arrive()
        checkin = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        self.assertEqual(booking.checklist_template_id, checkin, "added when the vehicle arrives")
        self.assertEqual(booking.checklist_line_ids.mapped("name"), checkin.item_ids.mapped("name"))
        self.assertFalse(booking.checklist_complete)

        inspection = self.env["carwash.inspection"].create(
            {"appointment_id": booking.id, "inspection_type_id": self.pre_type.id}
        )
        self.assertEqual(inspection.checklist_template_id, self.env.ref("carwash_jobcard.checklist_template_inspection_pre"))
        self.assertEqual(inspection.state, "draft")

    def test_checklist_template_lists_its_records(self):
        checkin = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        pre = self.env.ref("carwash_jobcard.checklist_template_inspection_pre")
        before = (checkin.usage_count, pre.usage_count)
        booking = self._booking()
        booking.action_confirm()
        booking.action_arrive()
        inspection = self.env["carwash.inspection"].create(
            {"appointment_id": booking.id, "inspection_type_id": self.pre_type.id}
        )
        checkin.invalidate_recordset(["usage_count"])
        pre.invalidate_recordset(["usage_count"])
        self.assertEqual((checkin.usage_count, pre.usage_count), (before[0] + 1, before[1] + 1))

        action = checkin.action_view_usage()
        self.assertEqual(action["res_model"], "carwash.appointment")
        self.assertIn(booking, self.env[action["res_model"]].search(action["domain"]))
        action = pre.action_view_usage()
        self.assertEqual(action["res_model"], "carwash.inspection")
        self.assertIn(inspection, self.env[action["res_model"]].search(action["domain"]))

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

    def test_two_wheeler_gets_its_own_checklists(self):
        bike = self.env["carwash.vehicle"].create(
            {"license_plate": "BIKE-1", "customer_id": self.customer.id,
             "vehicle_type_id": self.env.ref("carwash_base.vehicle_type_bike").id}
        )
        booking = self._booking()
        booking.vehicle_id = bike
        booking.action_confirm()
        booking.action_arrive()
        self.assertEqual(booking.checklist_template_id, self.env.ref("carwash_jobcard.checklist_template_booking_checkin_bike"))
        inspection = self.env["carwash.inspection"].create(
            {"appointment_id": booking.id, "inspection_type_id": self.pre_type.id}
        )
        self.assertEqual(inspection.checklist_template_id, self.env.ref("carwash_jobcard.checklist_template_inspection_pre_bike"))

    def test_own_vehicle_type_shares_the_two_wheeler_checklist(self):
        """A type created by the user (Scooter) can be added to the two-wheeler checklists."""
        scooter = self.env["carwash.vehicle.type"].sudo().create({"name": "Scooter", "icon": "fa-motorcycle"})
        checkin_bike = self.env.ref("carwash_jobcard.checklist_template_booking_checkin_bike")
        checkin_bike.sudo().vehicle_type_ids = [(4, scooter.id)]
        vehicle = self.env["carwash.vehicle"].create(
            {"license_plate": "SCOOT-1", "customer_id": self.customer.id, "vehicle_type_id": scooter.id}
        )
        booking = self._booking()
        booking.vehicle_id = vehicle
        booking.action_confirm()
        booking.action_arrive()
        self.assertEqual(booking.checklist_template_id, checkin_bike)
        booking.action_cancel()  # frees the bay slot for the next booking
        # a type no checklist is limited to gets the general (any vehicle) one
        bus = self.env["carwash.vehicle.type"].sudo().create({"name": "Bus", "icon": "fa-bus"})
        booking2 = self._booking()
        booking2.vehicle_id = self.env["carwash.vehicle"].create(
            {"license_plate": "BUS-1", "customer_id": self.customer.id, "vehicle_type_id": bus.id}
        )
        booking2.action_confirm()
        booking2.action_arrive()
        self.assertEqual(booking2.checklist_template_id, self.env.ref("carwash_jobcard.checklist_template_booking_checkin"))

    def test_checklists_switched_off(self):
        self.env["res.config.settings"].sudo().create({"group_carwash_checklist": False}).execute()
        booking = self._booking()
        booking.action_confirm()
        booking.action_arrive()
        self.assertFalse(booking.checklist_line_ids, "no check-in checklist while Process Checklists is off")
        booking.action_start_service()
        self.assertEqual(booking.state, "in_service")

    def test_form_keeps_template_tasks_mandatory(self):
        """Tasks loaded in the form stay linked to their template task, so mandatory stays mandatory."""
        booking = self._booking()
        booking.action_confirm()
        booking.action_arrive()
        with Form(self.env["carwash.inspection"]) as form:
            form.appointment_id = booking
            form.inspection_type_id = self.env.ref("carwash_jobcard.inspection_type_post")  # loads its checklist in the form
        lines = form.record.checklist_line_ids
        self.assertTrue(lines)
        self.assertTrue(all(lines.mapped("template_item_id")), "the link to the template task is saved")
        mandatory = lines.filtered(lambda line: line.template_item_id.is_required)
        self.assertTrue(mandatory and all(mandatory.mapped("is_required")))
        mandatory[:1].is_required = False
        self.assertTrue(mandatory[:1].is_required, "a template task can't be made optional on the record")

    def test_job_cards_get_their_tasks(self):
        """Job cards get the crew's task list without any demo data: Standard Wash for cars, the
        Two-Wheeler list for two-wheelers; Quick Wash / Premium Detailing can be picked."""
        standard = self.env.ref("carwash_jobcard.demo_checklist_template_standard")
        bike_tasks = self.env.ref("carwash_jobcard.checklist_template_jobcard_bike")
        self.assertEqual((standard.checklist_type, standard.is_default), ("jobcard", True))
        self.assertEqual((bike_tasks.checklist_type, bike_tasks.is_default), ("jobcard", True))

        booking = self._booking()
        booking.action_confirm()
        jobcard = self.env["carwash.jobcard"].create({"appointment_id": booking.id})
        self.assertEqual(jobcard.checklist_template_id, standard)
        self.assertEqual(jobcard.checklist_line_ids.mapped("name"), standard.item_ids.mapped("name"))

        bike = self.env["carwash.vehicle"].create(
            {"license_plate": "BIKE-JC", "customer_id": self.customer.id,
             "vehicle_type_id": self.env.ref("carwash_base.vehicle_type_bike").id}
        )
        bike_booking = self._booking()
        bike_booking.write({"vehicle_id": bike.id, "bay_id": False})
        bike_booking.action_confirm()
        bike_card = self.env["carwash.jobcard"].create({"appointment_id": bike_booking.id})
        self.assertEqual(bike_card.checklist_template_id, bike_tasks, "the two-wheeler gets its own task list")
        self.assertIn("Chain lubricated", bike_card.checklist_line_ids.mapped("name"))

        premium = self.env.ref("carwash_jobcard.demo_checklist_template_premium")
        with Form(jobcard) as form:
            form.checklist_template_id = premium
        self.assertEqual(jobcard.checklist_line_ids.mapped("name"), premium.item_ids.mapped("name"),
                         "another task list picked on the Tasks tab replaces the tasks")
