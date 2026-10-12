from odoo import api, fields, models

STOCK_STATUS = [("ok", "In Stock"), ("low", "Low Stock"), ("out", "Out of Stock")]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_carwash_consumable = fields.Boolean(
        string="Car Wash Consumable",
        help="Material used up by the car wash (shampoo, wax, cloths...): tracked per branch, "
        "consumed by services and issued through Consumable Requests.",
    )

    @api.onchange("is_carwash_consumable")
    def _onchange_is_carwash_consumable(self):
        for template in self.filtered("is_carwash_consumable"):
            template.type = "consu"
            template.is_storable = True


class ProductProduct(models.Model):
    _inherit = "product.product"

    carwash_branch_qty = fields.Float(
        compute="_compute_carwash_branch_stock", string="On Hand (Branch)", digits="Product Unit",
        help="Quantity in stock at the current branch's warehouse.",
    )
    carwash_min_qty = fields.Float(
        compute="_compute_carwash_branch_stock", inverse="_inverse_carwash_min_qty",
        string="Minimum Stock", digits="Product Unit",
        help="Below this quantity at the current branch the consumable is Low Stock (a reordering rule of the branch warehouse).",
    )
    carwash_stock_status = fields.Selection(
        STOCK_STATUS, compute="_compute_carwash_branch_stock", search="_search_carwash_stock_status", string="Stock Status"
    )

    def write(self, vals):
        # car wash managers set a consumable's minimum stock without needing product-admin rights;
        # any other product change still goes through the normal access rights
        if (
            set(vals) == {"carwash_min_qty"}
            and not self.env.su
            and self.env.user.has_group("carwash_base.group_carwash_manager")
            and all(self.mapped("is_carwash_consumable"))
        ):
            return super(ProductProduct, self.sudo()).write(vals)
        return super().write(vals)

    def _carwash_orderpoint(self, warehouse):
        self.ensure_one()
        return self.env["stock.warehouse.orderpoint"].sudo().search(
            [("product_id", "=", self.id), ("warehouse_id", "=", warehouse.id), ("location_id", "=", warehouse.lot_stock_id.id)],
            limit=1,
        )

    @api.depends_context("company")
    def _compute_carwash_branch_stock(self):
        warehouse = self.env.company._carwash_warehouse()
        quantities = {}
        if warehouse:
            quantities = {p.id: p.qty_available for p in self.sudo().with_context(warehouse_id=warehouse.id)}
        for product in self:
            qty = quantities.get(product.id, 0.0)
            minimum = product._carwash_orderpoint(warehouse).product_min_qty if warehouse else 0.0
            product.carwash_branch_qty = qty
            product.carwash_min_qty = minimum
            if qty <= 0:
                product.carwash_stock_status = "out"
            elif minimum and qty < minimum:
                product.carwash_stock_status = "low"
            else:
                product.carwash_stock_status = "ok"

    def _inverse_carwash_min_qty(self):
        warehouse = self.env.company._carwash_warehouse(create=True)
        for product in self:
            orderpoint = product._carwash_orderpoint(warehouse)
            if orderpoint:
                orderpoint.write({"product_min_qty": product.carwash_min_qty})
            elif product.carwash_min_qty:
                # manual trigger: no automatic procurement (no Purchase app needed) - it only defines the minimum
                self.env["stock.warehouse.orderpoint"].sudo().create({
                    "product_id": product.id,
                    "warehouse_id": warehouse.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "company_id": warehouse.company_id.id,
                    "product_min_qty": product.carwash_min_qty,
                    "product_max_qty": product.carwash_min_qty,
                    "trigger": "manual",
                })

    def _search_carwash_stock_status(self, operator, value):
        if operator not in ("=", "in"):
            raise NotImplementedError(self.env._("Unsupported search on Stock Status"))
        wanted = {value} if operator == "=" else set(value)
        consumables = self.search([("is_carwash_consumable", "=", True)])
        return [("id", "in", consumables.filtered(lambda p: p.carwash_stock_status in wanted).ids)]

    @api.model
    def _carwash_low_stock(self, companies):
        """[(branch, product, on hand, minimum)] of consumables below their minimum at `companies`."""
        result = []
        for company in companies:
            warehouse = company._carwash_warehouse()
            if not warehouse:
                continue
            orderpoints = self.env["stock.warehouse.orderpoint"].sudo().search([
                ("warehouse_id", "=", warehouse.id),
                ("product_id.is_carwash_consumable", "=", True),
                ("product_min_qty", ">", 0),
            ])
            for orderpoint in orderpoints:
                qty = orderpoint.product_id.sudo().with_context(warehouse_id=warehouse.id).qty_available
                if qty < orderpoint.product_min_qty:
                    result.append((company, orderpoint.product_id, qty, orderpoint.product_min_qty))
        return result

    @api.model
    def _cron_carwash_low_stock_alert(self):
        """Daily: a To-Do for the branch managers on each consumable that is below its minimum."""
        if not self.env["carwash.feature"]._enabled("carwash_consumable.group_carwash_consumable"):
            return
        manager_group = self.env.ref("carwash_base.group_carwash_manager")
        todo = self.env.ref("mail.mail_activity_data_todo")
        for company, product, qty, minimum in self._carwash_low_stock(self.env["res.company"].search([])):
            summary = self.env._("Low stock at %s", company.name)
            template = product.product_tmpl_id
            if template.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            managers = manager_group.all_user_ids.filtered(lambda u: company in u.company_ids and not u.share)
            for manager in managers[:3]:
                template.activity_schedule(
                    activity_type_id=todo.id,
                    summary=summary,
                    note=self.env._(
                        "%(product)s: %(qty)s %(uom)s left at %(branch)s (minimum %(min)s). Restock it.",
                        product=product.display_name, qty=round(qty, 2), uom=product.uom_id.name,
                        branch=company.name, min=minimum,
                    ),
                    user_id=manager.id,
                )


class CarwashServiceMaterialLine(models.Model):
    _inherit = "carwash.service.material.line"

    product_id = fields.Many2one(domain=[("is_carwash_consumable", "=", True)])
