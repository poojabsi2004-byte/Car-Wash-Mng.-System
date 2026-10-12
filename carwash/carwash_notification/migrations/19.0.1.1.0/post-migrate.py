# Booking emails now show dates as DD MMM, YY (e.g. 06 Oct, 26 10:30 AM). The templates are
# noupdate (editable), so the data file doesn't touch existing ones - rewrite the date patterns.
REPLACEMENTS = [
    ("dt_format='EEEE d MMMM y, h:mm a'", "dt_format='dd MMM, yy h:mm a'"),
    ("dt_format='d MMM, h:mm a'", "dt_format='dd MMM, yy h:mm a'"),
    ("dt_format='EEEE, h:mm a'", "dt_format='dd MMM, yy h:mm a'"),
]


def migrate(cr, version):
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module = 'carwash_notification' AND model = 'mail.template'"
    )
    ids = tuple(row[0] for row in cr.fetchall())
    if not ids:
        return
    for old, new in REPLACEMENTS:
        cr.execute(
            """
            UPDATE mail_template
               SET body_html = replace(body_html::text, %s, %s)::jsonb,
                   subject = replace(subject::text, %s, %s)::jsonb
             WHERE id IN %s
            """,
            (old, new, old, new, ids),
        )
