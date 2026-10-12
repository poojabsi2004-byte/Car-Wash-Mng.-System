def migrate(cr, version):
    """Booking requests (leads) no longer have a checklist - the process checklists start when
    the vehicle arrives. Remove the request checklists and their template."""
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_checklist_line' AND column_name = 'lead_id'"
    )
    if cr.fetchone():
        cr.execute("DELETE FROM carwash_checklist_line WHERE lead_id IS NOT NULL")
        cr.execute("ALTER TABLE carwash_checklist_line DROP COLUMN lead_id")
    cr.execute(
        "DELETE FROM carwash_checklist_template_item WHERE template_id IN "
        "(SELECT id FROM carwash_checklist_template WHERE checklist_type = 'lead')"
    )
    cr.execute("DELETE FROM carwash_checklist_template WHERE checklist_type = 'lead'")
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'carwash_crm' AND name = 'checklist_template_lead_verification'"
    )
    cr.execute("ALTER TABLE crm_lead DROP COLUMN IF EXISTS checklist_template_id")
