# The Owner rules follow the company switcher (ir_rules.xml is noupdate - update the stored domains).
RULES = {
    'carwash_rule_branch_vehicle': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_bay': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_appointment': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_jobcard': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_inspection': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_membership': "[('company_id', 'in', company_ids + [False])]",
    'carwash_rule_branch_staff_commission': "[('company_id', 'in', company_ids)]",
}


def migrate(cr, version):
    for xmlid, domain in RULES.items():
        cr.execute(
            "UPDATE ir_rule SET domain_force = %s WHERE id = (SELECT res_id FROM ir_model_data "
            "WHERE module = 'carwash_multibranch' AND name = %s AND model = 'ir.rule')",
            (domain, xmlid),
        )
