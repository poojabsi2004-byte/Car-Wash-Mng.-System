{
    "name": "Car Wash Job Cards & Quality Control",
    "version": "19.0.1.45.0",
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
    "depends": ["carwash_base", "hr", "hr_timesheet", "rating"],
    "data": [
        "security/carwash_jobcard_security.xml",
        "security/ir.model.access.csv",
        "security/ir_rules.xml",
        "data/ir_sequence_data.xml",
        "data/product_data.xml",
        "data/product_staff_payable_data.xml",
        "data/project_data.xml",
        "data/carwash_inspection_type_data.xml",
        "data/carwash_checklist_type_data.xml",
        "data/carwash_checklist_template_data.xml",
        "data/carwash_service_package_data.xml",
        "data/carwash_staff_role_data.xml",
        "data/mail_template_rating.xml",
        "views/carwash_rating_templates.xml",
        "data/carwash_feature_data.xml",
        "views/carwash_checklist_type_views.xml",
        "views/carwash_checklist_template_views.xml",
        "views/carwash_staff_views.xml",
        "views/carwash_staff_user_views.xml",
        "views/carwash_service_package_views.xml",
        "views/carwash_inspection_views.xml",
        "views/carwash_jobcard_views.xml",
        "views/carwash_appointment_views.xml",
        "views/carwash_dashboard_views.xml",
        "views/res_config_settings_views.xml",
        "views/carwash_kanban_views.xml",
        "views/carwash_jobcard_menus.xml",
        "views/carwash_my_earnings_views.xml",
        "report/carwash_jobcard_report.xml",
        "views/carwash_staff_performance_views.xml",
        "report/carwash_staff_performance_report.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_jobcard/static/src/scss/carwash_jobcard_views.scss",
        ],
        "web.report_assets_common": [
            "carwash_jobcard/static/src/scss/carwash_staff_performance.scss",
        ],
    },
    "demo": [
        "demo/carwash_jobcard_demo.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": ["carwash_base"],  # installed together with Car Wash (chain from carwash_base)
}
