from odoo import api, fields, models
from odoo.exceptions import UserError

# 1-5 stars, stored on Odoo's rating.rating (rating 0-5). The rating email's happy / neutral /
# unhappy answers are 5 / 3 / 1, so both flows land on the same scale.
CARWASH_STARS = [
    ("0", "Not rated"),
    ("1", "Very poor"),
    ("2", "Poor"),
    ("3", "Average"),
    ("4", "Good"),
    ("5", "Excellent"),
]


class CarwashAppointment(models.Model):
    """Customer reviews with Odoo's standard ratings: once the booking is done the customer gets
    one email - the wash is complete, with 1-5 star links and a review box - and rates it there,
    from My Bookings on the website, or the front desk records it with Add Review."""

    _name = "carwash.appointment"
    # rating.mixin extends mail.thread, so it must come first (as Odoo does in im_livechat)
    _inherit = ["rating.mixin", "carwash.appointment"]

    rating_requested = fields.Boolean(
        string="Completion Email Sent", readonly=True, copy=False,
        help="The 'your car wash is complete' email (with the rating / review links) was sent to the customer.",
    )
    carwash_review_id = fields.Many2one("rating.rating", string="Customer Review",
                                        compute="_compute_carwash_review", compute_sudo=True)
    carwash_review_stars = fields.Selection(CARWASH_STARS, string="Rating",
                                            compute="_compute_carwash_review", compute_sudo=True)
    carwash_review_feedback = fields.Text(string="Review", compute="_compute_carwash_review", compute_sudo=True)

    @api.depends("rating_ids.rating", "rating_ids.consumed", "rating_ids.feedback")
    def _compute_carwash_review(self):
        for booking in self:
            review = booking._carwash_review()
            booking.carwash_review_id = review
            booking.carwash_review_stars = review.carwash_stars if review else False
            booking.carwash_review_feedback = review.feedback

    def _carwash_review(self):
        """The customer's submitted rating of this booking (the latest one)."""
        self.ensure_one()
        reviews = self.sudo().rating_ids.filtered(lambda r: r.consumed and r.rating >= 1)
        return reviews.sorted(lambda r: (r.write_date, r.id), reverse=True)[:1]

    def _rating_get_partner(self):
        return self.customer_id

    def _rating_get_operator(self):
        """The staff member being rated: the first one who worked on the booking."""
        return self.jobcard_ids.assigned_employee_ids[:1].work_contact_id

    def _carwash_rating_enabled(self):
        return self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_rating")

    def _carwash_ask_review(self):
        """The completion email carries the star / review links: Customer Ratings on, not reviewed yet."""
        self.ensure_one()
        return self._carwash_rating_enabled() and not self._carwash_review()

    def _carwash_send_completion_mail(self):
        """One email when the booking is done: the wash is complete (vehicle, services, total) and -
        with Customer Ratings on - rate it 1-5 stars and write a review."""
        template = self.env.ref("carwash_jobcard.mail_template_booking_completed", raise_if_not_found=False)
        if not template:
            return
        bookings = self.filtered(lambda b: b.customer_id.email)
        for booking in bookings:
            # posted on the booking as a note, emailed to the customer only; the star links carry
            # the booking's rating token (created by the template when it asks for a review)
            booking.rating_send_request(template, lang=booking.customer_id.lang, force_send=False)
            booking.rating_requested = True
        if bookings:
            self.env["carwash.mail"]._wake_mail_queue()

    def _carwash_apply_review(self, stars, feedback=None):
        """Record (or update) the customer's review of a completed booking on rating.rating -
        used by Add Review in the backend and by the review form in My Bookings."""
        self.ensure_one()
        if not self.env["carwash.feature"]._enabled("carwash_jobcard.group_carwash_rating"):
            raise UserError(self.env._("Customer Ratings are switched off in the Car Wash settings."))
        if self.state != "done":
            raise UserError(self.env._("A booking can be reviewed once its service is done."))
        stars = int(stars)
        if not 1 <= stars <= 5:
            raise UserError(self.env._("Choose a rating from 1 to 5 stars."))
        rating = self._carwash_review()
        if not rating:
            token = self.sudo()._rating_get_access_token(self.customer_id)
            rating = self.env["rating.rating"].sudo().search([("access_token", "=", token)], limit=1)
        return self.rating_apply(stars, rating=rating.sudo(), feedback=(feedback or "").strip() or False)

    def action_done(self):
        res = super().action_done()
        self.filtered(lambda b: not b.rating_requested)._carwash_send_completion_mail()
        return res

    def action_add_review(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Customer Review"),
            "res_model": "carwash.review.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_appointment_id": self.id},
        }

    def action_view_ratings(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_jobcard.action_carwash_rating")
        action["domain"] = [("res_model", "=", self._name), ("res_id", "=", self.id), ("consumed", "=", True)]
        return action


class RatingRating(models.Model):
    _inherit = "rating.rating"

    carwash_stars = fields.Selection(CARWASH_STARS, string="Stars", compute="_compute_carwash_stars", store=True)
    carwash_booking_id = fields.Many2one("carwash.appointment", string="Booking",
                                         compute="_compute_carwash_booking", store=True, index="btree_not_null")
    carwash_company_id = fields.Many2one("res.company", string="Branch",
                                         related="carwash_booking_id.company_id", store=True)
    carwash_vehicle_id = fields.Many2one("carwash.vehicle", string="Vehicle",
                                         related="carwash_booking_id.vehicle_id", store=True)

    @api.depends("rating")
    def _compute_carwash_stars(self):
        for rating in self:
            rating.carwash_stars = str(max(0, min(5, round(rating.rating))))

    @api.depends("res_model", "res_id")
    def _compute_carwash_booking(self):
        for rating in self:
            is_booking = rating.res_model == "carwash.appointment" and rating.res_id
            rating.carwash_booking_id = rating.res_id if is_booking else False


class CarwashReviewWizard(models.TransientModel):
    _name = "carwash.review.wizard"
    _description = "Car Wash Customer Review"

    appointment_id = fields.Many2one("carwash.appointment", string="Booking", required=True, readonly=True)
    customer_id = fields.Many2one(related="appointment_id.customer_id")
    # the full list (with "0") so the priority widget shows 5 clickable stars
    stars = fields.Selection(CARWASH_STARS, string="Rating", required=True, default="5")
    feedback = fields.Text(string="Review")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        booking = self.env["carwash.appointment"].browse(values.get("appointment_id"))
        review = booking._carwash_review() if booking else False
        if review:
            # editing an existing review: start from what the customer said
            values.update(stars=review.carwash_stars, feedback=review.feedback)
        return values

    def action_save(self):
        self.ensure_one()
        self.appointment_id._carwash_apply_review(self.stars, self.feedback)
        return {"type": "ir.actions.act_window_close"}
