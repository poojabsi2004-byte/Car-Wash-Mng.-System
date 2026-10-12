# Checklist templates: the single "vehicle_type" choice became the "Vehicle Types" list (carwash.vehicle.type).
# The template data is noupdate, so copy each template's former choice over.


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_checklist_template' AND column_name = 'vehicle_type'"
    )
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO carwash_checklist_template_vehicle_type_rel (template_id, vehicle_type_id)
        SELECT tpl.id, t.id
          FROM carwash_checklist_template tpl
          JOIN carwash_vehicle_type t ON t.code = tpl.vehicle_type
         WHERE tpl.vehicle_type IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
