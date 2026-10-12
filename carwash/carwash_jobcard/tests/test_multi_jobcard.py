from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestMultiJobcard(TransactionCase):
    """A booking's services can be split over several job cards; each service is on one job card only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["carwash.checklist.template"].search([]).is_default = False  # no check-in gate in these tests
        customer = cls.env["res.partner"].create({"name": "Split Customer"})
        vehicle = cls.env["carwash.vehicle"].create({"license_plate": "SPLIT 1", "customer_id": customer.id})
        Product = cls.env["product.product"]
        cls.wash = Product.create({"name": "Split Wash", "type": "service", "is_carwash_service": True, "list_price": 300})
        cls.detail = Product.create({"name": "Split Detailing", "type": "service", "is_carwash_service": True, "list_price": 900})
        cls.booking = cls.env["carwash.appointment"].create({
            "customer_id": customer.id, "vehicle_id": vehicle.id, "bay_id": cls.env["carwash.bay"].create({"name": "Split Bay"}).id,
            "appointment_date": fields.Datetime.now() + timedelta(days=1),
            "line_ids": [(0, 0, {"product_id": cls.wash.id}), (0, 0, {"product_id": cls.detail.id})],
        })
        cls.booking.action_confirm()
        cls.wash_line = cls.booking.line_ids.filtered(lambda line: line.product_id == cls.wash)
        cls.detail_line = cls.booking.line_ids.filtered(lambda line: line.product_id == cls.detail)
        # a job card needs its staff and QC inspector before the work starts
        Employee = cls.env["hr.employee"]

        def staff(name, role, group):
            user = cls.env["res.users"].create({
                "name": name, "login": name.lower().replace(" ", "_"),
                "group_ids": [(4, cls.env.ref("base.group_user").id), (4, cls.env.ref(f"carwash_jobcard.{group}").id)],
            })
            employee = Employee.search([("user_id", "=", user.id)]) or Employee.create({"name": name, "user_id": user.id})
            employee.carwash_role_ids = cls.env.ref(f"carwash_jobcard.{role}")
            return employee
        cls.crew_washer = staff("Split Crew Washer", "staff_role_washer", "group_carwash_washer")
        cls.inspector = staff("Split Inspector", "staff_role_qc", "group_carwash_qc")

    def test_split_services_over_job_cards(self):
        Jobcard = self.env["carwash.jobcard"]
        first = Jobcard.create({"appointment_id": self.booking.id})
        self.assertEqual(first.service_line_ids, self.wash_line | self.detail_line, "the first job card covers every service")
        self.assertEqual(first._commission_base_amount(), 1200)

        second = Jobcard.create({"appointment_id": self.booking.id})
        self.assertFalse(second.service_line_ids, "a further job card starts empty")
        self.assertEqual(second.taken_service_line_ids, self.wash_line | self.detail_line, "nothing left to pick")
        with self.assertRaises(ValidationError):
            second.service_line_ids = self.detail_line

        # move the detailing to the second job card
        first.service_line_ids = self.wash_line
        self.assertEqual(second.taken_service_line_ids, self.wash_line, "the dropdown offers the detailing now")
        second.service_line_ids = self.detail_line
        self.assertEqual((self.wash_line.jobcard_id, self.detail_line.jobcard_id), (first, second))
        self.assertEqual((first._commission_base_amount(), second._commission_base_amount()), (300, 900),
                         "each crew earns on its own services")

        new = Jobcard.new({"appointment_id": self.booking.id})
        new._onchange_appointment_services()
        self.assertFalse(new.service_line_ids)

        second.action_cancel()
        self.assertFalse(self.detail_line.jobcard_id, "a cancelled job card frees its services")
        self.assertFalse(first.taken_service_line_ids)
        other_booking = self.env["carwash.appointment"].create({
            "customer_id": self.booking.customer_id.id, "vehicle_id": self.booking.vehicle_id.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=5), "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        with self.assertRaises(ValidationError):
            first.service_line_ids = self.wash_line | other_booking.line_ids  # not a service of this booking

    def test_start_service_covers_the_services_left(self):
        Jobcard = self.env["carwash.jobcard"]
        planned = Jobcard.create({"appointment_id": self.booking.id, "service_line_ids": [(6, 0, self.wash_line.ids)]})
        self.booking.action_arrive()
        self.booking.action_start_service()
        auto = self.booking.jobcard_ids - planned
        self.assertEqual(len(auto), 1, "Start Service adds a job card for the services no job card covers")
        self.assertEqual(auto.service_line_ids, self.detail_line)

    def test_add_service_row_in_the_form(self):
        """Services tab: Add a line, then pick the service from the booking's remaining services."""
        Jobcard = self.env["carwash.jobcard"]
        first = Jobcard.create({"appointment_id": self.booking.id, "service_line_ids": [(6, 0, self.wash_line.ids)]})
        self.assertEqual(first.jobcard_service_ids.appointment_line_id, self.wash_line)
        with Form(Jobcard) as form:
            form.appointment_id = self.booking
            form.assigned_employee_ids.add(self.crew_washer)
            form.qc_inspector_id = self.inspector
            self.assertEqual(len(form.jobcard_service_ids), 0, "a second job card starts empty")
            with form.jobcard_service_ids.new() as row:
                row.appointment_line_id = self.detail_line
        second = form.record
        self.assertEqual(second.service_line_ids, self.detail_line)
        self.assertEqual(second.jobcard_service_ids.product_id, self.detail)
        self.assertEqual(self.detail_line.display_name, "Split Detailing")
        with self.assertRaises(ValidationError):
            first.jobcard_service_ids = [(0, 0, {"appointment_line_id": self.detail_line.id})]

    def test_staff_finish_a_service_before_another_job_card(self):
        user = self.env["res.users"].create({"name": "Busy Washer", "login": "busy_washer"})
        washer = self.env["hr.employee"].create({
            "name": "Busy Washer", "user_id": user.id,
            "carwash_role_ids": [(6, 0, self.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        Jobcard = self.env["carwash.jobcard"]
        first = Jobcard.create({"appointment_id": self.booking.id, "service_line_ids": [(6, 0, self.wash_line.ids)],
                                "assigned_employee_ids": [(6, 0, washer.ids)], "qc_inspector_id": self.inspector.id})
        second = Jobcard.create({"appointment_id": self.booking.id, "service_line_ids": [(6, 0, self.detail_line.ids)],
                                 "assigned_employee_ids": [(6, 0, washer.ids)], "qc_inspector_id": self.inspector.id})
        self.booking.action_arrive()
        self.booking.action_start_service()
        self.assertEqual(self.booking.jobcard_ids, first | second, "every service already had a job card")
        first.jobcard_service_ids.action_start_line()
        with self.assertRaisesRegex(UserError, "Busy Washer is still working on Split Wash"):
            second.jobcard_service_ids.action_start_line()
        first.jobcard_service_ids.action_end_line()
        second.jobcard_service_ids.action_start_line()
        self.assertEqual(self.detail_line.service_state, "in_progress")

    def test_submit_qc_once_every_service_ended(self):
        """Submit for QC is offered (and accepted) only once every service of the job card is ended."""
        user = self.env["res.users"].create({"name": "QC Ready Washer", "login": "qc_ready_washer"})
        washer = self.env["hr.employee"].create({
            "name": "QC Ready Washer", "user_id": user.id,
            "carwash_role_ids": [(6, 0, self.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        qc_user = self.env["res.users"].create({"name": "QC Ready Inspector", "login": "qc_ready_inspector"})
        inspector = self.env["hr.employee"].create({
            "name": "QC Ready Inspector", "user_id": qc_user.id,
            "carwash_role_ids": [(6, 0, self.env.ref("carwash_jobcard.staff_role_qc").ids)],
        })
        Jobcard = self.env["carwash.jobcard"]
        crew = {"assigned_employee_ids": [(6, 0, washer.ids)], "qc_inspector_id": inspector.id}
        jobcard = Jobcard.create({"appointment_id": self.booking.id, **crew})
        empty = Jobcard.create({"appointment_id": self.booking.id, **crew})
        self.booking.action_arrive()
        self.booking.action_start_service()
        (jobcard | empty).action_start()
        self.assertFalse(jobcard.services_ended, "Submit for QC hidden: nothing ended yet")
        with self.assertRaisesRegex(UserError, r"still open: Split Wash \(Pending\), Split Detailing \(Pending\)"):
            jobcard.action_submit_qc()

        jobcard.jobcard_service_ids[0].action_start_line()
        jobcard.jobcard_service_ids[0].action_end_line()
        jobcard.jobcard_service_ids[1].action_start_line()
        self.assertFalse(jobcard.services_ended, "still hidden while Split Detailing runs")
        with self.assertRaisesRegex(UserError, r"still open: Split Detailing \(In Progress\)"):
            jobcard.action_submit_qc()

        jobcard.jobcard_service_ids[1].action_end_line()
        self.assertTrue(jobcard.services_ended, "every service ended: Submit for QC shows")
        jobcard.qc_inspector_id = False  # cleared after the start: someone has to check the work
        with self.assertRaisesRegex(UserError, "Assign the QC inspector"):
            jobcard.action_submit_qc()
        jobcard.qc_inspector_id = inspector
        jobcard.action_submit_qc()
        self.assertEqual(jobcard.stages, "qc")

        self.assertFalse(empty.services_ended, "a job card without services can't go to QC")
        with self.assertRaisesRegex(UserError, "has no services"):
            empty.action_submit_qc()

    def test_staff_and_qc_open_the_booking(self):
        """A washer and a QC inspector open their booking: its customer billing and staff payable figures come
        from invoices / bills they can't read, and are worked out with full rights."""
        Employee = self.env["hr.employee"]
        crew = {}
        for key, group, role in (("washer", "group_carwash_washer", "staff_role_washer"), ("qc", "group_carwash_qc", "staff_role_qc")):
            user = new_test_user(self.env, login=f"split_{key}", groups=f"base.group_user,carwash_jobcard.{group}")
            employee = Employee.search([("user_id", "=", user.id)]) or Employee.create({"name": f"Split {key}", "user_id": user.id})
            employee.carwash_role_ids = self.env.ref(f"carwash_jobcard.{role}")
            crew[key] = (user, employee)
        self.env["carwash.jobcard"].create({
            "appointment_id": self.booking.id,
            "assigned_employee_ids": [(6, 0, crew["washer"][1].ids)],
            "qc_inspector_id": crew["qc"][1].id,
        })
        for user, _employee in crew.values():
            booking = self.booking.with_user(user)
            fields_info = booking.get_views([(False, "form")])["models"]["carwash.appointment"]["fields"]
            spec = {
                name: {"fields": {"display_name": {}}} if info["type"] in ("many2one", "many2many", "one2many") else {}
                for name, info in fields_info.items()
            }
            values = booking.web_read(spec)[0]  # the booking form opens
            self.assertEqual(values["payment_state"], "quotation")

    def test_staff_and_qc_print_booking_and_job_card(self):
        """The washer and the QC inspector of a job card print its booking and job card - also when the booking
        has a service package (catalogue data they can read)."""
        package = self.env["carwash.service.package"].create({
            "name": "Split Package", "line_ids": [(0, 0, {"product_id": self.wash.id}), (0, 0, {"product_id": self.detail.id})],
        })
        self.booking._apply_service_package(package)
        self.assertEqual(self.booking.service_package_id, package)
        jobcard = self.env["carwash.jobcard"].create({
            "appointment_id": self.booking.id,
            "assigned_employee_ids": [(6, 0, self.crew_washer.ids)],
            "qc_inspector_id": self.inspector.id,
        })
        Report = self.env["ir.actions.report"]
        for user in (self.crew_washer.user_id, self.inspector.user_id):
            for xmlid, record in (("carwash_base.action_report_carwash_booking", self.booking),
                                  ("carwash_jobcard.action_report_carwash_jobcard", jobcard)):
                html, _kind = Report.with_user(user)._render_qweb_html(self.env.ref(xmlid).report_name, record.ids)
                self.assertIn("Split Package", html.decode(), f"{xmlid} printed by {user.name}")

    def test_start_service_with_another_vehicle_on_the_bay(self):
        """Bookings on a bay clash only by their booked times: another vehicle in service on the bay
        (booked for another time) doesn't block the start; a bay under maintenance does."""
        bay = self.booking.bay_id
        other = self.env["carwash.appointment"].create({
            "customer_id": self.booking.customer_id.id, "vehicle_id": self.booking.vehicle_id.id, "bay_id": bay.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=3), "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        other.action_confirm()
        (self.booking | other).action_arrive()  # the bay is free when both arrive
        other.action_start_service()
        self.assertEqual(bay.state, "occupied")
        self.booking.action_start_service()
        self.assertEqual((self.booking.state, other.state, bay.state), ("in_service", "in_service", "occupied"))

        later = self.env["carwash.appointment"].create({
            "customer_id": self.booking.customer_id.id, "vehicle_id": self.booking.vehicle_id.id, "bay_id": bay.id,
            "appointment_date": fields.Datetime.now() + timedelta(days=5), "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        later.action_confirm()
        later.action_arrive()
        bay.with_context(carwash_allow_bay_release=True).state = "maintenance"
        with self.assertRaisesRegex(UserError, "Bay Split Bay is under maintenance"):
            later.action_start_service()

    def test_consumption_tab(self):
        """Job card Consumption tab: filled in from the services' consumables, adjusted by the crew,
        and what the booking books out of stock."""
        Product = self.env["product.product"]
        shampoo, wax, cloth = Product.create([
            {"name": f"Split {name}", "type": "consu", "is_storable": True} for name in ("Shampoo", "Wax", "Cloth")
        ])
        self.wash.product_tmpl_id.carwash_material_line_ids = [(0, 0, {"product_id": shampoo.id, "quantity": 0.5})]
        self.detail.product_tmpl_id.carwash_material_line_ids = [(0, 0, {"product_id": wax.id, "quantity": 0.2})]

        def used(record):
            totals = {}
            for product, qty in record:
                totals[product] = round(totals.get(product, 0.0) + qty, 4)
            return totals

        jobcard = self.env["carwash.jobcard"].create({"appointment_id": self.booking.id})
        self.assertEqual(
            {(line.product_id, line.quantity, line.service_id) for line in jobcard.consumption_line_ids},
            {(shampoo, 0.5, self.wash), (wax, 0.2, self.detail)},
            "filled in from the services' consumables",
        )
        # the crew used more shampoo and a cloth
        jobcard.consumption_line_ids.filtered(lambda line: line.product_id == shampoo).quantity = 0.8
        jobcard.consumption_line_ids = [(0, 0, {"product_id": cloth.id, "quantity": 1})]
        self.assertEqual(used(self.booking._carwash_consumption_items()), {shampoo: 0.8, wax: 0.2, cloth: 1.0},
                         "the booking books out what the job card lists")
        jobcard.action_reload_consumption()
        self.assertEqual(used((l.product_id, l.quantity) for l in jobcard.consumption_line_ids), {shampoo: 0.5, wax: 0.2})

        # the tab follows the Services tab: a service taken off takes its consumables along
        jobcard.service_line_ids = self.wash_line
        self.assertEqual(used((l.product_id, l.quantity) for l in jobcard.consumption_line_ids), {shampoo: 0.5})
        self.assertEqual(used(self.booking._carwash_consumption_items()), {shampoo: 0.5, wax: 0.2},
                         "the detailing (on no job card now) counts its own consumables, once")
        second = self.env["carwash.jobcard"].create({"appointment_id": self.booking.id})
        second.service_line_ids = self.detail_line
        self.assertEqual(used((l.product_id, l.quantity) for l in second.consumption_line_ids), {wax: 0.2},
                         "a service added to a job card brings its consumables")
        self.assertEqual(used(self.booking._carwash_consumption_items()), {shampoo: 0.5, wax: 0.2})

        admin = self.env.ref("base.user_admin")
        Line = self.env["carwash.jobcard.consumption"].with_user(admin)
        # a cancelled job card's consumption is final
        second.action_cancel()
        with self.assertRaisesRegex(UserError, "is cancelled"):
            second.consumption_line_ids[:1].with_user(admin).quantity = 2
        with self.assertRaisesRegex(UserError, "is cancelled"):
            Line.create({"jobcard_id": second.id, "product_id": cloth.id, "quantity": 1})

        # a completed job card still takes consumption (Add a line) until the booking is completed
        jobcard.write({"stages": "done"})
        jobcard.consumption_line_ids[:1].with_user(admin).quantity = 0.6
        Line.create({"jobcard_id": jobcard.id, "product_id": cloth.id, "quantity": 2})
        self.assertFalse(any(jobcard.consumption_line_ids.mapped("booked_out")))

        # completing the booking books it all out of stock - then those lines are locked
        self.booking.write({"state": "done"})
        self.assertTrue(self.booking._create_consumption_moves())
        self.assertTrue(all(jobcard.consumption_line_ids.mapped("booked_out")))
        booked_line = jobcard.consumption_line_ids[:1].with_user(admin)
        with self.assertRaisesRegex(UserError, "already booked out"):
            booked_line.quantity = 2
        with self.assertRaisesRegex(UserError, "already booked out"):
            booked_line.unlink()
        with self.assertRaisesRegex(UserError, "already booked out"):
            jobcard.action_reload_consumption()

        # ... and a line added after that is booked out of stock right away
        before = self.booking.sudo().stock_move_ids
        extra = Line.create({"jobcard_id": jobcard.id, "product_id": wax.id, "quantity": 2})
        self.assertTrue(extra.booked_out)
        new_moves = self.booking.sudo().stock_move_ids - before
        self.assertEqual((new_moves.product_id, new_moves.product_uom_qty, new_moves.state), (wax, 2.0, "done"))

    def test_extra_consumption_charged_on_booking(self):
        """A consumable used on top of the services (Extra) is charged: its amount is added to the booking."""
        polish = self.env["product.product"].create(
            {"name": "Split Polish", "type": "consu", "is_storable": True, "list_price": 150})
        jobcard = self.env["carwash.jobcard"].create({"appointment_id": self.booking.id})
        total = self.booking.amount_total
        jobcard.consumption_line_ids = [(0, 0, {"product_id": polish.id, "quantity": 2, "is_extra": True})]
        extra = jobcard.consumption_line_ids.filtered("is_extra")
        self.assertEqual((extra.price_unit, extra.amount, jobcard.consumption_extra_amount), (150, 300, 300))
        charge = extra.appointment_line_id
        self.assertEqual(charge.appointment_id, self.booking)
        self.assertEqual(charge.product_id, self.env.ref("carwash_jobcard.product_extra_consumables"))
        self.assertIn("Split Polish", charge.description)
        self.assertEqual(self.booking.amount_total, total + 300, "added to the booking total")
        self.assertNotIn(charge, self.booking._service_lines(), "nothing to perform: not a service")
        self.assertNotIn(charge, jobcard.service_line_ids)

        extra.quantity = 3
        self.assertEqual((charge.price_subtotal, self.booking.amount_total), (450, total + 450))
        with self.assertRaisesRegex(UserError, "Consumption tab"):
            charge.unlink()
        with self.assertRaisesRegex(UserError, "Consumption tab"):
            charge.price_unit = 10
        jobcard.action_reload_consumption()
        self.assertIn(extra, jobcard.consumption_line_ids, "reloading from the services keeps the extra lines")

        extra.is_extra = False
        self.assertFalse(charge.exists(), "not extra any more: not charged")
        self.assertEqual(self.booking.amount_total, total)
        extra.is_extra = True
        self.assertEqual(self.booking.amount_total, total + 450)
        extra.unlink()
        self.assertEqual(self.booking.amount_total, total)

    def test_service_starts_only_with_staff(self):
        """A job card's service can't start before its staff and QC inspector are assigned."""
        jobcard = self.env["carwash.jobcard"].create({"appointment_id": self.booking.id})
        self.booking.action_arrive()
        self.booking.action_start_service()
        with self.assertRaisesRegex(UserError, "Assign the staff and the QC inspector on job card"):
            jobcard.jobcard_service_ids[0].action_start_line()
        with self.assertRaisesRegex(UserError, "Assign the staff and the QC inspector on job card"):
            self.wash_line.action_start_line()
        user = self.env["res.users"].create({"name": "Staffed Washer", "login": "staffed_washer"})
        washer = self.env["hr.employee"].create({
            "name": "Staffed Washer", "user_id": user.id,
            "carwash_role_ids": [(6, 0, self.env.ref("carwash_jobcard.staff_role_washer").ids)],
        })
        jobcard.assigned_employee_ids = washer
        with self.assertRaisesRegex(UserError, "Assign the staff and the QC inspector on job card"):
            jobcard.jobcard_service_ids[0].action_start_line()
        jobcard.qc_inspector_id = self.inspector
        jobcard.jobcard_service_ids[0].action_start_line()
        self.assertEqual(jobcard.jobcard_service_ids[0].service_state, "in_progress")
