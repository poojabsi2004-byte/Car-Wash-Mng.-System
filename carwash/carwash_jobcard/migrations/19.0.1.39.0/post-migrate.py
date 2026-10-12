"""New switch Individual Staff Pay (Car Wash > Settings > Staff Payable). A database where a staff member already
has their own pay keeps using it: the switch starts on there (new databases: off, everyone paid by their role)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT 1 FROM hr_employee WHERE carwash_commission_type IS NOT NULL AND carwash_commission_type != 'role' LIMIT 1")
    if cr.fetchone():
        env.ref("base.group_user").write({"implied_ids": [(4, env.ref("carwash_jobcard.group_carwash_individual_pay").id)]})
