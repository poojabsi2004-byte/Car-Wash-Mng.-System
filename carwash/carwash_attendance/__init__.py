from . import models


def post_init_hook(env):
    """Everyone checks in / out (dashboard My Attendance + the top bar): on for every branch at install,
    and every Car Wash user has an employee to check in with."""
    env["res.company"].with_context(active_test=False).search([]).write({"attendance_from_systray": True})
    # Car Wash users without an employee (e.g. created in Settings > Users) get one, to check in / out
    env["res.users"].search([("share", "=", False)])._carwash_ensure_attendance_employee()
