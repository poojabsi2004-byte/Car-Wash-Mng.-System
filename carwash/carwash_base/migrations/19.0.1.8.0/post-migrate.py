# Dates in DD MMM, YY (06 Oct, 26) everywhere in the backend and in emails using format_date:
# set the date format of the active languages once (Settings > Languages keeps it editable).
DATE_FORMAT = "%d %b, %y"


def migrate(cr, version):
    cr.execute("UPDATE res_lang SET date_format = %s WHERE active", (DATE_FORMAT,))
