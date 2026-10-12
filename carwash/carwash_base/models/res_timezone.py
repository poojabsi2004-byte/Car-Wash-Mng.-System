from odoo import api, models

# Old IANA alias -> current name. pytz knows both, but PostgreSQL servers without the "backward"
# tz data don't know the alias, which breaks every date-grouped report (graph / pivot by day)
# for users or calendars set to it.
TZ_ALIASES = {"Asia/Calcutta": "Asia/Kolkata"}


def _normalize_tz(vals):
    if vals.get("tz") in TZ_ALIASES:
        vals["tz"] = TZ_ALIASES[vals["tz"]]
    return vals


def fix_tz_aliases(cr):
    """Existing records on an alias (e.g. the admin, the company and its working hours, created by Odoo
    before the car wash modules were installed) move to the current name."""
    for table in ("res_partner", "resource_calendar", "resource_resource"):
        for alias, name in TZ_ALIASES.items():
            cr.execute(f"UPDATE {table} SET tz = %s WHERE tz = %s", [name, alias])  # noqa: S608 - fixed table names


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([_normalize_tz(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(_normalize_tz(vals))


class ResourceCalendar(models.Model):
    _inherit = "resource.calendar"

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([_normalize_tz(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(_normalize_tz(vals))


class ResourceResource(models.Model):
    _inherit = "resource.resource"

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([_normalize_tz(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(_normalize_tz(vals))

