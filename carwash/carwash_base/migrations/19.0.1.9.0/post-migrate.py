# Dates now always show in the language format (06 Oct, 26) - see static/src/js/carwash_date_format.js.
# Date-times then use the language time format too: drop the seconds of Odoo's default (10:30 AM).
# Only the untouched default is changed; a custom time format in Settings > Languages is kept.


def migrate(cr, version):
    cr.execute("UPDATE res_lang SET time_format = '%I:%M %p' WHERE active AND time_format = '%I:%M:%S %p'")
