from odoo import api, models
from odoo.tools import clean_context

from odoo.addons.carwash_jobcard.models.res_users import STAFF_ACCESS

# the highest Car Wash access of a user decides the staff role of the employee created for them
ACCESS_ORDER = ("manager", "front_desk", "qc", "washer")


class ResUsers(models.Model):
    """Everyone with Car Wash access checks in / out, and check in / out needs an employee: a Car Wash
    user without one (e.g. created in Settings > Users) gets it automatically. Their user, Car Wash
    access and rights stay as they are - the employee only links the person to HR (attendance)."""

    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        # Odoo already writes the groups of a user it is still creating: the employee waits for the user
        users = super(ResUsers, self.with_context(carwash_creating_users=True)).create(vals_list)
        users = self.browse(users.ids)
        users._carwash_ensure_attendance_employee()
        return users

    def write(self, vals):
        res = super().write(vals)
        if {"group_ids", "active", "share"} & set(vals) and not self.env.context.get("carwash_creating_users"):
            self._carwash_ensure_attendance_employee()
        return res

    def _carwash_access(self):
        """The user's highest Car Wash access (a key of STAFF_ACCESS), or False."""
        self.ensure_one()
        for access in ACCESS_ORDER:
            group = self.env.ref(STAFF_ACCESS[access][0], raise_if_not_found=False)
            if group and group in self.all_group_ids:
                return access
        return False

    def _carwash_ensure_attendance_employee(self):
        """Create the missing employee of Car Wash users, while Staff Attendance is on. It gets the staff
        role of their access, as New Staff Member does (Manager: Supervisor, Front Desk: Front Desk...)."""
        if not self.env["carwash.feature"]._enabled("carwash_attendance.group_carwash_attendance"):
            return
        Employee = self.env["hr.employee"].sudo().with_context(clean_context(self.env.context), active_test=False)
        vals_list = []
        for user in self.sudo().filtered(lambda u: u.active and not u.share):
            # an archived employee still counts: the person left, don't bring them back
            if Employee.search_count([("user_id", "=", user.id)]):
                continue
            access = user._carwash_access()
            if not access:
                continue
            role = self.env.ref(STAFF_ACCESS[access][1], raise_if_not_found=False)
            vals_list.append({
                "name": user.name,
                "company_id": user.company_id.id,
                "work_email": user.email,
                "carwash_role_ids": [(6, 0, role.ids)] if role else [],
                **Employee._sync_user(user),
            })
        if vals_list:
            Employee.create(vals_list)
