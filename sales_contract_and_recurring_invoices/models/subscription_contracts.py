# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools import date_utils
from odoo.tools.safe_eval import datetime
from dateutil.relativedelta import relativedelta

class SubscriptionContracts(models.Model):
    """ Model for subscription contracts """
    _name = 'subscription.contracts'
    _description = 'Subscription Contracts'
    _inherit = [
        'mail.thread',
        'mail.activity.mixin'
    ]

    name = fields.Char(string='Contract Name', required=True, help='Name of Contract')
    reference = fields.Char(string='Reference', help='Contract reference')
    partner_id = fields.Many2one('res.partner', string="Customer", help='Customer for this contract')
    recurring_period = fields.Integer(string='Recurring Period', help='Recurring period of '
                                                                      'subscription contract')
    recurring_period_interval = fields.Selection([
        ('Days', 'Days'),
        ('Weeks', 'Weeks'),
        ('Months', 'Months'),
        ('Years', 'Years'),
    ], help='Recurring interval of subscription contract')
    contract_reminder = fields.Integer(string='Contract Expiration Reminder (Days)', help='Expiry reminder of subscription contract in days.')
    recurring_invoice = fields.Integer(string='Recurring Invoice Interval (Days)', help='Recurring invoice interval in days')
    next_invoice_date = fields.Date(string='Next Invoice Date', store=True, compute='_compute_next_invoice_date', help='Date of next invoice')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.company.currency_id)
    date_start = fields.Date(string='Start Date', default=fields.Date.today(), help='Subscription contract start date')
    invoice_count = fields.Integer(store=True, compute='_compute_invoice_count', string='Invoice count', help='Number of invoices generated')
    date_end = fields.Date(string='End Date', help='Subscription End Date')
    current_reference = fields.Integer(compute='_compute_sale_order_lines', string='Current Subscription Id', help='Current Subscription id')
    lock = fields.Boolean(string='Lock', default=False, help='Lock subscription contract so that further'
                                                             ' modifications are not possible.')
    state = fields.Selection([
        ('New', 'New'),
        ('Ongoing', 'Ongoing'),
        ('Expire Soon', 'Expire Soon'),
        ('Expired', 'Expired'),
        ('Cancelled', 'Cancelled'),
    ], string='Stage', default='New', copy=False, tracking=True, readonly=True, help='Status of subscription contract')
    contract_line_ids = fields.One2many('subscription.contracts.line', 'subscription_contract_id', string='Contract lines', help='Products to be added in the contract')
    amount_total = fields.Monetary(string="Total", store=True, compute='_compute_amount_total', tracking=4, help='Total amount')
    sale_order_line_ids = fields.One2many('sale.order.line', 'contract_id', string='Sale Order Lines', help='Order lines of Sale Orders which belongs to this contract')
    note = fields.Html(string="Terms and conditions", help='Add any notes', translate=True)
    invoices_active = fields.Boolean('Invoice active', default=False, compute='_compute_invoice_active', help='Compute invoices are active or not')

    def action_to_confirm(self):
        """ Confirm the Contract """
        self.write({
                       'state': 'Ongoing'
                   })

    def action_to_cancel(self):
        """ Cancel the Contract """
        self.write({
                       'state': 'Cancelled'
                   })

    def action_generate_invoice(self):
        """ Generate invoice manually """

        self.ensure_one()

        if not self.next_invoice_date:
            return

        invoice_date = self.next_invoice_date

        self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': invoice_date,
            'invoice_date_due': invoice_date,
            'contract_origin': self.id,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': line.product_id.id,
                    'name': line.description,
                    'quantity': line.qty_ordered,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': [(6, 0, line.tax_ids.ids)],
                })
                for line in self.contract_line_ids
            ]
        })

        # 🔢 Actualizar contador
        self.invoice_count = self.env['account.move'].search_count([
            ('contract_origin', '=', self.id)
        ])

        # 📅 Avanzar próxima fecha
        interval = self.recurring_period or 1

        if self.recurring_period_interval == 'Days':
            self.next_invoice_date += relativedelta(days=interval)
        elif self.recurring_period_interval == 'Weeks':
            self.next_invoice_date += relativedelta(weeks=interval)
        elif self.recurring_period_interval == 'Months':
            self.next_invoice_date += relativedelta(months=interval)
        elif self.recurring_period_interval == 'Years':
            self.next_invoice_date += relativedelta(years=interval)

        # 🟢 Estado
        if self.state == 'New':
            self.state = 'Ongoing'

    def action_lock(self):
        """ Lock subscription contract """
        self.lock = True

    def action_to_unlock(self):
        """ Unlock subscription contract """
        self.lock = False

    def action_get_invoice(self):
        """ Access generated invoices """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'view_mode': 'list,form',
            'res_model': 'account.move',
            'domain': [
                ('contract_origin', '=', self.id)
            ],
        }

    @api.depends('contract_line_ids.sub_total')
    def _compute_amount_total(self):
        """ Compute total amount of Contract """
        for order in self:
            order_lines = order.contract_line_ids
            order.amount_total = sum(order_lines.mapped('sub_total'))

    @api.depends('partner_id')
    def _compute_invoice_count(self):
        """ Compute the count of invoices generated """
        self.invoice_count = self.env['account.move'].search_count([
            ('contract_origin', '=', self.id)
        ])

    @api.depends('invoices_active')
    def _compute_invoice_active(self):
        """ Check invoice count to display the invoice smart button """
        invoice_count = self.env['account.move'].search_count([
            ('contract_origin', '=', self.id)
        ])
        if invoice_count != 0:
            self.invoices_active = True
        else:
            self.invoices_active = False

    @api.onchange('date_start')
    def _onchange_date_start_clear_end(self):
        self.date_end = False

    @api.depends('date_start', 'recurring_period', 'recurring_period_interval')
    def _compute_next_invoice_date(self):
        for record in self:
            if not record.date_start or not record.recurring_period or not record.recurring_period_interval:
                record.next_invoice_date = record.date_start
                continue

            start = record.date_start
            interval = record.recurring_period

            if record.recurring_period_interval == 'Days':
                record.next_invoice_date = start + relativedelta(days=interval)
            elif record.recurring_period_interval == 'Weeks':
                record.next_invoice_date = start + relativedelta(weeks=interval)
            elif record.recurring_period_interval == 'Months':
                record.next_invoice_date = start + relativedelta(months=interval)
            elif record.recurring_period_interval == 'Years':
                record.next_invoice_date = start + relativedelta(years=interval)
            else:
                record.next_invoice_date = start

    @api.model
    def subscription_contract_state_change(self):
        """ Automatic invoice generation for subscription contracts """

        today = fields.Date.today()
        contracts = self.search([
            ('state', '!=', 'Cancelled')
        ])

        for rec in contracts:
            if not rec.next_invoice_date:
                continue

            # 🔁 Generar factura solo el día exacto
            if rec.next_invoice_date != today:
                continue

            # 🧾 Crear factura con líneas
            invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': rec.partner_id.id,
                'invoice_date': rec.next_invoice_date,
                'contract_origin': rec.id,
                'invoice_line_ids': [
                    (0, 0, {
                        'product_id': line.product_id.id,
                        'name': line.description,
                        'quantity': line.qty_ordered,
                        'price_unit': line.price_unit,
                        'discount': line.discount,
                        'tax_ids': line.tax_ids,
                    })
                    for line in rec.contract_line_ids
                ]
            })

            # 🔢 Actualizar contador
            rec.invoice_count = self.env['account.move'].search_count([
                ('contract_origin', '=', rec.id)
            ])

            # 📅 Avanzar próxima fecha de factura
            interval = rec.recurring_period or 1

            if rec.recurring_period_interval == 'Days':
                rec.next_invoice_date += relativedelta(days=interval)
            elif rec.recurring_period_interval == 'Weeks':
                rec.next_invoice_date += relativedelta(weeks=interval)
            elif rec.recurring_period_interval == 'Months':
                rec.next_invoice_date += relativedelta(months=interval)
            elif rec.recurring_period_interval == 'Years':
                rec.next_invoice_date += relativedelta(years=interval)

            # 🟢 Estado
            if rec.state == 'New':
                rec.state = 'Ongoing'

    @api.depends('current_reference')
    def _compute_sale_order_lines(self):
        """ Get sale order line of contract lines """
        print("sale order line compute", self.current_reference)
        self.current_reference = self.id

        product_id = self.contract_line_ids.mapped('product_id')
        sale_order_line = self.env['sale.order.line'].search([
            ('order_partner_id', '=', self.partner_id.id)
        ])
        print(sale_order_line)
        print("products", product_id)
        for rec in sale_order_line:
            if self.date_start <= datetime.datetime.date(rec.create_date) <= self.date_end:
                if rec.product_id in product_id:
                    rec.contract_id = self.id
