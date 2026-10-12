from . import models


def _carwash_consumable_post_init(env):
    """Make consumable management usable right away on an existing database:
    - every branch with car wash bays gets a warehouse (consumption needs one),
    - products already used in a service's materials are flagged as car wash consumables."""
    branches = env["carwash.bay"].with_context(active_test=False).search([]).company_id
    for branch in branches:
        branch._carwash_warehouse(create=True)
    recipe_products = env["carwash.service.material.line"].search([]).product_id.product_tmpl_id
    recipe_products.write({"is_carwash_consumable": True})
