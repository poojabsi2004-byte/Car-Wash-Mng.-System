# Old timezone alias Asia/Calcutta -> Asia/Kolkata on users/contacts and working-hour calendars
# (PostgreSQL without the "backward" tz data can't group reports by day for the alias).


def migrate(cr, version):
    cr.execute("UPDATE res_partner SET tz = 'Asia/Kolkata' WHERE tz = 'Asia/Calcutta'")
    cr.execute("UPDATE resource_calendar SET tz = 'Asia/Kolkata' WHERE tz = 'Asia/Calcutta'")
