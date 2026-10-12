from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _load_menus_blacklist(self):
        """My Earnings is there only while staff payables are recorded (Settings > Staff Payable)."""
        res = super()._load_menus_blacklist()
        menu = self.env.ref("carwash_jobcard.menu_carwash_my_earnings", raise_if_not_found=False)
        if menu and not self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_commission"):
            res.append(menu.id)
        return res
