from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.addons.mail.models.mail_mail import MailMail
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashNotifications(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Notify Customer", "email": "notify.customer@example.com"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "NTF-1", "customer_id": cls.customer.id})
        cls.wash = cls.env["product.product"].create(
            {"name": "Notify Wash", "type": "service", "is_carwash_service": True, "list_price": 200}
        )
        fee = cls.env["product.product"].create({"name": "Notify Fee", "type": "service", "list_price": 500})
        cls.plan = cls.env["carwash.membership.plan"].create(
            {"name": "Notify Gold", "product_id": fee.id, "wash_allowance": 2, "plan_service_ids": [(6, 0, cls.wash.ids)]}
        )
        # no checklist / inspection rules in the way of the booking flow
        cls.env["carwash.checklist.template"].search([]).is_default = False

    def _mails(self, record, subject_part=None):
        mails = self.env["mail.mail"].search([("model", "=", record._name), ("res_id", "=", record.id)])
        if subject_part:
            mails = mails.filtered(lambda m: subject_part in (m.subject or ""))
        return mails

    def _booking(self, hours_ahead=48):
        return self.env["carwash.appointment"].create({
            "customer_id": self.customer.id,
            "vehicle_id": self.vehicle.id,
            "appointment_date": fields.Datetime.now() + timedelta(hours=hours_ahead),
            "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })

    def _switch(self, **values):
        self.env["res.config.settings"].create(values).execute()

    def test_booking_confirmed_logged_and_switchable(self):
        booking = self._booking()
        booking.action_confirm()
        mail = self._mails(booking, "Booking confirmed")
        self.assertEqual(len(mail), 1)
        self.assertIn(self.customer, mail.recipient_ids)
        self.assertIn("Notify Wash", mail.body_html)
        self.assertTrue(booking.message_ids.filtered(lambda m: "Email sent to" in (m.body or "")), "logged in the chatter")

        # handed to Odoo's "send right after commit" - not left for the hourly mail queue job
        with patch.object(MailMail, "send_after_commit", autospec=True) as send_after_commit:
            self._booking(hours_ahead=72).action_confirm()
        self.assertEqual(send_after_commit.call_count, 1)
        self.assertIn("Booking confirmed", send_after_commit.call_args[0][0].subject)

        self._switch(carwash_notify_booking_confirmed=False)
        other = self._booking()
        other.action_confirm()
        self.assertFalse(self._mails(other, "Booking confirmed"), "switched off in Settings")

    def test_updated_cancelled_ready(self):
        booking = self._booking()
        booking.action_confirm()
        booking.carwash_reminder_sent = True
        booking.appointment_date = booking.appointment_date + timedelta(hours=3)
        self.assertEqual(len(self._mails(booking, "was updated")), 1)
        self.assertFalse(booking.carwash_reminder_sent, "a moved visit gets a new reminder")
        booking.notes = "no email for this"
        self.assertEqual(len(self._mails(booking, "was updated")), 1)

        booking._send_carwash_template("carwash_membership.mail_template_appointment_ready")
        self.assertEqual(len(self._mails(booking, "ready for pickup")), 1)

        booking.action_cancel()
        self.assertEqual(len(self._mails(booking, "was cancelled")), 1)

    def test_visit_reminder(self):
        soon = self._booking(hours_ahead=10)
        later = self._booking(hours_ahead=60)
        just_booked = self._booking(hours_ahead=5)
        (soon | later | just_booked).action_confirm()
        three_hours_ago = fields.Datetime.now() - timedelta(hours=3)
        self.env.cr.execute("UPDATE carwash_appointment SET create_date = %s WHERE id IN %s",
                            (three_hours_ago, (soon.id, later.id)))
        self.env.invalidate_all()
        self.env["carwash.appointment"]._cron_carwash_booking_reminders()
        self.assertEqual(len(self._mails(soon, "Reminder")), 1)
        self.assertFalse(self._mails(later, "Reminder"), "outside the 24h window")
        self.assertFalse(self._mails(just_booked, "Reminder"), "just got its confirmation")
        self.env["carwash.appointment"]._cron_carwash_booking_reminders()
        self.assertEqual(len(self._mails(soon, "Reminder")), 1, "sent once")

    def test_membership_activated_renewed_and_renew_reminder(self):
        membership = self.env["carwash.membership"].create({"partner_id": self.customer.id, "plan_id": self.plan.id})
        membership.action_request_payment()
        self.assertEqual(len(self._mails(membership, "Complete your")), 1)
        membership._register_paid_order(membership.pending_order_id)
        self.assertEqual(len(self._mails(membership, "Welcome!")), 1, "first payment = activated")
        membership._register_paid_order(membership._get_or_create_billing_order())
        self.assertEqual(len(self._mails(membership, "is renewed")), 1, "next payment = renewed")

        today = fields.Date.context_today(membership)
        Membership = self.env["carwash.membership"]
        self.assertFalse(membership.auto_renew, "a new membership starts without auto-renewal")
        # 10 days before the end: the auto-renew reminder, with the Auto Renew button
        membership.paid_until = today + relativedelta(days=10)
        self.assertEqual(Membership._cron_carwash_membership_expiry_reminders(), membership, "10 days before the end")
        mail = self._mails(membership, "ends on")
        self.assertIn("turn on auto-renew", mail.subject)
        self.assertIn(f"/car-wash/membership/{membership.id}/auto-renew/{membership._carwash_auto_renew_token()}", mail.body_html)
        self.assertFalse(Membership._cron_carwash_membership_expiry_reminders(), "one reminder per period")

        membership.paid_until = today + relativedelta(days=12)
        self.assertFalse(Membership._cron_carwash_membership_expiry_reminders(), "not yet within 10 days")
        self._switch(carwash_membership_expiry_days=14)
        self.assertEqual(Membership._cron_carwash_membership_expiry_reminders(), membership, "timing from Settings")

        # the customer pressed Auto Renew: the next reminder only says it renews automatically
        membership._carwash_turn_on_auto_renew(by_customer=True)
        self.assertTrue(membership.auto_renew)
        self.assertIn("Auto-renewal turned on by the customer", membership.message_ids[0].body)
        membership.paid_until = today + relativedelta(days=3)
        self.assertEqual(Membership._cron_carwash_membership_expiry_reminders(), membership)
        self.assertTrue(self._mails(membership, "it renews automatically"))

    def test_membership_expired_and_cancelled(self):
        membership = self.env["carwash.membership"].create({"partner_id": self.customer.id, "plan_id": self.plan.id})
        membership._register_paid_order(membership._get_or_create_billing_order())
        yesterday = fields.Date.context_today(membership) - relativedelta(days=1)
        membership.write({"paid_until": yesterday, "valid_until": yesterday})
        self.env["carwash.membership"]._cron_process_membership_billing()
        self.assertEqual(membership.state, "expired")
        self.assertEqual(len(self._mails(membership, "has expired")), 1)

        other = self.env["carwash.membership"].create({"partner_id": self.customer.id, "plan_id": self.plan.id})
        other.action_cancel()
        self.assertEqual(len(self._mails(other, "was cancelled")), 1)

    def test_booking_request_received(self):
        lead = self.env["crm.lead"].create({
            "name": "Website request", "type": "opportunity", "is_carwash_booking": True,
            "partner_id": self.customer.id, "carwash_booking_date": fields.Datetime.now() + timedelta(days=2),
        })
        self.assertEqual(len(self._mails(lead, "We received your car wash booking request")), 1)
        plain = self.env["crm.lead"].create({"name": "Not a car wash lead", "partner_id": self.customer.id})
        self.assertFalse(self._mails(plain))
