{
    "name": "Car Wash Job Cards & Quality Control",
    "version": "19.0.1.5.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 11,
    "summary": "Job cards, employee assignment, inspections, quality control, service packages and dashboard for Car Wash",
    "description": """Car Wash Management System - Phase 2
Employee-assigned job cards with task checklists and a QC gate, pre/post-wash
vehicle inspections, process checklists (booking check-in, inspections) whose
mandatory tasks gate the next step, sellable service packages, and a lightweight standard-view
dashboard. Depends on carwash_base (Phase 1).""",
    "depends": ["carwash_base", "hr", "hr_timesheet"],
    "data": [
        "security/carwash_jobcard_security.xml",
        "security/ir.model.access.csv",
        "security/ir_rules.xml",
        "data/ir_sequence_data.xml",
        "data/project_data.xml",
        "data/carwash_inspection_type_data.xml",
        "data/carwash_checklist_template_data.xml",
        "views/carwash_checklist_template_views.xml",
        "views/carwash_service_package_views.xml",
        "views/carwash_inspection_views.xml",
        "views/carwash_jobcard_views.xml",
        "views/carwash_appointment_views.xml",
        "views/carwash_dashboard_views.xml",
        "views/carwash_jobcard_menus.xml",
        "report/carwash_jobcard_report.xml",
    ],
    "demo": [
        "demo/carwash_jobcard_demo.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
