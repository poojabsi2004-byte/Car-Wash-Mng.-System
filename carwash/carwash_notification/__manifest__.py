{
    "name": "Car Wash Notifications",
    "version": "19.0.1.3.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 18,
    "summary": "Customer email notifications for bookings, packages and memberships (Odoo mail), each switchable in Settings",
    "description": """Car Wash Management System - Notifications
Customer emails sent through Odoo's mail queue and logged in the chatter:
booking request received, booking confirmed (services, package, membership saving),
booking updated (time / package), visit reminder, ready for pickup, cancelled,
membership payment request, activated, renewed, ending soon (renew reminder N days
before the end date, default 2), expired and cancelled.
Every notification can be switched off and the reminder timings changed in
Car Wash > Configuration > Settings > Notifications; templates are editable.""",
    "depends": ["carwash_crm", "carwash_membership", "carwash_jobcard"],
    "data": [
        "data/ir_config_parameter_data.xml",
        "data/mail_template_booking.xml",
        "data/mail_template_membership.xml",
        "data/ir_cron_data.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": ["carwash_crm", "carwash_membership", "carwash_jobcard"],  # installed together with Car Wash (chain from carwash_base)
}
