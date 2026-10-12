OLD_TEMPLATES = (
    "checklist_template_booking_checkin",
    "checklist_template_inspection_pre",
    "checklist_template_inspection_post",
)


def migrate(cr, version):
    """The default checklists were rewritten for the car-wash workflow (car / two-wheeler).

    Data files marked noupdate never touch existing records, so archive the three templates
    shipped before and free their XML ids - the data file then creates the new ones. Records
    that already used an old template keep it (archived), nothing is deleted.
    """
    cr.execute(
        """
        UPDATE carwash_checklist_template template
           SET active = FALSE, is_default = FALSE
          FROM ir_model_data data
         WHERE data.model = 'carwash.checklist.template'
           AND data.res_id = template.id
           AND data.module = 'carwash_jobcard'
           AND data.name IN %s
        """,
        (OLD_TEMPLATES,),
    )
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'carwash_jobcard' AND model = 'carwash.checklist.template' AND name IN %s",
        (OLD_TEMPLATES,),
    )
