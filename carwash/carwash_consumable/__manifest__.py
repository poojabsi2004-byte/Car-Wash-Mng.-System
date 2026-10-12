{
    "name": "Car Wash Consumable Management",
    "version": "19.0.1.4.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 17,
    "summary": "Branch-wise consumable stock, floor issue / wastage / return requests with approval, low-stock alerts and consumption analysis",
    "description": """Car Wash Management System - Consumable Management
Built on Odoo Inventory:
- consumables (shampoo, wax, cloths...) with a minimum stock per branch (reordering rules),
- service recipes consume them automatically when a booking is completed,
- Consumable Requests: floor issue / wastage / return, Draft > Submitted > Approved > Issued,
- daily low-stock alerts for branch managers and a dashboard card,
- Consumption Analysis by product, branch, usage and month.""",
    "depends": ["carwash_jobcard", "carwash_dashboard", "stock"],
    "data": [
        "security/carwash_consumable_security.xml",
        "security/ir.model.access.csv",
        "security/ir_rules.xml",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "data/carwash_feature_data.xml",
        "views/product_views.xml",
        "views/stock_move_views.xml",
        "views/carwash_consumable_request_views.xml",
        "views/carwash_appointment_views.xml",
        "views/res_config_settings_views.xml",
        "views/carwash_consumable_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_consumable/static/src/xml/consumable_dashboard.xml",
            "carwash_consumable/static/src/scss/consumable_dashboard.scss",
        ],
    },
    "post_init_hook": "_carwash_consumable_post_init",
    "installable": True,
    "application": False,
    "auto_install": ["carwash_jobcard", "carwash_dashboard"],  # installed together with Car Wash (chain from carwash_base)
}
