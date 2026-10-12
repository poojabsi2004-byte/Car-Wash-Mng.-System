from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_purchase = fields.Boolean(
        "Purchases", implied_group="carwash_purchase.group_carwash_purchase",
        help="Suppliers, RFQs and purchase orders with approval, receipts, returns, vendor bills, payments and GST.",
    )
    carwash_auto_rfq = fields.Boolean(related="company_id.carwash_auto_rfq", readonly=False)
    carwash_company_state_id = fields.Many2one(
        related="company_id.state_id", string="Branch State", readonly=False,
        domain="[('country_id.code', '=', 'IN')]",
    )
    carwash_company_gstin = fields.Char(related="company_id.vat", string="Branch GSTIN", readonly=False)
    carwash_gst_ready = fields.Boolean(compute="_compute_carwash_gst_ready", string="GST Accounting Set Up")

    @api.depends("company_id.chart_template")
    def _compute_carwash_gst_ready(self):
        for settings in self:
            settings.carwash_gst_ready = settings.company_id._carwash_gst_ready()

    def set_values(self):
        """The purchase approval saved on a main company applies to its branches too (saved on a branch: that
        branch only)."""
        super().set_values()
        company = self.company_id
        branches = self.env["res.company"].sudo().search([("id", "child_of", company.id), ("id", "!=", company.id)])
        if branches:
            branches.write({
                "po_double_validation": company.po_double_validation,
                "po_double_validation_amount": company.po_double_validation_amount,
            })

    def action_carwash_setup_gst(self):
        """Set up GST for the branch (Indian chart of accounts, INR, GST on the car wash purchases)."""
        self.ensure_one()
        self.company_id._carwash_setup_gst()
        return {"type": "ir.actions.client", "tag": "reload_context"}
