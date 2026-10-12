from . import models
from .models.res_timezone import fix_tz_aliases

# car wash date / time display: 06 Oct, 26 - 10:30 AM (dates are shown numerically, see static/src/js/carwash_date_format.js)
DATE_FORMAT = "%d %b, %y"
TIME_FORMAT = "%I:%M %p"


def post_init_hook(env):
    """Set the car wash date / time format on the active languages.

    Odoo 19 only offers fixed choices for these in Settings > Languages, so they are written
    directly (as the 19.0.1.8.0 / 19.0.1.9.0 migrations did for existing databases). The time
    format only replaces Odoo's default with seconds; a format chosen by the user is kept.
    """
    env.cr.execute("UPDATE res_lang SET date_format = %s WHERE active", [DATE_FORMAT])
    env.cr.execute("UPDATE res_lang SET time_format = %s WHERE active AND time_format = %s", [TIME_FORMAT, "%I:%M:%S %p"])
    # time zone aliases PostgreSQL may not know (Asia/Calcutta) break the date-grouped reports
    fix_tz_aliases(env.cr)
    # each branch numbers its own documents with its code in front (CWB1/26/0001)
    for company in env["res.company"].search([("carwash_code", "=", False)], order="id"):
        company._carwash_branch_code()
    env.registry.clear_cache()
