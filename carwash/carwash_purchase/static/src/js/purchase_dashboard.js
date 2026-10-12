import { patch } from "@web/core/utils/patch";

import { CarwashDashboard } from "@carwash_dashboard/js/carwash_dashboard";

patch(CarwashDashboard.prototype, {
    /** Create RFQs for Low Stock: one per supplier, for the selected branch(es). */
    async createLowStockRfqs() {
        const action = await this.orm.call("carwash.dashboard", "action_carwash_create_low_stock_rfqs", []);
        if (action) {
            await this.actionService.doAction(action);
        }
    },

    newRfq() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Request for Quotation",
            res_model: "purchase.order",
            views: [[false, "form"]],
            target: "current",
        });
    },

    openPurchases(kind) {
        const actions = {
            approve: "carwash_purchase.action_carwash_purchase_to_approve",
            rfq: "carwash_purchase.action_carwash_rfq",
            orders: "carwash_purchase.action_carwash_purchase_order",
            receipts: "carwash_purchase.action_carwash_receipt",
            dues: "carwash_purchase.action_carwash_supplier_due",
        };
        this.actionService.doAction(actions[kind]);
    },
});
