{
    "name": "Car Wash Multi-Branch",
    "version": "19.0.1.7.0",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 13,
    "summary": "Owner role and cross-branch data isolation for multi-location Car Wash deployments",
    "description": """Car Wash Management System - Phase 4 (multi-branch foundation)
Treats each branch as an Odoo company (standard multi-company). Adds an Owner
role that sees every branch; all other roles (Front Desk, Washer, QC Inspector,
Manager) stay scoped to their own branch's company_id via record rules.""",
    "depends": ["carwash_membership", "carwash_jobcard"],
    "data": [
        "security/carwash_multibranch_security.xml",
        "security/ir_rules.xml",
        "data/carwash_branch_data.xml",
    ],
    "demo": [
        "demo/carwash_multibranch_demo.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": ["carwash_membership", "carwash_jobcard"],  # installed together with Car Wash (chain from carwash_base)
}
