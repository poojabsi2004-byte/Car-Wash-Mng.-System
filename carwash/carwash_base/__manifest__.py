{
    "name": "Car Wash Management",
    "version": "19.0.1.2.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 10,
    "summary": "Customers, vehicles, services, appointments, bays, queue and inventory for a car wash business",
    "description": """Car Wash Management System - Phase 1
Core operations: customer & vehicle registry, service catalogue with consumables,
walk-in appointment scheduling with bay assignment and live queue, standard
Sales Order handoff on completion, and inventory consumption via standard
Odoo stock moves.""",
    "depends": ["base", "mail", "contacts", "product", "sale_management", "stock"],
    "data": [
        "security/carwash_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/carwash_vehicle_views.xml",
        "views/res_partner_views.xml",
        "views/product_template_views.xml",
        "views/carwash_bay_views.xml",
        "views/carwash_appointment_views.xml",
        "views/carwash_menus.xml",
    ],
    "demo": [
        "demo/carwash_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_base/static/src/css/carwash_theme_overrides.css",
            "carwash_base/static/src/scss/carwash_appointment.scss",
            "carwash_base/static/src/js/carwash_navbar_theme.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
