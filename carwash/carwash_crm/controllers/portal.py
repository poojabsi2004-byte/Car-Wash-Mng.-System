from odoo import http
from odoo.http import request

from odoo.addons.carwash_website.controllers.portal import CustomerPortal


class CarwashCrmCustomerPortal(CustomerPortal):

    def _carwash_open_requests(self, partner):
        return request.env["crm.lead"].sudo().search(
            [
                ("partner_id", "=", partner.id),
                ("is_carwash_booking", "=", True),
                ("carwash_appointment_id", "=", False),
                ("active", "=", True),
            ],
            order="carwash_booking_date",
        )

    def _prepare_carwash_bookings_values(self, page=1):
        values = super()._prepare_carwash_bookings_values(page)
        values["booking_requests"] = self._carwash_open_requests(request.env.user.partner_id)
        values["request_message"] = request.params.get("request_message")
        return values

    @http.route(["/my/booking-requests/<int:lead_id>/membership"], type="http", auth="user", website=True,
                methods=["POST"])
    def portal_request_membership(self, lead_id, use_membership=None, **kwargs):
        """Customer switches their membership on/off for a request staff haven't confirmed yet."""
        partner = request.env.user.partner_id
        lead = self._carwash_open_requests(partner).filtered(lambda l: l.id == lead_id)
        if not lead:
            return request.redirect("/my/bookings")
        use = use_membership == "1" and bool(partner._carwash_get_usable_membership())
        lead.carwash_use_membership = use
        lead.expected_revenue = lead.carwash_member_amount
        lead.message_post(
            body=request.env._("Customer turned the membership %s for this request.", request.env._("on") if use else request.env._("off"))
        )
        return request.redirect(f"/my/bookings?request_message={'membership_on' if use else 'membership_off'}")
