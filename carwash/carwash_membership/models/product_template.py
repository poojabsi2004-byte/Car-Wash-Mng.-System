from odoo import api, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        if any(vals.get("is_carwash_service") for vals in vals_list):
            self.env["carwash.membership.plan"].search([("discount_percent", ">", 0)])._sync_member_level()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if "is_carwash_service" in vals:
            # member discount rules list every car wash service - keep them complete
            self.env["carwash.membership.plan"].search([("discount_percent", ">", 0)])._sync_member_level()
        return res
