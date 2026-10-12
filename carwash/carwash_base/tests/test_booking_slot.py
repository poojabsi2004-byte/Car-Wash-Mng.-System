from datetime import date, datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBookingSlot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # these tests are about the features below - make sure they are switched on
        cls.env.ref("base.group_user").write({"implied_ids": [(4, cls.env.ref(x).id) for x in ['carwash_base.group_carwash_time_slot']]})
        cls.company = cls.env["res.company"].create({"name": "Slot Branch"})
        # standard 40h calendar: 08:00-12:00 and 13:00-17:00, Monday to Friday, branch time
        cls.company.resource_calendar_id.tz = "Asia/Kolkata"
        Bay = cls.env["carwash.bay"]
        cls.bay_a = Bay.create({"name": "Slot Bay A", "company_id": cls.company.id})
        cls.bay_b = Bay.create({"name": "Slot Bay B", "company_id": cls.company.id})
        cls.customer = cls.env["res.partner"].create({"name": "Slot Customer"})
        cls.vehicle = cls.env["carwash.vehicle"].create(
            {"license_plate": "SLOT-1", "customer_id": cls.customer.id, "company_id": cls.company.id}
        )
        cls.wash = cls.env["product.product"].create(
            {"name": "Slot Wash", "type": "service", "is_carwash_service": True, "list_price": 100, "carwash_duration": 1.0}
        )
        today = date.today() + timedelta(days=14)
        cls.monday = today + timedelta(days=(7 - today.weekday()) % 7)
        cls.Appointment = cls.env["carwash.appointment"].with_company(cls.company)

    def _booking(self, local_hour, bay=None):
        booking = self.Appointment.create(
            {
                "customer_id": self.customer.id,
                "vehicle_id": self.vehicle.id,
                "company_id": self.company.id,
                "bay_id": bay.id if bay else False,
                "appointment_date": self.Appointment._slot_utc(self.monday, local_hour),
                "line_ids": [(0, 0, {"product_id": self.wash.id})],
            }
        )
        booking.action_confirm()
        return booking

    def _hours(self, record):
        return sorted(record.available_slot_ids.mapped("hour"))

    def test_slot_follows_branch_timezone(self):
        booking = self._booking(9.0)
        self.assertEqual(booking.appointment_date, datetime.combine(self.monday, datetime.min.time()) + timedelta(hours=3, minutes=30),
                         "09:00 in India is 03:30 UTC")
        self.assertEqual(booking.booking_slot_date, self.monday)
        self.assertEqual(booking.booking_slot_id, self.env.ref("carwash_base.time_slot_0900"))
        self.assertEqual(booking.booking_time_mode, "slot")

    def test_free_slots_follow_working_hours_and_bookings(self):
        booking = self._booking(9.0, self.bay_a)
        hours = self._hours(booking)
        # a 1-hour service fits 08:00-11:00 and 13:00-16:00; lunch and after-hours aren't offered
        self.assertEqual(hours, [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5, 16.0])
        self._booking(9.0, self.bay_b)  # both bays now busy 09:00-10:00
        other = self.Appointment.new({"company_id": self.company.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        other.booking_slot_date = self.monday
        hours = self._hours(other)
        for busy in (8.5, 9.0, 9.5):
            self.assertNotIn(busy, hours, "overlaps the two 09:00 bookings")
        self.assertIn(8.0, hours)
        self.assertIn(10.0, hours)
        # the booking itself doesn't block its own slot
        self.assertIn(9.0, self._hours(booking))

    def test_custom_time_and_bay_switch(self):
        self._booking(9.0, self.bay_a)
        new = self.Appointment.new(
            {"company_id": self.company.id, "bay_id": self.bay_a.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]}
        )
        new.booking_slot_date = self.monday
        new.booking_time_mode = "custom"
        new.booking_custom_time = 9.25
        result = new._onchange_booking_slot()
        self.assertEqual(new.appointment_date, self.Appointment._slot_utc(self.monday, 9.25))
        self.assertEqual(new.bay_id, self.bay_b, "Bay A is busy at 09:15 - switched to the free bay")
        self.assertIn("Slot Bay B", result["warning"]["message"])
        self.assertIn("1 of 2 bays free", new.booking_slot_info)

        # a time set elsewhere (website, import) that isn't on a slot shows as a custom time
        odd = self._booking(10 + 10 / 60)
        self.assertEqual(odd.booking_time_mode, "custom")
        self.assertAlmostEqual(odd.booking_custom_time, 10 + 10 / 60, places=3)
        self.assertFalse(odd.booking_slot_id)

    def test_branch_without_bays_or_closed_day(self):
        sunday = self.monday + timedelta(days=6)
        new = self.Appointment.new({"company_id": self.company.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        new.booking_slot_date = sunday
        self.assertFalse(new.available_slot_ids)
        self.assertIn("No free time slot", new.booking_slot_info)

    def test_date_first_then_slot(self):
        """Picking the day before any time exists keeps the day, and the slot then sets the booking time."""
        new = self.Appointment.new({"company_id": self.company.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        new.booking_slot_date = self.monday
        self.assertTrue(new.available_slot_ids)  # reading the free slots mustn't reset the picked day
        self.assertEqual(new.booking_slot_date, self.monday)
        new.booking_slot_id = self.env.ref("carwash_base.time_slot_1330")
        new._onchange_booking_slot()
        self.assertEqual(new.appointment_date, self.Appointment._slot_utc(self.monday, 13.5))

    def test_configured_slots_drive_the_picker(self):
        Slot = self.env["carwash.time.slot"]
        self.env.ref("carwash_base.time_slot_0800").active = False
        extra = Slot.create({"hour": 8.25, "company_ids": [(6, 0, self.company.ids)]})
        self.assertEqual(extra.name, "08:15 AM")
        other_branch = self.env["res.company"].create({"name": "Other Branch"})
        Slot.create({"hour": 8.75, "company_ids": [(6, 0, other_branch.ids)]})

        new = self.Appointment.new({"company_id": self.company.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        new.booking_slot_date = self.monday
        hours = self._hours(new)
        self.assertNotIn(8.0, hours, "archived slots aren't offered")
        self.assertIn(8.25, hours, "a slot added in Configuration is offered")
        self.assertNotIn(8.75, hours, "another branch's own slot isn't offered here")

        # a booking at the new time maps back onto that slot
        booking = self._booking(8.25)
        self.assertEqual(booking.booking_slot_id, extra)
        self.assertEqual(booking.booking_time_mode, "slot")

        with self.assertRaises(ValidationError):
            Slot.create({"hour": 8.25, "company_ids": [(6, 0, self.company.ids)]})

    def test_slot_for_several_branches(self):
        Slot = self.env["carwash.time.slot"]
        branch_b, branch_c = self.env["res.company"].create([{"name": "Branch B"}, {"name": "Branch C"}])
        shared = Slot.create({"hour": 7.25, "company_ids": [(6, 0, (self.company | branch_b).ids)]})
        self.assertEqual(Slot._by_hour(self.company).get(7.25), shared)
        self.assertEqual(Slot._by_hour(branch_b).get(7.25), shared, "offered at every branch it's assigned to")
        self.assertNotIn(7.25, Slot._by_hour(branch_c), "not offered at other branches")
        self.assertIn(9.0, Slot._by_hour(branch_c), "slots without a branch are offered everywhere")
        # the same time can't be given twice to a branch, but another branch can have its own
        with self.assertRaises(ValidationError):
            Slot.create({"hour": 7.25, "company_ids": [(6, 0, branch_b.ids)]})
        own = Slot.create({"hour": 7.25, "company_ids": [(6, 0, branch_c.ids)]})
        self.assertEqual(Slot._by_hour(branch_c).get(7.25), own)
        with self.assertRaises(ValidationError):
            Slot.create({"hour": 9.0})  # every-branch 09:00 already exists

    def test_slot_field_search_and_quick_create(self):
        Slot = self.env["carwash.time.slot"]
        found = Slot.name_search("16:15")
        self.assertFalse(found, "no 16:15 slot yet")
        self.assertIn(self.env.ref("carwash_base.time_slot_1630").id, [r[0] for r in Slot.name_search("4:30 pm")],
                      "a slot is found by the time typed any way")

        # typing a new time in a booking's slot field creates it for that booking's branch
        slot_id, label = Slot.with_context(default_company_id=self.company.id).name_create("4:15 PM")
        slot = Slot.browse(slot_id)
        self.assertEqual((slot.hour, slot.company_ids, label), (16.25, self.company, "04:15 PM"))
        with self.assertRaises(UserError):
            Slot.name_create("teatime")

    def test_services_required(self):
        vals = {
            "customer_id": self.customer.id,
            "vehicle_id": self.vehicle.id,
            "company_id": self.company.id,
            "appointment_date": self.Appointment._slot_utc(self.monday, 10),
        }
        with self.assertRaisesRegex(ValidationError, "at least one service"):
            self.Appointment.create(vals)

        # services added right after creation (package from the website / a booking request)
        booking = self.Appointment.with_context(carwash_services_pending=True).create(vals)
        booking = booking.with_context(carwash_services_pending=False)
        with self.assertRaisesRegex(UserError, "at least one service"):
            booking.action_confirm()
        booking.line_ids = [(0, 0, {"product_id": self.wash.id})]
        booking.action_confirm()
        self.assertEqual(booking.state, "confirmed")
        with self.assertRaises(ValidationError, msg="a booking can't lose all its services"):
            booking.line_ids = [(5, 0, 0)]

    def test_bay_bookings_smart_button(self):
        first = self._booking(9, self.bay_a)
        second = self._booking(11, self.bay_a)
        self._booking(9, self.bay_b)
        self.assertEqual((self.bay_a.appointment_count, self.bay_b.appointment_count), (2, 1))
        action = self.bay_a.action_view_appointments()
        self.assertEqual(self.Appointment.search(action["domain"]), first | second)
        self.assertEqual(action["context"]["default_bay_id"], self.bay_a.id)

    def test_time_slot_am_pm(self):
        """A slot's start time is entered on the 12-hour clock with AM / PM picked by hand."""
        Slot = self.env["carwash.time.slot"]
        with Form(Slot, view="carwash_base.view_carwash_time_slot_form") as form:
            self.assertEqual((form.hour_12, form.meridiem), (9.0, "am"), "a new slot starts at 09:00 AM")
            form.hour_12 = 4.25
            form.meridiem = "pm"
        slot = form.record
        self.assertEqual((slot.hour, slot.name), (16.25, "04:15 PM"), "PM picked by hand is kept")

        # 12 o'clock: 12:15 AM is just after midnight, 12:15 PM just after noon
        midnight, noon = Slot.create([
            {"hour_12": 12.25, "meridiem": "am", "company_ids": [(6, 0, self.company.ids)]},
            {"hour_12": 12.25, "meridiem": "pm", "company_ids": [(6, 0, self.company.ids)]},
        ])
        self.assertEqual((midnight.hour, midnight.name, noon.hour, noon.name), (0.25, "12:15 AM", 12.25, "12:15 PM"))
        self.assertEqual((midnight.hour_12, midnight.meridiem, noon.hour_12, noon.meridiem), (12.25, "am", 12.25, "pm"))

        # changing one half keeps the other
        slot.meridiem = "am"
        self.assertEqual(slot.hour, 4.25)
        slot.hour_12 = 5.75
        self.assertEqual((slot.hour, slot.name), (5.75, "05:45 AM"))
        with self.assertRaises(ValidationError):
            slot.hour_12 = 13.5
        # the 24-hour start time still works (imports, data files)
        slot.hour = 23.75
        self.assertEqual((slot.hour_12, slot.meridiem, slot.name), (11.75, "pm", "11:45 PM"))

    def test_bay_checked_when_vehicle_arrives(self):
        """Bookings on a bay clash only when their booked times overlap: a vehicle in service on the
        bay doesn't stop the next booking from arriving; a bay under maintenance does."""
        holder = self._booking(9, self.bay_a)
        holder.write({"state": "in_service", "service_started_at": self.Appointment._slot_utc(self.monday, 13.9)})
        self.bay_a.with_context(carwash_bay_by_service=True).state = "occupied"

        waiting = self._booking(14, self.bay_a)  # its own time, though the 9:00 vehicle is still in service
        waiting.action_arrive()
        self.assertEqual(waiting.state, "arrived")
        with self.assertRaisesRegex(UserError, f"Bay Slot Bay A is already booked by booking {holder.name}"):
            self._booking(9.25, self.bay_a)  # overlaps the 9:00 booking's own time

        other = self._booking(11, self.bay_b)
        self.bay_b.action_set_maintenance()
        with self.assertRaisesRegex(UserError, "Bay Slot Bay B is under maintenance"):
            other.action_arrive()
        self.bay_b.action_set_free()
        other.action_arrive()
        self.assertEqual(other.state, "arrived")

        # cancelling a booking that never started leaves the bay to the vehicle on it
        self._booking(15, self.bay_a).action_cancel()
        self.assertEqual(self.bay_a.state, "occupied")

    def test_search_bookings(self):
        """Bookings are found by number, vehicle number / name, customer, time slot, bay, token and date."""
        self.vehicle.write({"make": "Toyota", "vehicle_model": "Corolla"})
        morning = self._booking(10.5, self.bay_a)
        evening = self._booking(16.5, self.bay_b)
        self.assertNotEqual(morning.token_no, evening.token_no)

        def find(domain):
            return self.Appointment.search(domain + [("id", "in", (morning | evening).ids)])

        # the time slot, typed any way or picked (local time of the branch)
        self.assertEqual(find([("booking_slot_id", "ilike", "10:30 AM")]), morning)
        self.assertEqual(find([("booking_slot_id", "ilike", "16:30")]), evening)
        self.assertEqual(find([("booking_slot_id", "ilike", "4:30 pm")]), evening)
        self.assertEqual(find([("booking_slot_id", "in", self.env.ref("carwash_base.time_slot_1030").ids)]), morning)
        self.assertFalse(find([("booking_slot_id", "ilike", "teatime")]))
        custom = self._booking(14.6)  # a custom time no slot has: 02:36 PM
        self.assertEqual(self.Appointment.search([("booking_slot_id", "ilike", "2:36 pm"), ("id", "=", custom.id)]), custom)
        self.assertEqual((morning.booking_slot_hour, evening.booking_slot_hour), (10.5, 16.5))

        # the search view's fields
        search_view = self.Appointment.get_views([(False, "search")])["views"]["search"]["arch"]
        for label in ("Vehicle Number", "Vehicle Name", "Customer", "Time Slot", "Token Number", "Booking Date"):
            self.assertIn(f'string="{label}"', search_view)
        self.assertEqual(find([("vehicle_id.license_plate", "ilike", "slot-1")]), morning | evening)
        self.assertEqual(find(["|", ("vehicle_id.make", "ilike", "toyota"), ("vehicle_id.vehicle_model", "ilike", "toyota")]),
                         morning | evening)
        self.assertEqual(find([("customer_id", "ilike", "Slot Customer")]), morning | evening)
        self.assertEqual(find([("bay_id", "ilike", "Slot Bay B")]), evening)
        self.assertEqual(find([("token_no", "=", evening.token_no)]), evening)
        self.assertEqual(find([("booking_slot_date", "=", self.monday)]), morning | evening)

    def test_branch_slots_and_branch_without_bays(self):
        """A slot set up for a branch is its own opening time (offered outside the calendar too); a branch without
        bays yet still gets its slots - the bay is given when the vehicle arrives."""
        Slot = self.env["carwash.time.slot"]
        Slot.create({"hour": 1.75, "company_ids": [(6, 0, self.company.ids)]})
        new = self.Appointment.new({"company_id": self.company.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        new.booking_slot_date = self.monday
        hours = self._hours(new)
        self.assertIn(1.75, hours, "the branch's own 01:45 AM slot is offered")
        self.assertNotIn(2.0, hours, "slots for every branch still follow the working hours")
        new.booking_slot_date = self.monday + timedelta(days=6)  # Sunday: closed
        self.assertEqual(self._hours(new), [1.75], "on a closed day only the branch's own slots")

        no_bays = self.env["res.company"].create({"name": "Slot Branch Without Bays"})
        no_bays.resource_calendar_id.tz = "Asia/Kolkata"
        other = self.env["carwash.appointment"].with_company(no_bays).new(
            {"company_id": no_bays.id, "line_ids": [(0, 0, {"product_id": self.wash.id})]})
        other.booking_slot_date = self.monday
        self.assertIn(9.0, self._hours(other), "a branch without bays yet gets its slots")
        self.assertIn("has no bays yet", other.booking_slot_info)

    def test_branch_numbering_and_tokens(self):
        """Each branch numbers its bookings on its own, with its code in front; tokens count per branch."""
        east = self.env["res.company"].create({"name": "Car Wash Branch 9"})
        self.assertEqual(east._carwash_branch_code(), "CWB9")
        first = self._booking(9.0)
        code = self.company.carwash_code
        self.assertTrue(code and first.name.startswith(f"{code}/"), first.name)
        Appointment = self.env["carwash.appointment"].with_company(east)
        vehicle = self.env["carwash.vehicle"].create(
            {"license_plate": "SLOT-EAST", "customer_id": self.customer.id, "company_id": east.id})
        other = Appointment.create({
            "customer_id": self.customer.id, "vehicle_id": vehicle.id, "company_id": east.id,
            "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        self.assertRegex(other.name, r"^CWB9/\d{2}/0001$", "the branch's own sequence starts at 1")
        self.assertEqual(other.token_no, 1, "the first token of the day at this branch")
        east.carwash_code = "EAST"
        again = Appointment.create({
            "customer_id": self.customer.id, "vehicle_id": vehicle.id, "company_id": east.id,
            "line_ids": [(0, 0, {"product_id": self.wash.id})],
        })
        self.assertRegex(again.name, r"^EAST/\d{2}/0002$", "a new code carries on the numbering")
        self.assertEqual(again.token_no, 2)
        with self.assertRaises(ValidationError):
            self.company.carwash_code = "east"  # already used
