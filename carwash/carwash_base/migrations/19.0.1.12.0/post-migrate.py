# Vehicle Type became a configurable model (carwash.vehicle.type): link every vehicle to the
# record of its former choice (the old selection column "vehicle_type" holds the code).


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_vehicle' AND column_name = 'vehicle_type'")
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE carwash_vehicle v
           SET vehicle_type_id = t.id
          FROM carwash_vehicle_type t
         WHERE t.code = v.vehicle_type AND v.vehicle_type_id IS DISTINCT FROM t.id
    """)
    cr.execute("""
        UPDATE carwash_vehicle
           SET vehicle_type_id = (SELECT id FROM carwash_vehicle_type WHERE code = 'other')
         WHERE vehicle_type_id IS NULL AND vehicle_type IS NOT NULL
    """)
