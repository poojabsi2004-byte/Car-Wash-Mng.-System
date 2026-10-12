from odoo import api, fields, models


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    lead_id = fields.Many2one("crm.lead", string="Lead", readonly=True, copy=False, index=True)

    @api.model
    def _carwash_find_free_bay(self, company, start, duration):
        """First active bay of `company` with no blocking booking overlapping [start, start + duration)."""
        return self._carwash_free_bays(company, start, duration)[:1]

    def action_view_lead(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.lead_id.id,
        }
