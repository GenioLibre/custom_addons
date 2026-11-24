from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContractIntegration(TransactionCase):
    def test_contract_xml_ids(self):
        for name in (
            'model_subscription_contracts',
            'model_subscription_contracts_line',
            'action_report_subscription_contracts',
            'subscription_contracts_view_form',
            'ir_cron_refresh_contract_status',
            'portal_my_home_contracts',
        ):
            self.assertTrue(self.env.ref('gl_geniolibre.' + name))
        report = self.env.ref('gl_geniolibre.action_report_subscription_contracts')
        self.assertEqual(report.report_name, 'gl_geniolibre.report_subscription_contracts')

    def test_contract_cron_only_refreshes_status(self):
        cron = self.env.ref('gl_geniolibre.ir_cron_refresh_contract_status')
        self.assertEqual(cron.code, 'model.subscription_contract_state_change()')

    def test_portal_acl_does_not_grant_write(self):
        for name in (
            'access_subscription_contracts_portal',
            'access_subscription_contracts_line_portal',
            'access_product_product_portal',
            'access_product_template_portal',
            'access_uom_uom_portal',
        ):
            acl = self.env.ref('gl_geniolibre.' + name)
            self.assertFalse(acl.perm_write)
