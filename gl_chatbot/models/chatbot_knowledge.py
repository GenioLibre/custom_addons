from odoo import fields, models
from odoo import api


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


class ResCompany(models.Model):
    _inherit = 'res.company'

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
