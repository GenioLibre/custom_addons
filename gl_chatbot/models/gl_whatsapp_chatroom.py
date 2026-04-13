# models/whatsapp_chatroom.py
import json
from urllib import error, request as urlrequest

from odoo import models, fields, api
from odoo.exceptions import UserError


class WhatsappChatroom(models.Model):
    _name = 'whatsapp.chatroom'
    _description = 'WhatsApp Chatroom'
    _rec_name = 'name'

    name = fields.Char(string='Chat Name', required=True)
    phone_number = fields.Char(string='Phone Number', required=True, help="Número de teléfono del cliente.")
    partner_id = fields.Many2one('res.partner', string='Cliente')
    last_message = fields.Text(string='Último Mensaje')
    last_message_time = fields.Datetime(string='Hora del Último Mensaje')
    message_ids = fields.One2many('whatsapp.chatmessage', 'chatroom_id', string='Mensajes')
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('open', 'Abierto'),
        ('closed', 'Cerrado'),
    ], string='Estado', default='open')
    has_partner = fields.Boolean(compute="_compute_has_partner", string="Tiene Cliente")

    @api.depends('partner_id')
    def _compute_has_partner(self):
        for record in self:
            record.has_partner = bool(record.partner_id)

    def set_closed(self):
        for record in self:
            record.state = 'closed'

    def set_open(self):
        for record in self:
            record.state = 'open'

    def create_outgoing_message(self, message_text, sender='bot', message_type='text'):
        self.ensure_one()
        timestamp = fields.Datetime.now()

        self.write({
            'last_message': message_text,
            'last_message_time': timestamp,
            'state': 'open',
        })

        message = self.env['whatsapp.chatmessage'].create({
            'chatroom_id': self.id,
            'sender': sender,
            'message': message_text,
            'message_type': message_type,
            'timestamp': timestamp,
        })

        return message.id

    def _build_ai_prompt(self):
        self.ensure_one()
        recent_messages = self.message_ids.sorted('timestamp')[-10:]
        conversation_lines = []
        knowledge_documents = self.env.company.chatbot_knowledge_document_ids.filtered('active')
        database_queries = self.env.company.chatbot_database_query_ids.filtered('active')
        automatic_messages = self.env.company.chatbot_automatic_message_ids.filtered('activo')
        sender_labels = {
            'client': 'Cliente',
            'user': 'Agente',
            'bot': 'Bot',
        }
        for message in recent_messages:
            sender_label = sender_labels.get(message.sender, message.sender or 'Sistema')
            conversation_lines.append(f"{sender_label}: {message.message or ''}")

        conversation_text = "\n".join(conversation_lines) if conversation_lines else "No hay mensajes previos."
        knowledge_text = "\n\n".join(
            f"{document.name}:\n{document.content}"
            for document in knowledge_documents
        ) if knowledge_documents else "No hay documentos de conocimiento configurados."
        database_query_text = "\n\n".join(
            f"{query.name}:\n{query.query_text}"
            for query in database_queries
        ) if database_queries else "No hay consultas de base de datos configuradas."
        automatic_message_text = "\n\n".join(
            f"{message.name}:\n{message.contenido}"
            for message in automatic_messages
        ) if automatic_messages else "No hay mensajes automaticos configurados."
        return (
            "Eres un asistente comercial que ayuda a responder clientes desde Odoo. "
            "Responde en espanol, con tono claro, cordial y breve. "
            "No inventes datos. Usa primero la base de conocimiento proporcionada. "
            "Si algun mensaje automatico encaja con la intencion del cliente, puedes reutilizarlo o adaptarlo. "
            "Usa consultas de base de datos solo como referencia de lo que puede consultarse o verificarse. "
            "Si falta contexto, pide una aclaracion de forma amable.\n\n"
            f"Cliente: {self.name or self.phone_number}\n"
            f"Telefono: {self.phone_number}\n\n"
            "Base de conocimiento:\n"
            f"{knowledge_text}\n\n"
            "Consultas de base de datos permitidas o sugeridas:\n"
            f"{database_query_text}\n\n"
            "Mensajes automaticos disponibles:\n"
            f"{automatic_message_text}\n\n"
            "Conversacion reciente:\n"
            f"{conversation_text}\n\n"
            "Genera una propuesta de respuesta lista para enviar al cliente."
        )

    def _generate_local_ai_reply(self):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        local_url = config.get_param('gl_chatbot.local_url')
        local_model = config.get_param('gl_chatbot.local_model') or 'gemma3:4b'

        if not local_url:
            raise UserError("Configura la ruta local del modelo en Ajustes > Chatbot.")

        payload = {
            'model': local_model,
            'prompt': self._build_ai_prompt(),
            'stream': False,
        }
        req = urlrequest.Request(
            local_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=60) as response:
                raw_response = response.read().decode('utf-8')
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise UserError(f"Ollama devolvio un error HTTP {exc.code}: {error_body}") from exc
        except error.URLError as exc:
            raise UserError(f"No se pudo conectar con Ollama en {local_url}: {exc.reason}") from exc

        try:
            response_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise UserError("La respuesta de Ollama no es JSON valido.") from exc

        reply_text = (response_data.get('response') or '').strip()
        if not reply_text:
            raise UserError("Ollama no devolvio texto para la respuesta sugerida.")
        return reply_text

    def generate_ai_reply(self):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        connection_mode = config.get_param('gl_chatbot.connection_mode', default='local')

        if connection_mode != 'local':
            raise UserError("Por ahora este chatbot solo genera respuestas con el modo local.")

        return self._generate_local_ai_reply()

    @api.model
    def handle_incoming_message(self, phone_number, message_text, message_type='text', sender='client', timestamp=None, external_message_id=None, media_url=None, media_filename=None, media_mimetype=None):
        if not timestamp:
            timestamp = fields.Datetime.now()

        chatroom = self.search([
            ('phone_number', '=', phone_number)
        ], limit=1)
        if not chatroom:
            chatroom = self.create({
                'name': f"Chat con {phone_number}",
                'phone_number': phone_number,
                'state': 'open',
                'last_message': message_text,
                'last_message_time': timestamp,
            })
        else:
            chatroom.write({
                'last_message': message_text,
                'last_message_time': timestamp,
                'state': 'open',
            })

        self.env['whatsapp.chatmessage'].create({
            'chatroom_id': chatroom.id,
            'sender': sender,
            'message': message_text,
            'message_type': message_type,
            'timestamp': timestamp,
            'external_message_id': external_message_id,
            'media_url': media_url,
            'media_filename': media_filename,
            'media_mimetype': media_mimetype,
        })

        return chatroom.id


class WhatsappChatMessage(models.Model):
    _name = 'whatsapp.chatmessage'
    _description = 'Mensaje de WhatsApp'
    _order = 'timestamp asc'

    chatroom_id = fields.Many2one('whatsapp.chatroom', string='Chatroom', ondelete='cascade')
    sender = fields.Selection([
        ('user', 'Usuario'),
        ('bot', 'Bot'),
        ('client', 'Cliente')
    ], string='Remitente')
    message = fields.Text(string='Mensaje')
    timestamp = fields.Datetime(string='Fecha y Hora')
    message_type = fields.Selection([
        ('text', 'Texto'),
        ('image', 'Imagen'),
        ('file', 'Archivo'),
        ('audio', 'Audio'),
        ('video', 'Video'),
    ], string='Tipo de Mensaje', default='text')

    external_message_id = fields.Char(string="ID del Mensaje en WhatsApp", index=True)
    media_url = fields.Char(string="URL del Archivo/Multimedia")
    media_filename = fields.Char(string="Nombre del Archivo")
    media_mimetype = fields.Char(string="Tipo MIME")


class MensajesAutomaticos(models.Model):
    _name = 'mensajes.automaticos'
    _description = 'Mensajes Automáticos para Chatbot'

    name = fields.Char(string='Nombre del Mensaje', required=True)
    category = fields.Char(string='Categoria')
    contenido = fields.Text(string='Contenido del Mensaje', required=True)
    activo = fields.Boolean(string='Activo', default=True)
    prioridad = fields.Integer(string='Prioridad', default=10)
