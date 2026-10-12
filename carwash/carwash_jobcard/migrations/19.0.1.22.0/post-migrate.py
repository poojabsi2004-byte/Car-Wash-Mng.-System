# A job card's services are rows of carwash.jobcard.service (editable on the Services tab).
# - Databases on 19.0.1.21.0 kept them in the many2many table carwash_jobcard_service_line_rel: move them over.
# - Older job cards covered the whole booking: link each service to the booking's first job card that isn't cancelled.


def migrate(cr, version):
    cr.execute("SELECT to_regclass('carwash_jobcard_service_line_rel')")
    if cr.fetchone()[0]:
        cr.execute("""
            INSERT INTO carwash_jobcard_service (jobcard_id, appointment_line_id, sequence)
            SELECT rel.jobcard_id, rel.line_id, 10 FROM carwash_jobcard_service_line_rel rel
            ON CONFLICT DO NOTHING
        """)
        cr.execute("DROP TABLE carwash_jobcard_service_line_rel")
    cr.execute("""
        INSERT INTO carwash_jobcard_service (jobcard_id, appointment_line_id, sequence)
        SELECT DISTINCT ON (line.id) jobcard.id, line.id, 10
          FROM carwash_jobcard jobcard
          JOIN carwash_appointment_line line ON line.appointment_id = jobcard.appointment_id
         WHERE jobcard.stages != 'cancel' AND NOT COALESCE(line.is_discount_line, FALSE)
           AND NOT EXISTS (SELECT 1 FROM carwash_jobcard_service row WHERE row.appointment_line_id = line.id)
         ORDER BY line.id, jobcard.id
        ON CONFLICT DO NOTHING
    """)
