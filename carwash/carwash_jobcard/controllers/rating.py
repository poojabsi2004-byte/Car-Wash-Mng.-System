import werkzeug

from odoo import http
from odoo.http import request
from odoo.tools.misc import get_lang

from ..models.carwash_rating import CARWASH_STARS


class CarwashRating(http.Controller):
    """The star links of the 'your car wash is complete' email: rate the booking 1-5 stars and
    write a review. Opening a link only pre-selects the stars - the review is saved when the
    customer sends the form (email scanners open links on their own)."""

    def _carwash_rating_and_booking(self, token):
        rating = request.env["rating.rating"].sudo().search(
            [("access_token", "=", token), ("res_model", "=", "carwash.appointment")], limit=1
        )
        booking = request.env["carwash.appointment"].sudo().browse(rating.res_id).exists() if rating else None
        if not booking or not booking._carwash_rating_enabled():
            raise werkzeug.exceptions.NotFound()
        return rating, booking

    def _carwash_other_customer_page(self, rating, booking):
        """A logged-in user who isn't the customer can't rate their booking (as Odoo's rating page)."""
        user = request.env.user
        if user._is_public() or user.partner_id.commercial_partner_id == rating.partner_id.commercial_partner_id:
            return None
        return request.render("rating.rating_external_page_invalid_partner", {
            "model_name": request.env["ir.model"]._get(rating.res_model).display_name,
            "name": booking.display_name,
            "web_base_url": rating.get_base_url(),
        })

    @http.route("/car-wash/rate/<string:token>/<int:stars>", type="http", auth="public", website=True, sitemap=False)
    def carwash_rate(self, token, stars, **kwargs):
        rating, booking = self._carwash_rating_and_booking(token)
        other = self._carwash_other_customer_page(rating, booking)
        if other:
            return other
        lang = rating.partner_id.lang or get_lang(request.env).code
        return request.env["ir.ui.view"].with_context(lang=lang)._render_template("carwash_jobcard.carwash_rating_page", {
            "rating": rating,
            "booking": booking,
            "token": token,
            "stars": stars if 1 <= stars <= 5 else int(rating.rating) or 5,
            "star_labels": dict(CARWASH_STARS),
            "error": kwargs.get("error"),
        })

    @http.route("/car-wash/rate/<string:token>/submit", type="http", auth="public", methods=["POST"],
                website=True, sitemap=False)
    def carwash_rate_submit(self, token, stars=None, feedback=None, **kwargs):
        rating, booking = self._carwash_rating_and_booking(token)
        other = self._carwash_other_customer_page(rating, booking)
        if other:
            return other
        try:
            stars = int(stars or 0)
        except ValueError:
            stars = 0
        if not 1 <= stars <= 5:
            return request.redirect(f"/car-wash/rate/{token}/0?error=stars")
        booking.rating_apply(stars, rating=rating, feedback=(feedback or "").strip()[:2000] or False)
        lang = rating.partner_id.lang or get_lang(request.env).code
        return request.env["ir.ui.view"].with_context(lang=lang)._render_template("rating.rating_external_page_view", {
            "web_base_url": rating.get_base_url(),
            "rating": rating,
        })
