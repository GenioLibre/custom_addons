# models/whatsapp_chatroom.py
from odoo import models, fields, api


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
    contenido = fields.Text(string='Contenido del Mensaje', required=True)
    activo = fields.Boolean(string='Activo', default=True)
    prioridad = fields.Integer(string='Prioridad', default=10)
