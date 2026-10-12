from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_carwash_service = fields.Boolean(string="Car Wash Service", default=False)
    carwash_duration = fields.Float(
        string="Estimated Service Time", default=0.5,
        help="How long the service takes (hours:minutes). It sets the booking's length, its time slot and the "
        "calendar, and is compared with the actual time taken on the job card.",
    )
    carwash_bay_type_id = fields.Many2one(
        "carwash.bay.type", string="Bay Type Needed", ondelete="set null",
        help="Kind of bay this service is done in. Leave empty when any bay will do.",
    )
    carwash_material_line_ids = fields.One2many(
        "carwash.service.material.line", "product_tmpl_id", string="Consumables / Materials"
    )


class CarwashServiceMaterialLine(models.Model):
    _name = "carwash.service.material.line"
    _description = "Car Wash Service Consumable"

    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one(
        "product.product", required=True, string="Consumable", domain=[("is_storable", "=", True)]
    )
    quantity = fields.Float(string="Qty Used per Service", required=True, default=1.0)
    uom_id = fields.Many2one(related="product_id.uom_id", readonly=True, store=True)

    _product_tmpl_material_uniq = models.Constraint(
        "UNIQUE(product_tmpl_id, product_id)", "This consumable is already listed for this service."
    )
    _quantity_positive = models.Constraint("CHECK(quantity > 0)", "Quantity used must be positive.")
