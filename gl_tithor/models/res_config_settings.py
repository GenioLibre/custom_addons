from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    """Inherits the model res.config.settings to add the field"""
    _inherit = 'res.config.settings'

    is_show_product_image_in_sale_report = fields.Boolean(
        string="Mostrar imagen del producto",
        config_parameter='sale_product_image.is_show_product_image_in_sale_report',
        help='Mostrar producto en el reporte de cotización')
