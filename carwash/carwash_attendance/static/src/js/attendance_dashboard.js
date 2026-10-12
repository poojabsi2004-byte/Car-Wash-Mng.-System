import { useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

import { CarwashDashboard } from "@carwash_dashboard/js/carwash_dashboard";

// Cards visible at once in the "Staff Attendance" strip; more slide in from the right.
export const ATTENDANCE_VISIBLE = 5;

patch(CarwashDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        this.attendanceTrack = useRef("attendanceTrack");
        this.notification = useService("notification");
        this.state.attendanceBusy = false;
    },

    /** My Attendance: check the logged-in staff member in / out. */
    async checkInOut() {
        if (this.state.attendanceBusy) {
            return;
        }
        this.state.attendanceBusy = true;
        try {
            const mine = await this.orm.call("carwash.dashboard", "action_carwash_check_in_out", []);
            this.state.data.my_attendance = mine;
            this.notification.add(mine.checked_in ? `Checked in at ${mine.since}.` : "Checked out - see you next shift!", {
                type: mine.checked_in ? "success" : "info",
            });
        } finally {
            this.state.attendanceBusy = false;
        }
    },

    openMyAttendance() {
        this.actionService.doAction("carwash_attendance.action_carwash_my_attendance", {
            additionalContext: { search_default_myattendances: 1 },
        });
    },

    get attendanceVisible() {
        return ATTENDANCE_VISIBLE;
    },

    /** Slide the attendance strip one "page" (the visible width) left (-1) or right (+1). */
    scrollAttendance(direction) {
        const track = this.attendanceTrack.el;
        if (!track) {
            return;
        }
        const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        track.scrollBy({ left: direction * track.clientWidth, behavior: reduce ? "auto" : "smooth" });
    },

    openAttendances() {
        this.actionService.doAction("carwash_attendance.action_carwash_attendance");
    },

    openCheckedIn() {
        this.actionService.doAction("carwash_attendance.action_carwash_attendance", {
            additionalContext: { search_default_nocheckout: 1, search_default_carwash_today: 0 },
        });
    },
});
