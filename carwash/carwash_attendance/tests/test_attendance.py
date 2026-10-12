from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCarwashAttendance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.group_user").write(
            {"implied_ids": [(4, cls.env.ref("carwash_attendance.group_carwash_attendance").id)]}
        )
        cls.branch_a = cls.env["res.company"].create({"name": "Attendance Branch A"})
        cls.branch_b = cls.env["res.company"].create({"name": "Attendance Branch B"})
        cls.washer_role = cls.env.ref("carwash_jobcard.staff_role_washer")
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Attendance Manager",
                "login": "attendance_manager",
                "company_id": cls.branch_a.id,
                "company_ids": [(6, 0, (cls.branch_a | cls.branch_b).ids)],
                "group_ids": [(6, 0, [cls.env.ref("carwash_base.group_carwash_manager").id])],
            }
        )
        Employee = cls.env["hr.employee"]

        def staff(name, branch):
            # car wash staff are users first, then employees linked to them
            user = cls.env["res.users"].create({
                "name": name, "login": name.lower().replace(" ", "_"), "company_id": branch.id,
                "company_ids": [(6, 0, branch.ids)], "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            })
            return {"name": name, "user_id": user.id, "company_id": branch.id, "carwash_role_ids": [(6, 0, cls.washer_role.ids)]}

        cls.staff_a = Employee.create([staff(f"Branch A Washer {i}", cls.branch_a) for i in range(7)])
        cls.staff_b = Employee.create(staff("Branch B Washer", cls.branch_b))

    def test_manager_gets_attendance_rights(self):
        self.assertTrue(self.manager.has_group("hr_attendance.group_hr_attendance_user"))

    def test_branch_is_recorded_and_kept(self):
        employee = self.staff_a[0]
        attendance = self.env["hr.attendance"].create({"employee_id": employee.id})
        self.assertEqual(attendance.carwash_branch_id, self.branch_a)
        employee.company_id = self.branch_b  # moved to another branch later
        self.assertEqual(attendance.carwash_branch_id, self.branch_a, "past shifts stay at the branch they were worked")

    def test_check_in_out_from_employee(self):
        employee = self.staff_a[1].with_user(self.manager).with_company(self.branch_a)
        employee.action_carwash_check_in_out()
        self.assertEqual(employee.attendance_state, "checked_in")
        self.assertFalse(employee.last_attendance_id.check_out)
        employee.action_carwash_check_in_out()
        employee.invalidate_recordset(["attendance_state"])
        self.assertEqual(employee.attendance_state, "checked_out")
        self.assertTrue(employee.last_attendance_id.check_out)

    def test_dashboard_attendance_by_branch(self):
        Attendance = self.env["hr.attendance"]
        now = fields.Datetime.now()
        # six of branch A in (more than the five shown at once), one already left, branch B's washer in
        Attendance.create([{"employee_id": e.id, "check_in": now - timedelta(minutes=30 + i)} for i, e in enumerate(self.staff_a[:6])])
        Attendance.create({"employee_id": self.staff_a[6].id, "check_in": now - timedelta(hours=2), "check_out": now - timedelta(hours=1)})
        Attendance.create({"employee_id": self.staff_b.id, "check_in": now - timedelta(minutes=10)})

        data = self.env["carwash.dashboard"].with_user(self.manager).with_company(self.branch_a).get_dashboard_data()
        att = data["attendance"]
        self.assertEqual(att["counts"]["present"], 6)
        self.assertEqual(att["counts"]["checked_out"], 1)
        self.assertEqual(att["counts"]["absent"], 0)
        self.assertEqual(len(att["present"]), 6)
        self.assertNotIn("Branch B Washer", [p["name"] for p in att["present"]], "only the selected branch")
        self.assertEqual(att["present"][0]["name"], "Branch A Washer 5", "longest checked-in first")

        both = self.env["carwash.dashboard"].with_user(self.manager).with_context(
            allowed_company_ids=(self.branch_a | self.branch_b).ids
        ).get_dashboard_data()
        self.assertEqual(both["attendance"]["counts"]["present"], 7)

    def test_switched_off(self):
        self.env["res.config.settings"].create({"group_carwash_attendance": False}).execute()
        data = self.env["carwash.dashboard"].with_user(self.manager).with_company(self.branch_a).get_dashboard_data()
        self.assertNotIn("attendance", data)
        with self.assertRaises(UserError):
            self.staff_a[2].with_user(self.manager).with_company(self.branch_a).action_carwash_check_in_out()
