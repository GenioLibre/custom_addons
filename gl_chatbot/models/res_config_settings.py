import json
from urllib import error, request as urlrequest

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    """Inherits the model res.config.settings to add the field"""
    _inherit = 'res.config.settings'

    OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'

    whatsapp_verify_token = fields.Char(string='Token de verificación ', config_parameter='whatsapp.verify_token')
    whatsapp_token_api = fields.Char(string='Token API (envío)', config_parameter='whatsapp.token_api')
    chatbot_connection_mode = fields.Selection(
        selection=[
            ('local', 'Servidor local'),
            ('openai', 'ChatGPT API'),
        ],
        string='Modo de conexión IA',
        config_parameter='gl_chatbot.connection_mode',
        default='openai',
    )
    chatbot_local_url = fields.Char(
        string='Ruta local del modelo',
        config_parameter='gl_chatbot.local_url',
        default='http://192.168.1.130:11434/api/generate',
    )
    chatbot_local_model = fields.Char(
        string='Modelo local',
        config_parameter='gl_chatbot.local_model',
        default='qwen2.5:3b',
    )
    chatbot_ollama_temperature = fields.Float(
        string='Temperature',
        config_parameter='gl_chatbot.ollama_temperature',
        default=0.2,
    )
    chatbot_ollama_top_p = fields.Float(
        string='Top P',
        config_parameter='gl_chatbot.ollama_top_p',
        default=0.8,
    )
    chatbot_ollama_num_ctx = fields.Integer(
        string='Contexto maximo',
        config_parameter='gl_chatbot.ollama_num_ctx',
        default=2048,
    )
    chatbot_ollama_num_predict = fields.Integer(
        string='Tokens de respuesta',
        config_parameter='gl_chatbot.ollama_num_predict',
        default=120,
    )
    openai_api_key = fields.Char(string='Clave API de OpenAI', config_parameter='openai.api_key')
    openai_model = fields.Char(
        string='Modelo ChatGPT',
        config_parameter='gl_chatbot.openai_model',
        default='gpt-4.1-mini',
    )
    openai_workflow_id = fields.Char(
        string='Workflow ID',
        config_parameter='gl_chatbot.openai_workflow_id',
        default='wf_6a0b5cd93f408190968609c6074e73710c6b6f2f8e703a12',
    )
    openai_agent_endpoint = fields.Char(
        string='Agent Endpoint',
        config_parameter='gl_chatbot.openai_agent_endpoint',
        help='Endpoint HTTP de tu backend que ejecuta el workflow publicado.',
    )
    chatbot_knowledge_document_ids = fields.Many2many(
        related='company_id.chatbot_knowledge_document_ids',
        readonly=False,
        string='Documentos de conocimiento',
    )
    chatbot_database_query_ids = fields.Many2many(
        related='company_id.chatbot_database_query_ids',
        readonly=False,
        string='Consultas de base de datos para IA',
    )
    chatbot_automatic_message_ids = fields.Many2many(
        related='company_id.chatbot_automatic_message_ids',
        readonly=False,
        string='Mensajes automáticos para IA',
    )
    chatbot_system_prompt = fields.Text(
        related='company_id.chatbot_system_prompt',
        readonly=False,
        string='Prompt base del chatbot',
    )
    chatbot_history_message_limit = fields.Integer(
        related='company_id.chatbot_history_message_limit',
        readonly=False,
        string='Mensajes de historial para IA',
    )
    chatbot_model_timeout = fields.Integer(
        related='company_id.chatbot_model_timeout',
        readonly=False,
        string='Timeout del modelo (segundos)',
    )
    whatsapp_redirect_uri = fields.Char(string='Redirect URI', config_parameter='whatsapp.redirect_uri')

    is_show_product_image_in_sale_report = fields.Boolean(
        string="Mostrar imagen del producto",
        config_parameter='sale_product_image.is_show_product_image_in_sale_report',
        help='Mostrar producto en el reporte de cotización')

    @staticmethod
    def _extract_openai_text(response_data):
        output_text = (response_data.get('output_text') or '').strip()
        if output_text:
            return output_text

        for item in response_data.get('output', []):
            if item.get('type') != 'message':
                continue
            for content in item.get('content', []):
                text_value = (content.get('text') or '').strip()
                if text_value:
                    return text_value
        return ''

    def _test_openai_connection(self):
        self.ensure_one()

        if not self.openai_api_key:
            raise UserError(_("Configura primero la clave API de OpenAI."))

        if not self.openai_model:
            raise UserError(_("Configura primero el modelo de OpenAI."))

        timeout_seconds = max(self.chatbot_model_timeout or 120, 10)
        payload = {
            'model': self.openai_model,
            'input': 'Responde solo con la palabra OK',
            'max_output_tokens': 20,
        }
        req = urlrequest.Request(
            self.OPENAI_RESPONSES_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.openai_api_key}',
            },
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
                raw_response = response.read().decode('utf-8')
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise UserError(_("OpenAI devolvio un error HTTP %(code)s: %(body)s", code=exc.code, body=error_body)) from exc
        except error.URLError as exc:
            raise UserError(_("No se pudo conectar con OpenAI: %(reason)s", reason=exc.reason)) from exc

        try:
            response_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise UserError(_("La respuesta de OpenAI no es JSON valido.")) from exc

        reply_text = self._extract_openai_text(response_data)
        if not reply_text:
            raise UserError(_("OpenAI no devolvio texto para la prueba."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Conexion exitosa'),
                'message': _('OpenAI respondio correctamente con el modelo %(model)s. Respuesta: %(reply)s', model=self.openai_model, reply=reply_text[:120]),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_test_ai_connection(self):
        self.ensure_one()
        if self.openai_agent_endpoint and self.openai_workflow_id:
            return self._test_agent_endpoint_connection()
        return self._test_openai_connection()

    def _test_agent_endpoint_connection(self):
        self.ensure_one()

        if not self.openai_api_key:
            raise UserError(_("Configura primero la clave API de OpenAI."))

        if not self.openai_workflow_id:
            raise UserError(_("Configura primero el workflow ID."))

        if not self.openai_agent_endpoint:
            raise UserError(_("Configura primero el Agent Endpoint."))

        timeout_seconds = max(self.chatbot_model_timeout or 120, 10)
        payload = {
            'message': 'Responde solo con la palabra OK',
            'workflow_id': self.openai_workflow_id,
        }
        req = urlrequest.Request(
            self.openai_agent_endpoint,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.openai_api_key}',
            },
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
                raw_response = response.read().decode('utf-8')
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise UserError(_("El backend del agente devolvio un error HTTP %(code)s: %(body)s", code=exc.code, body=error_body)) from exc
        except error.URLError as exc:
            raise UserError(_("No se pudo conectar con el Agent Endpoint: %(reason)s", reason=exc.reason)) from exc

        try:
            response_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise UserError(_("La respuesta del Agent Endpoint no es JSON valido.")) from exc

        reply_text = (response_data.get('output_text') or '').strip()
        if not reply_text:
            raise UserError(_("El Agent Endpoint no devolvio output_text."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Conexion exitosa'),
                'message': _('El workflow %(workflow)s respondio correctamente. Respuesta: %(reply)s', workflow=self.openai_workflow_id, reply=reply_text[:120]),
                'type': 'success',
                'sticky': False,
            },
        }
