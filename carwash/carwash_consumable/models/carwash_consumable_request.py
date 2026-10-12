from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

REQUEST_TYPES = [
    ("issue", "Floor Issue"),
    ("wastage", "Wastage / Damage"),
    ("return", "Return to Store"),
]
STATES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("approved", "Approved"),
    ("done", "Issued"),
    ("rejected", "Rejected"),
    ("cancel", "Cancelled"),
]


class CarwashConsumableRequest(models.Model):
    """Consumables taken from (or given back to) a branch's store outside the service recipes.

    Draft -> Submitted (staff) -> Approved (manager) -> Issued (stock moved) | Rejected / Cancelled.
    - Floor Issue: stock -> consumption (extra material for a bay / the floor),
    - Wastage / Damage: stock -> inventory loss (spilled, expired, broken),
    - Return to Store: consumption -> stock (unused material brought back).
    """

    _name = "carwash.consumable.request"
    _description = "Car Wash Consumable Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    request_type = fields.Selection(REQUEST_TYPES, string="Type", default="issue", required=True, tracking=True)
    state = fields.Selection(STATES, default="draft", required=True, tracking=True, copy=False, group_expand="_expand_states")
    company_id = fields.Many2one(
        "res.company", string="Branch", required=True, default=lambda self: self.env.company, tracking=True, index=True
    )
    requested_by_id = fields.Many2one("res.users", string="Requested By", default=lambda self: self.env.user,
                                      required=True, tracking=True)
    employee_id = fields.Many2one("hr.employee", string="For Staff", tracking=True,
                                  help="Staff member who takes the consumables (optional).")
    bay_id = fields.Many2one("carwash.bay", string="Bay", domain="[('company_id', '=', company_id)]", tracking=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    reason = fields.Text(help="Why it's needed / what happened (required for wastage).")
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False, tracking=True)
    issued_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    issue_date = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Text(readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("carwash.consumable.request.line", "request_id", string="Consumables", copy=True)
    move_ids = fields.One2many("stock.move", "carwash_consumable_request_id", string="Stock Moves",
                               groups="stock.group_stock_user")
    line_count = fields.Integer(compute="_compute_line_count")
    can_approve = fields.Boolean(compute="_compute_can_approve")

    @api.model
    def _expand_states(self, states, domain):
        return [key for key, _label in STATES if key not in ("cancel",)]

    @api.depends("line_ids")
    def _compute_line_count(self):
        for request in self:
            request.line_count = len(request.line_ids)

    def _compute_can_approve(self):
        is_manager = self.env.user.has_group("carwash_base.group_carwash_manager")
        for request in self:
            request.can_approve = is_manager

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
                vals["name"] = self.env["ir.sequence"]._carwash_next_by_code("carwash.consumable.request", company) or "New"
        return super().create(vals_list)

    def write(self, vals):
        # staff edit their own drafts; once submitted only managers change a request
        if (
            not self.env.su
            and not self.env.user.has_group("carwash_base.group_carwash_manager")
            and any(request.state != "draft" for request in self)
        ):
            raise UserError(self.env._("Only a Car Wash Manager can change a request after it's submitted."))
        return super().write(vals)

    def unlink(self):
        if any(request.state not in ("draft", "cancel") for request in self):
            raise UserError(self.env._("Only draft or cancelled requests can be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_manager(self):
        if not self.env.user.has_group("carwash_base.group_carwash_manager"):
            raise UserError(self.env._("Only a Car Wash Manager can approve, reject or issue consumable requests."))

    def action_submit(self):
        for request in self:
            if request.state != "draft":
                raise UserError(self.env._("Only draft requests can be submitted."))
            if not request.line_ids:
                raise UserError(self.env._("Add at least one consumable to %s.", request.name))
            if request.request_type == "wastage" and not (request.reason or "").strip():
                raise UserError(self.env._("Explain what happened (Reason) before reporting wastage."))
            request.state = "submitted"
            request._notify_managers()
        return True

    def _notify_managers(self):
        """A To-Do for the branch's car wash managers to approve the request."""
        self.ensure_one()
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        # sudo: staff submitting a request may not read the users of the manager group
        managers = self.env.ref("carwash_base.group_carwash_manager").sudo().all_user_ids.filtered(
            lambda u: self.company_id in u.company_ids and not u.share and u != self.env.user
        )
        for manager in managers[:3]:
            self.sudo().activity_schedule(
                activity_type_id=todo.id if todo else False,
                summary=self.env._("Approve consumable request"),
                user_id=manager.id,
            )

    def action_approve(self):
        self._check_manager()
        for request in self:
            if request.state != "submitted":
                raise UserError(self.env._("Only submitted requests can be approved."))
            request.write({"state": "approved", "approved_by_id": self.env.user.id})
            request.activity_ids.action_feedback(feedback=self.env._("Approved"))
        return True

    def action_reject(self):
        self._check_manager()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Reject Request"),
            "res_model": "carwash.consumable.request.reject",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_ids": [(6, 0, self.ids)]},
        }

    def _do_reject(self, reason):
        self._check_manager()
        for request in self:
            if request.state not in ("submitted", "approved"):
                raise UserError(self.env._("Only submitted or approved requests can be rejected."))
            request.write({"state": "rejected", "reject_reason": reason})
            request.activity_ids.action_feedback(feedback=self.env._("Rejected: %s", reason))
            request.message_post(body=self.env._("Rejected: %s", reason))

    def action_cancel(self):
        for request in self:
            if request.state in ("done",):
                raise UserError(self.env._("An issued request can't be cancelled - create a Return to Store instead."))
            request.state = "cancel"
            request.activity_ids.unlink()
        return True

    def action_reset_to_draft(self):
        self.filtered(lambda r: r.state in ("rejected", "cancel")).write({"state": "draft", "reject_reason": False})
        return True

    # ------------------------------------------------------------------
    # Issue: move the stock
    # ------------------------------------------------------------------
    def _locations(self, product, warehouse):
        """(source, destination) of a line of this request at the branch warehouse."""
        self.ensure_one()
        stock = warehouse.lot_stock_id
        consumption = product.with_company(self.company_id).property_stock_production
        loss = product.with_company(self.company_id).property_stock_inventory
        if self.request_type == "issue":
            return stock, consumption
        if self.request_type == "wastage":
            return stock, loss
        return consumption, stock

    def action_issue(self):
        self._check_manager()
        for request in self:
            if request.state != "approved":
                raise UserError(self.env._("Approve %s before issuing it.", request.name))
            warehouse = request.company_id._carwash_warehouse()
            if not warehouse:
                raise UserError(self.env._("%s has no warehouse - create one in Inventory first.", request.company_id.name))
            request._check_availability(warehouse)
            Move = self.env["stock.move"].sudo().with_company(request.company_id)
            vals_list = []
            for line in request.line_ids.filtered(lambda l: not float_is_zero(l.quantity, precision_rounding=l.uom_id.rounding)):
                source, destination = request._locations(line.product_id, warehouse)
                vals_list.append({
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.quantity,
                    "product_uom": line.uom_id.id,
                    "location_id": source.id,
                    "location_dest_id": destination.id,
                    "company_id": request.company_id.id,
                    "origin": request.name,
                    "carwash_consumable_request_id": request.id,
                })
            moves = Move.create(vals_list)
            moves._action_confirm()
            moves._action_assign()
            for move in moves:
                move.quantity = move.product_uom_qty
            moves.picked = True
            moves._action_done()
            request.write({"state": "done", "issued_by_id": self.env.user.id, "issue_date": fields.Datetime.now()})
            request.message_post(body=self.env._("%s issued.", dict(REQUEST_TYPES)[request.request_type]))
        return True

    def _check_availability(self, warehouse):
        """Floor issues and wastage can't take more than the branch has in stock."""
        self.ensure_one()
        if self.request_type == "return":
            return
        short = []
        for line in self.line_ids:
            available = line.product_id.sudo().with_context(warehouse_id=warehouse.id).qty_available
            needed = line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
            if float_compare(needed, available, precision_rounding=line.product_id.uom_id.rounding) > 0:
                short.append(self.env._(
                    "%(product)s: %(needed)s needed, %(available)s in stock",
                    product=line.product_id.display_name, needed=needed, available=available,
                ))
        if short:
            raise UserError(self.env._("Not enough stock at %(branch)s:\n%(lines)s", branch=self.company_id.name,
                                       lines="\n".join(short)))


class CarwashConsumableRequestLine(models.Model):
    _name = "carwash.consumable.request.line"
    _description = "Car Wash Consumable Request Line"

    request_id = fields.Many2one("carwash.consumable.request", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True)
    product_id = fields.Many2one(
        "product.product", string="Consumable", required=True,
        domain="[('is_carwash_consumable', '=', True)]",
    )
    quantity = fields.Float(required=True, default=1.0, digits="Product Unit")
    uom_id = fields.Many2one(
        "uom.uom", string="Unit", compute="_compute_uom_id", store=True, readonly=False, required=True, precompute=True,
    )
    available_qty = fields.Float(compute="_compute_available_qty", string="In Stock", digits="Product Unit")
    note = fields.Char()

    _quantity_positive = models.Constraint("CHECK(quantity > 0)", "The quantity must be positive.")

    @api.depends("product_id")
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.depends("product_id", "request_id.company_id")
    def _compute_available_qty(self):
        for line in self:
            warehouse = line.request_id.company_id._carwash_warehouse() if line.request_id.company_id else False
            # sudo: staff without Inventory rights still see how much the store has (read-only figure)
            line.available_qty = (
                line.product_id.sudo().with_context(warehouse_id=warehouse.id).qty_available
                if warehouse and line.product_id else 0.0
            )


class CarwashConsumableRequestReject(models.TransientModel):
    _name = "carwash.consumable.request.reject"
    _description = "Reject Consumable Request"

    request_ids = fields.Many2many("carwash.consumable.request", "carwash_cons_request_reject_rel", "wizard_id", "request_id")
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.request_ids._do_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
