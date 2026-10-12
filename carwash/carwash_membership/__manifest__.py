{
    "name": "Car Wash Memberships & Loyalty",
    "version": "19.0.1.18.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 12,
    "summary": "Membership plans, recurring billing, loyalty points and email notifications for Car Wash",
    "description": """Car Wash Management System - Phase 3
Membership plans with cron-based recurring billing (standard Sales Order flow,
no Subscriptions app dependency), usage tracking against appointments, a
standard Odoo Loyalty Cards program on wash sale orders, and templated email
notifications at key appointment/membership milestones.""",
    "depends": ["carwash_base", "loyalty", "partnership", "account_payment"],
    "data": [
        "security/carwash_membership_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/product_data.xml",
        "data/ir_cron_data.xml",
        "data/mail_template_data.xml",
        "data/loyalty_program_data.xml",
        "data/carwash_feature_data.xml",
        "data/carwash_membership_plan_data.xml",
        "views/carwash_membership_plan_views.xml",
        "views/carwash_appointment_views.xml",
        "views/carwash_membership_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/carwash_membership_menus.xml",
        "views/carwash_auto_renew_templates.xml",
        "report/carwash_booking_report.xml",
    ],
    "demo": [
        "demo/carwash_membership_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_membership/static/src/scss/carwash_membership.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": ["carwash_base"],  # installed together with Car Wash (chain from carwash_base)
}
