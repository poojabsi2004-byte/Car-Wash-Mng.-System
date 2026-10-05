/* global ApexCharts */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import {
    Component,
    onMounted,
    onPatched,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useRef,
    useState,
} from "@odoo/owl";

const AUTO_REFRESH_MS = 60000;
const THEME_KEY = "carwash_dashboard_theme";

const PERIODS = [
    { key: "today", label: "Today" },
    { key: "week", label: "7D" },
    { key: "month", label: "30D" },
    { key: "quarter", label: "90D" },
    { key: "year", label: "1Y" },
    { key: "custom", label: "Custom" },
];

const PERIOD_LABELS = {
    today: "Today",
    week: "Last 7 days",
    month: "Last 30 days",
    quarter: "Last 90 days",
    year: "Last 12 months",
    custom: "Selected range",
};

const PIPELINE_STAGES = [
    { key: "confirmed", label: "Booked", icon: "fa-calendar-check-o", hint: "Waiting to arrive" },
    { key: "arrived", label: "Arrived", icon: "fa-sign-in", hint: "Waiting for a bay" },
    { key: "in_service", label: "Washing", icon: "fa-tint", hint: "In a bay right now" },
    { key: "ready", label: "Ready", icon: "fa-flag-checkered", hint: "Waiting for pickup" },
];

// Chart palettes per theme - aqua/ocean family with a warm accent for contrast.
const PALETTE = {
    day: { aqua: "#0096c7", teal: "#14b8a6", deep: "#0a2540", coral: "#ff6b6b", amber: "#f59f00", violet: "#7c5cff", grid: "rgba(10,37,64,0.08)", text: "#5b7085" },
    night: { aqua: "#48cae4", teal: "#2dd4bf", deep: "#caf0f8", coral: "#ff8787", amber: "#ffc078", violet: "#a78bfa", grid: "rgba(255,255,255,0.07)", text: "#8aa3b8" },
};

function prefersReducedMotion() {
    return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function readStoredTheme() {
    try {
        const stored = window.localStorage.getItem(THEME_KEY);
        if (stored === "day" || stored === "night") {
            return stored;
        }
    } catch {
        // storage unavailable (private mode, blocked) - fall through to Odoo's scheme
    }
    return document.cookie.includes("color_scheme=dark") ? "night" : "day";
}

/**
 * Number that counts up/down to its new value (easeOutCubic).
 */
export class CwCount extends Component {
    static template = "carwash_dashboard.Count";
    static props = {
        value: { optional: true },
        format: { type: Function, optional: true },
        decimals: { type: Number, optional: true },
    };

    setup() {
        this.state = useState({ display: 0 });
        onMounted(() => this.animate(0, this.props.value || 0));
        onWillUpdateProps((next) => {
            if ((next.value || 0) !== (this.props.value || 0)) {
                this.animate(this.state.display, next.value || 0);
            }
        });
        onWillUnmount(() => cancelAnimationFrame(this.frame));
    }

    animate(from, to) {
        cancelAnimationFrame(this.frame);
        if (prefersReducedMotion() || from === to) {
            this.state.display = to;
            return;
        }
        const start = performance.now();
        const duration = 1100;
        const step = (now) => {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 3);
            this.state.display = from + (to - from) * eased;
            if (t < 1) {
                this.frame = requestAnimationFrame(step);
            } else {
                this.state.display = to;
            }
        };
        this.frame = requestAnimationFrame(step);
    }

    get text() {
        const value = this.state.display;
        if (this.props.format) {
            return this.props.format(value);
        }
        const decimals = this.props.decimals || 0;
        return value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    }
}

export class CarwashDashboard extends Component {
    static template = "carwash_dashboard.Dashboard";
    static components = { CwCount };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.periods = PERIODS;
        this.pipelineStages = PIPELINE_STAGES;
        this.bubbles = Array.from({ length: 14 }, (_, i) => ({
            id: i,
            style: `left:${(i * 7.3 + 3) % 100}%;--cw-size:${8 + ((i * 13) % 22)}px;--cw-delay:${(i * 0.9) % 9}s;--cw-dur:${9 + ((i * 5) % 8)}s;`,
        }));
        this.state = useState({
            data: null,
            period: "week",
            customFrom: "",
            customTo: "",
            lastUpdated: null,
            refreshing: false,
            theme: readStoredTheme(),
            clock: this.currentClock(),
            globalSearch: "",
            search: {
                pipeline: "",
                bays: "",
                jobcards: "",
                services: "",
                products: "",
                recent: "",
                branches: "",
                staff: "",
                memberships: "",
            },
        });
        this.formatMoney = this.formatMoney.bind(this);
        this.formatPercent = (v) => `${Math.round(v)}%`;
        this.formatMinutes = (v) => `${v.toFixed(1)}m`;

        this.root = useRef("root");
        this.globalSearchRef = useRef("globalSearch");
        this.chartRefs = {
            trend: useRef("trendChart"),
            hourly: useRef("hourlyChart"),
            services: useRef("servicesChart"),
            branches: useRef("branchChart"),
        };
        this.charts = [];
        this.chartsDirty = true;
        this.onKeydown = this.onKeydown.bind(this);

        onWillStart(() => this.fetchData());
        onMounted(() => {
            this.renderCharts();
            this.refreshTimer = setInterval(() => this.fetchData(), AUTO_REFRESH_MS);
            this.clockTimer = setInterval(() => (this.state.clock = this.currentClock()), 15000);
            document.addEventListener("keydown", this.onKeydown);
        });
        onPatched(() => {
            if (this.chartsDirty) {
                this.renderCharts();
            }
        });
        onWillUnmount(() => {
            clearInterval(this.refreshTimer);
            clearInterval(this.clockTimer);
            document.removeEventListener("keydown", this.onKeydown);
            this.destroyCharts();
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    async fetchData() {
        this.state.refreshing = true;
        const { period, customFrom, customTo } = this.state;
        try {
            this.state.data = await this.orm.call("carwash.dashboard", "get_dashboard_data", [
                period,
                period === "custom" ? customFrom || false : false,
                period === "custom" ? customTo || false : false,
            ]);
            this.state.lastUpdated = this.currentClock();
            this.chartsDirty = true;
        } finally {
            this.state.refreshing = false;
        }
    }

    async setPeriod(period) {
        this.state.period = period;
        if (period !== "custom") {
            await this.fetchData();
        }
    }

    async applyCustomRange() {
        if (this.state.customFrom && this.state.customTo) {
            await this.fetchData();
        }
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "night" ? "day" : "night";
        try {
            window.localStorage.setItem(THEME_KEY, this.state.theme);
        } catch {
            // not persisted - fine, it's a convenience
        }
        this.chartsDirty = true;
    }

    // ------------------------------------------------------------------
    // Search - every card has its own box; the hero search narrows all cards.
    // ------------------------------------------------------------------
    onKeydown(ev) {
        const target = ev.target;
        const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
        if (ev.key === "/" && !typing && this.globalSearchRef.el) {
            ev.preventDefault();
            this.globalSearchRef.el.focus();
        }
    }

    clearSearch(key) {
        if (key === "global") {
            this.state.globalSearch = "";
        } else {
            this.state.search[key] = "";
        }
    }

    matches(item, keys, cardKey) {
        const terms = [this.state.globalSearch, this.state.search[cardKey]]
            .map((t) => (t || "").trim().toLowerCase())
            .filter(Boolean);
        if (!terms.length) {
            return true;
        }
        const haystack = keys
            .map((k) => item[k])
            .filter((v) => v !== undefined && v !== null && v !== false)
            .join(" ")
            .toLowerCase();
        return terms.every((term) => haystack.includes(term));
    }

    filterList(list, keys, cardKey) {
        return (list || []).filter((item) => this.matches(item, keys, cardKey));
    }

    pipelineCards(stage) {
        return this.filterList(
            this.state.data.pipeline[stage],
            ["plate", "customer", "vehicle", "services", "bay", "name", "token"],
            "pipeline"
        );
    }

    get pipelineMatchCount() {
        return PIPELINE_STAGES.reduce((sum, s) => sum + this.pipelineCards(s.key).length, 0);
    }

    get filteredBays() {
        return (this.state.data.bays || []).filter((bay) =>
            this.matches(
                {
                    name: bay.name,
                    type: bay.type,
                    state: bay.state,
                    plate: bay.current && bay.current.plate,
                    customer: bay.current && bay.current.customer,
                    next: bay.next && bay.next.plate,
                },
                ["name", "type", "state", "plate", "customer", "next"],
                "bays"
            )
        );
    }

    get filteredJobcards() {
        return this.filterList(
            (this.state.data.jobcards || []).map((j) => ({ ...j, staffNames: j.staff.map((s) => s.name).join(" ") })),
            ["name", "plate", "customer", "bay", "stage_label", "staffNames"],
            "jobcards"
        );
    }

    get filteredServices() {
        return this.filterList(this.state.data.top_services, ["name"], "services");
    }

    get filteredProducts() {
        return this.filterList(this.state.data.top_products, ["name", "uom"], "products");
    }

    get filteredRecent() {
        return this.filterList(this.state.data.recent_done, ["name", "plate", "customer", "services"], "recent");
    }

    get filteredBranches() {
        return this.filterList(this.state.data.branch_breakdown, ["name"], "branches");
    }

    get filteredStaff() {
        return this.filterList(this.state.data.staff_leaderboard, ["name"], "staff");
    }

    get filteredMemberships() {
        return this.filterList(this.state.data.memberships, ["name", "customer", "plan", "next_billing"], "memberships");
    }

    get maxServiceRevenue() {
        return Math.max(1, ...(this.state.data.top_services || []).map((s) => s.revenue));
    }

    get maxStaffCompleted() {
        return Math.max(1, ...(this.state.data.staff_leaderboard || []).map((s) => s.completed));
    }

    // ------------------------------------------------------------------
    // Presentation helpers
    // ------------------------------------------------------------------
    currentClock() {
        return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    get greeting() {
        const hour = new Date().getHours();
        const first = (this.state.data.user_name || "").split(" ")[0];
        const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
        return first ? `${part}, ${first}` : part;
    }

    get periodLabel() {
        return PERIOD_LABELS[this.state.period] || "Selected period";
    }

    formatMoney(value) {
        const currency = (this.state.data && this.state.data.currency) || { symbol: "", position: "before" };
        const amount = (value || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
        return currency.position === "after" ? `${amount} ${currency.symbol}` : `${currency.symbol}${amount}`;
    }

    trendClass(change) {
        if (change === null || change === undefined) {
            return "o_cwd_trend_flat";
        }
        return change >= 0 ? "o_cwd_trend_up" : "o_cwd_trend_down";
    }

    trendIcon(change) {
        if (change === null || change === undefined) {
            return "fa-minus";
        }
        return change >= 0 ? "fa-arrow-up" : "fa-arrow-down";
    }

    trendText(change) {
        if (change === null || change === undefined) {
            return "no prior data";
        }
        return `${Math.abs(change)}% vs prev.`;
    }

    ringOffset(percent) {
        const circumference = 2 * Math.PI * 26;
        return circumference - (circumference * Math.max(0, Math.min(100, percent || 0))) / 100;
    }

    etaText(eta) {
        if (eta === null || eta === undefined) {
            return "";
        }
        return eta >= 0 ? `${eta} min left` : `${Math.abs(eta)} min over`;
    }

    stagger(index) {
        // cap the delay so long lists don't keep animating in for seconds
        return `--cw-i:${Math.min(index, 12)};`;
    }

    // ------------------------------------------------------------------
    // Charts
    // ------------------------------------------------------------------
    destroyCharts() {
        this.charts.forEach((chart) => chart.destroy());
        this.charts = [];
    }

    baseChart(type, height) {
        const p = PALETTE[this.state.theme];
        return {
            chart: {
                type,
                height,
                background: "transparent",
                toolbar: { show: false },
                fontFamily: "inherit",
                foreColor: p.text,
                animations: { enabled: !prefersReducedMotion(), easing: "easeinout", speed: 900 },
            },
            theme: { mode: this.state.theme === "night" ? "dark" : "light" },
            grid: { borderColor: p.grid, strokeDashArray: 4 },
            dataLabels: { enabled: false },
            tooltip: { theme: this.state.theme === "night" ? "dark" : "light" },
            legend: { labels: { colors: p.text } },
        };
    }

    mountChart(ref, options) {
        if (!ref.el || typeof ApexCharts === "undefined") {
            return;
        }
        ref.el.innerHTML = "";
        const chart = new ApexCharts(ref.el, options);
        chart.render();
        this.charts.push(chart);
    }

    renderCharts() {
        this.chartsDirty = false;
        this.destroyCharts();
        const data = this.state.data;
        if (!data) {
            return;
        }
        const p = PALETTE[this.state.theme];

        if (data.hourly_load) {
            const base = this.baseChart("bar", 230);
            this.mountChart(this.chartRefs.hourly, {
                ...base,
                series: [{ name: "Vehicles", data: data.hourly_load.values }],
                xaxis: { categories: data.hourly_load.labels, labels: { rotate: 0, hideOverlappingLabels: true } },
                yaxis: { labels: { formatter: (v) => Math.round(v) }, forceNiceScale: true, min: 0 },
                plotOptions: { bar: { borderRadius: 6, columnWidth: "55%" } },
                fill: {
                    type: "gradient",
                    gradient: { shade: "light", type: "vertical", gradientToColors: [p.teal], stops: [0, 100] },
                },
                colors: [p.aqua],
            });
        }

        if (data.revenue_trend) {
            const base = this.baseChart("line", 300);
            this.mountChart(this.chartRefs.trend, {
                ...base,
                series: [
                    { name: "Revenue", type: "area", data: data.revenue_trend.revenue },
                    { name: "Washes", type: "column", data: data.revenue_trend.washes },
                ],
                stroke: { curve: "smooth", width: [3, 0] },
                fill: {
                    type: ["gradient", "solid"],
                    opacity: [1, 0.85],
                    gradient: { shadeIntensity: 1, opacityFrom: 0.45, opacityTo: 0.02, stops: [0, 95] },
                },
                plotOptions: { bar: { borderRadius: 4, columnWidth: "35%" } },
                colors: [p.aqua, p.violet],
                xaxis: { categories: data.revenue_trend.labels, labels: { hideOverlappingLabels: true } },
                yaxis: [
                    { labels: { formatter: (v) => this.formatMoney(v) } },
                    { opposite: true, labels: { formatter: (v) => Math.round(v) }, min: 0, forceNiceScale: true },
                ],
                legend: { ...base.legend, position: "top", horizontalAlign: "right" },
                markers: { size: 0, hover: { size: 5 } },
            });
        }

        if (data.top_services && data.top_services.length) {
            const base = this.baseChart("donut", 260);
            this.mountChart(this.chartRefs.services, {
                ...base,
                series: data.top_services.map((s) => s.revenue),
                labels: data.top_services.map((s) => s.name),
                colors: [p.aqua, p.teal, p.violet, p.amber, p.coral, "#4dabf7", "#63e6be", "#b197fc"],
                stroke: { width: 0 },
                legend: { show: false },
                plotOptions: {
                    pie: {
                        donut: {
                            size: "72%",
                            labels: {
                                show: true,
                                value: { formatter: (v) => this.formatMoney(Number(v)) },
                                total: { show: true, label: "Revenue", formatter: () => this.formatMoney(data.revenue_period) },
                            },
                        },
                    },
                },
                tooltip: { ...base.tooltip, y: { formatter: (v) => this.formatMoney(v) } },
            });
        }

        if (data.branch_breakdown && data.branch_breakdown.length) {
            const base = this.baseChart("bar", Math.max(180, 60 + data.branch_breakdown.length * 44));
            this.mountChart(this.chartRefs.branches, {
                ...base,
                series: [{ name: "Revenue", data: data.branch_breakdown.map((b) => b.revenue) }],
                xaxis: { categories: data.branch_breakdown.map((b) => b.name), labels: { formatter: (v) => this.formatMoney(v) } },
                plotOptions: { bar: { horizontal: true, borderRadius: 6, barHeight: "55%", distributed: true } },
                colors: [p.teal, p.aqua, p.violet, p.amber, p.coral],
                legend: { show: false },
                tooltip: { ...base.tooltip, y: { formatter: (v) => this.formatMoney(v) } },
            });
        }
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------
    openAction(resModel, domain, name, views) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: views || [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: domain || [],
        });
    }

    openRecord(resModel, resId) {
        if (!resId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
        });
    }

    openNewAppointment() {
        this.actionService.doAction("carwash_base.action_carwash_appointment_new");
    }

    openQueue() {
        this.actionService.doAction("carwash_base.action_carwash_appointment_queue");
    }

    openStage(stage) {
        const label = PIPELINE_STAGES.find((s) => s.key === stage).label;
        this.openAction("carwash.appointment", [["state", "=", stage]], `Queue: ${label}`);
    }

    openBay(bay) {
        if (bay.current) {
            this.openRecord("carwash.appointment", bay.current.id);
        } else {
            this.openRecord("carwash.bay", bay.id);
        }
    }

    openBays(state) {
        this.openAction("carwash.bay", state ? [["state", "=", state]] : [], "Bays", [[false, "kanban"], [false, "list"], [false, "form"]]);
    }

    openJobcards(stage) {
        const domain = stage ? [["stages", "=", stage]] : [["stages", "not in", ["done", "cancel"]]];
        this.openAction("carwash.jobcard", domain, stage === "qc" ? "Pending QC" : "Job Cards");
    }

    openDoneInPeriod() {
        const data = this.state.data;
        this.openAction(
            "carwash.appointment",
            [["state", "=", "done"], ["done_at", ">=", data.period_from], ["done_at", "<=", `${data.period_to} 23:59:59`]],
            `Completed Washes (${this.periodLabel})`,
            [[false, "list"], [false, "kanban"], [false, "form"]]
        );
    }

    openTodayAppointments() {
        this.openAction("carwash.appointment", [["state", "not in", ["cancelled", "no_show"]]], "Bookings", [
            [false, "list"],
            [false, "kanban"],
            [false, "form"],
        ]);
    }

    openMemberships(domain, name) {
        this.openAction("carwash.membership", domain, name, [[false, "list"], [false, "kanban"], [false, "form"]]);
    }

    openLoyaltyCards() {
        this.openAction("loyalty.card", [], "Loyalty Cards", [[false, "list"], [false, "form"]]);
    }
}

registry.category("actions").add("carwash_dashboard", CarwashDashboard);
