from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    carwash_membership_ids = fields.One2many("carwash.membership", "partner_id", string="Memberships")
    carwash_active_membership_id = fields.Many2one(
        "carwash.membership", compute="_compute_carwash_active_membership_id"
    )

    @api.depends("carwash_membership_ids.state")
    def _compute_carwash_active_membership_id(self):
        for partner in self:
            partner.carwash_active_membership_id = partner.carwash_membership_ids.filtered(
                lambda m: m.state == "active"
            )[:1]

    def _carwash_get_usable_membership(self):
        """The active membership this customer can use on a booking right now (sudo), if any."""
        self.ensure_one()
        membership = self.sudo().carwash_active_membership_id
        if not membership or not self.env["carwash.feature"]._enabled("carwash_membership.group_carwash_membership"):
            return membership.browse()
        try:
            membership._check_usable()
        except UserError:
            return membership.browse()
        return membership

    def _carwash_sync_member_level(self):
        """Give the partner the Odoo member level (and its pricelist) of their active plan, or take it away."""
        member_pricelists = self.env["carwash.membership.plan"].with_context(active_test=False).search([]).pricelist_id
        member_grades = self.env["carwash.membership.plan"].with_context(active_test=False).search([]).grade_id
        for partner in self.sudo():
            grade = partner.carwash_active_membership_id.plan_id.grade_id
            if grade:
                if partner.grade_id != grade:
                    partner.write({"grade_id": grade.id, "specific_property_product_pricelist": grade.default_pricelist_id.id})
            elif partner.grade_id in member_grades:
                vals = {"grade_id": False}
                if partner.specific_property_product_pricelist in member_pricelists:
                    vals["specific_property_product_pricelist"] = False
                partner.write(vals)

    def action_view_carwash_memberships(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Memberships",
            "res_model": "carwash.membership",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
