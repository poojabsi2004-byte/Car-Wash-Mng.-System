from odoo import api, models

FEATURE = "carwash_consumable.group_carwash_consumable"


class CarwashDashboard(models.AbstractModel):
    _inherit = "carwash.dashboard"

    @api.model
    def get_dashboard_data(self, period="week", date_from=None, date_to=None):
        data = super().get_dashboard_data(period=period, date_from=date_from, date_to=date_to)
        if data.get("has_manager_data") and self.env["carwash.feature"]._enabled(FEATURE):
            data["consumables"] = self._get_consumable_data(self.env.companies)
        return data

    def _get_consumable_data(self, companies):
        """Low-stock consumables and requests waiting for the manager at the selected branch(es)."""
        low = self.env["product.product"]._carwash_low_stock(companies)
        Request = self.env["carwash.consumable.request"].sudo()
        branch_domain = [("company_id", "in", companies.ids)]
        return {
            "low_stock": [
                {
                    "id": product.id,
                    "name": product.display_name,
                    "branch": company.name,
                    "qty": round(qty, 2),
                    "min": round(minimum, 2),
                    "uom": product.uom_id.name,
                    "out": qty <= 0,
                    "fill": max(0, min(100, round(qty / minimum * 100))) if minimum else 0,
                }
                for company, product, qty, minimum in sorted(low, key=lambda r: r[2] / r[3] if r[3] else 0)
            ],
            "to_approve": Request.search_count(branch_domain + [("state", "=", "submitted")]),
            "to_issue": Request.search_count(branch_domain + [("state", "=", "approved")]),
        }
