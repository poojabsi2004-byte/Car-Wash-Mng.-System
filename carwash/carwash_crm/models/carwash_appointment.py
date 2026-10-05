from datetime import timedelta

from odoo import api, fields, models


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    lead_id = fields.Many2one("crm.lead", string="Lead", readonly=True, copy=False, index=True)

    @api.model
    def _carwash_find_free_bay(self, company, start, duration):
        """First active bay of `company` with no blocking booking overlapping [start, start + duration)."""
        end = start + timedelta(hours=duration or 0.5)
        bays = self.env["carwash.bay"].search([("company_id", "=", company.id), ("active", "=", True)])
        busy = self.search(
            [("company_id", "=", company.id), ("bay_id", "in", bays.ids), ("state", "in", self._BAY_BLOCKING_STATES)]
        )
        busy_bay_ids = set()
        for appointment in busy:
            o_start, o_end = appointment._get_bay_window()
            if start < o_end and o_start < end:
                busy_bay_ids.add(appointment.bay_id.id)
        return bays.filtered(lambda bay: bay.id not in busy_bay_ids)[:1]

    def action_view_lead(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "view_mode": "form",
            "views": [(False, "form")],
            "res_id": self.lead_id.id,
        }
