from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _create_payments(self):
        """A staff bill paid (from the staff payable's Pay, or the bill's own Register Payment) pays its staff
        payables."""
        payments = super()._create_payments()
        bills = self.line_ids.move_id.filtered(lambda m: m.move_type == "in_invoice")
        if bills:
            self.env["carwash.staff.commission"].sudo().search(
                [("bill_id", "in", bills.ids), ("state", "=", "to_pay")]
            )._carwash_sync_paid()
        return payments
