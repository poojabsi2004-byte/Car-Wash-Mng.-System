from . import models


def _carwash_purchase_post_init(env):
    """Make supplier management usable right away on an existing database:
    - consumables get the "Consumables" purchase type and the Car Wash Supplies category (average cost),
    - the branches' minimum-stock rules buy from the supplier (manual RFQs until switched to automatic),
    - every branch warehouse can buy (Buy route rule)."""
    products = env["product.template"].with_context(active_test=False).search([("is_carwash_consumable", "=", True)])
    products.filtered(lambda p: not p.carwash_supply_type).write({"carwash_supply_type": "consumable"})
    env["product.category"]._carwash_supplies_category()._carwash_set_average_cost(env["res.company"].search([]))
    env["product.template"]._carwash_use_supplies_category(
        env["product.template"].with_context(active_test=False).search([("carwash_supply_type", "!=", False)])
    )
    for warehouse in env["stock.warehouse"].search([]):
        if not warehouse.buy_to_resupply:
            warehouse.buy_to_resupply = True
    env["res.company"].search([])._carwash_sync_orderpoints()
