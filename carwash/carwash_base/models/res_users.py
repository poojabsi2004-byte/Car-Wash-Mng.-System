from odoo import api, fields, models


class ResUsers(models.Model):
    """The user's Access Rights tab: the Car Wash role dropdown (Front Desk, Washer/Detailer, QC Inspector,
    Manager, Owner) is what gives a person car wash access. The "Car Wash: ..." feature switches (Car Wash >
    Configuration > Settings) aren't personal rights - every user gets them while the feature is on - so they
    aren't listed on the user (Developer Mode > Extra Rights)."""

    _inherit = "res.users"

    view_group_hierarchy = fields.Json(default=lambda self: self._carwash_view_group_hierarchy())

    @api.model
    def _carwash_feature_group_ids(self):
        """The car wash feature-switch groups: car wash groups that aren't a role (no privilege)."""
        data = self.env["ir.model.data"].sudo().search([("model", "=", "res.groups"), ("module", "=like", "carwash_%")])
        groups = self.env["res.groups"].sudo().browse(data.mapped("res_id")).exists()
        return set(groups.filtered(lambda g: not g.privilege_id).ids)

    @api.model
    def _carwash_view_group_hierarchy(self):
        hierarchy = self.env["res.groups"]._get_view_group_hierarchy()
        hidden = self._carwash_feature_group_ids()
        if not hidden:
            return hierarchy
        groups = {}
        for group_id, group in hierarchy["groups"].items():
            if group_id in hidden:
                continue
            group = dict(group)  # the hierarchy is cached: never change it in place
            for key in ("disjoint_ids", "implied_ids", "all_implied_ids", "all_implied_by_ids"):
                group[key] = [gid for gid in group[key] if gid not in hidden]
            groups[group_id] = group
        return dict(hierarchy, groups=groups)
