from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    carwash_membership_id = fields.Many2one(
        "carwash.membership", string="Car Wash Membership", ondelete="set null", index=True
    )
    carwash_membership_paid = fields.Boolean(
        string="Membership Payment Registered", copy=False, readonly=True,
        help="Set once this billing order's payment has activated/extended the membership.",
    )

    def _carwash_register_membership_payment(self):
        for order in self.filtered("carwash_membership_id"):
            order.carwash_membership_id.sudo()._register_paid_order(order)
