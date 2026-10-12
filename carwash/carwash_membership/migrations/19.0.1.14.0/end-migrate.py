from odoo import SUPERUSER_ID, api
from odoo.tools import convert_file


def migrate(cr, version):
    """The three membership plans (Silver, Gold, Platinum) are now regular data. On an upgrade they are added
    here, once every module is loaded - a plan creates its fee product, and products can't be made halfway
    through the upgrade. A database that already has them (demo data) is left as it is."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    if env.ref("carwash_membership.demo_plan_silver", raise_if_not_found=False):
        return
    convert_file(env, "carwash_membership", "data/carwash_membership_plan_data.xml", {}, mode="init", noupdate=True)
