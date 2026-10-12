from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

COMMISSION_TYPES = [
    ("none", "No Staff Payable"),
    ("percent", "% of Service Value"),
    ("fixed", "Fixed per Job"),
]


class CarwashStaffRole(models.Model):
    """What a staff member does at the car wash - used to find and filter staff, to decide who
    can be put on a job card or do the quality check, and as the default staff payable."""

    _name = "carwash.staff.role"
    _description = "Car Wash Staff Role"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    can_do_jobs = fields.Boolean(
        string="Works on Job Cards", help="Staff with this role can be assigned to job cards (washing, detailing...)."
    )
    can_do_qc = fields.Boolean(string="Does Quality Checks", help="Staff with this role can be the QC inspector of a job card.")
    commission_type = fields.Selection(COMMISSION_TYPES, string="Default Staff Payable", default="none", required=True)
    commission_rate = fields.Float(string="Staff Payable (%)", help="Percentage of the booking's service value, shared by the staff on the job.")
    commission_fixed = fields.Monetary(string="Staff Payable per Job", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    employee_ids = fields.Many2many("hr.employee", "carwash_staff_role_employee_rel", "role_id", "employee_id", string="Staff")
    employee_count = fields.Integer(compute="_compute_employee_count", string="Staff Count")

    _name_uniq = models.Constraint("UNIQUE(name)", "A staff role with this name already exists.")
    _rate_range = models.Constraint(
        "CHECK(commission_rate >= 0 AND commission_rate <= 100)", "The staff payable must be between 0 and 100%."
    )

    @api.depends("employee_ids")
    def _compute_employee_count(self):
        for role in self:
            role.employee_count = len(role.employee_ids)

    def action_view_staff(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_staff")
        action["domain"] = [("carwash_role_ids", "in", self.ids)]
        action["context"] = {"default_carwash_role_ids": [(6, 0, self.ids)]}
        action["display_name"] = self.name
        return action


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    carwash_role_ids = fields.Many2many(
        "carwash.staff.role", "carwash_staff_role_employee_rel", "employee_id", "role_id",
        string="Car Wash Roles", help="What this person does at the car wash - used to filter staff and assign jobs.",
    )
    # a person's own pay is HR data: managers (Employees officers) only. Without `groups`, every read of an
    # employee by Front Desk / Washer / QC (who only see public profiles) would also load these and fail.
    carwash_commission_type = fields.Selection(
        [("role", "Role Default")] + COMMISSION_TYPES, string="Staff Payable", default="role", required=True,
        groups="hr.group_hr_user",
        help="Role Default: use the staff payable of the staff member's role (the highest one if several). "
        "% of Service Value / Fixed per Job: this person's own pay, used instead of the role's.",
    )
    carwash_commission_rate = fields.Float(string="Staff Payable (%)", groups="hr.group_hr_user")
    # who can be put on a job card: the Assigned Staff / QC Inspector lists of the job card
    carwash_can_do_jobs = fields.Boolean(
        compute="_compute_carwash_abilities", search="_search_carwash_can_do_jobs", string="Works on Job Cards",
        help="Has a user and a role that works on job cards (Washer, Detailer, Supervisor...) or Washer / Detailer access.",
    )
    carwash_can_do_qc = fields.Boolean(
        compute="_compute_carwash_abilities", search="_search_carwash_can_do_qc", string="Does Quality Checks",
        help="Has a user and a role that does quality checks (QC Inspector, Supervisor...) or QC Inspector access.",
    )

    # ability -> (staff role flag, Car Wash access group)
    _CARWASH_ABILITIES = {
        "jobs": ("can_do_jobs", "carwash_jobcard.group_carwash_washer"),
        "qc": ("can_do_qc", "carwash_jobcard.group_carwash_qc"),
    }

    def _carwash_ability_domain(self, ability):
        role_flag, group_xmlid = self._CARWASH_ABILITIES[ability]
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        return [
            ("user_id", "!=", False),
            "|", (f"carwash_role_ids.{role_flag}", "=", True), ("user_id.group_ids", "in", group.ids if group else []),
        ]

    def _compute_carwash_abilities(self):
        saved = self.filtered("id")
        able = {
            ability: set(self.sudo().search([("id", "in", saved.ids)] + self._carwash_ability_domain(ability)).ids)
            if saved else set()
            for ability in self._CARWASH_ABILITIES
        }
        for employee in self:
            employee.carwash_can_do_jobs = employee.id in able["jobs"]
            employee.carwash_can_do_qc = employee.id in able["qc"]

    def _carwash_search_ability(self, ability, operator, value):
        if operator not in ("=", "!="):
            return NotImplemented
        domain = self._carwash_ability_domain(ability)
        if (operator == "=") == bool(value):
            return domain
        return [("id", "not in", self.sudo()._search(domain))]

    def _search_carwash_can_do_jobs(self, operator, value):
        return self._carwash_search_ability("jobs", operator, value)

    def _search_carwash_can_do_qc(self, operator, value):
        return self._carwash_search_ability("qc", operator, value)

    @api.constrains("carwash_role_ids", "user_id")
    def _check_carwash_staff_user(self):
        """Car wash staff are users first: an employee without a login can't get a Car Wash role."""
        for employee in self:
            if employee.carwash_role_ids and not employee.user_id:
                raise ValidationError(self.env._(
                    "%s has no user. Create the user first (Staff > New Staff Member, or Create User on the "
                    "employee) - only employees with a login can get a Car Wash role.",
                    employee.name,
                ))

    @api.constrains("carwash_commission_rate")
    def _check_carwash_commission_rate(self):
        for employee in self:
            if not 0 <= employee.carwash_commission_rate <= 100:
                raise ValidationError(self.env._("The staff payable must be between 0 and 100%."))
    # hr.employee.currency_id is HR-officers only; car wash managers need their own
    carwash_currency_id = fields.Many2one("res.currency", related="company_id.currency_id", string="Car Wash Currency")
    carwash_commission_fixed = fields.Monetary(
        string="Staff Payable per Job", currency_field="carwash_currency_id", groups="hr.group_hr_user",
    )
    carwash_commission_ids = fields.One2many("carwash.staff.commission", "employee_id", string="Staff Payables")
    carwash_commission_due = fields.Monetary(
        compute="_compute_carwash_stats", string="Staff Payable To Pay", currency_field="carwash_currency_id"
    )
    carwash_jobcard_count = fields.Integer(compute="_compute_carwash_stats", string="Jobs Done")
    carwash_rating_avg = fields.Float(compute="_compute_carwash_stats", string="Customer Rating", digits=(16, 1))
    carwash_rating_count = fields.Integer(compute="_compute_carwash_stats", string="Customer Ratings Received")
    carwash_commission_enabled = fields.Boolean(compute="_compute_carwash_feature_flags")
    carwash_individual_pay_enabled = fields.Boolean(compute="_compute_carwash_feature_flags")
    carwash_rating_enabled = fields.Boolean(compute="_compute_carwash_feature_flags")

    def _compute_carwash_feature_flags(self):
        Feature = self.env["carwash.feature"]
        commission = Feature._enabled("carwash_jobcard.group_carwash_commission")
        individual = commission and Feature._enabled("carwash_jobcard.group_carwash_individual_pay")
        rating = Feature._enabled("carwash_jobcard.group_carwash_rating")
        for employee in self:
            employee.carwash_commission_enabled = commission
            employee.carwash_individual_pay_enabled = individual
            employee.carwash_rating_enabled = rating

    def _compute_carwash_stats(self):
        Jobcard = self.env["carwash.jobcard"].sudo()
        Rating = self.env["rating.rating"].sudo()
        for employee in self:
            jobcards = Jobcard.search([("assigned_employee_ids", "in", employee.ids), ("stages", "=", "done")])
            employee.carwash_jobcard_count = len(jobcards)
            employee.carwash_commission_due = sum(
                employee.sudo().carwash_commission_ids.filtered(lambda c: c.state == "to_pay").mapped("amount")
            )
            ratings = Rating.search([
                ("res_model", "=", "carwash.appointment"),
                ("res_id", "in", jobcards.appointment_id.ids),
                ("consumed", "=", True),
                ("rating", ">=", 1),
            ]) if jobcards else Rating
            employee.carwash_rating_count = len(ratings)
            employee.carwash_rating_avg = sum(ratings.mapped("rating")) / len(ratings) if ratings else 0.0

    def _carwash_commission_rule(self):
        """(type, rate %, fixed amount) that applies to this staff member: their own pay when Individual Staff
        Pay is on and set on them, else their role's."""
        self.ensure_one()
        # sudo: the pay is HR data, and the payable is recorded by whoever passes QC (a QC inspector)
        employee = self.sudo()
        individual = self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_individual_pay")
        if individual and employee.carwash_commission_type != "role":
            return employee.carwash_commission_type, employee.carwash_commission_rate, employee.carwash_commission_fixed
        roles = employee.carwash_role_ids.filtered(lambda r: r.commission_type != "none")
        if not roles:
            return "none", 0.0, 0.0
        # several commissioned roles: the most generous percentage wins, else the highest fixed amount
        percent = roles.filtered(lambda r: r.commission_type == "percent").sorted("commission_rate", reverse=True)[:1]
        if percent:
            return "percent", percent.commission_rate, 0.0
        fixed = roles.sorted("commission_fixed", reverse=True)[:1]
        return "fixed", 0.0, fixed.commission_fixed

    def action_view_carwash_commissions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_staff_commission")
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {"search_default_to_pay": 1}
        return action

    def action_view_carwash_jobcards(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Jobs: %s", self.name),
            "res_model": "carwash.jobcard",
            "view_mode": "list,form",
            "domain": [("assigned_employee_ids", "in", self.ids)],
        }

    def action_view_carwash_ratings(self):
        self.ensure_one()
        jobcards = self.env["carwash.jobcard"].sudo().search([("assigned_employee_ids", "in", self.ids)])
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_rating")
        action["domain"] = [("res_model", "=", "carwash.appointment"), ("res_id", "in", jobcards.appointment_id.ids)]
        return action


class HrEmployeePublic(models.Model):
    """Users without HR rights (washers, front desk) read employees through this public copy:
    the roles must be there too so they can pick staff by role on job cards."""

    _inherit = "hr.employee.public"

    carwash_role_ids = fields.Many2many(
        "carwash.staff.role", "carwash_staff_role_employee_rel", "employee_id", "role_id",
        string="Car Wash Roles", readonly=True,
    )


class CarwashStaffCommission(models.Model):
    """Staff Payable earned by a staff member on a completed job card."""

    _name = "carwash.staff.commission"
    _description = "Car Wash Staff Payable"
    _order = "date desc, id desc"

    employee_id = fields.Many2one("hr.employee", string="Staff", required=True, index=True, ondelete="restrict")
    payable_role = fields.Selection(
        [("staff", "Staff"), ("qc", "QC")], string="For", default="staff", required=True, index=True,
        help="Staff: the crew who did the work (Assigned Staff). QC: the inspector who checked it.",
    )
    jobcard_id = fields.Many2one("carwash.jobcard", string="Job Card", required=True, index=True, ondelete="cascade")
    appointment_id = fields.Many2one(related="jobcard_id.appointment_id", store=True, string="Booking")
    customer_id = fields.Many2one(related="jobcard_id.customer_id", store=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    commission_type = fields.Selection(COMMISSION_TYPES[1:], string="Type", required=True)
    base_amount = fields.Monetary(string="Service Value (share)", help="This staff member's share of the booking's service value.")
    rate = fields.Float(string="Rate (%)")
    amount = fields.Monetary(required=True, string="Staff Payable")
    state = fields.Selection(
        [("to_pay", "To Pay"), ("paid", "Paid"), ("cancelled", "Cancelled")], default="to_pay", required=True, index=True
    )
    paid_date = fields.Date(readonly=True)
    bill_id = fields.Many2one(
        "account.move", string="Staff Bill", readonly=True, copy=False, index="btree_not_null",
        help="The staff member's bill for this amount (Create Bill, or Pay). Paid -> the staff payable is Paid.",
    )
    bill_payment_state = fields.Selection(related="bill_id.payment_state", string="Bill Payment")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    # the staff member's side of it (My Earnings): what they still receive, and what they received
    earning_state = fields.Selection(
        [("to_receive", "To Receive"), ("received", "Received"), ("cancelled", "Cancelled")],
        string="Earning Status", compute="_compute_earning_state", store=True, index=True,
    )

    @api.depends("state")
    def _compute_earning_state(self):
        earning = {"to_pay": "to_receive", "paid": "received", "cancelled": "cancelled"}
        for commission in self:
            commission.earning_state = earning.get(commission.state, "to_receive")

    @api.depends("employee_id", "jobcard_id")
    def _compute_display_name(self):
        for commission in self:
            role = " (QC)" if commission.payable_role == "qc" else ""
            commission.display_name = f"{commission.jobcard_id.name or ''} - {commission.employee_id.name or ''}{role}"

    @api.onchange("employee_id")
    def _onchange_employee_commission_rule(self):
        """Start from the staff member's own staff payable rule (their setting, or their role's)."""
        for commission in self.filtered("employee_id"):
            commission_type, rate, fixed = commission.employee_id._carwash_commission_rule()
            if commission_type == "percent":
                commission.update({"commission_type": "percent", "rate": rate})
            elif commission_type == "fixed":
                commission.update({"commission_type": "fixed", "rate": 0.0, "amount": fixed})

    @api.onchange("jobcard_id")
    def _onchange_jobcard_base_amount(self):
        """The service value a % staff payable is on: this staff member's share of the job card's services."""
        for commission in self:
            jobcard = commission.jobcard_id.sudo()
            staff_count = len(jobcard.assigned_employee_ids) or 1
            commission.base_amount = jobcard._commission_base_amount() / staff_count if jobcard else 0.0

    @api.onchange("commission_type", "rate", "base_amount")
    def _onchange_percent_amount(self):
        """% of Service Value: the staff payable is calculated, nothing to type in rupees."""
        for commission in self.filtered(lambda c: c.commission_type == "percent"):
            currency = commission.currency_id or self.env.company.currency_id
            commission.amount = currency.round(commission.base_amount * commission.rate / 100.0)

    # ------------------------------------------------------------------ bill + payment (like a customer invoice)
    def _carwash_check_payable(self):
        if self.filtered(lambda c: c.state == "cancelled"):
            raise UserError(self.env._("Cancelled staff payables can't be paid."))

    def _carwash_create_bills(self):
        """A validated bill per staff member (and branch) for the payables to pay that have no bill yet."""
        product = self.env.ref("carwash_jobcard.product_staff_payable")
        today = fields.Date.context_today(self)
        groups = {}
        for payable in self.filtered(lambda c: c.state == "to_pay" and not (c.bill_id and c.bill_id.state != "cancel")):
            groups.setdefault((payable.employee_id, payable.company_id), self.browse())
            groups[(payable.employee_id, payable.company_id)] |= payable
        for (employee, company), payables in groups.items():
            employee = employee.sudo()
            partner = employee.work_contact_id or employee.user_id.partner_id
            if not partner:
                raise UserError(self.env._(
                    "%s has no contact to make the staff bill for - link the employee to a user first.", employee.name))
            # sudo: paying the staff is a car wash manager's job, without Accounting rights
            bill = self.env["account.move"].sudo().with_company(company).create({
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "invoice_date": today,
                "ref": self.env._("Staff payable: %s", ", ".join(payables.mapped("jobcard_id.name"))),
                "invoice_line_ids": [Command.create({
                    "product_id": product.id,
                    "name": f"{payable.jobcard_id.name} / {payable.appointment_id.name} - {employee.name}",
                    "quantity": 1,
                    "price_unit": payable.amount,
                    "tax_ids": [Command.clear()],
                }) for payable in payables],
            })
            bill.action_post()
            payables.sudo().write({"bill_id": bill.id})
            for booking in payables.appointment_id:
                booking.message_post(body=self.env._(
                    "Staff bill %(bill)s created for %(staff)s (%(amount)s).", bill=bill.name, staff=employee.name,
                    amount=f"{bill.currency_id.symbol or ''}{bill.amount_total:.2f}",
                ))

    def action_create_bill(self):
        """Create Bill: the staff member's bill for this amount, validated - paid later with Pay."""
        self._carwash_check_payable()
        if not self.filtered(lambda c: c.state == "to_pay"):
            raise UserError(self.env._("There is nothing to bill: these staff payables are already paid."))
        self._carwash_create_bills()
        return True

    def action_pay(self):
        """Pay: the bill is created first when there's none yet, then Odoo's Register Payment opens (Cash by
        default). Once the payment is registered the staff payable is Paid."""
        self._carwash_check_payable()
        to_pay = self.filtered(lambda c: c.state == "to_pay")
        if not to_pay:
            raise UserError(self.env._("These staff payables are already paid."))
        to_pay._carwash_create_bills()
        bills = to_pay.bill_id.filtered(lambda m: m.state == "posted" and m.payment_state not in ("paid", "in_payment"))
        if not bills:
            to_pay._carwash_sync_paid()
            return True
        action = bills.action_register_payment()
        journal = self.env["carwash.appointment"]._carwash_cash_journal(to_pay[:1].company_id)
        action["context"] = dict(action.get("context", {}), default_journal_id=journal.id)
        return action

    def _carwash_sync_paid(self):
        """Staff payables whose bill is paid become Paid (after Register Payment, from here or from the bill)."""
        today = fields.Date.context_today(self)
        paid = self.filtered(lambda c: c.state == "to_pay" and c.bill_id.payment_state in ("paid", "in_payment"))
        if not paid:
            return
        paid.sudo().write({"state": "paid", "paid_date": today})
        for booking in paid.appointment_id:
            mine = paid.filtered(lambda c: c.appointment_id == booking)
            booking.message_post(body=self.env._(
                "Staff paid: %s", ", ".join(
                    f"{c.employee_id.name}{' (QC)' if c.payable_role == 'qc' else ''} "
                    f"{c.currency_id.symbol or ''}{c.amount:.2f} ({c.bill_id.name})" for c in mine),
            ))

    def action_mark_paid(self):
        """Pay at once, without the payment window: bill + payment from Cash (used by code / automations)."""
        self._carwash_check_payable()
        to_pay = self.filtered(lambda c: c.state == "to_pay")
        to_pay._carwash_create_bills()
        today = fields.Date.context_today(self)
        for company in to_pay.company_id:
            bills = to_pay.filtered(lambda c: c.company_id == company).bill_id.filtered(
                lambda m: m.state == "posted" and m.payment_state not in ("paid", "in_payment"))
            if bills:
                self.env["account.payment.register"].sudo().with_company(company).with_context(
                    active_model="account.move", active_ids=bills.ids,
                ).create({
                    "journal_id": self.env["carwash.appointment"]._carwash_cash_journal(company).id,
                    "payment_date": today,
                })._create_payments()
        to_pay._carwash_sync_paid()
        return True

    def action_reset_to_pay(self):
        paid_by_bill = self.filtered(lambda c: c.bill_id and c.bill_id.state != "cancel")
        if paid_by_bill:
            raise UserError(self.env._(
                "%(payable)s has bill %(bill)s - cancel or refund that bill in Invoicing first.",
                payable=paid_by_bill[0].display_name, bill=paid_by_bill[0].bill_id.name,
            ))
        self.filtered(lambda c: c.state != "to_pay").write({"state": "to_pay", "paid_date": False, "bill_id": False})
        return True

    def action_view_bill(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.bill_id.id,
        }

    def action_cancel(self):
        billed = self.filtered(lambda c: c.state == "to_pay" and c.bill_id and c.bill_id.state != "cancel")
        if billed:
            raise UserError(self.env._(
                "%(payable)s has bill %(bill)s - cancel that bill in Invoicing first.",
                payable=billed[0].display_name, bill=billed[0].bill_id.name,
            ))
        self.filtered(lambda c: c.state == "to_pay").write({"state": "cancelled"})
        return True
