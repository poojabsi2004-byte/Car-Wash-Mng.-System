from datetime import timedelta

from odoo import api, fields, models

FEATURE = "carwash_purchase.group_carwash_purchase"


class CarwashDashboard(models.AbstractModel):
    _inherit = "carwash.dashboard"

    @api.model
    def get_dashboard_data(self, period="week", date_from=None, date_to=None):
        data = super().get_dashboard_data(period=period, date_from=date_from, date_to=date_to)
        if data.get("has_manager_data") and self.env["carwash.feature"]._enabled(FEATURE):
            data["purchases"] = self._get_purchase_data(self.env.companies)
        return data

    def _get_purchase_data(self, companies):
        """Purchases waiting for the manager at the selected branch(es): approvals, deliveries, bills."""
        Order = self.env["purchase.order"]
        branch = [("company_id", "in", companies.ids)]
        now = fields.Datetime.now()
        today_start = self._day_start_utc(self._local_now().date())
        tomorrow_start = today_start + timedelta(days=1)
        month_start = self._day_start_utc(self._local_now().date().replace(day=1))
        currency = self.env.company.currency_id
        receipts = self.env["stock.picking"].search(branch + [
            ("picking_type_code", "=", "incoming"), ("purchase_id", "!=", False),
            ("state", "not in", ("done", "cancel")),
        ])
        bills = self.env["account.move"].search(branch + [
            ("move_type", "=", "in_invoice"), ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
        ])
        due_soon = bills.filtered(lambda b: b.invoice_date_due and b.invoice_date_due <= fields.Date.today() + timedelta(days=7))
        spend = sum(
            o.currency_id._convert(o.amount_untaxed, currency, o.company_id, o.date_approve or now)
            for o in Order.search(branch + [("state", "in", ("purchase", "done")), ("date_approve", ">=", month_start)])
        )
        low = self.env["product.product"]._carwash_low_stock(companies)
        with_supplier = [r for r in low if r[1]._carwash_seller(r[0])]
        return {
            "to_approve": Order.search_count(branch + [("state", "=", "to approve")]),
            "rfqs": Order.search_count(branch + [("state", "in", ("draft", "sent"))]),
            "receipts_today": len(receipts.filtered(lambda p: today_start <= p.scheduled_date < tomorrow_start)),
            "receipts_late": len(receipts.filtered(lambda p: p.scheduled_date < today_start)),
            "receipts_open": len(receipts),
            "bills_to_pay": len(bills),
            "bills_due": len(due_soon),
            "amount_due": sum(b.currency_id._convert(b.amount_residual, currency, b.company_id, now) for b in bills),
            "spend_month": spend,
            "low_with_supplier": len(with_supplier),
            "low_without_supplier": len(low) - len(with_supplier),
            "auto_rfq": any(companies.mapped("carwash_auto_rfq")),
        }

    @api.model
    def action_carwash_create_low_stock_rfqs(self):
        return self.env["product.product"].action_carwash_create_low_stock_rfqs()
