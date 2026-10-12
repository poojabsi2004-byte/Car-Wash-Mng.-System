from odoo import SUPERUSER_ID, api
from odoo.tools import convert_file


def migrate(cr, version):
    """The five branches (with warehouses and bays) are now regular data. On an upgrade they are added
    here, once every module is loaded - creating a company also creates records of other apps (e.g. the
    Timesheets project of the company), which can't be made halfway through the upgrade. A database that
    already has them (loaded as demo data) is left as it is."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    if env.ref("carwash_multibranch.demo_company_satellite", raise_if_not_found=False):
        return
    # mode "init": creates the branches, their warehouses and bays, and gives the administrator access to them
    convert_file(env, "carwash_multibranch", "data/carwash_branch_data.xml", {}, mode="init", noupdate=True)
