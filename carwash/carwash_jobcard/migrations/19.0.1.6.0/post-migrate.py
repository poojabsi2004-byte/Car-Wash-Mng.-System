def migrate(cr, version):
    """The check-in checklist is now added when the vehicle arrives, not when it's booked.
    Drop the untouched checklists already put on bookings that haven't arrived yet."""
    cr.execute(
        """
        DELETE FROM carwash_checklist_line line
         USING carwash_appointment booking
         WHERE line.appointment_id = booking.id
           AND booking.state IN ('draft', 'confirmed')
           AND NOT EXISTS (SELECT 1 FROM carwash_checklist_line done
                            WHERE done.appointment_id = booking.id AND done.is_done)
        """
    )
    cr.execute(
        """
        UPDATE carwash_appointment booking SET checklist_template_id = NULL
         WHERE state IN ('draft', 'confirmed')
           AND NOT EXISTS (SELECT 1 FROM carwash_checklist_line line WHERE line.appointment_id = booking.id)
        """
    )
