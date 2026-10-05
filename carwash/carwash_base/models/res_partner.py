from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    carwash_vehicle_ids = fields.One2many("carwash.vehicle", "customer_id", string="Vehicles")
    carwash_vehicle_count = fields.Integer(compute="_compute_carwash_counts")
    carwash_appointment_ids = fields.One2many("carwash.appointment", "customer_id", string="Car Wash Bookings")
    carwash_appointment_count = fields.Integer(compute="_compute_carwash_counts", string="Booking Count")

    @api.depends("carwash_vehicle_ids", "carwash_appointment_ids")
    def _compute_carwash_counts(self):
        for partner in self:
            partner.carwash_vehicle_count = len(partner.carwash_vehicle_ids)
            partner.carwash_appointment_count = len(partner.carwash_appointment_ids)

    def action_view_carwash_vehicles(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Vehicles",
            "res_model": "carwash.vehicle",
            "view_mode": "list,form",
            "domain": [("customer_id", "=", self.id)],
            "context": {"default_customer_id": self.id},
        }

    def action_view_carwash_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Bookings",
            "res_model": "carwash.appointment",
            "view_mode": "list,form",
            "domain": [("customer_id", "=", self.id)],
            "context": {"default_customer_id": self.id},
        }
