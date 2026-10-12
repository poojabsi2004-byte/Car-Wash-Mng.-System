import werkzeug

from odoo import http
from odoo.http import request
from odoo.tools.misc import get_lang


class CarwashMembershipAutoRenew(http.Controller):
    """The Auto Renew button of the 'membership ending soon' email. Opening the link only shows the
    membership and a Turn on Auto Renew button - auto-renewal is switched on when the customer presses
    it (email scanners open links on their own, and auto-renewal takes the payment automatically)."""

    def _carwash_membership(self, membership_id, token):
        membership = request.env["carwash.membership"].sudo().browse(membership_id).exists()
        if not membership or not membership._carwash_check_auto_renew_token(token):
            raise werkzeug.exceptions.NotFound()
        return membership

    def _carwash_render(self, membership, token, done=False):
        lang = membership.partner_id.lang or get_lang(request.env).code
        return request.env["ir.ui.view"].with_context(lang=lang)._render_template(
            "carwash_membership.carwash_auto_renew_page",
            {"membership": membership, "token": token, "done": done},
        )

    @http.route("/car-wash/membership/<int:membership_id>/auto-renew/<string:token>", type="http",
                auth="public", website=True, sitemap=False)
    def carwash_auto_renew(self, membership_id, token, **kwargs):
        return self._carwash_render(self._carwash_membership(membership_id, token), token)

    @http.route("/car-wash/membership/<int:membership_id>/auto-renew/<string:token>/confirm", type="http",
                auth="public", methods=["POST"], website=True, sitemap=False)
    def carwash_auto_renew_confirm(self, membership_id, token, **kwargs):
        membership = self._carwash_membership(membership_id, token)
        membership._carwash_turn_on_auto_renew(by_customer=True)
        return self._carwash_render(membership, token, done=True)
