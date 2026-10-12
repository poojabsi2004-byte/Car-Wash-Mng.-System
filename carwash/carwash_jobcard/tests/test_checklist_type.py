from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestChecklistType(TransactionCase):
    """"Used On" of a checklist template is a configurable Checklist Type that applies to one step."""

    def test_standard_types(self):
        booking_type = self.env.ref("carwash_jobcard.checklist_type_booking")
        self.assertEqual(booking_type.applies_to, "booking")
        template = self.env.ref("carwash_jobcard.checklist_template_booking_checkin")
        self.assertEqual((template.checklist_type_id, template.checklist_type), (booking_type, "booking"))
        self.assertGreaterEqual(booking_type.template_count, 1)
        self.assertEqual(booking_type.action_view_templates()["domain"], [("checklist_type_id", "=", booking_type.id)])
        # the step's technical key is still accepted (data files, imports)
        Template = self.env["carwash.checklist.template"]
        old_style = Template.create({"name": "Old style", "checklist_type": "inspection"})
        self.assertEqual(old_style.checklist_type_id, self.env.ref("carwash_jobcard.checklist_type_inspection"))
        self.assertEqual(Template.create({"name": "No type"}).checklist_type, "jobcard", "default: job card")
        # a type with templates can't move to another step, nor be deleted
        with self.assertRaises(UserError):
            booking_type.applies_to = "jobcard"
        with mute_logger("odoo.sql_db"), self.assertRaises(Exception), self.cr.savepoint():
            booking_type.unlink()
            self.env.flush_all()

    def test_own_type_is_loaded_at_its_step(self):
        self.env.ref("base.group_user").write({"implied_ids": [(4, self.env.ref("carwash_jobcard.group_carwash_checklist").id)]})
        express = self.env["carwash.checklist.type"].create({"name": "Express Check-in", "applies_to": "booking"})
        Template = self.env["carwash.checklist.template"]
        Template.search([("checklist_type", "=", "booking")]).is_default = False
        template = Template.create({
            "name": "Express arrival", "checklist_type_id": express.id, "is_default": True,
            "item_ids": [(0, 0, {"name": "Keys tagged with the token", "is_required": True})],
        })
        self.assertEqual(template.checklist_type, "booking")
        customer = self.env["res.partner"].create({"name": "Express Customer"})
        vehicle = self.env["carwash.vehicle"].create({"license_plate": "EXP 1", "customer_id": customer.id})
        wash = self.env["product.product"].create({"name": "Express Wash", "type": "service", "is_carwash_service": True})
        booking = self.env["carwash.appointment"].create({
            "customer_id": customer.id, "vehicle_id": vehicle.id, "bay_id": self.env["carwash.bay"].create({"name": "Express Bay"}).id,
            "appointment_date": fields.Datetime.now() + timedelta(days=2), "line_ids": [(0, 0, {"product_id": wash.id})],
        })
        booking.action_confirm()
        booking.action_arrive()
        self.assertEqual(booking.checklist_template_id, template)
        self.assertEqual(booking.checklist_line_ids.mapped("name"), ["Keys tagged with the token"])
