from odoo import api, fields, models


class CarwashFeature(models.AbstractModel):
    """Car Wash > Configuration > Settings switches features on/off. Each switch is a
    technical group implied by "Internal User": menus and fields use it through `groups`,
    and code asks `_enabled()` before doing the feature's automatic work."""

    _name = "carwash.feature"
    _description = "Car Wash Feature Switches"

    @api.model
    def _enabled(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return False
        return group.sudo() in self.env.ref("base.group_user").sudo().all_implied_ids


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_time_slot = fields.Boolean(
        "Booking Time Slots", implied_group="carwash_base.group_carwash_time_slot",
        help="Pick a booking's time from the branch's free time slots (or a custom time).",
    )

    carwash_branch_code = fields.Char(related="company_id.carwash_code", readonly=False, string="Branch Code")

    # printed reports: the branch's letterhead (see report/carwash_report_layout.xml)
    carwash_report_logo = fields.Binary(related="company_id.logo", readonly=False, string="Branch Logo")

    def action_carwash_edit_branch(self):
        """Name, address, phone, email, website and GSTIN printed on the Car Wash reports."""
        return {
            "type": "ir.actions.act_window",
            "name": self.company_id.name,
            "res_model": "res.company",
            "res_id": self.company_id.id,
            "view_mode": "form",
            "target": "current",
        }
