from odoo import api, fields, models
from odoo.exceptions import UserError

# GST on car wash purchases (chemicals, equipment, spares and repair services are 18% GST in India):
# CGST 9% + SGST 9% within the state, IGST 18% between states (the Indian chart ships them archived)
GST_PURCHASE_TAX = "sgst_purchase_18"
GST_PURCHASE_TAX_INTERSTATE = "igst_purchase_18"


class ResCompany(models.Model):
    _inherit = "res.company"

    carwash_auto_rfq = fields.Boolean(
        string="Automatic RFQs for Low Stock",
        help="When a consumable drops below its minimum at this branch, an RFQ to its preferred supplier is created "
        "automatically (right away and by the daily scheduler). Off: the manager clicks Create RFQs for Low Stock.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        # a new branch values its car wash supplies at average purchase cost too
        self.env["product.category"]._carwash_supplies_category()._carwash_set_average_cost(companies)
        return companies

    def write(self, vals):
        res = super().write(vals)
        if "carwash_auto_rfq" in vals:
            self._carwash_sync_orderpoints()
        return res

    # ------------------------------------------------------------------
    # Low stock -> RFQs
    # ------------------------------------------------------------------
    def _carwash_orderpoints(self):
        """Minimum-stock rules of the branch's consumables (its warehouse)."""
        self.ensure_one()
        warehouse = self._carwash_warehouse()
        if not warehouse:
            return self.env["stock.warehouse.orderpoint"]
        return self.env["stock.warehouse.orderpoint"].sudo().with_context(active_test=False).search([
            ("warehouse_id", "=", warehouse.id),
            ("location_id", "=", warehouse.lot_stock_id.id),
            ("product_id.is_carwash_consumable", "=", True),
        ])

    def _carwash_sync_orderpoints(self):
        for company in self:
            company._carwash_orderpoints()._carwash_sync()

    def _carwash_create_low_stock_rfqs(self):
        """RFQs for the consumables below their minimum, one per supplier (Odoo groups the lines of a supplier
        in its open RFQ). Returns (RFQs, products without a supplier)."""
        orders = self.env["purchase.order"]
        missing = self.env["product.product"]
        for company in self:
            orderpoints = company._carwash_orderpoints().filtered(lambda op: op.active and op.product_min_qty > 0)
            if not orderpoints:
                continue
            orderpoints._carwash_sync()
            orderpoints = orderpoints.with_company(company)
            # below the minimum on hand; what is already on order (open RFQs) counts in the quantity to order
            low = orderpoints.filtered(lambda op: op.qty_on_hand < op.product_min_qty)
            with_supplier = low.filtered(lambda op: op.product_id._carwash_seller(company))
            missing |= (low - with_supplier).product_id
            to_order = with_supplier.filtered(lambda op: op.qty_to_order > 0)
            if to_order:
                to_order._procure_orderpoint_confirm(company_id=company, raise_user_error=False)
            if with_supplier:
                # the branch's open RFQs for these products (just created, or already waiting)
                orders |= self.env["purchase.order.line"].sudo().search([
                    ("product_id", "in", with_supplier.product_id.ids), ("order_id.company_id", "=", company.id),
                    ("order_id.state", "in", ("draft", "sent", "to approve")),
                ]).order_id
        return orders, missing

    def _carwash_auto_replenish(self):
        """Automatic RFQs right after stock went down (consumption, issue, wastage) - never blocks that step."""
        companies = self.filtered("carwash_auto_rfq")
        if not companies or not self.env["carwash.feature"]._enabled("carwash_purchase.group_carwash_purchase"):
            return
        try:
            with self.env.cr.savepoint():
                companies.sudo()._carwash_create_low_stock_rfqs()
        except Exception:  # noqa: BLE001 - replenishing must not stop the car wash; the daily scheduler retries
            pass

    # ------------------------------------------------------------------
    # GST (Indian accounting)
    # ------------------------------------------------------------------
    def _carwash_gst_ready(self):
        self.ensure_one()
        return self.root_id.chart_template == "in"

    def _carwash_setup_gst(self):
        """Indian accounting for the branch: country India, currency INR, the Indian chart of accounts with the
        GST taxes (CGST + SGST within the state, IGST between states) and 18% GST on the car wash purchases.
        Branches share the accounting (currency, chart, taxes) of their main company: it is set up there, for
        the main company and all its branches at once."""
        if not self.env.is_system():
            raise UserError(self.env._("Only an administrator can set up the accounting of a branch."))
        india = self.env.ref("base.in")
        inr = self.env.ref("base.INR")
        for root in self.root_id:
            if root.chart_template == "in":
                root._carwash_finish_gst()
                continue
            if root._existing_accounting():
                raise UserError(self.env._(
                    "%s already has accounting entries - its chart of accounts can't be changed any more. "
                    "Set up GST from Invoicing > Configuration > Settings instead.", root.name,
                ))
            states = (root | self.filtered(lambda c: c.root_id == root)).state_id.filtered(lambda s: s.country_id == india)
            if not states:
                raise UserError(self.env._(
                    "Set the State of %s (an Indian state) first - GST within the state (CGST + SGST) and between "
                    "states (IGST) depends on it.", self.filtered(lambda c: c.root_id == root)[:1].name or root.name,
                ))
            group = self.search([("id", "child_of", root.id)])
            for company in group.filtered(lambda c: c.country_id != india):
                company.country_id = india
            if root.state_id not in states:
                root.state_id = states[:1]
            if root.currency_id != inr:
                inr.sudo().active = True
                root.currency_id = inr  # the branches follow their main company
                group._carwash_align_pricelist_currency(inr)
            self.env["account.chart.template"].try_loading("in", root, install_demo=False)
            root = self.env["res.company"].browse(root.id)  # registry may have changed (l10n module install)
            root._carwash_finish_gst()

    def _carwash_finish_gst(self):
        """18% GST: active, the default purchase tax of the main company and its branches, and on the car wash
        purchase products."""
        self.ensure_one()
        gst = self._carwash_gst_tax(GST_PURCHASE_TAX)
        self._carwash_gst_tax(GST_PURCHASE_TAX_INTERSTATE)
        if gst:
            self.search([("id", "child_of", self.id)]).write({"account_purchase_tax_id": gst.id})
        self._carwash_apply_gst_to_products(replace_chart_default=True)

    def _carwash_align_pricelist_currency(self, currency):
        """The companies' price lists follow their new currency (shared ones once no company uses another one)."""
        Pricelist = self.env["product.pricelist"].sudo().with_context(active_test=False)
        own = Pricelist.search([("company_id", "in", self.ids), ("currency_id", "!=", currency.id)])
        own.write({"currency_id": currency.id})
        if not self.search([("currency_id", "!=", currency.id)]):
            Pricelist.search([("company_id", "=", False), ("currency_id", "!=", currency.id)]).write(
                {"currency_id": currency.id}
            )

    def _carwash_gst_tax(self, xmlid):
        """A GST tax of the (main) company's Indian chart, made active with its parts (CGST / SGST)."""
        self.ensure_one()
        tax = self.env.ref(f"account.{self.root_id.id}_{xmlid}", raise_if_not_found=False)
        if not tax:
            return self.env["account.tax"]
        tax = tax.sudo().with_context(active_test=False)
        (tax | tax.children_tax_ids).filtered(lambda t: not t.active).write({"active": True})
        return tax.with_context(active_test=True)

    def _carwash_apply_gst_to_products(self, templates=None, replace_chart_default=False):
        """18% GST on the car wash purchase products (or `templates`) that have no purchase tax of the company
        group yet. When GST is set up, the chart's default purchase tax it gave every product (5% GST) is
        replaced by the 18% too."""
        for root in self.root_id:
            tax = root._carwash_gst_tax(GST_PURCHASE_TAX)
            root._carwash_gst_tax(GST_PURCHASE_TAX_INTERSTATE)
            if not tax:
                continue
            group = self.search([("id", "child_of", root.id)])
            chart_default = self.env.ref(f"account.{root.id}_sgst_purchase_5", raise_if_not_found=False)
            products = templates.sudo() if templates is not None else self.env["product.template"].sudo().with_context(
                active_test=False).search([("carwash_supply_type", "!=", False)])
            for template in products.with_company(root).with_context(active_test=False):
                group_taxes = template.supplier_taxes_id.filtered(lambda t: t.company_id in group)
                if replace_chart_default and chart_default and group_taxes == chart_default:
                    template.supplier_taxes_id = [(3, chart_default.id), (4, tax.id)]
                elif not group_taxes:
                    template.supplier_taxes_id = [(4, tax.id)]
