{
    "name": "Car Wash Interactive Dashboard",
    "version": "19.0.1.4.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 14,
    "summary": "Role-aware interactive dashboard (KPI tiles + charts) for Car Wash",
    "description": """Car Wash Management System - Phase 4 (dashboard)
A single OWL dashboard whose content adapts to the logged-in user's role:
Front Desk sees the live queue, Washers see their own job cards, QC Inspectors
see their pending queue, Managers see branch KPIs, and Owners see everything
across every branch plus staff/financial roll-ups. Charts are rendered with
ApexCharts (MIT licensed, vendored under static/src/js/lib).""",
    "depends": ["carwash_multibranch"],
    "data": [
        "security/ir.model.access.csv",
        "views/carwash_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_dashboard/static/src/js/lib/apexcharts.js",
            "carwash_dashboard/static/src/js/carwash_dashboard.js",
            "carwash_dashboard/static/src/xml/carwash_dashboard.xml",
            "carwash_dashboard/static/src/scss/carwash_dashboard.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": ["carwash_multibranch"],  # installed together with Car Wash (chain from carwash_base)
}
