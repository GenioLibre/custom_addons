# models/whatsapp_chatroom.py
import json
import logging
import re
import unicodedata
from urllib import error, request as urlrequest

from odoo import models, fields, api
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class WhatsappChatroom(models.Model):
    _name = 'whatsapp.chatroom'
    _description = 'WhatsApp Chatroom'
    _rec_name = 'name'
    OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'

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

    @staticmethod
    def _normalize_text(text):
        text = unicodedata.normalize('NFKD', (text or '').lower())
        text = ''.join(char for char in text if not unicodedata.combining(char))
        return re.sub(r'[^a-z0-9\s]', ' ', text)

    def _extract_product_search_text(self, message_text):
        normalized_text = self._normalize_text(message_text)
        stopwords = {
            'a', 'al', 'algo', 'con', 'cuesta', 'cuestan', 'cuanto', 'cuantoo', 'cual', 'cuales',
            'de', 'del', 'el', 'en', 'es', 'esta', 'estan', 'hay', 'la', 'las', 'lo', 'los',
            'me', 'necesito', 'para', 'por', 'precio', 'precios', 'producto', 'productos', 'que',
            'quiero', 'sale', 'su', 'sus', 'tiene', 'tienen', 'un', 'una', 'unas', 'unos', 'valor',
            'vale', 'ver', 'y'
        }
        tokens = [token for token in normalized_text.split() if len(token) > 2 and token not in stopwords]
        return ' '.join(tokens).strip()

    def _find_matching_visible_products(self, message_text, limit=5):
        self.ensure_one()
        search_text = self._extract_product_search_text(message_text)
        ProductTemplate = self.env['product.template'].sudo()
        products = ProductTemplate.search([
            ('chatbot_visible', '=', True),
            ('active', '=', True),
        ], order='name asc')
        if not products:
            return ProductTemplate

        if not search_text:
            return products[:limit]

        search_tokens = search_text.split()
        scored_products = []
        for product in products:
            product_text = self._normalize_text(
                f"{product.display_name or ''} {product.name or ''} {product.default_code or ''}"
            )
            score = sum(1 for token in search_tokens if token in product_text)
            if score:
                scored_products.append((score, product.id))

        scored_products.sort(key=lambda item: (-item[0], item[1]))
        matched_ids = [product_id for _, product_id in scored_products[:limit]]
        return ProductTemplate.browse(matched_ids)

    def _build_product_price_response(self, auto_message, message_text):
        self.ensure_one()
        products = self._find_matching_visible_products(message_text)
        if not products:
            return auto_message.contenido or (
                "No encontre un producto visible para chatbot que coincida con tu consulta. "
                "¿Me indicas el nombre exacto?"
            )

        product_lines = []
        currency = self.env.company.currency_id
        for product in products:
            symbol = currency.symbol or ''
            price = f"{symbol}{product.list_price:.2f}"
            code = f" ({product.default_code})" if product.default_code else ""
            product_lines.append(f"- {product.display_name or product.name}{code}: {price}")

        intro = auto_message.contenido.strip() if auto_message.contenido else "Estos son los productos encontrados:"
        if '{products}' in intro:
            return intro.replace('{products}', "\n".join(product_lines))
        return f"{intro}\n" + "\n".join(product_lines)

    def _get_active_automatic_messages(self):
        self.ensure_one()
        automatic_messages = self.env.company.chatbot_automatic_message_ids.filtered('activo').sorted('prioridad')
        if not automatic_messages:
            automatic_messages = self.env['mensajes.automaticos'].sudo().search(
                [('activo', '=', True)],
                order='prioridad asc, id asc',
            )
        return automatic_messages

    def _get_automatic_reply(self, message_text):
        self.ensure_one()
        normalized_message = self._normalize_text(message_text)
        automatic_messages = self._get_active_automatic_messages()
        for auto_message in automatic_messages:
            keywords = auto_message._get_keywords()
            if not keywords:
                continue
            if not any(keyword in normalized_message for keyword in keywords):
                continue
            if auto_message.action_type == 'product_price':
                return self._build_product_price_response(auto_message, message_text)
            return auto_message.contenido
        return False

    def _call_local_ollama(self, prompt, num_predict=None, temperature=None):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        local_url = config.get_param('gl_chatbot.local_url')
        local_model = config.get_param('gl_chatbot.local_model') or 'qwen2.5:3b'
        ollama_temperature = float(config.get_param('gl_chatbot.ollama_temperature', default='0.2') or 0.2)
        ollama_top_p = float(config.get_param('gl_chatbot.ollama_top_p', default='0.8') or 0.8)
        ollama_num_ctx = max(int(config.get_param('gl_chatbot.ollama_num_ctx', default='2048') or 2048), 256)
        ollama_num_predict = max(int(config.get_param('gl_chatbot.ollama_num_predict', default='120') or 120), 1)
        timeout_seconds = max(self.env.company.chatbot_model_timeout or 120, 10)

        if not local_url:
            raise UserError("Configura la ruta local del modelo en Ajustes > Chatbot.")

        payload = {
            'model': local_model,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': ollama_temperature if temperature is None else temperature,
                'top_p': ollama_top_p,
                'num_ctx': ollama_num_ctx,
                'num_predict': num_predict or ollama_num_predict,
            },
        }
        req = urlrequest.Request(
            local_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
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

    def _call_openai_responses(self, prompt, instructions=None, temperature=None, max_output_tokens=None):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('openai.api_key')
        model = config.get_param('gl_chatbot.openai_model') or 'gpt-4.1-mini'
        timeout_seconds = max(self.env.company.chatbot_model_timeout or 120, 10)

        if not api_key:
            raise UserError("Configura la clave API de OpenAI en Ajustes > Chatbot.")

        payload = {
            'model': model,
            'input': prompt,
        }
        if instructions:
            payload['instructions'] = instructions
        if temperature is not None:
            payload['temperature'] = temperature
        if max_output_tokens:
            payload['max_output_tokens'] = max_output_tokens

        req = urlrequest.Request(
            self.OPENAI_RESPONSES_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
                raw_response = response.read().decode('utf-8')
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise UserError(f"OpenAI devolvio un error HTTP {exc.code}: {error_body}") from exc
        except error.URLError as exc:
            raise UserError(f"No se pudo conectar con OpenAI: {exc.reason}") from exc

        try:
            response_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise UserError("La respuesta de OpenAI no es JSON valido.") from exc

        reply_text = self._extract_openai_text(response_data)
        if not reply_text:
            raise UserError("OpenAI no devolvio texto para la respuesta sugerida.")
        return reply_text

    def _call_openai_workflow(self, prompt):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('openai.api_key')
        workflow_id = config.get_param('gl_chatbot.openai_workflow_id')
        agent_endpoint = config.get_param('gl_chatbot.openai_agent_endpoint')
        timeout_seconds = max(self.env.company.chatbot_model_timeout or 120, 10)

        if not workflow_id:
            raise UserError("Configura el workflow ID en Ajustes > Chatbot.")

        if not agent_endpoint:
            raise UserError("Configura el Agent Endpoint para ejecutar el workflow publicado.")

        if not api_key:
            raise UserError("Configura la clave API de OpenAI en Ajustes > Chatbot.")

        payload = {
            'message': prompt,
            'workflow_id': workflow_id,
        }
        req = urlrequest.Request(
            agent_endpoint,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            method='POST',
        )

        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as response:
                raw_response = response.read().decode('utf-8')
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise UserError(f"El backend del agente devolvio un error HTTP {exc.code}: {error_body}") from exc
        except error.URLError as exc:
            raise UserError(f"No se pudo conectar con el Agent Endpoint: {exc.reason}") from exc

        try:
            response_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise UserError("La respuesta del Agent Endpoint no es JSON valido.") from exc

        reply_text = (response_data.get('output_text') or '').strip()
        if not reply_text:
            raise UserError("El Agent Endpoint no devolvio output_text.")
        return reply_text

    def _extract_json_object(self, raw_text):
        raw_text = (raw_text or '').strip()
        if not raw_text:
            return {}
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw_text, re.S)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}

    def _classify_automatic_action_with_ai(self, message_text):
        self.ensure_one()
        automatic_messages = self._get_active_automatic_messages()
        if not automatic_messages:
            return {}

        automatic_message_lines = []
        for message in automatic_messages:
            automatic_message_lines.append(
                f"- id: {message.id} | nombre: {message.name} | tipo: {message.action_type} | "
                f"categoria: {message.category or ''} | palabras_clave: {message.trigger_keywords or ''}"
            )

        prompt = (
            "Eres un clasificador de intenciones para un chatbot comercial.\n"
            "Debes decidir si el mensaje del cliente debe usar un mensaje automatico, "
            "buscar precio de producto o pasar a respuesta libre.\n"
            "Responde SOLO JSON valido, sin explicacion.\n"
            "Formato:\n"
            "{\"action\":\"automatic_message|product_price|ai_reply\","
            "\"automatic_message_id\":123 o null,"
            "\"product_query\":\"texto corto o vacio\"}\n\n"
            "Mensajes automaticos disponibles:\n"
            f"{chr(10).join(automatic_message_lines)}\n\n"
            f"Mensaje del cliente: {message_text}\n"
            "Si la consulta encaja claramente con un mensaje automatico de tipo message, "
            "usa action=automatic_message y su id.\n"
            "Si la consulta pide precio, costo, valor o disponibilidad de un producto, "
            "usa action=product_price y en product_query pon el nombre probable del producto.\n"
            "Si no encaja claramente, usa action=ai_reply."
        )
        raw_reply = self._call_openai_workflow(
            prompt,
        )
        parsed_reply = self._extract_json_object(raw_reply)
        if not parsed_reply:
            _logger.info("No se pudo parsear clasificacion IA: %s", raw_reply)
        return parsed_reply

    def _resolve_incoming_reply(self, message_text):
        self.ensure_one()
        automatic_messages = self._get_active_automatic_messages()
        automatic_message_by_id = {message.id: message for message in automatic_messages}

        classification = self._classify_automatic_action_with_ai(message_text)
        action = classification.get('action')
        automatic_message_id = classification.get('automatic_message_id')
        if automatic_message_id:
            try:
                automatic_message_id = int(automatic_message_id)
            except (TypeError, ValueError):
                automatic_message_id = False

        if action == 'automatic_message' and automatic_message_id in automatic_message_by_id:
            return automatic_message_by_id[automatic_message_id].contenido

        if action == 'product_price':
            price_template = next(
                (message for message in automatic_messages if message.action_type == 'product_price'),
                False,
            )
            if price_template:
                return self._build_product_price_response(
                    price_template,
                    classification.get('product_query') or message_text,
                )

        automatic_reply = self._get_automatic_reply(message_text)
        if automatic_reply:
            return automatic_reply

        return self.generate_ai_reply()

    def _build_ai_prompt(self):
        self.ensure_one()
        company = self.env.company
        history_limit = max(company.chatbot_history_message_limit or 10, 1)
        system_prompt = company.chatbot_system_prompt or (
            "Eres un asistente comercial que ayuda a responder clientes desde Odoo. "
            "Responde en espanol, con tono claro, cordial y breve. "
            "No inventes datos. Usa primero la base de conocimiento proporcionada. "
            "Si falta contexto, pide una aclaracion de forma amable."
        )
        recent_messages = self.message_ids.sorted('timestamp')[-history_limit:]
        conversation_lines = []
        knowledge_documents = company.chatbot_knowledge_document_ids.filtered('active')
        database_queries = company.chatbot_database_query_ids.filtered('active')
        automatic_messages = self._get_active_automatic_messages()
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
            f"{system_prompt}\n\n"
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
        return self._call_local_ollama(self._build_ai_prompt())

    def _generate_openai_ai_reply(self):
        self.ensure_one()
        return self._call_openai_workflow(self._build_ai_prompt())

    def generate_ai_reply(self):
        self.ensure_one()
        return self._generate_openai_ai_reply()

    def simulate_client_message(self, message_text):
        self.ensure_one()
        return self.handle_incoming_message(
            phone_number=self.phone_number,
            message_text=message_text,
            message_type='text',
            sender='client',
        )

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

        if sender == 'client' and message_type == 'text':
            reply_text = chatroom._resolve_incoming_reply(message_text)
            if reply_text:
                chatroom.create_outgoing_message(reply_text, sender='bot', message_type='text')

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
    _order = 'prioridad, id'

    name = fields.Char(string='Nombre del Mensaje', required=True)
    category = fields.Char(string='Categoria')
    action_type = fields.Selection(
        [
            ('message', 'Mensaje directo'),
            ('product_price', 'Buscar precio de producto'),
        ],
        string='Tipo de accion',
        default='message',
        required=True,
    )
    trigger_keywords = fields.Text(
        string='Palabras clave',
        help='Escribe palabras o frases separadas por coma o por linea para activar esta regla.',
    )
    contenido = fields.Text(string='Contenido del Mensaje', required=True)
    activo = fields.Boolean(string='Activo', default=True)
    prioridad = fields.Integer(string='Prioridad', default=10)

    def _get_keywords(self):
        self.ensure_one()
        raw_keywords = self.trigger_keywords or ''
        if not raw_keywords.strip():
            return []
        return [
            ''.join(
                char for char in unicodedata.normalize('NFKD', keyword.strip().lower())
                if not unicodedata.combining(char)
            )
            for keyword in re.split(r'[\n,]+', raw_keywords)
            if keyword.strip()
        ]
