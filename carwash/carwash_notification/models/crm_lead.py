from odoo import api, models


def _requester(lead):
    if lead.partner_id.email:
        return lead.partner_id
    return lead.email_from or False


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        self.env["carwash.notification"]._send(leads.filtered("is_carwash_booking"), "booking_request", _requester)
        return leads
