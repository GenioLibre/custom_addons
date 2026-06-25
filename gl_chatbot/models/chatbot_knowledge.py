import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class ChatbotKnowledgeDocument(models.Model):
    _name = 'chatbot.knowledge.document'
    _description = 'Documento de conocimiento del chatbot'
    _order = 'sequence, name'

    name = fields.Char(string='Titulo', required=True)
    category = fields.Char(string='Categoria')
    content = fields.Text(string='Contenido', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)


class ChatbotKnowledgeQuery(models.Model):
    _name = 'chatbot.knowledge.query'
    _description = 'Consulta de base de datos para el chatbot'
    _order = 'sequence, name'

    name = fields.Char(string='Titulo', required=True)
    category = fields.Char(string='Categoria')
    query_text = fields.Text(string='Consulta / Regla', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)

    def action_test_query(self):
        self.ensure_one()
        query = (self.query_text or '').strip().rstrip(';')

        if not query:
            raise UserError(_("Primero escribe una consulta SQL."))

        if not query.lower().startswith('select'):
            raise UserError(_("Solo se permiten consultas SELECT para la prueba."))

        limited_query = f"SELECT * FROM ({query}) AS chatbot_query LIMIT 10"

        try:
            self.env.cr.execute(limited_query)
            rows = self.env.cr.dictfetchall()
        except Exception as exc:
            raise UserError(_("Error al ejecutar la consulta: %(error)s", error=str(exc))) from exc

        preview = json.dumps(rows[:5], ensure_ascii=False, default=str)
        if len(preview) > 500:
            preview = f"{preview[:500]}..."

        _logger.info("Chatbot query test [%s]: %s", self.name, rows)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta ejecutada'),
                'message': _(
                    'Filas obtenidas: %(count)s. Vista previa: %(preview)s',
                    count=len(rows),
                    preview=preview or '[]',
                ),
                'type': 'success',
                'sticky': True,
            },
        }


class ResCompany(models.Model):
    _inherit = 'res.company'

    chatbot_system_prompt = fields.Text(
        string='Prompt base del chatbot',
        default=(
            "Eres un asistente comercial que ayuda a responder clientes desde Odoo. "
            "Responde en espanol, con tono claro, cordial y breve. "
            "No inventes datos. Usa primero la base de conocimiento proporcionada. "
            "Si algun mensaje automatico encaja con la intencion del cliente, puedes reutilizarlo o adaptarlo. "
            "Usa consultas de base de datos solo como referencia de lo que puede consultarse o verificarse. "
            "Si falta contexto, pide una aclaracion de forma amable."
        ),
        help='Instruccion principal que siempre se enviara al modelo antes de la conversacion.',
    )
    chatbot_history_message_limit = fields.Integer(
        string='Mensajes de historial para IA',
        default=10,
        help='Cantidad de mensajes recientes del chat que se enviaran al modelo.',
    )
    chatbot_model_timeout = fields.Integer(
        string='Timeout del modelo (segundos)',
        default=120,
        help='Tiempo maximo de espera para la respuesta de Ollama.',
    )

    chatbot_knowledge_document_ids = fields.Many2many(
        'chatbot.knowledge.document',
        'res_company_chatbot_knowledge_rel',
        'company_id',
        'document_id',
        string='Documentos del chatbot',
    )
    chatbot_database_query_ids = fields.Many2many(
        'chatbot.knowledge.query',
        'res_company_chatbot_query_rel',
        'company_id',
        'query_id',
        string='Consultas a la base de datos para IA',
        help='Selecciona las consultas, reglas o ejemplos de acceso a base de datos que la IA puede usar como referencia.',
    )
    chatbot_automatic_message_ids = fields.Many2many(
        'mensajes.automaticos',
        'res_company_chatbot_message_rel',
        'company_id',
        'message_id',
        string='Mensajes automáticos para IA',
        help='Selecciona los mensajes automáticos que la IA puede reutilizar o adaptar según la consulta del cliente.',
    )

    @api.model
    def action_open_chatbot_knowledge_base(self):
        company = self.env.company
        return {
            'type': 'ir.actions.act_window',
            'name': 'Base de Conocimiento',
            'res_model': 'res.company',
            'view_mode': 'form',
            'view_id': self.env.ref('gl_chatbot.view_chatbot_knowledge_company_form').id,
            'res_id': company.id,
            'target': 'current',
            'context': {
                'form_view_initial_mode': 'edit',
            },
        }
