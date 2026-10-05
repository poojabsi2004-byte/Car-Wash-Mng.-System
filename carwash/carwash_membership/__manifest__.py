{
    "name": "Car Wash Memberships & Loyalty",
    "version": "19.0.1.3.0",
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
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/product_data.xml",
        "data/ir_cron_data.xml",
        "data/mail_template_data.xml",
        "data/loyalty_program_data.xml",
        "views/carwash_membership_plan_views.xml",
        "views/carwash_appointment_views.xml",
        "views/carwash_membership_views.xml",
        "views/res_partner_views.xml",
        "views/carwash_membership_menus.xml",
    ],
    "demo": [
        "demo/carwash_membership_demo.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
