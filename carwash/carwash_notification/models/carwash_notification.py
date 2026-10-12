import logging

from markupsafe import Markup

from odoo import api, models

_logger = logging.getLogger(__name__)

# key: (email template, label shown in Settings)
NOTIFICATIONS = {
    "booking_request": ("carwash_notification.mail_template_booking_request", "Booking request received"),
    "booking_confirmed": ("carwash_notification.mail_template_booking_confirmed", "Booking confirmed"),
    "booking_updated": ("carwash_notification.mail_template_booking_updated", "Booking updated (time / package)"),
    "booking_reminder": ("carwash_notification.mail_template_booking_reminder", "Visit reminder"),
    "booking_ready": ("carwash_notification.mail_template_booking_ready", "Vehicle ready for pickup"),
    "booking_cancelled": ("carwash_notification.mail_template_booking_cancelled", "Booking cancelled"),
    "membership_payment_request": ("carwash_notification.mail_template_membership_payment_request", "Membership payment request"),
    "membership_activated": ("carwash_notification.mail_template_membership_activated", "Membership activated"),
    "membership_renewed": ("carwash_notification.mail_template_membership_renewed", "Membership renewed"),
    "membership_expiring": ("carwash_notification.mail_template_membership_expiring", "Membership ending soon (auto-renew)"),
    "membership_expired": ("carwash_notification.mail_template_membership_expired", "Membership expired"),
    "membership_cancelled": ("carwash_notification.mail_template_membership_cancelled", "Membership cancelled"),
}
PARAM = "carwash_notification.%s"


class CarwashNotification(models.AbstractModel):
    """Sends the car wash customer emails: one switch per notification (Settings), Odoo mail
    templates, the outgoing mail queue, and a note in the record's chatter."""

    _name = "carwash.notification"
    _description = "Car Wash Notifications"

    @api.model
    def _enabled(self, key):
        return self.env["ir.config_parameter"].sudo().get_param(PARAM % key, "1") != "0"

    @api.model
    def _get_int_param(self, name, default):
        value = self.env["ir.config_parameter"].sudo().get_param(PARAM % name)
        try:
            return int(value) if value not in (None, False, "") else default
        except ValueError:
            return default

    @api.model
    def _send(self, records, key, recipient):
        """Email `records` with the `key` notification. `recipient(record)` returns the
        (partner or email) it goes to - records without one are skipped. Returns the records emailed."""
        sent = records.browse()
        if not records or not self._enabled(key):
            return sent
        template = self.env.ref(NOTIFICATIONS[key][0], raise_if_not_found=False)
        if not template:
            _logger.warning("Car wash notification %s: template missing", key)
            return sent
        for record in records:
            to = recipient(record)
            if not to:
                continue
            # sudo: notifications are a system side effect of the workflow (e.g. a washer marks
            # the vehicle ready) - the acting user doesn't need rights on mail templates
            mail_id = template.sudo().send_mail(record.id, force_send=False, email_layout_xmlid="mail.mail_notification_light")
            # out right after this action is saved - not at the next run of the hourly mail queue
            self.env["carwash.mail"]._send_now([mail_id])
            subject = template.sudo()._render_field("subject", record.ids)[record.id]
            record.sudo().message_post(
                body=Markup("%s <b>%s</b>") % (
                    self.env._("Email sent to %s:", getattr(to, "display_name", to)), subject,
                ),
                subtype_xmlid="mail.mt_note",
            )
            sent |= record
        return sent
