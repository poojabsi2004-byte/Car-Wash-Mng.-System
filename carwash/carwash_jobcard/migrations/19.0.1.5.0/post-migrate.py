OWNERS = [
    ("appointment_id", "carwash_appointment"),
    ("inspection_id", "carwash_inspection"),
    ("lead_id", "crm_lead"),  # added by carwash_crm
]


def migrate(cr, version):
    """Checklist lines now remember the template task they were loaded from, which decides
    whether they're mandatory. Link existing lines (same task name on the record's template)
    and take the template's mandatory flag - lines saved by a stale browser view had lost it."""
    for column, table in OWNERS:
        cr.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_checklist_line' AND column_name = %s",
            (column,),
        )
        if not cr.fetchone():
            continue
        cr.execute(
            f"""
            UPDATE carwash_checklist_line line
               SET template_item_id = item.id,
                   is_required = item.is_required
              FROM {table} owner
              JOIN carwash_checklist_template_item item ON item.template_id = owner.checklist_template_id
             WHERE line.{column} = owner.id
               AND line.template_item_id IS NULL
               AND item.name = line.name
            """
        )
