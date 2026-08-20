from datetime import timedelta

from odoo import api, fields, models


class GlConfectionOrder(models.Model):
    _name = 'gl.confection.order'
    _description = 'Orden de Confección'
    _rec_name = 'name'

    name = fields.Char(string='Referencia', required=True, copy=False, default='Nuevo')
    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta', required=True)
    partner_id = fields.Many2one(related='sale_order_id.partner_id', string='Cliente', store=True, readonly=True)
    sale_date_order = fields.Datetime(related='sale_order_id.date_order', string='Fecha Orden', store=True, readonly=True)
    sale_amount_total = fields.Monetary(related='sale_order_id.amount_total', string='Total', readonly=True)
    currency_id = fields.Many2one(related='sale_order_id.currency_id', readonly=True)
    sale_order_line_ids = fields.One2many(related='sale_order_id.order_line', string='Orden de Venta', readonly=True)

    state = fields.Selection([
        ('design', 'Diseño'),
        ('printing', 'Impresión'),
        ('cutting', 'Corte'),
        ('sewing', 'Confección'),
        ('delivery', 'Delivery'),
        ('done', 'Cerrado'),
    ], string='Etapa', default='design', required=True, copy=False)
    sent_date = fields.Date(string='Enviado a Confección', default=fields.Date.context_today, copy=False, readonly=True)
    delivery_date = fields.Date(string='Fecha de Entrega', default=lambda self: self._get_default_delivery_date(), copy=False)
    schedule_status = fields.Selection([
        ('green', 'A tiempo'),
        ('yellow', 'Mitad del periodo'),
        ('orange', 'Preparar'),
        ('red', 'Entrega hoy'),
    ], string='Entrega', compute='_compute_schedule_status', store=False)
    delivery_days_left = fields.Char(string='Entrega', compute='_compute_schedule_status', store=False)

    design_file_ids = fields.Many2many(
        'ir.attachment',
        'gl_confection_design_attachment_rel',
        'confection_id',
        'attachment_id',
        string='Archivos',
        domain="[('mimetype', 'ilike', 'image/')]",
    )
    mockup_image = fields.Image(string='Mockup', compute='_compute_mockup_image')

    printing_file_ids = fields.Many2many(
        'ir.attachment',
        'gl_confection_printing_attachment_rel',
        'confection_id',
        'attachment_id',
        string='Ficha Técnica',
        domain="[('mimetype', 'ilike', 'image/')]",
    )
    printing_supplier_id = fields.Many2one('res.partner', string='Proveedor')
    printing_pickup_date = fields.Date(string='Fecha de Recojo')
    printing_notes = fields.Text(string='Notas')

    cut_location = fields.Char(string='Ubicación Cortes')
    final_location = fields.Char(string='Ubicación Final')
    sewing_photo = fields.Image(string='Foto')

    delivery_type = fields.Selection([
        ('shalom', 'Shalom'),
        ('motorizado', 'Motorizado'),
        ('recojo', 'Recojo'),
        ('otros', 'Otros'),
    ], string='Tipo')
    delivery_notes = fields.Text(string='Notas')
    delivery_voucher = fields.Image(string='Voucher')
    delivery_code = fields.Char(string='Código')
    done = fields.Boolean(string='Pedido Completo', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nuevo') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('gl.confection.order') or 'Nuevo'
        records = super().create(vals_list)
        for record in records.filtered(lambda r: r.sale_order_id and not r.design_file_ids):
            record.design_file_ids = [(6, 0, record.sale_order_id.camiseta_foto_ids.ids)]
        return records

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id and not self.design_file_ids:
            self.design_file_ids = [(6, 0, self.sale_order_id.camiseta_foto_ids.ids)]

    def _get_default_delivery_date(self):
        delivery_date = fields.Date.context_today(self)
        business_days = 0
        while business_days < 7:
            delivery_date += timedelta(days=1)
            if delivery_date.weekday() != 6:
                business_days += 1
        return delivery_date

    def action_next_stage(self):
        next_stage = {
            'design': 'printing',
            'printing': 'cutting',
            'cutting': 'sewing',
            'sewing': 'delivery',
        }
        for record in self:
            if record.done:
                continue
            record.state = next_stage.get(record.state, record.state)
        return True

    def action_previous_stage(self):
        previous_stage = {
            'printing': 'design',
            'cutting': 'printing',
            'sewing': 'cutting',
            'delivery': 'sewing',
        }
        for record in self:
            if record.done:
                continue
            record.state = previous_stage.get(record.state, record.state)
        return True

    def action_complete_order(self):
        for record in self:
            record.state = 'done'
            record.done = True
        return True

    def action_reopen_order(self):
        for record in self:
            record.state = 'delivery'
            record.done = False
        return True

    @api.depends('sent_date', 'delivery_date')
    def _compute_schedule_status(self):
        today = fields.Date.context_today(self)
        for record in self:
            if not record.sent_date or not record.delivery_date:
                record.schedule_status = False
                record.delivery_days_left = False
                continue

            if record.done:
                record.schedule_status = 'green'
                record.delivery_days_left = 'Completado'
                continue

            total_days = max((record.delivery_date - record.sent_date).days, 1)
            remaining_days = (record.delivery_date - today).days
            elapsed_days = max((today - record.sent_date).days, 0)

            if remaining_days <= 0:
                record.schedule_status = 'red'
            elif remaining_days <= 2:
                record.schedule_status = 'orange'
            elif elapsed_days >= total_days / 2:
                record.schedule_status = 'yellow'
            else:
                record.schedule_status = 'green'

            if remaining_days < 0:
                record.delivery_days_left = f"Vencido hace {abs(remaining_days)} día(s)"
            elif remaining_days == 0:
                record.delivery_days_left = "Entrega hoy"
            elif remaining_days == 1:
                record.delivery_days_left = "Falta 1 día"
            else:
                record.delivery_days_left = f"Faltan {remaining_days} días"

    @api.depends('design_file_ids', 'design_file_ids.datas', 'printing_file_ids', 'printing_file_ids.datas')
    def _compute_mockup_image(self):
        for record in self:
            image = record.design_file_ids[:1] or record.printing_file_ids[:1]
            record.mockup_image = image.datas if image else False
