# Consumption lines are "booked out" once their booking is completed (its stock moves are made):
# mark the lines of bookings completed before this version.
# (The job card task templates come with the data files: created here if the database has none.)


def migrate(cr, version):
    cr.execute("""
        UPDATE carwash_jobcard_consumption line
           SET booked_out = TRUE
          FROM carwash_jobcard jobcard
          JOIN carwash_appointment booking ON booking.id = jobcard.appointment_id
         WHERE line.jobcard_id = jobcard.id
           AND booking.state = 'done'
           AND jobcard.stages != 'cancel'
    """)
