from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMembershipFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # these tests are about the features below - make sure they are switched on
        cls.env.ref("base.group_user").write({"implied_ids": [(4, cls.env.ref(x).id) for x in ['carwash_membership.group_carwash_membership']]})
        Product = cls.env["product.product"]
        cls.wash = Product.create({"name": "T Wash", "type": "service", "is_carwash_service": True, "list_price": 300})
        cls.wax = Product.create({"name": "T Wax", "type": "service", "is_carwash_service": True, "list_price": 500})
        cls.fee = Product.create({"name": "T Gold Fee", "type": "service", "list_price": 1000})
        cls.plan = cls.env["carwash.membership.plan"].create(
            {
                "name": "T Gold",
                "product_id": cls.fee.id,
                "monthly_price": 1000,
                "yearly_price": 10000,
                "wash_allowance": 1,
                "plan_service_ids": [(6, 0, cls.wash.ids)],
                "discount_percent": 20,
            }
        )
        cls.customer = cls.env["res.partner"].create({"name": "T Member", "email": "t.member@example.com"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "T-1", "customer_id": cls.customer.id})

    def _new_membership(self):
        return self.env["carwash.membership"].create({"partner_id": self.customer.id, "plan_id": self.plan.id})

    def _pay_backend(self, membership):
        action = membership.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({})._create_payments()
        return invoice

    def _booking(self, products):
        return self.env["carwash.appointment"].create(
            {
                "customer_id": self.customer.id,
                "vehicle_id": self.vehicle.id,
                "appointment_date": fields.Datetime.now() + timedelta(days=1),
                "line_ids": [(0, 0, {"product_id": p.id}) for p in products],
            }
        )

    def test_plan_creates_member_level_and_discount_pricelist(self):
        self.assertTrue(self.plan.grade_id)
        self.assertEqual(self.plan.grade_id.default_pricelist_id, self.plan.pricelist_id)
        self.assertAlmostEqual(self.plan.pricelist_id._get_product_price(self.wax, 1.0), 400.0)
        self.assertAlmostEqual(self.plan.pricelist_id._get_product_price(self.fee, 1.0), 1000.0,
                               msg="the member discount only applies to car wash services")

    def test_backend_payment_activates(self):
        membership = self._new_membership()
        self.assertEqual(membership.state, "pending")
        invoice = self._pay_backend(membership)
        self.assertIn(invoice.payment_state, ("paid", "in_payment"))
        self.assertEqual(membership.state, "active")
        today = fields.Date.context_today(membership)
        # starts today, ends the same day next month, expires the day after
        self.assertEqual(membership.billing_period, "monthly")
        self.assertEqual(membership.start_date, today)
        self.assertEqual(membership.valid_until, today + relativedelta(months=1))
        self.assertEqual(membership.paid_until, membership.valid_until)
        self.assertEqual(membership.expiry_date, today + relativedelta(months=1, days=1))
        self.assertEqual(invoice.amount_untaxed, 1000)
        self.assertEqual(self.customer.grade_id, self.plan.grade_id)
        self.assertEqual(self.customer.specific_property_product_pricelist, self.plan.pricelist_id)
        self.assertFalse(membership.pending_order_id)

    def test_online_payment_activates(self):
        membership = self._new_membership()
        membership.action_request_payment()
        order = membership.pending_order_id
        self.assertTrue(order.require_payment)
        provider = self.env.ref("payment.payment_provider_demo")
        provider.state = "test"
        tx = self.env["payment.transaction"].create(
            {
                "provider_id": provider.id,
                "payment_method_id": provider.payment_method_ids[:1].id,
                "amount": order.amount_total,
                "currency_id": order.currency_id.id,
                "partner_id": self.customer.id,
                "reference": f"TEST-{order.name}",
                "sale_order_ids": [(6, 0, order.ids)],
            }
        )
        tx._set_done()
        tx._post_process()
        self.assertEqual(membership.state, "active")
        self.assertTrue(order.carwash_membership_paid)
        self.assertEqual(order.state, "sale")

    def test_booking_benefits_and_allowance(self):
        membership = self._new_membership()
        self._pay_backend(membership)

        first = self._booking(self.wash | self.wax)
        first.action_apply_membership()
        wash_line = first.line_ids.filtered(lambda l: l.product_id == self.wash)
        wax_line = first.line_ids.filtered(lambda l: l.product_id == self.wax)
        discount_line = first.line_ids.filtered("is_discount_line")
        self.assertTrue(wash_line.membership_covered)
        self.assertEqual(wash_line.price_unit, 0.0, "the free service is its own line at 0")
        self.assertIn("free with membership", wash_line.description)
        self.assertAlmostEqual(wax_line.price_unit, 500.0, msg="discounted services keep their normal price")
        self.assertEqual(discount_line.product_id, self.env.ref("carwash_membership.product_membership_discount"))
        self.assertAlmostEqual(discount_line.price_unit, -100.0, msg="the 20% discount is one separate line")
        self.assertAlmostEqual(first.amount_total, 400.0)
        self.assertAlmostEqual(first.membership_saving, 400.0)
        self.assertEqual(first.services_total, 2, "the discount line isn't a service to perform")
        self.assertEqual(membership.washes_remaining, 0, "the booking reserves the only free wash")

        # re-applying doesn't stack discount lines
        first.action_apply_membership()
        self.assertEqual(len(first.line_ids.filtered("is_discount_line")), 1)
        self.assertAlmostEqual(first.amount_total, 400.0)

        # allowance used up -> the covered service only gets the member discount
        second = self._booking(self.wash)
        second.action_apply_membership()
        self.assertFalse(second.line_ids.filtered("membership_covered"))
        self.assertAlmostEqual(second.line_ids.filtered("is_discount_line").price_unit, -60.0)
        self.assertAlmostEqual(second.amount_total, 240.0)

        # removing restores normal prices, drops the discount line and frees the wash
        first.action_remove_membership()
        self.assertFalse(first.line_ids.filtered("is_discount_line"))
        self.assertNotIn("free with membership", wash_line.description or "")
        self.assertAlmostEqual(first.amount_total, 800.0)
        membership.invalidate_recordset(["washes_reserved", "washes_remaining"])
        self.assertEqual(membership.washes_remaining, 1)

        # completing a booking with a free wash consumes it
        first.action_apply_membership()
        first.action_confirm()
        first.state = "ready"  # shortcut through the wash itself (covered by the workflow tests)
        first.action_done()
        self.assertEqual(membership.washes_used, 1)
        self.assertEqual(first.sale_order_id.amount_untaxed, 400.0)
        self.assertEqual(
            first.sale_order_id.order_line.filtered(lambda l: l.price_unit < 0).product_id,
            self.env.ref("carwash_membership.product_membership_discount"),
            "the discount shows as its own line on the sales order",
        )

    def test_no_membership_or_inactive(self):
        booking = self._booking(self.wash)
        with self.assertRaises(UserError):
            booking.action_apply_membership()
        membership = self._new_membership()  # pending, not paid
        with self.assertRaises(UserError):
            booking.action_apply_membership()
        self.assertEqual(membership.state, "pending")

    def test_renewal_rollover_and_expiry(self):
        membership = self._new_membership()
        self._pay_backend(membership)
        self.assertFalse(membership.auto_renew, "off until the customer turns it on (reminder email)")
        membership._carwash_turn_on_auto_renew(by_customer=True)
        self.assertIn("by the customer", membership.message_ids[0].body)
        membership.washes_used = 1
        today = fields.Date.context_today(membership)
        yesterday = today - relativedelta(days=1)

        # up to the end date nothing happens
        membership.write({"valid_until": today, "paid_until": today, "next_billing_date": today})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertFalse(membership.pending_order_id)
        self.assertEqual(len(membership.sale_order_ids), 1)

        # the day after the end date (Expires On): auto-renewal invoices and pays the renewal -> one more month
        # from the end date, without a gap
        membership.write({"valid_until": yesterday, "paid_until": yesterday, "next_billing_date": yesterday})
        orders_before = membership.sale_order_ids
        self.env["carwash.membership"]._cron_process_membership_billing()
        renewal = membership.sale_order_ids - orders_before
        self.assertEqual(membership.state, "active")
        self.assertEqual(membership.paid_until, yesterday + relativedelta(months=1))
        self.assertTrue(renewal.carwash_membership_paid)
        self.assertEqual(renewal.invoice_ids.payment_state in ("paid", "in_payment"), True)
        self.assertFalse(membership.pending_order_id, "nothing left to pay")
        self.assertTrue(membership.message_ids.filtered(lambda m: "Auto-renewal" in (m.body or "")), "logged")
        self.assertEqual(membership.washes_used, 1, "the current month's washes are untouched")

        # a new month -> free washes reset, still active
        membership.write({"wash_period_start": today - relativedelta(months=1)})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.wash_period_start, today)
        self.assertEqual(membership.washes_used, 0)
        self.assertEqual(membership.state, "active")

        # auto-renewal off and nothing paid beyond the period -> expired, member level removed
        membership.auto_renew = False
        membership.write({"valid_until": today - relativedelta(days=1), "paid_until": today - relativedelta(days=1)})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.state, "expired")
        self.assertFalse(self.customer.grade_id)
        self.assertFalse(self.customer.specific_property_product_pricelist)

    def test_yearly_billing(self):
        membership = self.env["carwash.membership"].create(
            {"partner_id": self.customer.id, "plan_id": self.plan.id, "billing_period": "monthly"})
        order = membership._get_or_create_billing_order()
        self.assertEqual(order.amount_untaxed, 1000)
        # switched to yearly before paying -> the unpaid order follows
        membership.billing_period = "yearly"
        self.assertEqual(membership.amount, 10000)
        self.assertEqual(order.amount_untaxed, 10000)
        self.assertEqual(order.carwash_billing_period, "yearly")
        self._pay_backend(membership)
        today = fields.Date.context_today(membership)
        self.assertEqual(membership.state, "active")
        self.assertEqual(membership.start_date, today)
        self.assertEqual(membership.valid_until, today + relativedelta(years=1))
        self.assertEqual(membership.expiry_date, today + relativedelta(years=1, days=1))
        # the day after the end date -> expired
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.state, "active")
        membership.write({"valid_until": today - relativedelta(days=1)})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.state, "expired")
        # a plan sold monthly only can't be billed yearly
        membership.billing_period = "monthly"
        self.plan.yearly_price = 0
        with self.assertRaisesRegex(ValidationError, "isn't offered yearly"):
            membership.billing_period = "yearly"

    def test_preview_matches_applied_prices(self):
        membership = self._new_membership()
        self._pay_backend(membership)
        preview = membership._preview_member_total([(self.wash, 300.0, 1.0), (self.wax, 500.0, 1.0)])
        self.assertEqual(preview, {"normal": 800.0, "member": 400.0, "saving": 400.0, "has_benefit": True, "free_wash": True})

        booking = self._booking(self.wash | self.wax)
        booking.action_apply_membership()
        self.assertAlmostEqual(booking.amount_total, preview["member"])
        self.assertAlmostEqual(booking.membership_saving, preview["saving"])

        # the only free wash is now reserved -> the next preview only has the discount
        membership.invalidate_recordset(["washes_reserved", "washes_remaining"])
        preview = membership._preview_member_total([(self.wash, 300.0, 1.0)])
        self.assertFalse(preview["free_wash"])
        self.assertAlmostEqual(preview["member"], 240.0)

    def test_auto_renew_off_lets_membership_lapse(self):
        membership = self._new_membership()
        self._pay_backend(membership)
        self.assertFalse(membership.auto_renew, "a new membership starts without auto-renewal")
        membership.action_toggle_auto_renew()
        self.assertTrue(membership.auto_renew)
        membership.action_toggle_auto_renew()
        self.assertFalse(membership.auto_renew)
        today = fields.Date.context_today(membership)
        membership.write({"valid_until": today + relativedelta(days=1), "paid_until": today + relativedelta(days=1),
                          "next_billing_date": today + relativedelta(days=2)})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertFalse(membership.pending_order_id, "no renewal order without auto-renewal")
        self.assertEqual(membership.state, "active", "it stays active until the paid period ends")
        membership.write({"valid_until": today - relativedelta(days=1), "paid_until": today - relativedelta(days=1)})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.state, "expired")

    def test_one_open_membership_and_cancel_closes_billing(self):
        membership = self._new_membership()
        with self.assertRaisesRegex(ValidationError, "already has membership"):
            self._new_membership()
        action = membership.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(invoice.state, "posted")
        membership.action_cancel()
        self.assertEqual(invoice.state, "cancel", "an unpaid invoice of a cancelled membership can't be paid any more")
        self.assertEqual(membership.sale_order_ids.mapped("state"), ["cancel"])

    def test_membership_lapsing_during_the_wash_can_be_removed(self):
        membership = self._new_membership()
        self._pay_backend(membership)
        booking = self._booking(self.wash)
        booking.action_apply_membership()
        booking.action_confirm()
        booking.state = "ready"
        membership.action_cancel()
        with self.assertRaisesRegex(UserError, "Click Remove"):
            booking.action_done()
        booking.action_remove_membership()
        booking.action_done()
        self.assertEqual((booking.state, booking.amount_total), ("done", 300.0))

    def test_memberships_switched_off(self):
        membership = self._new_membership()
        self._pay_backend(membership)
        self.assertTrue(self.env.user.has_group("product.group_product_pricelist"),
                        "memberships switch on the Pricelists feature")
        self.env["res.config.settings"].create({"group_carwash_membership": False}).execute()
        self.assertFalse(self.customer._carwash_get_usable_membership())
        with self.assertRaises(UserError):
            self._booking(self.wash).action_apply_membership()
