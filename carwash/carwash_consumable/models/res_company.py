from odoo import models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _carwash_warehouse(self, create=False):
        """The branch's warehouse (its consumables are stocked there); created if asked and missing."""
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].sudo().search([("company_id", "=", self.id)], limit=1)
        if not warehouse and create:
            code = f"CW{self.id}"[:5]
            warehouse = self.env["stock.warehouse"].sudo().create(
                {"name": self.name, "code": code, "company_id": self.id, "partner_id": self.partner_id.id}
            )
        return warehouse
