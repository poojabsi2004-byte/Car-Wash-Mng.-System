from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import clean_context

# Car Wash access of a staff member -> (security group, default staff role)
STAFF_ACCESS = {
    "washer": ("carwash_jobcard.group_carwash_washer", "carwash_jobcard.staff_role_washer"),
    "qc": ("carwash_jobcard.group_carwash_qc", "carwash_jobcard.staff_role_qc"),
    "front_desk": ("carwash_base.group_carwash_user", "carwash_jobcard.staff_role_front_desk"),
    "manager": ("carwash_base.group_carwash_manager", "carwash_jobcard.staff_role_supervisor"),
}
STAFF_FIELDS = ("carwash_access", "carwash_role_ids", "carwash_branch_id")


class ResUsers(models.Model):
    """New Staff Member is a user form: saving it creates the user, then the employee linked to it."""

    _inherit = "res.users"

    # filled in on the New Staff Member form only (not stored): the user's Car Wash access
    # and the employee created with it
    carwash_access = fields.Selection(
        [("washer", "Washer / Detailer"), ("qc", "QC Inspector"), ("front_desk", "Front Desk"), ("manager", "Manager")],
        string="Car Wash Access", store=False, copy=False, default="washer",
        help="What the person can do in the Car Wash app (their user role).",
    )
    carwash_role_ids = fields.Many2many(
        "carwash.staff.role", string="Staff Roles", store=False, copy=False,
        default=lambda self: self.env.ref(STAFF_ACCESS["washer"][1], raise_if_not_found=False),
        help="What they do at the car wash: decides the job cards they can be assigned to and their staff payable.",
    )
    carwash_branch_id = fields.Many2one(
        "res.company", string="Branch", store=False, copy=False, default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
        help="The branch the staff member works at.",
    )

    def _carwash_can_add_staff(self):
        return self.env.user.has_group("carwash_base.group_carwash_manager") or self.env.user.has_group("base.group_erp_manager")

    def onchange(self, values, field_names, fields_spec):
        if not self and self.env.context.get("carwash_new_staff") and self._carwash_can_add_staff():
            # New Staff Member: a Car Wash Manager fills in a new user without Settings rights
            # (create() keeps only the staff values)
            self = self.sudo()
        return super().onchange(values, field_names, fields_spec)

    @api.onchange("carwash_access")
    def _onchange_carwash_access(self):
        role = self.env.ref(STAFF_ACCESS[self.carwash_access][1], raise_if_not_found=False) if self.carwash_access else None
        if role:
            self.carwash_role_ids = role

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("carwash_new_staff"):
            return self._carwash_create_staff(vals_list)
        return super().create([{key: value for key, value in vals.items() if key not in STAFF_FIELDS} for vals in vals_list])

    def _carwash_create_staff(self, vals_list):
        """New Staff Member: create the user with its Car Wash access, then the employee linked to it."""
        if not self._carwash_can_add_staff():
            raise UserError(self.env._("Only a Car Wash Manager can add staff."))
        user_ids = []
        for vals in vals_list:
            access = vals.get("carwash_access") or "washer"
            if access not in STAFF_ACCESS:
                raise UserError(self.env._("Choose the staff member's Car Wash Access."))
            branch = self.env["res.company"].browse(vals.get("carwash_branch_id") or self.env.company.id)
            if branch not in self.env.companies:
                raise UserError(self.env._("You can only add staff to your own branches."))
            login = (vals.get("login") or "").strip()
            if self.sudo().with_context(active_test=False).search_count([("login", "=", login)]):
                raise UserError(self.env._("A user with the login %s already exists.", login))
            # only these values are taken from the form: staff get a Car Wash access, no other rights
            user_vals = {
                "name": vals.get("name"),
                "login": login,
                "email": login if "@" in login else False,
                "phone": vals.get("phone") or False,
                "company_id": branch.id,
                "company_ids": [Command.set(branch.ids)],
                "group_ids": [Command.set((self.env.ref("base.group_user") | self.env.ref(STAFF_ACCESS[access][0])).ids)],
            }
            if vals.get("password"):
                user_vals["password"] = vals["password"]
            # sudo: creating users needs Settings rights; Car Wash Managers add staff with the values above only
            # (without a password, a login that is an email address gets an invitation to set one)
            creator = self.sudo().with_context(clean_context(self.env.context), no_reset_password=bool(vals.get("password")))
            user = super(ResUsers, creator).create([user_vals])
            roles = vals.get("carwash_role_ids")
            if roles is None:
                roles = [Command.set(self.env.ref(STAFF_ACCESS[access][1]).ids)]
            self.env["hr.employee"].sudo().with_context(clean_context(self.env.context)).create({
                "name": user.name,
                "user_id": user.id,
                "company_id": branch.id,
                "work_email": user.email,
                "mobile_phone": user.phone,
                "carwash_role_ids": roles,
            })
            user_ids.append(user.id)
        return self.browse(user_ids)

    def action_carwash_open_staff(self):
        """Create Staff Member: the form is saved (user + employee) - open the new employee."""
        self.ensure_one()
        employee = self.env["hr.employee"].search([("user_id", "=", self.id)], limit=1)
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_staff")
        action.update(res_id=employee.id, view_mode="form", views=[(False, "form")])
        return action
