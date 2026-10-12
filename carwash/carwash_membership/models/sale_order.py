from odoo import fields, models

from .carwash_membership_plan import BILLING_CYCLES


class SaleOrder(models.Model):
    _inherit = "sale.order"

    carwash_membership_id = fields.Many2one(
        "carwash.membership", string="Car Wash Membership", ondelete="set null", index=True
    )
    carwash_membership_paid = fields.Boolean(
        string="Membership Payment Registered", copy=False, readonly=True,
        help="Set once this billing order's payment has activated/extended the membership.",
    )
    carwash_billing_period = fields.Selection(
        BILLING_CYCLES, string="Membership Billing", copy=False, readonly=True,
        help="One month or one year of membership - what this billing order pays for.",
    )

    def _carwash_register_membership_payment(self):
        for order in self.filtered("carwash_membership_id"):
            order.carwash_membership_id.sudo()._register_paid_order(order)
