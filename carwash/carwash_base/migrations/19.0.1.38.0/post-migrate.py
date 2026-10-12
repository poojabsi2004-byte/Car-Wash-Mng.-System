"""The "Car Wash: ..." feature switches are given to everyone through Internal User while the feature is on
(Car Wash > Configuration > Settings) - they aren't personal rights. Remove the ones ticked directly on users, so the
Settings switch alone decides (a feature switched off is off for everyone)."""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM res_groups_users_rel rel
         USING res_groups g, ir_model_data d
         WHERE rel.gid = g.id AND d.model = 'res.groups' AND d.res_id = g.id
           AND d.module LIKE 'carwash\\_%%' AND g.privilege_id IS NULL
    """)
