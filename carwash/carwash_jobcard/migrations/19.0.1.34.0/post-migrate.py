"""The staff timesheet task of a job card now closes with it: Done when its booking is done, Cancelled when the job
card is cancelled. Bring the tasks of bookings / job cards that were already closed up to date."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    jobcards = env["carwash.jobcard"].with_context(active_test=False).search([("task_id", "!=", False)])
    jobcards.filtered(lambda j: j.stages != "cancel" and j.appointment_id.state == "done")._carwash_close_task("1_done")
    jobcards.filtered(lambda j: j.stages == "cancel")._carwash_close_task("1_canceled")
