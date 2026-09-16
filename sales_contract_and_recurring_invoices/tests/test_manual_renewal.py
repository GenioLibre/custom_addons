from datetime import date
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestManualRenewal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Renewal customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Annual service', 'type': 'service', 'lst_price': 100,
        })
        if not cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.env.company.id),
        ], limit=1):
            cls.env['account.journal'].create({
                'name': 'Renewal sales', 'code': 'RENEW', 'type': 'sale',
                'company_id': cls.env.company.id,
            })

    def _contract(self, **values):
        return self.env['subscription.contracts'].create({
            'name': 'Annual contract',
            'partner_id': self.partner.id,
            'date_start': date(2024, 9, 1),
            'recurring_period': 1,
            'recurring_period_interval': 'Years',
            'contract_line_ids': [Command.create({
                'product_id': self.product.id,
                'description': 'Agreed annual service',
                'qty_ordered': 2,
                'price_unit': 80,
                'discount': 10,
                'tax_ids': [Command.clear()],
            })],
            **values,
        })

    def test_expiration_waits_without_invoice_or_new_contract(self):
        contract = self._contract()
        old_date = contract.next_invoice_date
        with patch.object(fields.Date, 'today', return_value=date(2025, 9, 12)):
            contract.subscription_contract_state_change()
            contract.subscription_contract_state_change()
        self.assertEqual(contract.state, 'Expired Not Paid')
        self.assertEqual(contract.next_invoice_date, old_date)
        self.assertFalse(contract.invoice_ids)

    def test_repeated_renewal_keeps_same_contract_and_invoice_history(self):
        contract = self._contract()
        count = self.env['subscription.contracts'].search_count([])
        lines = contract.contract_line_ids
        original_start = contract.date_start
        with patch.object(fields.Date, 'today', return_value=date(2025, 9, 12)):
            action = contract.action_renew_contract()
            contract.subscription_contract_state_change()
            self.assertEqual(contract.state, 'Ongoing')
        self.assertEqual(action['res_id'], contract.id)
        self.assertEqual(contract.next_invoice_date, date(2026, 9, 1))
        invoice = contract.invoice_ids
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(invoice.contract_origin, contract.id)
        self.assertEqual(invoice.currency_id, contract.currency_id)
        self.assertEqual(invoice.invoice_line_ids.price_unit, 80)
        self.assertEqual(invoice.invoice_line_ids.quantity, 2)
        self.assertEqual(invoice.invoice_line_ids.discount, 10)
        self.assertEqual(contract.invoice_count, 1)
        self.assertTrue(contract.invoices_active)
        with patch.object(fields.Date, 'today', return_value=date(2026, 9, 12)):
            contract.subscription_contract_state_change()
            self.assertEqual(contract.state, 'Expired Not Paid')
            self.assertEqual(contract.next_invoice_date, date(2026, 9, 1))
            self.assertEqual(contract.invoice_ids, invoice)
            action = contract.action_renew_contract()
            self.assertEqual(contract.state, 'Ongoing')
        self.assertEqual(action['res_id'], contract.id)
        self.assertEqual(contract.next_invoice_date, date(2027, 9, 1))
        self.assertEqual(len(contract.invoice_ids), 2)
        self.assertEqual(contract.invoice_count, 2)
        self.assertIn(invoice, contract.invoice_ids)
        self.assertEqual(contract.date_start, original_start)
        self.assertEqual(contract.contract_line_ids, lines)
        self.assertEqual(self.env['subscription.contracts'].search_count([]), count)

    def test_cancelled_and_invalid_period_cannot_renew(self):
        contract = self._contract()
        contract.action_to_cancel()
        with self.assertRaises(UserError):
            contract.action_renew_contract()
        invalid = self._contract(recurring_period=0)
        with self.assertRaises(UserError):
            invalid.action_renew_contract()
        self.assertFalse(invalid.invoice_ids)

    def test_legacy_invoice_button_uses_renewal_flow(self):
        contract = self._contract()
        contract.action_generate_invoice()
        self.assertEqual(len(contract.invoice_ids), 1)
        self.assertEqual(contract.next_invoice_date, date(2026, 9, 1))

    def test_renewal_respects_period_and_leap_year(self):
        contract = self._contract(
            date_start=date(2023, 2, 28),
            next_invoice_date=date(2024, 2, 29),
        )
        contract.action_renew_contract()
        self.assertEqual(contract.next_invoice_date, date(2025, 2, 28))
        monthly = self._contract(
            recurring_period_interval='Months', next_invoice_date=date(2025, 1, 31),
        )
        monthly.action_renew_contract()
        self.assertEqual(monthly.next_invoice_date, date(2025, 2, 28))
