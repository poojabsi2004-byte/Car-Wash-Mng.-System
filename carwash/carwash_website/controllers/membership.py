from odoo import http
from odoo.http import request


class CarwashMembershipController(http.Controller):

    def _published_plans(self):
        return request.env["carwash.membership.plan"].sudo().search([("website_published", "=", True)])

    @http.route("/car-wash/membership", type="http", auth="public", website=True, sitemap=True)
    def membership_plans(self, **kwargs):
        partner = request.env.user.partner_id
        is_public = request.env.user._is_public()
        memberships = request.env["carwash.membership"].sudo()
        if not is_public:
            memberships = memberships.search([("partner_id", "=", partner.id), ("state", "in", ("pending", "active"))])
        return request.render(
            "carwash_website.membership_plans_page",
            {
                "plans": self._published_plans(),
                "is_public": is_public,
                "active_membership": memberships.filtered(lambda m: m.state == "active")[:1],
                "pending_membership": memberships.filtered(lambda m: m.state == "pending")[:1],
            },
        )

    @http.route("/car-wash/membership/join", type="http", auth="user", website=True, methods=["POST"], sitemap=False)
    def membership_join(self, plan_id=None, **kwargs):
        try:
            plan = self._published_plans().filtered(lambda p: p.id == int(plan_id))
        except (TypeError, ValueError):
            plan = None
        if not plan:
            return request.redirect("/car-wash/membership")
        partner = request.env.user.partner_id
        Membership = request.env["carwash.membership"].sudo()
        if Membership.search_count([("partner_id", "=", partner.id), ("state", "=", "active")]):
            return request.redirect("/my/membership")
        pending = Membership.search([("partner_id", "=", partner.id), ("state", "=", "pending")])
        membership = pending.filtered(lambda m: m.plan_id == plan)[:1]
        (pending - membership).action_cancel()  # switched plans before paying
        if not membership:
            # re-joining a plan that lapsed reactivates the same membership (keeps its history)
            membership = Membership.search(
                [("partner_id", "=", partner.id), ("plan_id", "=", plan.id), ("state", "=", "expired")],
                order="id desc", limit=1,
            )
        if not membership:
            membership = Membership.create({"partner_id": partner.id, "plan_id": plan.id})
            membership.message_post(body=request.env._("Requested online - waiting for the customer's payment."))
        order = membership._get_or_create_billing_order()
        if order.state == "draft":
            order.with_context(tracking_disable=True).action_quotation_sent()
        return request.redirect(order.get_portal_url())

    def _own_membership(self, membership_id):
        return request.env["carwash.membership"].sudo().search(
            [("id", "=", membership_id), ("partner_id", "=", request.env.user.partner_id.id)]
        )

    @http.route("/my/membership/<int:membership_id>/renew", type="http", auth="user", website=True,
                methods=["POST"], sitemap=False)
    def membership_renew(self, membership_id, **kwargs):
        """Pay the next period now (active) or reactivate (expired): open the billing order to pay it."""
        membership = self._own_membership(membership_id)
        if not membership or membership.state not in ("active", "expired", "pending"):
            return request.redirect("/my/membership")
        order = membership._get_or_create_billing_order()
        if order.state == "draft":
            order.with_context(tracking_disable=True).action_quotation_sent()
        if membership.state == "expired" and not membership.auto_renew:
            membership.auto_renew = True
        membership.message_post(body=request.env._("Customer started a renewal payment online (%s).", order.name))
        return request.redirect(order.get_portal_url())

    @http.route("/my/membership/<int:membership_id>/auto-renew", type="http", auth="user", website=True,
                methods=["POST"], sitemap=False)
    def membership_auto_renew(self, membership_id, auto_renew=None, **kwargs):
        membership = self._own_membership(membership_id)
        if membership and membership.state in ("active", "pending") and membership.auto_renew != (auto_renew == "1"):
            membership.action_toggle_auto_renew()
            return request.redirect(f"/my/membership?message={'auto_renew_on' if membership.auto_renew else 'auto_renew_off'}")
        return request.redirect("/my/membership")
