from odoo import SUPERUSER_ID, api

FEATURE_GROUPS = "carwash_jobcard.group_carwash_package,carwash_jobcard.group_carwash_inspection,carwash_jobcard.group_carwash_checklist,carwash_jobcard.group_carwash_commission,carwash_jobcard.group_carwash_rating".split(",")


def migrate(cr, version):
    """New Car Wash > Configuration > Settings switches: databases that already use these
    features keep them switched on (fresh installs get that from the feature data file)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    groups = env["res.groups"]
    for xmlid in FEATURE_GROUPS:
        groups |= env.ref(xmlid)
    env.ref("base.group_user").write({"implied_ids": [(4, group.id) for group in groups]})
