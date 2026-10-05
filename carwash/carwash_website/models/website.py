from odoo import fields, models


class Website(models.Model):
    _inherit = "website"

    carwash_show_packages = fields.Boolean(
        string="Show Service Packages on Homepage",
        default=True,
        help="Display the Service Packages tab list on the Car Wash homepage, "
        "so customers can see what's included in each package before booking.",
    )
