import { registry } from "@web/core/registry";

const CARWASH_APP_XMLID = "carwash_base.menu_carwash_root";

/**
 * Flags <body> while the Car Wash app is open, so its navbar can wear the
 * dashboard's ocean gradient without restyling any other app.
 */
export const carwashNavbarThemeService = {
    dependencies: ["menu"],
    start(env, { menu }) {
        const apply = () => {
            const app = menu.getCurrentApp();
            document.body.classList.toggle("o_cw_app", Boolean(app && app.xmlid === CARWASH_APP_XMLID));
        };
        env.bus.addEventListener("MENUS:APP-CHANGED", apply);
        apply();
    },
};

registry.category("services").add("carwash_navbar_theme", carwashNavbarThemeService);
