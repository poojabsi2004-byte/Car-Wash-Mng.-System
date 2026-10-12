from odoo import api, models


class CarwashMail(models.AbstractModel):
    """Customer emails go out right away instead of waiting for Odoo's mail queue job (hourly)."""

    _name = "carwash.mail"
    _description = "Car Wash: send customer emails right away"

    @api.model
    def _send_now(self, mail_ids):
        """Send these mail.mail once the current transaction is committed - nothing is sent if the
        action that created them fails, and the user's click isn't slowed down by the mail server."""
        mails = self.env["mail.mail"].sudo().browse([mail_id for mail_id in mail_ids if mail_id]).exists()
        if mails:
            mails.send_after_commit()
        return mails

    @api.model
    def _wake_mail_queue(self):
        """For emails queued by standard Odoo flows (e.g. rating requests): run the mail queue job now."""
        cron = self.env.ref("mail.ir_cron_mail_scheduler_action", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
