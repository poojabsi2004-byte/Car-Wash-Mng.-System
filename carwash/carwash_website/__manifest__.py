{
    "name": "Car Wash Website Booking",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 14,
    "summary": "Real time-slot online booking for customers, plus a portal My Bookings area",
    "description": """Car Wash Management System - Website Booking
Logged-in portal customers pick a branch, a service and a date, see live
bay availability for that day, and confirm a booking - reusing the same
appointment workflow (action_confirm) staff use internally. Booked
appointments and vehicles appear read-only under My Bookings in the portal.""",
    "depends": ["carwash_multibranch", "website", "portal", "resource"],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rules.xml",
        "views/carwash_website_templates.xml",
        "views/portal_templates.xml",
        "views/membership_templates.xml",
        "views/res_config_settings_views.xml",
        "data/website_menu_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "carwash_website/static/src/scss/carwash_website.scss",
        ],
    },
    "post_init_hook": "_set_homepage_url",
    "installable": True,
    "application": False,
    "auto_install": False,
}
