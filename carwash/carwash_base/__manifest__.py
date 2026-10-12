{
    "name": "Car Wash Management",
    "version": "19.0.1.41.0",
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
    "depends": ["base", "mail", "contacts", "product", "sale_management", "stock", "resource"],
    "data": [
        "security/carwash_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/carwash_time_slot_data.xml",
        "data/carwash_feature_data.xml",
        "data/carwash_vehicle_type_data.xml",
        "data/carwash_bay_type_data.xml",
        "data/carwash_bay_data.xml",
        "data/carwash_service_data.xml",
        "views/carwash_vehicle_views.xml",
        "views/carwash_vehicle_type_views.xml",
        "views/carwash_bay_type_views.xml",
        "views/carwash_calendar_kanban_views.xml",
        "views/res_partner_views.xml",
        "views/product_template_views.xml",
        "views/carwash_bay_views.xml",
        "views/carwash_time_slot_views.xml",
        "views/carwash_appointment_views.xml",
        "views/res_config_settings_views.xml",
        "views/carwash_menus.xml",
        "data/carwash_report_emblem_data.xml",
        "report/carwash_report_layout.xml",
        "report/carwash_booking_report.xml",
    ],
    "demo": [
        "demo/carwash_demo.xml",
    ],
    "assets": {
        # the car wash colour is Odoo's primary colour in every app (backend, portal)
        "web._assets_primary_variables": [
            ("prepend", "carwash_base/static/src/scss/primary_variables.scss"),
        ],
        "web.assets_backend": [
            "carwash_base/static/src/scss/carwash_ui.scss",
            "carwash_base/static/src/scss/carwash_base_views.scss",
            "carwash_base/static/src/scss/carwash_appointment.scss",
            "carwash_base/static/src/js/carwash_date_format.js",
        ],
        "web.report_assets_common": [
            "carwash_base/static/src/scss/carwash_report.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
}
