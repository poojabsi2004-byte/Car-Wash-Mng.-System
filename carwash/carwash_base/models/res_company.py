import base64
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import file_open, html2plaintext

_logger = logging.getLogger(__name__)

CARWASH_REPORT_ICON = "carwash_base/static/description/icon.png"

# each branch numbers its documents on its own, with its code in front: CWB1/26/0001, CWB1/JC/26/0001...
CARWASH_BRANCH_SEQUENCES = {
    "carwash.appointment": "{code}/%(y)s/",
    "carwash.jobcard": "{code}/JC/%(y)s/",
    "carwash.inspection": "{code}/INS/%(y)s/",
    "carwash.consumable.request": "{code}/CR/%(range_year)s/",
}


class IrSequence(models.Model):
    _inherit = "ir.sequence"

    @api.model
    def _carwash_next_by_code(self, code, company=None):
        """Next number of the car wash document `code` in `company`'s (the branch's) own sequence - created on
        first use with the branch code as prefix."""
        company = (company or self.env.company).sudo()
        template = CARWASH_BRANCH_SEQUENCES.get(code)
        if not template:
            return self.next_by_code(code)
        Sequence = self.sudo()
        sequence = Sequence.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
        if not sequence:
            generic = Sequence.search([("code", "=", code), ("company_id", "=", False)], limit=1)
            sequence = Sequence.create({
                "name": f"{generic.name or code} - {company.name}",
                "code": code,
                "company_id": company.id,
                "prefix": template.format(code=company._carwash_branch_code()),
                "padding": generic.padding or 4,
                "use_date_range": generic.use_date_range,
            })
        return sequence._next()


class ResCompany(models.Model):
    _inherit = "res.company"

    carwash_code = fields.Char(
        string="Branch Code", size=8,
        help="Starts the numbers of this branch's bookings, job cards... (e.g. CWB1/26/0001). Each branch numbers "
        "its own documents. Empty: made from the branch name.",
    )

    @api.constrains("carwash_code")
    def _check_carwash_code(self):
        for company in self.filtered("carwash_code"):
            if not re.fullmatch(r"[A-Za-z0-9-]+", company.carwash_code):
                raise ValidationError(self.env._("The branch code can only have letters, digits and dashes."))
            if self.search_count([("id", "!=", company.id), ("carwash_code", "=ilike", company.carwash_code)]):
                raise ValidationError(self.env._("Branch code %s is already used by another branch.", company.carwash_code))

    def _carwash_branch_code(self):
        """The branch code, made from the name the first time: "Car Wash Branch 1" -> CWB1."""
        self.ensure_one()
        if not self.carwash_code:
            words = re.findall(r"[A-Za-z0-9]+", self.name or "")
            code = "".join(w if w.isdigit() else w[0] for w in words).upper()[:6] or "CW"
            base, number = code, 2
            while self.sudo().search_count([("id", "!=", self.id), ("carwash_code", "=ilike", code)]):
                code = f"{base[:5]}{number}"
                number += 1
            self.sudo().carwash_code = code
        return self.carwash_code.upper()

    def write(self, vals):
        res = super().write(vals)
        if vals.get("carwash_code"):
            # the branch's sequences carry on with the new code
            for company in self:
                for sequence in self.env["ir.sequence"].sudo().search([
                    ("company_id", "=", company.id), ("code", "in", list(CARWASH_BRANCH_SEQUENCES)),
                ]):
                    sequence.prefix = CARWASH_BRANCH_SEQUENCES[sequence.code].format(code=company.carwash_code.upper())
        return res

    def _carwash_report_chain(self):
        """The branch first, then its parent companies up to the main company."""
        self.ensure_one()
        chain = self.env["res.company"]
        company = self.sudo().with_context(bin_size=False)
        while company and company not in chain:
            chain |= company
            company = company.parent_id
        return chain

    def _carwash_report_logo(self):
        """Branch logo, else the parent company's; Odoo's "Your logo" placeholder is skipped
        and replaced by the Car Wash emblem. The emblem is stored in the database (module data), so the
        report never depends on the module folder at print time; no logo at all rather than an error."""
        placeholder = self._get_logo()
        for company in self._carwash_report_chain():
            if company.logo and company.logo != placeholder:
                return company.logo, False
        emblem = self.env.ref("carwash_base.carwash_report_emblem", raise_if_not_found=False)
        if emblem and emblem.sudo().datas:
            return emblem.sudo().datas, True
        try:
            with file_open(CARWASH_REPORT_ICON, "rb") as icon:
                return base64.b64encode(icon.read()), True
        except (OSError, ValueError):
            _logger.warning("Car Wash report emblem not found (%s) - printing without a logo.", CARWASH_REPORT_ICON)
            return False, True

    def _carwash_report_details(self):
        """Everything the Car Wash report header / footer prints about the branch.
        Contact details missing on a branch are taken from its parent company."""
        self.ensure_one()
        chain = self._carwash_report_chain()
        company = chain[:1]

        def first(field):
            return next((value for value in chain.mapped(field) if value), False)

        partner = company.partner_id
        address = [
            ", ".join(filter(None, [partner.street, partner.street2])),
            ", ".join(filter(None, [partner.city, partner.state_id.name, partner.zip, partner.country_id.name])),
        ]
        logo, is_emblem = company._carwash_report_logo()
        vat = first("vat")
        return {
            "name": company.name,
            "tagline": html2plaintext(company.report_header or "").strip(),
            "footer_note": html2plaintext(company.report_footer or "").strip(),
            "address_lines": [line for line in address if line],
            "phone": first("phone"),
            "email": first("email"),
            "website": (first("website") or "").replace("https://", "").replace("http://", "").rstrip("/"),
            "vat": vat,
            "vat_label": (first("country_id") or self.env["res.country"]).vat_label or "Tax ID",
            "logo": logo,
            "is_emblem": is_emblem,
            "printed_at": self._carwash_report_now(),
        }

    def _carwash_report_now(self):
        """Current time in the branch's timezone (its working-hours calendar), as printed on reports."""
        tz = self.resource_calendar_id.tz or self.env.user.tz or "UTC"
        now = fields.Datetime.context_timestamp(self.with_context(tz=tz), fields.Datetime.now())
        return now.strftime("%d %b, %y %I:%M %p")
