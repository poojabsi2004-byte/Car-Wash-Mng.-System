"""The 'Rate your wash' email is replaced by the single 'your car wash is complete' email (with the rating /
review links): remove the old template, which noupdate kept in existing databases."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    old = env.ref("carwash_jobcard.mail_template_booking_rating_request", raise_if_not_found=False)
    if old:
        old.unlink()
