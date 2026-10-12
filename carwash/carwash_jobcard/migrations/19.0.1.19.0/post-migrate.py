# Tasks loaded from a checklist template in the form lost their link to the template task when the
# record was saved (the link was a readonly field the form didn't send), so their "Mandatory" flag could
# be switched off. Link them again - same checklist template, same task name - and restore the flag.


def migrate(cr, version):
    for owner_table, owner_column in (("carwash_inspection", "inspection_id"), ("carwash_appointment", "appointment_id")):
        cr.execute(f"""
            UPDATE carwash_checklist_line line
               SET template_item_id = item.id, is_required = item.is_required
              FROM {owner_table} owner
              JOIN carwash_checklist_template_item item ON item.template_id = owner.checklist_template_id
             WHERE line.{owner_column} = owner.id
               AND line.template_item_id IS NULL
               AND line.name = item.name
        """)
