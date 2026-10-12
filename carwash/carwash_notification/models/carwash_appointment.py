from datetime import timedelta

from odoo import api, fields, models

# templates the membership module sends from the booking workflow -> notification key
LEGACY_TEMPLATES = {
    "carwash_membership.mail_template_appointment_confirmed": "booking_confirmed",
    "carwash_membership.mail_template_appointment_ready": "booking_ready",
}


def _customer(appointment):
    return appointment.customer_id if appointment.customer_id.email else False


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    carwash_reminder_sent = fields.Boolean(string="Reminder Sent", copy=False, readonly=True)

    def _send_carwash_template(self, xml_id):
        key = LEGACY_TEMPLATES.get(xml_id)
        if not key:
            return super()._send_carwash_template(xml_id)
        self.env["carwash.notification"]._send(self, key, _customer)

    def write(self, vals):
        watched = {"appointment_date", "service_package_id"} & set(vals)
        before = {}
        if watched and not self.env.context.get("carwash_no_update_notification"):
            before = {a.id: (a.appointment_date, a.service_package_id.id) for a in self if a.state == "confirmed"}
        res = super().write(vals)
        if before:
            changed = self.filtered(
                lambda a: a.id in before and a.state == "confirmed"
                and (a.appointment_date, a.service_package_id.id) != before[a.id]
            )
            if changed:
                moved = changed.filtered(lambda a: a.appointment_date != before[a.id][0])
                if moved:
                    moved.with_context(carwash_no_update_notification=True).write({"carwash_reminder_sent": False})
                self.env["carwash.notification"]._send(changed, "booking_updated", _customer)
        return res

    def action_cancel(self):
        notify = self.filtered(lambda a: a.state in ("confirmed", "arrived"))
        res = super().action_cancel()
        self.env["carwash.notification"]._send(notify.filtered(lambda a: a.state == "cancelled"), "booking_cancelled", _customer)
        return res

    @api.model
    def _cron_carwash_booking_reminders(self):
        """Hourly: remind customers of a confirmed visit coming up within the reminder window.
        Bookings made in the last 2 hours are skipped - they just got their confirmation."""
        Notification = self.env["carwash.notification"]
        if not Notification._enabled("booking_reminder"):
            return
        hours = Notification._get_int_param("booking_reminder_hours", 24)
        now = fields.Datetime.now()
        bookings = self.search([
            ("state", "=", "confirmed"),
            ("carwash_reminder_sent", "=", False),
            ("appointment_date", ">", now),
            ("appointment_date", "<=", now + timedelta(hours=hours)),
            ("create_date", "<=", now - timedelta(hours=2)),
        ])
        sent = Notification._send(bookings, "booking_reminder", _customer)
        bookings.with_context(carwash_no_update_notification=True).write({"carwash_reminder_sent": True})
        return sent
