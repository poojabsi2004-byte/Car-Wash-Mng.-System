# Booking requests: the "carwash_vehicle_type" choice became a link to carwash.vehicle.type.


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'crm_lead' AND column_name = 'carwash_vehicle_type'")
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE crm_lead l
           SET carwash_vehicle_type_id = t.id
          FROM carwash_vehicle_type t
         WHERE t.code = l.carwash_vehicle_type AND l.carwash_vehicle_type_id IS DISTINCT FROM t.id
    """)
