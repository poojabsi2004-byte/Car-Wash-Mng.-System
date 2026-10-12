"""Staff / QC check in and out themselves now (dashboard My Attendance + the top bar): switch it on for every branch."""


def migrate(cr, version):
    cr.execute("UPDATE res_company SET attendance_from_systray = TRUE WHERE attendance_from_systray IS NOT TRUE")
