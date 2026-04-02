import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppBotController(http.Controller):
    def _load_json_payload(self):
        raw_data = request.httprequest.data.decode('utf-8') if request.httprequest.data else '{}'
        return json.loads(raw_data or '{}')

    def _register_local_message(self, payload):
        phone_number = payload.get('phone_number') or payload.get('from')
        message_text = payload.get('message') or payload.get('message_text')
        message_type = payload.get('message_type', 'text')
        sender = payload.get('sender', 'client')
        timestamp = payload.get('timestamp')

        if not phone_number:
            return {
                'ok': False,
                'error': "El campo 'phone_number' es obligatorio.",
            }, 400

        if not message_text:
            return {
                'ok': False,
                'error': "El campo 'message' es obligatorio.",
            }, 400

        chatroom_id = request.env['whatsapp.chatroom'].sudo().handle_incoming_message(
            phone_number=phone_number,
            message_text=message_text,
            message_type=message_type,
            sender=sender,
            timestamp=timestamp,
        )
        return {
            'ok': True,
            'chatroom_id': chatroom_id,
            'phone_number': phone_number,
            'message': message_text,
        }, 200

    @http.route('/whatsapp/webhook', type='http', auth='public', csrf=False, methods=['GET'])
    def verify_webhook(self, **kwargs):
        verify_token = request.env['ir.config_parameter'].sudo().get_param('whatsapp.verify_token')
        mode = kwargs.get('hub.mode')
        token = kwargs.get('hub.verify_token')
        challenge = kwargs.get('hub.challenge')

        if mode == 'subscribe' and token == verify_token:
            return request.make_response(challenge, headers=[('Content-Type', 'text/plain')])
        else:
            return request.make_response("Token inválido", status=403)

    @http.route('/whatsapp/webhook', type='http', auth='public', csrf=False, methods=['POST'])
    def whatsapp_webhook_post(self, **kwargs):
        try:
            data = self._load_json_payload()
            _logger.info("Webhook recibido en /whatsapp/webhook:\n%s", json.dumps(data, indent=2))
            response_data, status = self._register_local_message(data)
            return request.make_response(
                json.dumps(response_data),
                status=status,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.exception("Error procesando el webhook local: %s", str(e))
            return request.make_response(
                json.dumps({'ok': False, 'error': str(e)}),
                status=500,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/whatsapp/webhook/local_test', type='http', auth='public', csrf=False, methods=['POST'])
    def whatsapp_webhook_local_test(self, **kwargs):
        try:
            data = self._load_json_payload()
            _logger.info("Prueba local recibida en /whatsapp/webhook/local_test:\n%s", json.dumps(data, indent=2))
            response_data, status = self._register_local_message(data)
            return request.make_response(
                json.dumps(response_data),
                status=status,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.exception("Error procesando la prueba local: %s", str(e))
            return request.make_response(
                json.dumps({'ok': False, 'error': str(e)}),
                status=500,
                headers=[('Content-Type', 'application/json')]
            )
