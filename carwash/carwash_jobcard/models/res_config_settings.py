from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_carwash_package = fields.Boolean(
        "Service Packages", implied_group="carwash_jobcard.group_carwash_package",
        help="Sell bundles of services at a package price.",
    )
    group_carwash_inspection = fields.Boolean(
        "Vehicle Inspections", implied_group="carwash_jobcard.group_carwash_inspection",
        help="Pre-wash and post-wash inspections with photos and damage notes.",
    )
    group_carwash_checklist = fields.Boolean(
        "Process Checklists", implied_group="carwash_jobcard.group_carwash_checklist",
        help="Check-in checklist when the vehicle arrives and inspection checklists; mandatory tasks gate the next step.",
    )
    group_carwash_commission = fields.Boolean(
        "Staff Payable", implied_group="carwash_jobcard.group_carwash_commission",
        help="Record a staff payable for the staff on a job card when it passes QC.",
    )
    group_carwash_individual_pay = fields.Boolean(
        "Individual Staff Pay", implied_group="carwash_jobcard.group_carwash_individual_pay",
        help="Set a staff member's own pay (% or fixed per job) on their employee - used instead of their role's.",
    )
    group_carwash_rating = fields.Boolean(
        "Customer Ratings", implied_group="carwash_jobcard.group_carwash_rating",
        help="The 'car wash complete' email asks the customer to rate it (1-5 stars) and write a review.",
    )
