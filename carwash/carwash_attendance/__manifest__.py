{
    "name": "Car Wash Staff Attendance",
    "version": "19.0.1.0.8",
    "license": "LGPL-3",
    "author": "Botspot Infoware",
    "maintainer": "Botspot Infoware",
    "category": "Services",
    "sequence": 16,
    "summary": "Branch-wise staff attendance (Odoo Attendances) on the car wash staff, employee form and dashboard",
    "description": """Car Wash Management System - Staff Attendance
Uses Odoo's standard Attendances app (check-in / check-out, kiosk, overtime):
- every attendance records the branch the staff member worked at,
- an Attendance tab on the employee (status, Check In / Check Out, history),
- Staff > Attendances and Configuration > Staff > Attendances, by branch,
- a "Staff Attendance" section on the Car Wash dashboard (who is in now),
- a Staff Attendance switch in Car Wash > Configuration > Settings.""",
    "depends": ["carwash_jobcard", "carwash_dashboard", "hr_attendance"],
    "data": [
        "security/carwash_attendance_security.xml",
        "data/carwash_feature_data.xml",
        "views/hr_attendance_views.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_views.xml",
        "views/carwash_attendance_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "carwash_attendance/static/src/js/attendance_dashboard.js",
            "carwash_attendance/static/src/xml/attendance_dashboard.xml",
            "carwash_attendance/static/src/scss/attendance_dashboard.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": ["carwash_jobcard", "carwash_dashboard"],  # installed together with Car Wash (chain from carwash_base)
}
