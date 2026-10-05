{
    "name": "Car Wash Booking Leads (CRM)",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 15,
    "summary": "New booking requests arrive as CRM leads; confirming the lead creates the booking",
    "description": """Car Wash Management System - Booking Leads
Website booking requests (and phone/walk-in requests entered by staff) are
created as CRM leads in a "Car Wash Bookings" pipeline. Confirming the lead
creates and confirms the car wash booking, marks the lead Won and links both.
A request-verification checklist must be completed before a lead can be confirmed.""",
    "depends": ["carwash_website", "crm"],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rules.xml",
        "data/crm_team_data.xml",
        "data/carwash_checklist_template_data.xml",
        "views/crm_lead_views.xml",
        "views/carwash_appointment_views.xml",
        "views/website_templates.xml",
        "views/carwash_crm_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
