# Time zone aliases (Asia/Calcutta) unknown to PostgreSQL break every date-grouped report (Purchase Analysis,
# pivots / graphs by day or month): records still on them - created by Odoo before the car wash modules -
# move to the current name (Asia/Kolkata).
from odoo.addons.carwash_base.models.res_timezone import fix_tz_aliases


def migrate(cr, version):
    fix_tz_aliases(cr)
