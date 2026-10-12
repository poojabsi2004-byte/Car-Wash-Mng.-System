from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashConsumable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.group_user").write(
            {"implied_ids": [(4, cls.env.ref("carwash_consumable.group_carwash_consumable").id)]}
        )
        cls.branch = cls.env["res.company"].create({"name": "Consumable Branch"})
        cls.warehouse = cls.branch._carwash_warehouse(create=True)
        cls.manager = cls.env["res.users"].create({
            "name": "Store Manager", "login": "store_manager",
            "company_id": cls.branch.id, "company_ids": [(6, 0, cls.branch.ids)],
            "group_ids": [(6, 0, [cls.env.ref("carwash_base.group_carwash_manager").id])],
        })
        cls.washer = cls.env["res.users"].create({
            "name": "Floor Washer", "login": "floor_washer_cons",
            "company_id": cls.branch.id, "company_ids": [(6, 0, cls.branch.ids)],
            "group_ids": [(6, 0, [cls.env.ref("carwash_jobcard.group_carwash_washer").id])],
        })
        cls.shampoo = cls.env["product.product"].create({
            "name": "Test Car Shampoo", "type": "consu", "is_storable": True, "is_carwash_consumable": True,
        })
        cls.env["stock.quant"]._update_available_quantity(cls.shampoo, cls.warehouse.lot_stock_id, 10)
        cls.Request = cls.env["carwash.consumable.request"]

    def _branch_product(self, user=None):
        self.env.invalidate_all()  # stock quantities read earlier in this test are cached
        env = self.env(user=user or self.manager, context={"allowed_company_ids": self.branch.ids})
        return self.shampoo.with_env(env)

    def _request(self, user, qty, request_type="issue", reason=False):
        return self.Request.with_user(user).with_company(self.branch).create({
            "request_type": request_type,
            "company_id": self.branch.id,
            "reason": reason,
            "line_ids": [(0, 0, {"product_id": self.shampoo.id, "quantity": qty})],
        })

    def test_branch_stock_and_minimum(self):
        product = self._branch_product()
        self.assertEqual(product.carwash_branch_qty, 10)
        self.assertEqual(product.carwash_stock_status, "ok")
        product.carwash_min_qty = 12  # set right in the Stock list -> a manual reordering rule
        orderpoint = self.shampoo._carwash_orderpoint(self.warehouse)
        self.assertEqual((orderpoint.product_min_qty, orderpoint.trigger), (12, "manual"))
        product.invalidate_recordset()
        self.assertEqual(product.carwash_stock_status, "low")
        low = self.env["product.product"]._carwash_low_stock(self.branch)
        self.assertEqual([(c, p, q) for c, p, q, _m in low], [(self.branch, self.shampoo, 10)])

    def test_issue_workflow(self):
        request = self._request(self.washer, 3)
        self.assertEqual(request.line_ids.available_qty, 10)
        request.action_submit()
        self.assertEqual(request.state, "submitted")
        with self.assertRaises(UserError):
            request.action_approve()  # a washer can't approve
        with self.assertRaises(UserError):
            request.write({"reason": "changed my mind"})  # nor edit it once submitted
        as_manager = request.with_user(self.manager).with_company(self.branch)
        as_manager.action_approve()
        as_manager.action_issue()
        self.assertEqual(request.state, "done")
        self.assertEqual(as_manager.move_ids.carwash_usage_type, "issue")
        self.assertEqual(as_manager.move_ids.state, "done")
        self.assertEqual(self._branch_product().carwash_branch_qty, 7)

    def test_cannot_issue_more_than_stock(self):
        request = self._request(self.washer, 25)
        request.action_submit()
        as_manager = request.with_user(self.manager).with_company(self.branch)
        as_manager.action_approve()
        with self.assertRaisesRegex(UserError, "Not enough stock"):
            as_manager.action_issue()
        self.assertEqual(request.state, "approved")

    def test_wastage_return_and_reject(self):
        with self.assertRaisesRegex(UserError, "Reason"):
            self._request(self.washer, 2, "wastage").action_submit()
        wastage = self._request(self.washer, 2, "wastage", reason="Can dropped and split")
        wastage.action_submit()
        wastage.with_user(self.manager).with_company(self.branch).action_approve()
        wastage.with_user(self.manager).with_company(self.branch).action_issue()
        self.assertEqual(wastage.sudo().move_ids.location_dest_id, self.shampoo.with_company(self.branch).property_stock_inventory)
        self.assertEqual(self._branch_product().carwash_branch_qty, 8)

        back = self._request(self.washer, 1, "return", reason="Unused")
        back.action_submit()
        back.with_user(self.manager).with_company(self.branch).action_approve()
        back.with_user(self.manager).with_company(self.branch).action_issue()
        self.assertEqual(self._branch_product().carwash_branch_qty, 9)

        nope = self._request(self.washer, 1)
        nope.action_submit()
        self.env["carwash.consumable.request.reject"].with_user(self.manager).create(
            {"request_ids": [(6, 0, nope.ids)], "reason": "Use the bay stock first"}
        ).action_confirm()
        self.assertEqual((nope.state, nope.reject_reason), ("rejected", "Use the bay stock first"))

    def test_staff_see_only_their_requests(self):
        other = self.env["res.users"].create({
            "name": "Other Washer", "login": "other_washer_cons",
            "company_id": self.branch.id, "company_ids": [(6, 0, self.branch.ids)],
            "group_ids": [(6, 0, [self.env.ref("carwash_jobcard.group_carwash_washer").id])],
        })
        mine = self._request(self.washer, 1)
        self._request(other, 1)
        visible = self.Request.with_user(self.washer).with_company(self.branch).search([])
        self.assertEqual(visible, mine)
        with self.assertRaises(AccessError):
            self.env["stock.move"].with_user(self.washer).check_access("write")

    def test_booking_consumption_is_service_usage(self):
        service = self.env["product.product"].create({
            "name": "Shampoo Wash", "type": "service", "is_carwash_service": True, "list_price": 100,
            "carwash_material_line_ids": [(0, 0, {"product_id": self.shampoo.id, "quantity": 0.5})],
        })
        customer = self.env["res.partner"].create({"name": "Consumable Customer"})
        vehicle = self.env["carwash.vehicle"].create({"license_plate": "CON-1", "customer_id": customer.id, "company_id": self.branch.id})
        booking = self.env["carwash.appointment"].with_company(self.branch).create({
            "customer_id": customer.id, "vehicle_id": vehicle.id, "company_id": self.branch.id,
            "appointment_date": fields.Datetime.now() + timedelta(hours=1),
            "line_ids": [(0, 0, {"product_id": service.id})],
        })
        booking.action_confirm()
        booking.state = "ready"  # shortcut through the wash itself (covered by the workflow tests)
        booking.action_done()
        moves = self.env["stock.move"].search([("carwash_appointment_id", "=", booking.id)])
        self.assertEqual((moves.carwash_usage_type, moves.product_uom_qty), ("service", 0.5))
        self.assertEqual(booking.consumable_move_count, 1)

    def test_dashboard_and_low_stock_alert(self):
        self._branch_product().carwash_min_qty = 50
        submitted = self._request(self.washer, 1)
        submitted.action_submit()
        data = self.env["carwash.dashboard"].with_user(self.manager).with_company(self.branch).get_dashboard_data()
        cons = data["consumables"]
        self.assertEqual([i["name"] for i in cons["low_stock"]], ["Test Car Shampoo"])
        self.assertEqual(cons["to_approve"], 1)

        self.env["product.product"]._cron_carwash_low_stock_alert()
        activity = self.shampoo.product_tmpl_id.activity_ids.filtered(lambda a: "Low stock" in (a.summary or ""))
        self.assertIn(self.manager, activity.user_id)
        self.env["product.product"]._cron_carwash_low_stock_alert()  # no duplicates
        self.assertEqual(len(self.shampoo.product_tmpl_id.activity_ids.filtered(lambda a: a.user_id == self.manager and "Low stock" in (a.summary or ""))), 1)

    def test_switched_off(self):
        self.env["res.config.settings"].create({"group_carwash_consumable": False}).execute()
        data = self.env["carwash.dashboard"].with_user(self.manager).with_company(self.branch).get_dashboard_data()
        self.assertNotIn("consumables", data)
