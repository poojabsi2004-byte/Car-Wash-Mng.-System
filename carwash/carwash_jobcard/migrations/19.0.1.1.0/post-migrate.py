from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """inspection_type (selection pre/post) became inspection_type_id (carwash.inspection.type).

    Map the old column's values onto the two default type records, then drop it.
    """
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_inspection' AND column_name = 'inspection_type'"
    )
    if not cr.fetchone():
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    mapping = {
        "pre": env.ref("carwash_jobcard.inspection_type_pre").id,
        "post": env.ref("carwash_jobcard.inspection_type_post").id,
    }
    for old_value, type_id in mapping.items():
        cr.execute(
            "UPDATE carwash_inspection SET inspection_type_id = %s WHERE inspection_type = %s AND inspection_type_id IS NULL",
            (type_id, old_value),
        )
    cr.execute(
        "UPDATE carwash_inspection SET inspection_type_id = %s WHERE inspection_type_id IS NULL", (mapping["pre"],)
    )
    cr.execute("ALTER TABLE carwash_inspection ALTER COLUMN inspection_type_id SET NOT NULL")
    cr.execute("ALTER TABLE carwash_inspection DROP COLUMN inspection_type")
