# -*- coding: utf-8 -*-
"""Pruebas de estados y reintentos de publicación sin llamadas externas."""

from unittest.mock import patch

import requests

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.gl_geniolibre.services.social_http import (
    PUBLICATION_STATUS_SELECTION,
    request_with_retries,
    sanitize_error_message,
)


@tagged("post_install", "-at_install")
class TestProjectTaskPublication(TransactionCase):

    def test_publication_statuses_are_restricted(self):
        field = self.env["project.task"]._fields["ig_estado"]
        self.assertEqual(field.type, "selection")
        self.assertEqual(
            set(dict(PUBLICATION_STATUS_SELECTION)),
            {"Pendiente", "Programado", "Procesando", "Revisando", "Publicado", "Cancelado", "Error"},
        )

    def test_cancel_post_keeps_cancelled_state(self):
        task = self.env["project.task"].create({"name": "Prueba cancelación"})

        task.cancelar_post()

        self.assertEqual(task.post_estado, "Cancelado")

    @patch("odoo.addons.gl_geniolibre.services.social_http.time.sleep")
    @patch("odoo.addons.gl_geniolibre.services.social_http.requests.request")
    def test_read_requests_retry_only_transient_failures(self, request_mock, sleep_mock):
        temporary = requests.Response()
        temporary.status_code = 503
        success = requests.Response()
        success.status_code = 200
        request_mock.side_effect = [temporary, success]

        response = request_with_retries(
            "GET",
            "https://graph.facebook.com/test",
            attempts=2,
            timeout=60,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_error_messages_redact_tokens(self):
        message = sanitize_error_message(
            "https://graph.facebook.com/?access_token=abc123456789012345678901234567890"
        )
        self.assertNotIn("abc123", message)
        self.assertIn("[REDACTED]", message)

    @patch("odoo.addons.gl_geniolibre.services.social_http.requests.request")
    def test_post_is_not_retried_automatically(self, request_mock):
        response = requests.Response()
        response.status_code = 503
        request_mock.return_value = response

        result = request_with_retries(
            "POST",
            "https://graph.facebook.com/test",
            attempts=3,
            timeout=60,
        )

        self.assertEqual(result.status_code, 503)
        request_mock.assert_called_once()

    def test_error_network_moves_global_publication_to_error(self):
        instagram = self.env["red.social"].search([("name", "=", "Instagram")], limit=1)
        task = self.env["project.task"].new({
            "name": "Prueba de publicación",
            "red_social_ids": [Command.set([instagram.id])],
            "post_estado": "Procesando",
            "ig_estado": "Error",
        })

        task.revisar_post()

        self.assertEqual(task.post_estado, "Error")
