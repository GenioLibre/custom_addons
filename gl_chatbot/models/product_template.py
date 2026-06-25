from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    chatbot_visible = fields.Boolean(
        string='Visible para chatbot',
        default=False,
        help='Si esta activo, este producto puede aparecer en las busquedas comerciales que haga la IA.',
    )
