# Time slots can be offered at several branches (company_ids): a slot that was for one branch
# (the old company_id column) keeps that branch.


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'carwash_time_slot' AND column_name = 'company_id'"
    )
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO carwash_time_slot_company_rel (slot_id, company_id)
        SELECT id, company_id FROM carwash_time_slot WHERE company_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
