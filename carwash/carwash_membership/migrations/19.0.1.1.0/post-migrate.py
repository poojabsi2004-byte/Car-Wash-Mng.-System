from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Memberships now activate on payment and track their paid period; plans own an Odoo member level."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env["carwash.membership.plan"].with_context(active_test=False).search([])
    plans._sync_member_level()

    # existing active memberships: their current period ends the day before the next billing date
    for membership in env["carwash.membership"].search([("state", "=", "active")]):
        end = (membership.next_billing_date - relativedelta(days=1)) if membership.next_billing_date else None
        membership.write(
            {
                "period_start": membership.start_date,
                "valid_until": end,
                "paid_until": end,
            }
        )
    env["carwash.membership"].search([]).sale_order_ids.filtered(lambda o: o.state == "sale").write(
        {"carwash_membership_paid": True}
    )
    env["carwash.membership"].search([("state", "=", "active")]).partner_id._carwash_sync_member_level()

    # the "renewed" template is noupdate data - refresh its wording for the pay-to-activate flow
    template = env.ref("carwash_membership.mail_template_membership_renewed", raise_if_not_found=False)
    if template:
        template.write(
            {
                "name": "Car Wash: Membership Active",
                "subject": "Your car wash membership {{ object.name }} is active",
                "body_html": template.body_html.replace(
                    "has been renewed. Your next billing date is", "is active - your next billing date is"
                ),
            }
        )
