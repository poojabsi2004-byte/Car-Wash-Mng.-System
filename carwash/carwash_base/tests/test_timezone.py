from odoo.tests import TransactionCase, tagged

from odoo.addons.carwash_base.models.res_timezone import fix_tz_aliases


@tagged("post_install", "-at_install")
class TestTimezoneAlias(TransactionCase):
    """Asia/Calcutta (an alias PostgreSQL may not know) is stored as Asia/Kolkata, so date-grouped reports work."""

    def test_alias_is_stored_as_current_name(self):
        user = self.env["res.users"].create({"name": "TZ User", "login": "tz_user_cw", "tz": "Asia/Calcutta"})
        self.assertEqual(user.tz, "Asia/Kolkata")
        user.tz = "Asia/Calcutta"
        self.assertEqual(user.partner_id.tz, "Asia/Kolkata")
        calendar = self.env["resource.calendar"].create({"name": "TZ Hours", "tz": "Asia/Calcutta"})
        self.assertEqual(calendar.tz, "Asia/Kolkata")
        resource = self.env["resource.resource"].create({"name": "TZ Resource", "tz": "Asia/Calcutta"})
        self.assertEqual(resource.tz, "Asia/Kolkata")

    def test_existing_records_fixed_and_reports_group_by_day(self):
        partner = self.env["res.partner"].create({"name": "Old TZ"})
        self.env.cr.execute("UPDATE res_partner SET tz = 'Asia/Calcutta' WHERE id = %s", [partner.id])
        fix_tz_aliases(self.env.cr)
        partner.invalidate_recordset(["tz"])
        self.assertEqual(partner.tz, "Asia/Kolkata")
        # a date-grouped read in the user's time zone (what graphs / pivots do)
        groups = self.env["res.partner"].with_context(tz=partner.tz)._read_group(
            [("id", "=", partner.id)], ["create_date:day"], ["__count"]
        )
        self.assertEqual(len(groups), 1)
