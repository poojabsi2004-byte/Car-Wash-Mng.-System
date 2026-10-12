from odoo import api, fields, models
from odoo.exceptions import UserError

# what a car wash buys (purchase type of products and purchase orders)
SUPPLY_TYPES = [
    ("consumable", "Consumables"),
    ("equipment", "Equipment & Spares"),
    ("maintenance", "Maintenance Service"),
]


class ProductCategory(models.Model):
    _inherit = "product.category"

    @api.model
    def _carwash_supplies_category(self):
        return self.env.ref("carwash_purchase.product_category_carwash_supplies", raise_if_not_found=False) or self.browse()

    def _carwash_set_average_cost(self, companies):
        """Average cost: every receipt from a supplier updates the product's cost (the consumable cost of a
        wash is counted with it)."""
        for company in companies:
            for category in self.with_company(company).sudo():
                if category.property_cost_method != "average":
                    category.property_cost_method = "average"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    carwash_supply_type = fields.Selection(
        SUPPLY_TYPES, string="Car Wash Purchase Type",
        help="What the car wash buys this as: Consumables (used up by the services), Equipment & Spares "
        "(machines and parts) or a Maintenance Service (repairs of the bays and machines).",
    )

    @api.onchange("is_carwash_consumable")
    def _onchange_carwash_consumable_supply_type(self):
        for template in self.filtered("is_carwash_consumable"):
            template.carwash_supply_type = "consumable"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("is_carwash_consumable") and not vals.get("carwash_supply_type"):
                vals["carwash_supply_type"] = "consumable"
        templates = super().create(vals_list)
        templates.filtered("carwash_supply_type")._carwash_setup_purchase_product()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if vals.get("is_carwash_consumable"):
            self.filtered(lambda t: not t.carwash_supply_type).write({"carwash_supply_type": "consumable"})
        elif vals.get("carwash_supply_type"):
            self.filtered("carwash_supply_type")._carwash_setup_purchase_product()
        return res

    def _carwash_setup_purchase_product(self):
        """A car wash purchase product: average cost (Car Wash Supplies category) and 18% GST where the
        accounting is Indian."""
        self._carwash_use_supplies_category(self)
        roots = self.env["res.company"].sudo().search([("parent_id", "=", False), ("chart_template", "=", "in")])
        roots._carwash_apply_gst_to_products(self)

    @api.model
    def _carwash_use_supplies_category(self, templates):
        """Car wash purchases in the generic "All" category move to Car Wash Supplies (average cost)."""
        category = self.env["product.category"]._carwash_supplies_category()
        if not category:
            return
        generic = templates.filtered(lambda t: t.categ_id != category and not t.categ_id.parent_id)
        if generic:
            generic.sudo().write({"categ_id": category.id})


class ProductProduct(models.Model):
    _inherit = "product.product"

    carwash_max_qty = fields.Float(
        compute="_compute_carwash_purchase_info", inverse="_inverse_carwash_max_qty",
        string="Reorder Up To", digits="Product Unit",
        help="When the branch is below its Minimum Stock, the RFQ orders enough to come back up to this quantity.",
    )
    def _carwash_seller(self, company=None):
        """The product's preferred supplier price at `company` (first valid line)."""
        self.ensure_one()
        company = company or self.env.company
        today = fields.Date.context_today(self)
        sellers = self.sudo().seller_ids.filtered(
            lambda s: (not s.company_id or s.company_id == company)
            and (not s.product_id or s.product_id == self)
            and (not s.date_end or s.date_end >= today)
        )
        return sellers.sorted(lambda s: (s.sequence, s.id))[:1]

    @api.depends_context("company")
    def _compute_carwash_purchase_info(self):
        company = self.env.company
        warehouse = company._carwash_warehouse() if self else False
        for product in self:
            orderpoint = product._carwash_orderpoint(warehouse) if warehouse and product.id else False
            product.carwash_max_qty = orderpoint.product_max_qty if orderpoint else 0.0

    def _inverse_carwash_max_qty(self):
        warehouse = self.env.company._carwash_warehouse(create=True)
        for product in self:
            orderpoint = product._carwash_orderpoint(warehouse)
            maximum = max(product.carwash_max_qty, orderpoint.product_min_qty if orderpoint else product.carwash_min_qty)
            if orderpoint:
                orderpoint.write({"product_max_qty": maximum})
            elif product.carwash_max_qty:
                self.env["stock.warehouse.orderpoint"].sudo().create({
                    "product_id": product.id,
                    "warehouse_id": warehouse.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "company_id": warehouse.company_id.id,
                    "product_min_qty": product.carwash_min_qty,
                    "product_max_qty": maximum,
                })

    def write(self, vals):
        # car wash managers set a consumable's minimum / reorder-up-to without product-admin rights
        if (
            vals and set(vals) <= {"carwash_min_qty", "carwash_max_qty"}
            and not self.env.su
            and self.env.user.has_group("carwash_base.group_carwash_manager")
            and all(self.mapped("is_carwash_consumable"))
        ):
            return super(ProductProduct, self.sudo()).write(vals)
        return super().write(vals)

    def action_carwash_order(self):
        """Order button: a new RFQ for this product from its preferred supplier at the current branch."""
        self.ensure_one()
        company = self.env.company
        seller = self._carwash_seller(company)
        quantity = max(seller.min_qty, 1.0)
        warehouse = company._carwash_warehouse()
        orderpoint = self._carwash_orderpoint(warehouse) if warehouse else False
        if orderpoint and orderpoint.product_max_qty:
            on_hand = self.sudo().with_context(warehouse_id=warehouse.id).qty_available
            quantity = max(orderpoint.product_max_qty - on_hand, quantity)
        line = {"product_id": self.id, "product_qty": quantity, "product_uom_id": self.uom_id.id}
        if seller:
            line["price_unit"] = seller.price  # lines given as defaults aren't priced by the form
        context = {
            "default_company_id": company.id,
            "default_order_line": [(0, 0, line)],
        }
        if seller:
            context["default_partner_id"] = seller.partner_id.id
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Request for Quotation"),
            "res_model": "purchase.order",
            "view_mode": "form",
            "views": [(False, "form")],
            "context": context,
        }

    def action_carwash_create_low_stock_rfqs(self):
        """Create RFQs for low stock (header button of the consumables list - called with the selected rows, which
        don't matter - and the dashboard): one per supplier, for the branch(es) selected in the company switcher."""
        if not self.env.user.has_group("carwash_base.group_carwash_manager"):
            raise UserError(self.env._("Only a Car Wash Manager can create the purchase orders for low stock."))
        orders, missing = self.env.companies._carwash_create_low_stock_rfqs()
        return self.env["purchase.order"]._carwash_rfq_result_action(orders, missing)
