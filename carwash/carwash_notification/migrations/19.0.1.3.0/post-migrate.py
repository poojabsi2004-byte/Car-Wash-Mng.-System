from lxml import etree

from odoo import SUPERUSER_ID, api
from odoo.tools import file_open
from odoo.tools.convert import xml_import

TEMPLATE = "mail_template_membership_expiring"


def migrate(cr, version):
    """The 'membership ending soon' email became the auto-renew reminder (Auto Renew button), sent 10 days
    before the end date. Its template is noupdate data: reload just this one from the module file."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    with file_open("carwash_notification/data/mail_template_membership.xml", "rb") as file:
        tree = etree.parse(file)
    record = tree.xpath(f"//record[@id='{TEMPLATE}']")
    if record:
        root = etree.Element("odoo")
        root.append(record[0])
        xml_import(env, "carwash_notification", {}, mode="init", noupdate=True).parse(root)
    # the reminder now goes 10 days before the end (was 2 by default)
    params = env["ir.config_parameter"].sudo()
    if params.get_param("carwash_notification.membership_expiry_days") in (False, "", "2"):
        params.set_param("carwash_notification.membership_expiry_days", "10")
