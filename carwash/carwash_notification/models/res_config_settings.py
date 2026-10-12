from odoo import api, fields, models

from .carwash_notification import NOTIFICATIONS, PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    carwash_notify_booking_request = fields.Boolean("Booking request received")
    carwash_notify_booking_confirmed = fields.Boolean("Booking confirmed")
    carwash_notify_booking_updated = fields.Boolean("Booking updated")
    carwash_notify_booking_reminder = fields.Boolean("Visit reminder")
    carwash_notify_booking_ready = fields.Boolean("Ready for pickup")
    carwash_notify_booking_cancelled = fields.Boolean("Booking cancelled")
    carwash_notify_membership_payment_request = fields.Boolean("Membership payment request")
    carwash_notify_membership_activated = fields.Boolean("Membership activated")
    carwash_notify_membership_renewed = fields.Boolean("Membership renewed")
    carwash_notify_membership_expiring = fields.Boolean("Membership ending soon")
    carwash_notify_membership_expired = fields.Boolean("Membership expired")
    carwash_notify_membership_cancelled = fields.Boolean("Membership cancelled")
    carwash_booking_reminder_hours = fields.Integer(
        "Reminder before the visit (hours)", config_parameter="carwash_notification.booking_reminder_hours", default=24,
    )
    carwash_membership_expiry_days = fields.Integer(
        "Auto-renew reminder (days before the end)", config_parameter="carwash_notification.membership_expiry_days",
        default=10,
    )

    # on/off switches are stored as "1"/"0" so that "never set" means on
    @api.model
    def get_values(self):
        res = super().get_values()
        Notification = self.env["carwash.notification"]
        for key in NOTIFICATIONS:
            res[f"carwash_notify_{key}"] = Notification._enabled(key)
        return res

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        for key in NOTIFICATIONS:
            params.set_param(PARAM % key, "1" if self[f"carwash_notify_{key}"] else "0")
