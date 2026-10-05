def migrate(cr, version):
    """Services gained their own start/end tracking (service_state on the line).

    Appointments that already finished their main service before this existed get
    their lines marked done, timed with the appointment's own service window, so
    history stays consistent and the new "all services done" check holds for them.
    """
    cr.execute(
        """
        UPDATE carwash_appointment_line line
           SET service_state = 'done',
               start_time = appt.service_started_at,
               end_time = COALESCE(appt.ready_at, appt.done_at),
               actual_duration = CASE
                   WHEN appt.service_started_at IS NOT NULL AND COALESCE(appt.ready_at, appt.done_at) IS NOT NULL
                   THEN EXTRACT(EPOCH FROM (COALESCE(appt.ready_at, appt.done_at) - appt.service_started_at)) / 60.0
                   ELSE 0
               END
          FROM carwash_appointment appt
         WHERE line.appointment_id = appt.id
           AND appt.state IN ('ready', 'done')
        """
    )
