# -*- coding: utf-8 -*-
import json

from odoo import http
from odoo.http import request


class ChatbotAgentController(http.Controller):
    @staticmethod
    def _load_json_payload():
        raw_data = request.httprequest.data.decode('utf-8') if request.httprequest.data else '{}'
        return json.loads(raw_data or '{}')

    @http.route('/agent/reply', type='http', auth='public', csrf=False, methods=['POST'])
    def agent_reply(self, **kwargs):
        try:
            data = self._load_json_payload()
        except json.JSONDecodeError:
            return request.make_response(
                json.dumps({'ok': False, 'error': 'JSON invalido'}),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        message_text = (data.get('message') or '').strip()
        phone_number = (data.get('phone_number') or 'agent-test-user').strip()

        if not message_text:
            return request.make_response(
                json.dumps({'ok': False, 'error': "El campo 'message' es obligatorio."}),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        Chatroom = request.env['whatsapp.chatroom'].sudo()
        chatroom = Chatroom.search([('phone_number', '=', phone_number)], limit=1)
        if not chatroom:
            chatroom = Chatroom.create({
                'name': f"Chat con {phone_number}",
                'phone_number': phone_number,
                'state': 'open',
            })

        try:
            reply_text = chatroom._resolve_incoming_reply(message_text)
        except Exception as exc:
            return request.make_response(
                json.dumps({'ok': False, 'error': str(exc)}),
                status=500,
                headers=[('Content-Type', 'application/json')]
            )

        if reply_text:
            request.env['whatsapp.chatmessage'].sudo().create({
                'chatroom_id': chatroom.id,
                'sender': 'client',
                'message': message_text,
                'message_type': 'text',
            })
            chatroom.create_outgoing_message(reply_text, sender='bot', message_type='text')

        return request.make_response(
            json.dumps({
                'ok': True,
                'chatroom_id': chatroom.id,
                'phone_number': phone_number,
                'output_text': reply_text or '',
            }),
            status=200,
            headers=[('Content-Type', 'application/json')]
        )
