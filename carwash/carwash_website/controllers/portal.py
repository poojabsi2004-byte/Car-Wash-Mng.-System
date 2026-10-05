from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal as BaseCustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

# a customer may (un)apply their membership on a booking until the service starts
MEMBERSHIP_EDITABLE_STATES = ("draft", "confirmed", "arrived")


class CustomerPortal(BaseCustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "membership_count" in counters:
            values["membership_count"] = request.env["carwash.membership"].sudo().search_count(
                [("partner_id", "=", request.env.user.partner_id.id), ("state", "!=", "cancelled")]
            )
        if "booking_count" in counters:
            partner = request.env.user.partner_id
            values["booking_count"] = request.env["carwash.appointment"].search_count(
                [("customer_id", "=", partner.id)]
            )
        return values

    def _prepare_carwash_bookings_values(self, page=1):
        partner = request.env.user.partner_id
        Appointment = request.env["carwash.appointment"]
        domain = [("customer_id", "=", partner.id)]

        pager = portal_pager(
            url="/my/bookings",
            total=Appointment.search_count(domain),
            page=page,
            step=20,
        )
        appointments = Appointment.search(domain, order="appointment_date desc", limit=20, offset=pager["offset"])
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "appointments": appointments,
                "page_name": "booking",
                "pager": pager,
                "default_url": "/my/bookings",
                "membership": partner._carwash_get_usable_membership(),
            }
        )
        return values

    @http.route(["/my/bookings", "/my/bookings/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_bookings(self, page=1, **kwargs):
        return request.render("carwash_website.portal_my_bookings", self._prepare_carwash_bookings_values(page))

    @http.route(["/my/membership"], type="http", auth="user", website=True)
    def portal_my_membership(self, **kwargs):
        partner = request.env.user.partner_id
        memberships = request.env["carwash.membership"].sudo().search(
            [("partner_id", "=", partner.id), ("state", "!=", "cancelled")], order="id desc"
        )
        values = self._prepare_portal_layout_values()
        values.update({"memberships": memberships, "page_name": "membership", "message": kwargs.get("message")})
        return request.render("carwash_website.portal_my_membership", values)

    @http.route(["/my/bookings/<int:appointment_id>"], type="http", auth="user", website=True)
    def portal_booking_page(self, appointment_id, **kwargs):
        appointment_sudo = self._document_check_access("carwash.appointment", appointment_id)
        membership = request.env.user.partner_id._carwash_get_usable_membership()
        editable = appointment_sudo.state in MEMBERSHIP_EDITABLE_STATES
        preview = None
        if membership and editable and not appointment_sudo.membership_id:
            preview = membership._preview_member_total(
                [(line.product_id, line.price_unit, line.quantity) for line in appointment_sudo.line_ids]
            )
        values = self._get_page_view_values(
            appointment_sudo,
            None,
            {
                "page_name": "booking",
                "membership": membership,
                "membership_preview": preview,
                "can_apply_membership": bool(preview and preview["has_benefit"]),
                "can_remove_membership": bool(editable and appointment_sudo.membership_id),
                "message": kwargs.get("message"),
                "error": kwargs.get("error"),
            },
            False,
            False,
            **kwargs,
        )
        return request.render("carwash_website.portal_booking_page", values)

    @http.route(["/my/bookings/<int:appointment_id>/membership"], type="http", auth="user", website=True,
                methods=["POST"])
    def portal_booking_membership(self, appointment_id, apply=None, **kwargs):
        """Customer applies (apply=1) or removes (apply=0) their membership on their own booking."""
        try:
            appointment_sudo = self._document_check_access("carwash.appointment", appointment_id)
        except (AccessError, MissingError):
            return request.redirect("/my/bookings")
        url = f"/my/bookings/{appointment_sudo.id}"
        if appointment_sudo.state not in MEMBERSHIP_EDITABLE_STATES:
            return request.redirect(f"{url}?error=locked")
        if apply == "1" and not request.env.user.partner_id._carwash_get_usable_membership():
            return request.redirect(f"{url}?error=no_membership")
        try:
            with request.env.cr.savepoint():
                if apply == "1":
                    appointment_sudo.action_apply_membership()
                else:
                    appointment_sudo.action_remove_membership()
        except UserError:
            return request.redirect(f"{url}?error=no_benefit")
        return request.redirect(f"{url}?message={'applied' if apply == '1' else 'removed'}")
