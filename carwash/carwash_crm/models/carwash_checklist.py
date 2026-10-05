from odoo import fields, models


class CarwashChecklistTemplate(models.Model):
    _inherit = "carwash.checklist.template"

    checklist_type = fields.Selection(selection_add=[("lead", "Booking Request")], ondelete={"lead": "cascade"})


class CarwashChecklistLine(models.Model):
    _inherit = "carwash.checklist.line"

    lead_id = fields.Many2one("crm.lead", string="Booking Request", ondelete="cascade", index="btree_not_null")
