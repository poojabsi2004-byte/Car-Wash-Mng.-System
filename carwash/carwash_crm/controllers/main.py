from odoo import http
from odoo.http import request

from odoo.addons.carwash_website.controllers.main import CarwashBookingController


class CarwashCrmBookingController(CarwashBookingController):

    def _carwash_finalize_booking(self, partner, vehicle, company, service, start, bay, package=None,
                                  use_membership=False):
        """Website requests become CRM leads; staff confirm them into bookings."""
        package = package or request.env["carwash.service.package"]
        team = request.env.ref("carwash_crm.crm_team_carwash_bookings", raise_if_not_found=False)
        extra = service - package.line_ids.product_id
        title = " + ".join(filter(None, [package.name, extra.name]))
        lead = request.env["crm.lead"].sudo().create(
            {
                "name": request.env._("Car Wash Booking: %(service)s - %(plate)s", service=title, plate=vehicle.license_plate),
                "type": "opportunity",
                "is_carwash_booking": True,
                "partner_id": partner.id,
                "email_from": partner.email,
                "phone": partner.phone,
                "company_id": company.id,
                "team_id": team.id if team else False,
                "user_id": False,
                "carwash_booking_date": start,
                "carwash_package_id": package.id or False,
                "carwash_use_membership": use_membership,
                "carwash_service_ids": [(6, 0, extra.ids)],
                "carwash_vehicle_id": vehicle.id,
                "carwash_license_plate": vehicle.license_plate,
                "carwash_vehicle_make": vehicle.make,
                "carwash_vehicle_model": vehicle.vehicle_model,
                "carwash_vehicle_type": vehicle.vehicle_type,
                "carwash_bay_id": bay.id if bay else False,
                "expected_revenue": package.total_price + sum(extra.mapped("list_price")),
                "description": request.env._("Requested online via the website booking page."),
            }
        )
        if use_membership:
            lead.expected_revenue = lead.carwash_member_amount
        return request.redirect(f"/car-wash/book/requested/{lead.id}")

    @http.route("/car-wash/book/requested/<int:lead_id>", type="http", auth="user", website=True, sitemap=False)
    def book_requested(self, lead_id, **kwargs):
        lead = request.env["crm.lead"].sudo().browse(lead_id)
        if not lead.exists() or not lead.is_carwash_booking or lead.partner_id != request.env.user.partner_id:
            return request.redirect("/car-wash/book")
        return request.render("carwash_crm.book_requested_page", {"lead": lead})
