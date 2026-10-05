from odoo import models
from odoo.tools import float_compare


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _post_process(self):
        """Online payment (portal "Pay Now"): a fully paid membership billing order activates the membership."""
        res = super()._post_process()
        for tx in self.filtered(lambda t: t.state == "done" and t.operation != "validation"):
            for order in tx.sale_order_ids.filtered("carwash_membership_id"):
                paid = sum(order.transaction_ids.filtered(lambda t: t.state == "done").mapped("amount"))
                if float_compare(paid, order.amount_total, precision_rounding=order.currency_id.rounding) >= 0:
                    order._carwash_register_membership_payment()
        return res
