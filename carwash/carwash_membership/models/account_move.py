from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def _invoice_paid_hook(self):
        """Backend payment: a membership billing invoice became paid -> activate/extend the membership."""
        res = super()._invoice_paid_hook()
        orders = self.filtered(lambda m: m.is_invoice()).invoice_line_ids.sale_line_ids.order_id
        orders._carwash_register_membership_payment()
        return res
