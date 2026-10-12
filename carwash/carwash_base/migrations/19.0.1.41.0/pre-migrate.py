def migrate(cr, version):
    """Bay 1-4 of the main company are now regular data (carwash_base.demo_bay_1..4). A database that
    already has bays with those names (made by hand) keeps them: they become those records instead of
    being created again (the bay name is unique per company)."""
    cr.execute("SELECT res_id FROM ir_model_data WHERE module = 'base' AND name = 'main_company'")
    row = cr.fetchone()
    if not row:
        return
    main_company_id = row[0]
    for number in range(1, 5):
        xmlid = f"demo_bay_{number}"
        cr.execute("SELECT 1 FROM ir_model_data WHERE module = 'carwash_base' AND name = %s", [xmlid])
        if cr.fetchone():
            continue
        cr.execute(
            "SELECT id FROM carwash_bay WHERE company_id = %s AND name = %s LIMIT 1",
            [main_company_id, f"Bay {number}"],
        )
        bay = cr.fetchone()
        if bay:
            cr.execute(
                """INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
                   VALUES ('carwash_base', %s, 'carwash.bay', %s, true)""",
                [xmlid, bay[0]],
            )
