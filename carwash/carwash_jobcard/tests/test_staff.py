from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestStaffRolesCommissionRating(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # these tests are about the features below - make sure they are switched on
        cls.env.ref("base.group_user").write({"implied_ids": [(4, cls.env.ref(x).id) for x in ['carwash_jobcard.group_carwash_commission', 'carwash_jobcard.group_carwash_rating', 'carwash_jobcard.group_carwash_individual_pay']]})
        cls.washer_role = cls.env.ref("carwash_jobcard.staff_role_washer")
        cls.detailer_role = cls.env.ref("carwash_jobcard.staff_role_detailer")
        cls.qc_role = cls.env.ref("carwash_jobcard.staff_role_qc")
        Employee = cls.env["hr.employee"]

        def staff(name, role):
            # staff are users first, then employees linked to them - found and assigned by their role
            user = cls.env["res.users"].create({"name": name, "login": name.lower().replace(" ", "_")})
            return Employee.create({"name": name, "user_id": user.id, "carwash_role_ids": [(6, 0, role.ids)]})

        cls.washer = staff("Role Washer", cls.washer_role)
        cls.detailer = staff("Role Detailer", cls.detailer_role)
        cls.inspector = staff("Role Inspector", cls.qc_role)
        cls.customer = cls.env["res.partner"].create({"name": "Rating Customer", "email": "rating.customer@example.com"})
        cls.vehicle = cls.env["carwash.vehicle"].create({"license_plate": "STAFF-1", "customer_id": cls.customer.id})
        cls.wash = cls.env["product.product"].create(
            {"name": "Staff Wash", "type": "service", "is_carwash_service": True, "list_price": 200}
        )
        # keep these tests about staff: no check-in / inspection checklists in the way
        cls.env["carwash.checklist.template"].search([]).is_default = False

    def _jobcard(self, staff, inspector=None):
        booking = self.env["carwash.appointment"].create(
            {
                "customer_id": self.customer.id,
                "vehicle_id": self.vehicle.id,
                "appointment_date": fields.Datetime.now() + timedelta(days=2),
                "line_ids": [(0, 0, {"product_id": self.wash.id})],
            }
        )
        booking.action_confirm()
        jobcard = self.env["carwash.jobcard"].create(
            {"appointment_id": booking.id, "assigned_employee_ids": [(6, 0, staff.ids)],
             "qc_inspector_id": (inspector or self.inspector).id}  # both needed to start the job card
        )
        jobcard.action_start()
        booking.line_ids.sudo().write({"service_state": "done"})  # the crew ended every service
        jobcard.checklist_line_ids.write({"is_check": True})  # ... and ticked every task
        jobcard.action_submit_qc()
        return jobcard

    def test_roles_filter_staff_and_job_card_choices(self):
        Employee = self.env["hr.employee"]
        self.assertIn(self.washer, Employee.search([("carwash_role_ids", "in", self.washer_role.ids)]))
        Jobcard = self.env["carwash.jobcard"]
        assignable = Employee.search([("carwash_can_do_jobs", "=", True)])
        self.assertIn(self.washer, assignable)
        self.assertIn(self.detailer, assignable)
        self.assertNotIn(self.inspector, assignable, "a QC-only role isn't put on the work itself")
        inspectors = Employee.search([("carwash_can_do_qc", "=", True)])
        self.assertIn(self.inspector, inspectors)
        self.assertNotIn(self.washer, inspectors)

    def test_non_hr_user_can_pick_staff_by_role(self):
        washer_user = self.env["res.users"].create(
            {"name": "Floor Washer", "login": "floor_washer",
             "group_ids": [(6, 0, [self.env.ref("carwash_jobcard.group_carwash_washer").id])]}
        )
        self.assertFalse(washer_user.has_group("hr.group_hr_user"))
        found = self.env["hr.employee"].with_user(washer_user).search([("carwash_role_ids.can_do_jobs", "=", True)])
        self.assertIn(self.washer.id, found.ids)

    def test_commission_on_qc_pass(self):
        jobcard = self._jobcard(self.washer | self.detailer, inspector=self.inspector)
        jobcard.action_qc_pass()
        self.assertEqual(jobcard.qc_inspector_id, self.inspector, "the assigned QC inspector is kept")
        by_employee = {c.employee_id: c for c in jobcard.commission_ids}
        # 200 of services shared by two: washer 5% of 100, detailer 10% of 100
        self.assertAlmostEqual(by_employee[self.washer].amount, 5.0)
        self.assertAlmostEqual(by_employee[self.detailer].amount, 10.0)
        self.assertNotIn(self.inspector, by_employee)
        self.assertAlmostEqual(self.detailer.carwash_commission_due, 10.0)

        by_employee[self.washer].action_mark_paid()
        self.assertEqual(by_employee[self.washer].state, "paid")
        self.assertAlmostEqual(self.washer.carwash_commission_due, 0.0)

    def test_employee_override_and_cancel(self):
        self.washer.write({"carwash_commission_type": "fixed", "carwash_commission_fixed": 50})
        jobcard = self._jobcard(self.washer)
        jobcard.action_qc_pass()
        self.assertAlmostEqual(jobcard.commission_ids.amount, 50.0, msg="the employee's own commission wins")

        other = self._jobcard(self.detailer)
        other.action_cancel()
        self.assertFalse(other.commission_ids, "cancelled jobs earn nothing")

    def test_rating_request_and_staff_rating(self):
        jobcard = self._jobcard(self.washer)
        jobcard.action_qc_pass()
        booking = jobcard.appointment_id
        booking.action_arrive()
        booking.state = "ready"
        booking.action_done()
        self.assertTrue(booking.rating_requested, "completing the booking emails 'your car wash is complete' + rating")
        rating = booking.rating_ids
        self.assertEqual(rating.partner_id, self.customer)
        self.assertEqual(rating.rated_partner_id, self.washer.work_contact_id)

        booking.rating_apply(5, token=rating.access_token, feedback="Spotless, thanks!")
        self.assertEqual(booking.rating_avg, 5)
        self.assertEqual(self.washer.carwash_rating_count, 1)
        self.assertEqual(self.washer.carwash_rating_avg, 5)

    def _done_booking(self):
        jobcard = self._jobcard(self.washer)
        jobcard.action_qc_pass()
        booking = jobcard.appointment_id
        booking.action_arrive()
        booking.state = "ready"
        booking.action_done()
        return booking

    def test_add_review_after_done(self):
        jobcard = self._jobcard(self.washer)
        booking = jobcard.appointment_id
        with self.assertRaises(UserError, msg="no review before the service is done"):
            booking._carwash_apply_review(5, "Too early")
        jobcard.action_qc_pass()
        booking.action_arrive()
        booking.state = "ready"
        booking.action_done()

        # front desk records the customer's review (Add Review)
        action = booking.action_add_review()
        wizard = self.env[action["res_model"]].with_context(action["context"]).create({"stars": "4", "feedback": "Good job"})
        wizard.action_save()
        review = booking.carwash_review_id
        self.assertEqual(review, booking.rating_ids, "the emailed rating request is reused: one rating per booking")
        self.assertTrue(review.consumed)
        self.assertEqual((review.rating, review.carwash_stars, review.feedback), (4, "4", "Good job"))
        self.assertEqual((review.carwash_booking_id, review.carwash_vehicle_id), (booking, self.vehicle))
        self.assertEqual(review.partner_id, self.customer)
        self.assertEqual(review.rated_partner_id, self.washer.work_contact_id)
        self.assertEqual((booking.carwash_review_stars, booking.carwash_review_feedback), ("4", "Good job"))
        self.assertEqual(self.washer.carwash_rating_avg, 4)

        # editing updates the same review, pre-filled with what was said
        action = booking.action_add_review()
        wizard = self.env[action["res_model"]].with_context(action["context"]).create({})
        self.assertEqual((wizard.stars, wizard.feedback), ("4", "Good job"))
        wizard.write({"stars": "2", "feedback": "Spots on the glass"})
        wizard.action_save()
        self.assertEqual(booking.rating_ids, review)
        self.assertEqual((review.carwash_stars, review.feedback), ("2", "Spots on the glass"))

        listed = self.env["rating.rating"].search(safe_eval(self.env.ref("carwash_jobcard.action_carwash_rating").domain))
        self.assertIn(review, listed, "listed in Configuration > Reviews & Ratings")
        with self.assertRaises(UserError):
            booking._carwash_apply_review(0)

    def test_emailed_rating_shows_as_stars(self):
        booking = self._done_booking()
        rating = booking.rating_ids
        booking.rating_apply(3, token=rating.access_token, feedback="OK")  # the email's "neutral" face
        self.assertEqual((booking.carwash_review_stars, rating.carwash_stars), ("3", "3"))
        booking._carwash_send_completion_mail()
        self.assertEqual(len(booking.rating_ids), 1, "no new rating request once the customer has reviewed")

    def test_qc_needs_qc_role_and_stage(self):
        """A washer can't approve their own work, and QC only applies to a job card waiting for it."""
        washer_user = self.env["res.users"].create({
            "name": "Fix Washer", "login": "fix_washer",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("carwash_jobcard.group_carwash_washer").id])],
        })
        self.washer.user_id = washer_user
        jobcard = self._jobcard(self.washer)
        with self.assertRaisesRegex(UserError, "role needed"):
            jobcard.with_user(washer_user).action_qc_pass()
        jobcard.action_qc_pass()
        with self.assertRaisesRegex(UserError, "can't pass quality control now"):
            jobcard.action_qc_pass()
        with self.assertRaisesRegex(ValidationError, "between 0 and 100"):
            self.washer.carwash_commission_rate = 150

    def _switch(self, **features):
        """Turn Car Wash > Configuration > Settings switches on/off like an admin would."""
        self.env["res.config.settings"].create(features).execute()

    def test_switched_off_features_do_nothing(self):
        Feature = self.env["carwash.feature"]
        self._switch(group_carwash_commission=False, group_carwash_rating=False)
        self.assertFalse(Feature._enabled("carwash_jobcard.group_carwash_commission"))
        self.assertFalse(self.env.user.has_group("carwash_jobcard.group_carwash_commission"),
                         "the Commission menus/fields are hidden")
        jobcard = self._jobcard(self.washer)
        jobcard.action_qc_pass()
        self.assertFalse(jobcard.commission_ids, "no commission while Staff Commission is off")
        booking = jobcard.appointment_id
        booking.action_arrive()
        booking.state = "ready"
        booking.action_done()
        self.assertTrue(booking.rating_requested, "the 'car wash complete' email still goes out")
        self.assertFalse(booking.rating_ids, "... without the rating / review links while Customer Ratings is off")
        with self.assertRaises(UserError, msg="no reviews while Customer Ratings is off"):
            booking._carwash_apply_review(5)

        self._switch(group_carwash_commission=True)
        self.assertTrue(Feature._enabled("carwash_jobcard.group_carwash_commission"))
        self.assertTrue(self.env.user.has_group("carwash_jobcard.group_carwash_commission"))

    def test_staff_need_a_user(self):
        Employee = self.env["hr.employee"]
        no_login = Employee.create({"name": "No Login"})
        with self.assertRaises(ValidationError):
            no_login.carwash_role_ids = self.washer_role
        Jobcard = self.env["carwash.jobcard"]
        self.assertNotIn(no_login, Employee.search([("carwash_can_do_jobs", "=", True)]))
        self.assertNotIn(no_login, Employee.search([("carwash_can_do_qc", "=", True)]))
        booking = self.env["carwash.appointment"].create({
            "customer_id": self.customer.id, "vehicle_id": self.vehicle.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=2), "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        with self.assertRaises(ValidationError):
            Jobcard.create({"appointment_id": booking.id, "assigned_employee_ids": [(6, 0, no_login.ids)]})
        with self.assertRaises(ValidationError):
            Jobcard.create({"appointment_id": booking.id, "assigned_employee_ids": [(6, 0, self.washer.ids)],
                            "qc_inspector_id": no_login.id})

    def test_new_staff_member_creates_user_then_employee(self):
        """New Staff Member is a user form: saving it creates the user, then the employee linked to it -
        also for a Car Wash Manager without Settings rights."""
        manager = self.env["res.users"].create({
            "name": "Staff Manager", "login": "staff_manager",
            "group_ids": [(6, 0, (self.env.ref("base.group_user") | self.env.ref("carwash_base.group_carwash_manager")).ids)],
        })
        self.assertFalse(manager.has_group("base.group_erp_manager"))
        Users = self.env["res.users"].with_user(manager)
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_staff_new")
        self.assertEqual(action["res_model"], "res.users")

        with Form(Users.with_context(safe_eval(action["context"])), view="carwash_jobcard.view_carwash_staff_user_form") as form:
            self.assertEqual((form.carwash_access, form.carwash_role_ids[:]), ("washer", self.washer_role))
            form.carwash_access = "qc"
            self.assertEqual(form.carwash_role_ids[:], self.qc_role, "the role follows the access")
            form.carwash_access = "washer"
            form.name = "New Washer"
            form.login = "new.washer@example.com"
            form.password = "Washer-2026!"
            form.phone = "+91 98765 43210"
        user = form.record.sudo()
        self.assertEqual(user.login, "new.washer@example.com")
        self.assertTrue(user.has_group("carwash_jobcard.group_carwash_washer"))
        self.assertEqual(user.company_ids, self.env.company)

        employee = self.env["hr.employee"].browse(form.record.action_carwash_open_staff()["res_id"])
        self.assertEqual(employee.user_id, user, "the employee is linked to the new user")
        self.assertEqual((employee.carwash_role_ids, employee.company_id, employee.mobile_phone),
                         (self.washer_role, self.env.company, "+91 98765 43210"))
        Jobcard = self.env["carwash.jobcard"]
        self.assertIn(employee, self.env["hr.employee"].search([("carwash_can_do_jobs", "=", True)]))

        staff_users = Users.with_context(carwash_new_staff=True)
        with self.assertRaisesRegex(UserError, "already exists"):
            staff_users.create({"name": "Again", "login": "new.washer@example.com"})
        # only the staff fields are taken: no other rights can be given through the form
        sneaky = staff_users.create({
            "name": "Sneaky", "login": "sneaky@example.com", "carwash_access": "front_desk",
            "group_ids": [(4, self.env.ref("base.group_system").id)],
        }).sudo()
        self.assertFalse(sneaky.has_group("base.group_system"))
        self.assertTrue(sneaky.has_group("carwash_base.group_carwash_user"))
        self.assertEqual(sneaky.employee_ids.carwash_role_ids, self.env.ref("carwash_jobcard.staff_role_front_desk"))
        # outside New Staff Member, creating users still needs Settings rights
        with self.assertRaises(AccessError):
            Users.create({"name": "Plain", "login": "plain@example.com"})
        washer_user = self.washer.user_id
        with self.assertRaisesRegex(UserError, "Only a Car Wash Manager"):
            self.env["res.users"].with_user(washer_user).with_context(carwash_new_staff=True).create(
                {"name": "Nope", "login": "nope@example.com"})
