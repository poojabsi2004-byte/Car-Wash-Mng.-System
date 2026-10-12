from odoo import models


class WebsiteMenu(models.Model):
    _inherit = "website.menu"

    def _compute_visible(self):
        """The website "Membership" menu disappears while memberships are switched off."""
        super()._compute_visible()
        membership_menu = self.env.ref("carwash_website.website_menu_membership", raise_if_not_found=False)
        if membership_menu and membership_menu in self and not self.env["carwash.feature"].sudo()._enabled(
            "carwash_membership.group_carwash_membership"
        ):
            for menu in self.filtered(lambda m: m == membership_menu):
                menu.is_visible = False
