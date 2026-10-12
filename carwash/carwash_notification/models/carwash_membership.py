from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .carwash_notification import NOTIFICATIONS


def _member(membership):
    return membership.partner_id if membership.partner_id.email else False


class CarwashMembership(models.Model):
    _inherit = "carwash.membership"

    carwash_expiry_reminder_for = fields.Date(
        string="Renewal Reminder Sent For", copy=False, readonly=True,
        help="End date the 'ending soon - renew' email was sent for (one reminder per period).",
    )

    def _carwash_notify_membership(self, kind):
        key = f"membership_{kind}"
        if key not in NOTIFICATIONS:
            return super()._carwash_notify_membership(kind)
        self.env["carwash.notification"]._send(self, key, _member)

    @api.model
    def _cron_carwash_membership_expiry_reminders(self):
        """Daily: N days (Settings, default 10) before a membership's end date, email the member - once
        per period, and not when the next period is already paid. Auto-renewal off: the email has the
        Auto Renew button (turns it on, then the renewal is paid automatically the day after the end
        date); on: it says the renewal will be paid automatically on that day."""
        Notification = self.env["carwash.notification"]
        if not Notification._enabled("membership_expiring"):
            return self.browse()
        days = Notification._get_int_param("membership_expiry_days", 10)
        today = fields.Date.context_today(self)
        memberships = self.search([
            ("state", "=", "active"),
            ("paid_until", ">=", today),
            ("paid_until", "<=", today + relativedelta(days=days)),
        ]).filtered(lambda m: m.carwash_expiry_reminder_for != m.paid_until)
        sent = Notification._send(memberships, "membership_expiring", _member)
        for membership in memberships:
            membership.carwash_expiry_reminder_for = membership.paid_until
        return sent

    def _carwash_renew_url(self):
        """Where the member renews: the open billing order, else their membership page."""
        self.ensure_one()
        base = self.get_base_url()
        if self.pending_order_id:
            return base + self.pending_order_id.get_portal_url()
        return base + "/my/membership"
