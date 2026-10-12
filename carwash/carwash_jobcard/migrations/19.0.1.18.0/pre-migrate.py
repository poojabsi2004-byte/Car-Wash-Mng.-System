# "Used On" of a checklist template becomes a Checklist Type record (checklist_type_id); the old
# selection column (checklist_type) is now kept in sync from that type. Save each template's step
# before the field changes, so post-migrate can link it to the matching standard type.


def migrate(cr, version):
    cr.execute("ALTER TABLE carwash_checklist_template ADD COLUMN IF NOT EXISTS checklist_type_premig varchar")
    cr.execute("UPDATE carwash_checklist_template SET checklist_type_premig = checklist_type")
