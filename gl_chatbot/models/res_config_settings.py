from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Inherits the model res.config.settings to add the field"""
    _inherit = 'res.config.settings'

    whatsapp_verify_token = fields.Char(string='Token de verificación ', config_parameter='whatsapp.verify_token')
    whatsapp_token_api = fields.Char(string='Token API (envío)', config_parameter='whatsapp.token_api')
    chatbot_connection_mode = fields.Selection(
        selection=[
            ('local', 'Servidor local'),
            ('openai', 'ChatGPT API'),
        ],
        string='Modo de conexión IA',
        config_parameter='gl_chatbot.connection_mode',
        default='local',
    )
    chatbot_local_url = fields.Char(
        string='Ruta local del modelo',
        config_parameter='gl_chatbot.local_url',
        default='http://192.168.1.130:11434/api/generate',
    )
    chatbot_local_model = fields.Char(
        string='Modelo local',
        config_parameter='gl_chatbot.local_model',
        default='gemma3:4b',
    )
    openai_api_key = fields.Char(string='Clave API de OpenAI', config_parameter='openai.api_key')
    openai_model = fields.Char(
        string='Modelo ChatGPT',
        config_parameter='gl_chatbot.openai_model',
        default='gpt-4.1-mini',
    )
    whatsapp_redirect_uri = fields.Char(string='Redirect URI', config_parameter='whatsapp.redirect_uri')

    is_show_product_image_in_sale_report = fields.Boolean(
        string="Mostrar imagen del producto",
        config_parameter='sale_product_image.is_show_product_image_in_sale_report',
        help='Mostrar producto en el reporte de cotización')
