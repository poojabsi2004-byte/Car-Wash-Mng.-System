# Bay Type became a configurable model (carwash.bay.type): link every bay, and every service's
# "bay type needed", to the record of its former choice (the old selection columns hold the code).


def _has_column(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s", (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if _has_column(cr, "carwash_bay", "bay_type"):
        cr.execute("""
            UPDATE carwash_bay b
               SET bay_type_id = t.id
              FROM carwash_bay_type t
             WHERE t.code = b.bay_type AND b.bay_type_id IS DISTINCT FROM t.id
        """)
    # any bay still without a type (unknown old value): Hand Wash, the former default
    cr.execute("""
        UPDATE carwash_bay
           SET bay_type_id = (SELECT id FROM carwash_bay_type WHERE code = 'hand')
         WHERE bay_type_id IS NULL
    """)
    if _has_column(cr, "product_template", "carwash_bay_type"):
        # "any" (Any Bay) has no record: the field stays empty
        cr.execute("""
            UPDATE product_template p
               SET carwash_bay_type_id = t.id
              FROM carwash_bay_type t
             WHERE t.code = p.carwash_bay_type AND p.carwash_bay_type_id IS NULL
        """)
