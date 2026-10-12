from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestServicePackageBranches(TransactionCase):

    def test_package_with_branch_specific_service_readable_by_other_branch(self):
        """Packages are shared by every branch - their totals must not need access to each service product."""
        branch_a = self.env["res.company"].create({"name": "Pkg Branch A"})
        branch_b = self.env["res.company"].create({"name": "Pkg Branch B"})
        service = self.env["product.product"].create({
            "name": "Pkg Branch A Wash", "type": "service", "is_carwash_service": True,
            "list_price": 400, "company_id": branch_a.id,
        })
        package = self.env["carwash.service.package"].create({
            "name": "Pkg Combo", "price_type": "fixed", "fixed_price": 300,
            "line_ids": [(0, 0, {"product_id": service.id})],
        })
        manager_b = self.env["res.users"].create({
            "name": "Pkg Manager B", "login": "pkg_manager_b",
            "company_id": branch_b.id, "company_ids": [(6, 0, branch_b.ids)],
            "group_ids": [(6, 0, [self.env.ref("carwash_base.group_carwash_manager").id])],
        })
        self.env.invalidate_all()
        as_b = package.with_user(manager_b).with_context(allowed_company_ids=branch_b.ids)
        self.assertEqual((as_b.services_total, as_b.total_price, as_b.saving), (400, 300, 100))
