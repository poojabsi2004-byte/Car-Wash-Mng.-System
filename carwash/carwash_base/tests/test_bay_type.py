from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestBayType(TransactionCase):
    """Bay Type is a configurable model; the bay's state is driven from the status bar buttons."""

    def test_bay_type_records(self):
        BayType = self.env["carwash.bay.type"]
        self.assertLessEqual({"hand", "tunnel", "detail"}, set(BayType.search([]).mapped("code")))
        bay = self.env["carwash.bay"].create({"name": "Type Test Bay"})
        self.assertEqual(bay.bay_type_id, self.env.ref("carwash_base.bay_type_hand"), "new bays default to Hand Wash")
        self.assertEqual(bay.bay_type_icon, "fa-hand-paper-o")

        ceramic = BayType.create({"name": "Ceramic Coating", "icon": "fa-magic"})
        bay.bay_type_id = ceramic
        self.env["product.template"].create({
            "name": "Ceramic Coat", "type": "service", "is_carwash_service": True, "carwash_bay_type_id": ceramic.id,
        })
        self.assertEqual((ceramic.bay_count, ceramic.service_count), (1, 1))
        self.assertEqual(ceramic.action_view_bays()["domain"], [("bay_type_id", "=", ceramic.id)])
        self.assertIn(("carwash_bay_type_id", "=", ceramic.id), ceramic.action_view_services()["domain"])
        # a type still used by a bay can't be deleted
        with mute_logger("odoo.sql_db"), self.assertRaises(Exception), self.cr.savepoint():
            ceramic.unlink()
            self.env.flush_all()

    def test_status_bar_actions(self):
        bay = self.env["carwash.bay"].create({"name": "Status Bay"})
        self.assertEqual(bay.state, "free")
        bay.action_set_maintenance()
        self.assertEqual(bay.state, "maintenance")
        self.assertNotIn(bay, self.env["carwash.appointment"]._carwash_bookable_bays(bay.company_id))
        bay.action_set_free()
        self.assertEqual(bay.state, "free")
        # a bay left Occupied without a running service can be released
        bay.with_context(carwash_bay_by_service=True).write({"state": "occupied"})
        bay.action_set_free()
        self.assertEqual(bay.state, "free")
