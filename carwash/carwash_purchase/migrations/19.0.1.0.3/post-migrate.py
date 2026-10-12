"""The supplier management (supplier categories, branches served, rating, scorecard, car wash Suppliers / Supplier
Prices screens) was removed - the purchase flow stays. Clean up what Odoo leaves behind for a removed model:
the supplier categories' data ids (noupdate), their table and the two many2many tables."""

TABLES = ("carwash_supplier_category_partner_rel", "carwash_supplier_branch_rel", "carwash_supplier_category")


def migrate(cr, version):
    cr.execute("DELETE FROM ir_model_data WHERE module = 'carwash_purchase' AND model = 'carwash.supplier.category'")
    cr.execute("DELETE FROM ir_model_relation WHERE name IN %s", [TABLES[:2]])
    for table in TABLES:
        cr.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
