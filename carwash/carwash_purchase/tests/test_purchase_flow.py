from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.service.model import call_kw
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashPurchase(TransactionCase):
    """Supplier management: each branch buys for itself, with GST (Indian accounting)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        gujarat = cls.env.ref("base.state_in_gj")
        cls.branch = cls.env["res.company"].create({
            "name": "Purchase Branch", "state_id": gujarat.id, "country_id": cls.env.ref("base.in").id,
        })
        cls.branch._carwash_setup_gst()
        cls.branch = cls.env["res.company"].browse(cls.branch.id)
        cls.warehouse = cls.branch._carwash_warehouse(create=True)

        def user(login, groups):
            return cls.env["res.users"].create({
                "name": login.replace("_", " ").title(), "login": login,
                "company_id": cls.branch.id, "company_ids": [Command.set(cls.branch.ids)],
                "group_ids": [Command.set([cls.env.ref("base.group_user").id] + [cls.env.ref(g).id for g in groups])],
            })
        cls.manager = user("purchase_manager_cw", ["carwash_base.group_carwash_manager"])
        cls.front_desk = user("purchase_front_desk_cw", ["carwash_base.group_carwash_user"])
        cls.washer = user("purchase_washer_cw", ["carwash_jobcard.group_carwash_washer"])
        cls.manager_2 = user("purchase_manager_two_cw", ["carwash_base.group_carwash_manager"])
        cls.owner = user("purchase_owner_cw", ["carwash_multibranch.group_carwash_owner"])

        Partner = cls.env["res.partner"]
        cls.supplier = Partner.create({
            "name": "Local Chemicals", "is_company": True, "supplier_rank": 1,
            "state_id": gujarat.id, "country_id": cls.env.ref("base.in").id, "vat": "24AABCA1234A1ZP",
            "l10n_in_gst_treatment": "regular",
        })
        cls.supplier_mh = Partner.create({
            "name": "Pune Equipment", "is_company": True, "supplier_rank": 1,
            "state_id": cls.env.ref("base.state_in_mh").id, "country_id": cls.env.ref("base.in").id,
            "vat": "27AABCP5678B1ZE", "l10n_in_gst_treatment": "regular",
        })
        Template = cls.env["product.template"]
        cls.shampoo = Template.create({
            "name": "Branch Shampoo", "is_carwash_consumable": True, "type": "consu", "is_storable": True,
            "standard_price": 400, "l10n_in_hsn_code": "3402",
        }).product_variant_id
        cls.wax = Template.create({
            "name": "Branch Wax (no supplier)", "is_carwash_consumable": True, "type": "consu", "is_storable": True,
        }).product_variant_id
        cls.washer_machine = cls.env.ref("carwash_purchase.product_pressure_washer")
        cls.nozzle = cls.env.ref("carwash_purchase.product_nozzle_kit")
        cls.repair = cls.env.ref("carwash_purchase.product_bay_maintenance")
        cls.branch._carwash_apply_gst_to_products()  # products created after the GST set-up
        cls.shampoo.with_company(cls.branch).standard_price = 400  # the branch's cost
        Price = cls.env["product.supplierinfo"]
        Price.create({"partner_id": cls.supplier.id, "product_tmpl_id": cls.shampoo.product_tmpl_id.id,
                      "price": 450, "min_qty": 5, "delay": 3, "company_id": cls.branch.id})
        Price.create({"partner_id": cls.supplier_mh.id, "product_tmpl_id": cls.nozzle.product_tmpl_id.id,
                      "price": 1450, "company_id": cls.branch.id})
        Price.create({"partner_id": cls.supplier_mh.id, "product_tmpl_id": cls.washer_machine.product_tmpl_id.id,
                      "price": 43500, "company_id": cls.branch.id})

    def _as(self, user):
        # a user's request starts with an empty cache (no records read with other rights)
        self.env.invalidate_all()
        return self.env(user=user, context=dict(self.env.context, allowed_company_ids=[self.branch.id]))

    def _tax(self, xmlid):
        return self.env.ref(f"account.{self.branch.id}_{xmlid}")

    def _order(self, user, partner, product, qty, **vals):
        order = self._as(user)["purchase.order"].create({
            "partner_id": partner.id, "company_id": self.branch.id,
            "order_line": [Command.create({"product_id": product.id, "product_qty": qty})], **vals,
        })
        return order

    def _receive(self, order, qty=None):
        order = order.with_env(self.env)  # the branch manager / store receives the goods
        picking = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        for move in picking.move_ids:
            move.quantity = qty if qty is not None else move.product_uom_qty
        result = picking.button_validate()
        if isinstance(result, dict) and result.get("res_model") == "stock.backorder.confirmation":
            Form(self.env["stock.backorder.confirmation"].with_context(result["context"])).save().process()
        return picking

    # ------------------------------------------------------------------
    def test_product_made_a_purchase_product_later_gets_gst_and_average_cost(self):
        product = self.env["product.template"].create({"name": "Late Polish", "type": "consu"})
        product.is_carwash_consumable = True
        self.assertEqual(product.carwash_supply_type, "consumable")
        self.assertEqual(product.categ_id, self.env.ref("carwash_purchase.product_category_carwash_supplies"))
        self.assertIn(self._tax("sgst_purchase_18"), product.with_company(self.branch).supplier_taxes_id)

    def test_gst_setup(self):
        self.assertEqual((self.branch.chart_template, self.branch.currency_id.name), ("in", "INR"))
        gst18 = self._tax("sgst_purchase_18")
        self.assertIn(gst18, self.shampoo.with_company(self.branch).supplier_taxes_id)
        self.assertIn(gst18, self.repair.with_company(self.branch).supplier_taxes_id, "maintenance services too")
        with self.assertRaisesRegex(UserError, "State"):
            self.env["res.company"].create({"name": "No State Branch"})._carwash_setup_gst()

    def test_low_stock_button_creates_one_rfq_per_supplier(self):
        Product = self._as(self.manager)["product.product"]
        Product.browse(self.shampoo.id).write({"carwash_min_qty": 10})
        Product.browse(self.shampoo.id).write({"carwash_max_qty": 30})
        Product.browse(self.wax.id).write({"carwash_min_qty": 4})
        orderpoint = self.shampoo._carwash_orderpoint(self.warehouse)
        self.assertEqual((orderpoint.trigger, orderpoint.route_id, orderpoint.product_max_qty),
                         ("manual", self.env.ref("purchase_stock.route_warehouse0_buy"), 30))
        self.assertEqual(self.shampoo._carwash_seller(self.branch).partner_id, self.supplier, "its vendor price")

        # as the list's header button calls it: with the ids of the selected rows (none here)
        action = call_kw(Product, "action_carwash_create_low_stock_rfqs", [[]], {})
        self.assertEqual(action["tag"], "display_notification", "the wax has no supplier - it is reported")
        self.assertIn("Branch Wax", action["params"]["message"])
        rfq = self.env["purchase.order"].search([("partner_id", "=", self.supplier.id), ("company_id", "=", self.branch.id)])
        self.assertEqual(len(rfq), 1)
        self.assertEqual((rfq.state, rfq.order_line.product_id, rfq.order_line.product_qty), ("draft", self.shampoo, 30))
        self.assertEqual(rfq.order_line.price_unit, 450, "the supplier's price")
        self.assertEqual(rfq.carwash_supply_type, "consumable")
        # clicking again doesn't order twice; with a supplier for everything it opens the RFQ
        self.env["product.supplierinfo"].create({"partner_id": self.supplier.id, "price": 300, "company_id": False,
                                                  "product_tmpl_id": self.wax.product_tmpl_id.id})  # all branches
        action = self._as(self.manager)["product.product"].action_carwash_create_low_stock_rfqs()
        self.assertEqual(self.env["purchase.order"].search_count([("partner_id", "=", self.supplier.id)]), 1,
                         "the wax joins the supplier's open RFQ")
        self.assertEqual((action["res_model"], action["res_id"]), ("purchase.order", rfq.id))
        self.assertEqual(rfq.order_line.product_id, self.shampoo | self.wax)
        # Odoo's clean-up of processed manual rules leaves the car wash minimum-stock rules alone
        self.env["stock.warehouse.orderpoint"]._unlink_processed_orderpoints()
        self.assertTrue(orderpoint.exists())
        with self.assertRaises(UserError):
            self._as(self.front_desk)["product.product"].action_carwash_create_low_stock_rfqs()

    def test_automatic_rfq_when_stock_drops(self):
        self.branch.carwash_auto_rfq = True
        self._as(self.manager)["product.product"].browse(self.shampoo.id).write({"carwash_min_qty": 10, "carwash_max_qty": 30})
        self.assertEqual(self.shampoo._carwash_orderpoint(self.warehouse).trigger, "auto")
        self.env["stock.quant"]._update_available_quantity(self.shampoo, self.warehouse.lot_stock_id, 12)
        request = self._as(self.manager)["carwash.consumable.request"].create({
            "company_id": self.branch.id, "line_ids": [Command.create({"product_id": self.shampoo.id, "quantity": 5})],
        })
        request.action_submit()
        request.action_approve()
        request.action_issue()
        rfq = self.env["purchase.order"].search([("partner_id", "=", self.supplier.id), ("company_id", "=", self.branch.id)])
        self.assertEqual(len(rfq), 1, "stock fell to 7, below the minimum of 10: RFQ created automatically")
        self.assertEqual(rfq.order_line.product_qty, 23)
        self.assertEqual(request.move_ids.carwash_unit_cost, 400, "what the request used is costed")

    def test_approval_by_manager_above_the_amount(self):
        self.branch.write({"po_double_validation": "two_step", "po_double_validation_amount": 10000})
        order = self._order(self.front_desk, self.supplier_mh, self.washer_machine, 1)
        order.button_confirm()
        self.assertEqual(order.state, "to approve", "Front Desk can't buy above 10,000 on its own")
        activity = order.activity_ids.filtered(lambda a: a.summary == "Approve purchase order")
        self.assertEqual(activity.user_id, self.manager | self.manager_2 | self.owner, "the branch's approvers are asked")
        with self.assertRaisesRegex(UserError, "Only a Car Wash Manager or the Owner"):
            order.button_approve()
        self.assertEqual(order.state, "to approve", "Front Desk can't approve it")
        order.with_user(self.manager).button_approve()
        self.assertEqual(order.state, "purchase")
        self.assertFalse(order.activity_ids.filtered(lambda a: a.summary == "Approve purchase order"))
        # small orders go through at once
        small = self._order(self.front_desk, self.supplier, self.shampoo, 5)
        small.button_confirm()
        self.assertEqual(small.state, "purchase")
        # above the amount every order waits for approval - also a manager's or the owner's own
        big = self._order(self.manager, self.supplier_mh, self.washer_machine, 1)
        big.button_confirm()
        self.assertEqual(big.state, "to approve", "a manager's big order goes through approval too")
        self.assertEqual(big.activity_ids.filtered(lambda a: a.summary == "Approve purchase order").user_id,
                         self.manager_2 | self.owner, "the other approvers are asked")
        big.button_approve()
        self.assertEqual(big.state, "purchase", "a Manager (or the Owner) approves it")
        own = self._order(self.owner, self.supplier_mh, self.washer_machine, 1)
        own.button_confirm()
        self.assertEqual(own.state, "to approve")
        own.button_approve()
        self.assertEqual(own.state, "purchase")

    def test_approval_setting_covers_branches(self):
        main = self.env["res.company"].create({"name": "Purchase Main"})
        branch = self.env["res.company"].create({"name": "Purchase Main Branch", "parent_id": main.id})
        settings = self.env["res.config.settings"].with_company(main).create({
            "po_order_approval": True, "po_double_validation_amount": 3000,
        })
        settings.execute()
        self.assertEqual((main.po_double_validation, main.po_double_validation_amount), ("two_step", 3000))
        self.assertEqual((branch.po_double_validation, branch.po_double_validation_amount), ("two_step", 3000),
                         "set on the main company: its branches need approval too")

    def test_receive_bill_pay_and_return_with_gst(self):
        order = self._order(self.manager, self.supplier, self.shampoo, 10)
        self.assertIn(self._tax("sgst_purchase_18"), order.order_line.tax_ids, "within Gujarat: CGST + SGST")
        order.button_confirm()
        self.assertEqual(order.carwash_payment_state, "not_billed")
        self._receive(order, qty=6)
        self.assertEqual((order.order_line.qty_received, order.receipt_status), (6, "partial"))
        self.assertEqual(len(order.picking_ids), 2, "the rest is a backorder")

        order.action_create_invoice()
        bill = order.invoice_ids
        self.assertEqual((bill.move_type, bill.invoice_line_ids.quantity), ("in_invoice", 6), "only what was received")
        self.assertAlmostEqual(bill.amount_untaxed, 2700)
        self.assertAlmostEqual(bill.amount_tax, 486, msg="18% GST")
        bill.invoice_date = fields.Date.today()
        bill.action_post()
        self.assertEqual(order.carwash_payment_state, "to_pay")
        self.assertAlmostEqual(bill.amount_residual, 3186)
        self.env["account.payment.register"].with_context(active_model="account.move", active_ids=bill.ids).create({})._create_payments()
        self.assertEqual(order.carwash_payment_state, "paid")

        # 2 cans arrived damaged: back to the supplier, then a credit note
        receipt = order.picking_ids.filtered(lambda p: p.state == "done")
        wizard = Form(self.env["stock.return.picking"].with_context(active_id=receipt.id, active_model="stock.picking"))
        wizard.carwash_return_reason = "damaged"
        wizard.carwash_return_note = "2 cans leaking"
        with wizard.product_return_moves.edit(0) as line:
            line.quantity = 2
        return_picking = wizard.save()._create_return()
        self.assertEqual(return_picking.carwash_return_reason, "damaged")
        for move in return_picking.move_ids:
            move.quantity = move.product_uom_qty
        return_picking.button_validate()
        self.assertEqual(order.order_line.qty_received, 4)
        order.action_create_invoice()
        refund = order.invoice_ids.filtered(lambda m: m.move_type == "in_refund")
        self.assertEqual(refund.invoice_line_ids.quantity, 2, "credit note for the returned goods")
        self.assertAlmostEqual(self.shampoo.with_company(self.branch).standard_price, 450, msg="average purchase cost")

    def test_interstate_supplier_is_igst(self):
        order = self._order(self.manager, self.supplier_mh, self.nozzle, 2)
        self.assertIn(self._tax("igst_purchase_18"), order.order_line.tax_ids, "Maharashtra -> Gujarat: IGST")
        self.assertAlmostEqual(order.amount_tax, 2 * 1450 * 0.18)

    def test_consumable_request_short_of_stock_requests_a_purchase(self):
        request = self._as(self.front_desk)["carwash.consumable.request"].create({
            "company_id": self.branch.id, "line_ids": [Command.create({"product_id": self.shampoo.id, "quantity": 3})],
        })
        request.action_submit()
        action = request.action_carwash_request_purchase()
        order = request.carwash_purchase_ids
        self.assertEqual(action["res_id"], order.id)
        self.assertEqual((order.partner_id, order.order_line.product_qty), (self.supplier, 5), "at least the supplier's minimum")
        order.with_user(self.manager).button_confirm()
        self._receive(order)
        self.assertTrue(request.activity_ids.filtered(lambda a: a.user_id == self.front_desk),
                        "the requester is told the goods arrived")
        with self.assertRaisesRegex(UserError, "in stock"):
            request.action_carwash_request_purchase()

    def test_bay_repair_purchase(self):
        bay = self.env["carwash.bay"].create({"name": "Repair Bay", "company_id": self.branch.id})
        action = bay.with_user(self.manager).action_carwash_order_repair()
        form = Form(self._as(self.manager)["purchase.order"].with_context(action["context"]))
        form.partner_id = self.supplier
        order = form.save()
        self.assertEqual((order.carwash_bay_id, order.order_line.product_id, order.carwash_supply_type),
                         (bay, self.repair, "maintenance"))
        order.button_confirm()
        self.assertEqual(bay.carwash_purchase_count, 1)
        self.assertAlmostEqual(bay.carwash_maintenance_cost, order.amount_untaxed)

    def test_dashboard_and_reports(self):
        self.branch.write({"po_double_validation": "two_step", "po_double_validation_amount": 10000})
        self._order(self.front_desk, self.supplier_mh, self.washer_machine, 1).button_confirm()
        data = self._as(self.manager)["carwash.dashboard"].get_dashboard_data()
        self.assertEqual(data["purchases"]["to_approve"], 1)
        order = self._order(self.manager, self.supplier, self.shampoo, 5)
        html = self.env["ir.actions.report"]._render_qweb_html("carwash_purchase.action_report_carwash_rfq", order.ids)[0]
        self.assertIn(b"Request for Quotation", html)
        order.button_confirm()
        html = self.env["ir.actions.report"]._render_qweb_html("carwash_purchase.action_report_carwash_purchase_order", order.ids)[0]
        self.assertIn(b"Purchase Order", html)
        self.assertIn(b"3402", html, "HSN code printed")
        self.assertIn(b"24AABCA1234A1ZP", html, "supplier GSTIN printed")

    def test_washer_has_no_purchase_access(self):
        with self.assertRaises(AccessError):
            self._as(self.washer)["purchase.order"].search([])
