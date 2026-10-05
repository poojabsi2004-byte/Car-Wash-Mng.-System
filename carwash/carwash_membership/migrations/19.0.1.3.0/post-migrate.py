import logging

from odoo import SUPERUSER_ID, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """The member discount moved from the service prices to one "Membership Discount" line.

    Bookings that haven't started yet are re-applied so they show the new layout; bookings
    already in service or finished keep the prices they were billed with.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    bookings = env["carwash.appointment"].search(
        [("membership_id", "!=", False), ("state", "in", ("draft", "confirmed", "arrived"))]
    )
    for booking in bookings:
        try:
            with cr.savepoint():
                booking.action_apply_membership()
        except UserError as error:
            _logger.info("Membership not re-applied on %s: %s", booking.name, error)
