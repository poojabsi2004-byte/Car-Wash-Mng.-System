def migrate(cr, version):
    """Purchase approval set on a main company now covers its branches: branches still without approval get the
    main company's (before, the setting only applied to the company it was saved on)."""
    cr.execute("""
        UPDATE res_company branch
           SET po_double_validation = main.po_double_validation,
               po_double_validation_amount = main.po_double_validation_amount
          FROM res_company main
         WHERE branch.parent_id = main.id
           AND main.po_double_validation = 'two_step'
           AND COALESCE(branch.po_double_validation, 'one_step') = 'one_step'
    """)
