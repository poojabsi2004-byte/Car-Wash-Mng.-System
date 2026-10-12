from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestEmployeePublicRead(TransactionCase):
    """Front Desk / Washer / QC users only see employees' public profiles: reading an employee (a job card's
    crew, the dashboard...) must not touch HR-only fields such as a person's own pay."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.config.settings"].create({"group_carwash_individual_pay": True}).execute()
        cls.employee = cls.env["hr.employee"].create({
            "name": "Public Read Washer",
            "carwash_commission_type": "percent",
            "carwash_commission_rate": 7.0,
        })
        cls.front_desk = new_test_user(cls.env, login="cw_public_fd", groups="base.group_user,carwash_base.group_carwash_user")
        cls.qc = new_test_user(cls.env, login="cw_public_qc", groups="base.group_user,carwash_jobcard.group_carwash_qc")

    def test_non_hr_users_read_employees(self):
        for user in (self.front_desk, self.qc):
            employee = self.employee.with_user(user)
            self.assertEqual(employee.name, "Public Read Washer")
            employee.carwash_role_ids  # noqa: B018 - loads the employee's other fields too
            # the staff payable rule still uses the person's own pay
            self.assertEqual(employee._carwash_commission_rule(), ("percent", 7.0, 0.0))
