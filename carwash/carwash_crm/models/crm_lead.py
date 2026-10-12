from odoo import api, fields, models
from odoo.exceptions import UserError


class CrmLead(models.Model):
    _name = "crm.lead"
    _inherit = ["crm.lead", "carwash.booking.slot.mixin"]
    _slot_datetime_field = "carwash_booking_date"
    _slot_bay_field = "carwash_bay_id"

    is_carwash_booking = fields.Boolean(string="Car Wash Booking", index=True)
    carwash_booking_date = fields.Datetime(string="Requested Date")
    carwash_package_id = fields.Many2one(
        "carwash.service.package", string="Package", help="The package's services are booked at the package price."
    )
    carwash_package_service_ids = fields.Many2many(
        "product.product", compute="_compute_carwash_package_service_ids", string="Package Services"
    )
    carwash_package_amount = fields.Float(related="carwash_package_id.total_price", string="Package Amount")
    carwash_package_saving = fields.Float(related="carwash_package_id.saving", string="Customer Saves")
    carwash_service_ids = fields.Many2many(
        "product.product",
        "crm_lead_carwash_service_rel",
        "lead_id",
        "product_id",
        string="Extra Services",
        domain=[("is_carwash_service", "=", True)],
        help="Services requested on top of the package (or on their own, without a package).",
    )
    carwash_vehicle_id = fields.Many2one(
        "carwash.vehicle", string="Vehicle", domain="[('customer_id', '=', partner_id)]"
    )
    carwash_partner_has_vehicle = fields.Boolean(
        compute="_compute_carwash_partner_has_vehicle",
        help="The customer already has a vehicle - otherwise (first booking) the vehicle is entered by its plate.",
    )
    carwash_license_plate = fields.Char(string="Licence Plate")
    carwash_vehicle_make = fields.Char(string="Make")
    carwash_vehicle_model = fields.Char(string="Model")
    carwash_vehicle_type_id = fields.Many2one(
        "carwash.vehicle.type", string="Vehicle Type", default=lambda self: self.env["carwash.vehicle.type"]._default_type(),
    )
    carwash_bay_id = fields.Many2one("carwash.bay", string="Preferred Bay", domain="[('company_id', '=', company_id)]")
    carwash_use_membership = fields.Boolean(
        string="Use Membership", help="Apply the customer's active membership (free covered services / member discount)."
    )
    carwash_membership_id = fields.Many2one(
        "carwash.membership", compute="_compute_carwash_membership_id", string="Active Membership"
    )
    carwash_membership_benefit = fields.Char(compute="_compute_carwash_membership_id", string="Membership Benefit")
    carwash_normal_amount = fields.Float(compute="_compute_carwash_member_amount", string="Normal Price")
    carwash_member_amount = fields.Float(compute="_compute_carwash_member_amount", string="Member Price")
    carwash_member_saving = fields.Float(compute="_compute_carwash_member_amount", string="Member Saving")
    carwash_appointment_id = fields.Many2one("carwash.appointment", string="Booking", readonly=True, copy=False)
    carwash_duration = fields.Float(compute="_compute_carwash_duration", string="Duration (hours)",
                                    help="Package + extra services - the length shown in the calendar.")
    carwash_appointment_state = fields.Selection(related="carwash_appointment_id.state", string="Booking Status")

    @api.depends("partner_id")
    def _compute_carwash_partner_has_vehicle(self):
        partners = self.partner_id
        counts = dict(self.env["carwash.vehicle"]._read_group(
            [("customer_id", "in", partners.ids)], ["customer_id"], ["__count"]
        )) if partners else {}
        for lead in self:
            lead.carwash_partner_has_vehicle = bool(counts.get(lead.partner_id))

    @api.depends("carwash_package_id", "carwash_service_ids")
    def _compute_carwash_duration(self):
        for lead in self:
            lead.carwash_duration = lead._slot_duration()

    def _slot_duration(self):
        extras = self._carwash_extra_services()
        return (self.carwash_package_id.duration + sum(extras.mapped("carwash_duration"))) or 0.5

    def _slot_extra_depends(self):
        return ["carwash_package_id", "carwash_service_ids"]

    @api.onchange("carwash_vehicle_id")
    def _onchange_carwash_vehicle_id(self):
        for lead in self.filtered("carwash_vehicle_id"):
            vehicle = lead.carwash_vehicle_id
            lead.carwash_license_plate = vehicle.license_plate
            lead.carwash_vehicle_make = vehicle.make
            lead.carwash_vehicle_model = vehicle.vehicle_model
            lead.carwash_vehicle_type_id = vehicle.vehicle_type_id

    @api.depends("partner_id")
    def _compute_carwash_membership_id(self):
        for lead in self:
            membership = lead.partner_id.sudo().carwash_active_membership_id
            lead.carwash_membership_id = membership
            lead.carwash_membership_benefit = membership.plan_id._benefit_summary() if membership else False

    @api.depends("is_carwash_booking", "carwash_package_id", "carwash_service_ids", "carwash_use_membership", "partner_id")
    def _compute_carwash_member_amount(self):
        for lead in self:
            lines = lead._carwash_price_lines() if lead.is_carwash_booking else []
            normal = round(sum(price * qty for _product, price, qty in lines), 2)
            membership = lead.partner_id._carwash_get_usable_membership() if lead.partner_id else False
            preview = membership._preview_member_total(lines) if membership and lead.carwash_use_membership and lines else None
            lead.carwash_normal_amount = normal
            lead.carwash_member_amount = preview["member"] if preview else normal
            lead.carwash_member_saving = preview["saving"] if preview else 0.0

    def _carwash_price_lines(self):
        """(product, price_unit, quantity) of the booking this request would create."""
        self.ensure_one()
        lines = []
        if self.carwash_package_id:
            Product = self.env["product.product"]
            lines = [
                (Product.browse(vals["product_id"]), vals["price_unit"], vals["quantity"])
                for vals in self.carwash_package_id._prepare_booking_line_vals()
            ]
        lines += [(service, service.list_price, 1.0) for service in self._carwash_extra_services()]
        return lines

    @api.onchange("partner_id")
    def _onchange_partner_carwash_membership(self):
        """A member's request uses their membership unless staff untick it."""
        for lead in self.filtered(lambda l: l.is_carwash_booking and not l.carwash_appointment_id):
            lead.carwash_use_membership = bool(lead.partner_id and lead.partner_id._carwash_get_usable_membership())

    @api.depends("carwash_package_id.line_ids.product_id")
    def _compute_carwash_package_service_ids(self):
        for lead in self:
            lead.carwash_package_service_ids = lead.carwash_package_id.line_ids.product_id

    def _carwash_extra_services(self):
        """Extra services that aren't already part of the package (compared by id: onchange
        values are new-record copies of the products)."""
        self.ensure_one()
        package_product_ids = set(self.carwash_package_id.line_ids.product_id.ids)
        return self.carwash_service_ids.filtered(lambda p: (p._origin.id or p.id) not in package_product_ids)

    def _carwash_expected_revenue(self):
        self.ensure_one()
        if self.carwash_member_saving:
            return self.carwash_member_amount
        return self.carwash_package_id.total_price + sum(self._carwash_extra_services().mapped("list_price"))

    @api.onchange("carwash_package_id", "carwash_service_ids", "carwash_use_membership")
    def _onchange_carwash_amounts(self):
        for lead in self.filtered("is_carwash_booking"):
            lead.expected_revenue = lead._carwash_expected_revenue()

    def _carwash_get_or_create_vehicle(self, partner, company):
        self.ensure_one()
        if self.carwash_vehicle_id:
            return self.carwash_vehicle_id
        plate = (self.carwash_license_plate or "").strip()
        if not plate:
            raise UserError(self.env._("Select the customer's vehicle or enter its licence plate."))
        Vehicle = self.env["carwash.vehicle"]
        vehicle = Vehicle.search([("license_plate", "=ilike", plate), ("customer_id", "=", partner.id)], limit=1)
        return vehicle or Vehicle.create(
            {
                "license_plate": plate,
                "customer_id": partner.id,
                "company_id": company.id,
                "make": self.carwash_vehicle_make or "",
                "vehicle_model": self.carwash_vehicle_model or "",
                "vehicle_type_id": (self.carwash_vehicle_type_id or Vehicle.vehicle_type_id._default_type()).id,
            }
        )

    def action_print_carwash_request(self):
        return self.env.ref("carwash_crm.action_report_carwash_booking_request").report_action(self, config=False)

    def action_confirm_carwash_booking(self):
        """Confirm the request: create + confirm the booking, mark the lead Won, link both."""
        self.ensure_one()
        if not self.is_carwash_booking:
            raise UserError(self.env._("This lead isn't a car wash booking request."))
        if self.carwash_appointment_id:
            raise UserError(self.env._("A booking (%s) was already created for this lead.", self.carwash_appointment_id.name))
        if not (self.carwash_service_ids or self.carwash_package_id):
            raise UserError(self.env._("Add a package or at least one requested service before confirming."))
        if not self.carwash_booking_date:
            raise UserError(self.env._("Set the requested date and time before confirming."))
        # a bay picked on the request must be free when the request is confirmed
        busy = self.env["carwash.appointment"]._carwash_bay_busy_reason(self.carwash_bay_id)
        if busy:
            raise UserError(self.env._(
                "%s Pick a free bay on the request, or clear Preferred Bay to have a free one assigned.", busy
            ))

        if not self.partner_id:
            # sudo: confirming a request must be able to register a brand-new customer even
            # for Front Desk users without the "Contact Creation" right; the contact is built
            # only from this lead's own name/email/phone.
            self.sudo()._handle_partner_assignment(create_missing=True)
        partner = self.partner_id
        company = self.company_id or self.env.company
        vehicle = self._carwash_get_or_create_vehicle(partner, company)

        Appointment = self.env["carwash.appointment"]
        extras = self._carwash_extra_services()
        duration = (self.carwash_package_id.duration + sum(extras.mapped("carwash_duration"))) or 0.5
        bay = self.carwash_bay_id or Appointment._carwash_find_free_bay(company, self.carwash_booking_date, duration)
        # the package's services are added right after creating the booking
        appointment = Appointment.with_context(carwash_services_pending=True).create(
            {
                "customer_id": partner.id,
                "vehicle_id": vehicle.id,
                "company_id": company.id,
                "appointment_date": self.carwash_booking_date,
                "bay_id": bay.id if bay else False,
                "lead_id": self.id,
                "line_ids": [(0, 0, {"product_id": service.id, "quantity": 1}) for service in extras],
            }
        ).with_context(carwash_services_pending=False)
        if self.carwash_package_id:
            appointment._apply_service_package(self.carwash_package_id)
        if self.carwash_use_membership:
            try:
                appointment.action_apply_membership()
            except UserError as error:
                appointment.message_post(body=self.env._("Membership not applied: %s", error.args[0]))
        appointment.action_confirm()

        self.write({"carwash_vehicle_id": vehicle.id, "carwash_appointment_id": appointment.id})
        # sudo: marking Won also updates CRM's lead-scoring statistics, which only Sales
        # users can access - Front Desk confirming a booking shouldn't need Sales rights.
        self.sudo().action_set_won()
        self.message_post(body=self.env._("Booking %s created and confirmed.", appointment._get_html_link()))
        appointment.message_post(body=self.env._("Created from lead %s.", self._get_html_link()))
        if not bay:
            appointment.message_post(body=self.env._("No bay was free at the requested time - assign one before arrival."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "carwash.appointment",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": appointment.id,
        }

    def action_view_carwash_booking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "carwash.appointment",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.carwash_appointment_id.id,
        }
