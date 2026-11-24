from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    price_tax = fields.Monetary(string="Impuesto", compute="_compute_price_tax", store=True, currency_field='currency_id')
    price_total_with_tax = fields.Monetary(string="Precio Total (c/IGV)", compute="_compute_price_total_with_tax", store=True, currency_field='currency_id')

    @api.depends('tax_id', 'price_unit', 'product_uom_qty', 'discount')
    def _compute_price_tax(self):
        for line in self:
            taxes = line.tax_id.compute_all(line.price_unit * (1 - (
                        line.discount or 0.0) / 100.0), line.order_id.currency_id, line.product_uom_qty, product=line.product_id, partner=line.order_id.partner_id)
            line.price_tax = sum(t['amount'] for t in taxes['taxes'])

    @api.depends('price_subtotal', 'price_tax')
    def _compute_price_total_with_tax(self):
        for line in self:
            line.price_total_with_tax = line.price_subtotal + line.price_tax

    contract_id = fields.Many2one('subscription.contracts', string='Contracts', help='For adding Contracts in sale order line')
