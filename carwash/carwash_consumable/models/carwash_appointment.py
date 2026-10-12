from odoo import fields, models


class CarwashAppointment(models.Model):
    _inherit = "carwash.appointment"

    consumable_move_count = fields.Integer(compute="_compute_consumable_move_count", string="Consumables Used")

    def _compute_consumable_move_count(self):
        counts = dict(self.env["stock.move"].sudo()._read_group(
            [("carwash_appointment_id", "in", self.ids)], ["carwash_appointment_id"], ["__count"]
        ))
        for appointment in self:
            appointment.consumable_move_count = counts.get(appointment, 0)

    def action_view_consumables(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("carwash_consumable.action_carwash_consumption_analysis")
        action.update({
            "display_name": self.env._("Consumables: %s", self.name),
            "domain": [("carwash_appointment_id", "=", self.id)],
            "context": {},
            "view_mode": "list",
            "views": [(False, "list")],
        })
        return action

    def _carwash_book_out(self, items):
        # a branch without a warehouse would silently consume nothing - give it one
        self.company_id._carwash_warehouse(create=True)
        return super()._carwash_book_out(items)
