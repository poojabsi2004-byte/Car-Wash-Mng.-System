# Link every checklist template to the standard Checklist Type of its step (see pre-migrate).


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'carwash_checklist_template' AND column_name = 'checklist_type_premig'"
    )
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE carwash_checklist_template t
           SET checklist_type_id = d.res_id, checklist_type = t.checklist_type_premig
          FROM ir_model_data d
         WHERE d.module = 'carwash_jobcard' AND d.model = 'carwash.checklist.type'
           AND d.name = 'checklist_type_' || t.checklist_type_premig
    """)
    cr.execute("ALTER TABLE carwash_checklist_template DROP COLUMN checklist_type_premig")
