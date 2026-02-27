import requests
import time

from odoo import http
from odoo.http import request
from werkzeug.utils import redirect

import logging

_logger = logging.getLogger(__name__)

API_VERSION = None
class gl_facebook_oauth_controller(http.Controller):

    @http.route('/facebook-auth', type='http', auth='public', website=True, csrf=False)
    def facebook_auth_callback(self, **kw):
        API_VERSION = request.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        """Handle Facebook OAuth callback."""
        state = kw.get('state')
        expected_state = request.session.get('gl_oauth_facebook_state')
        expires_at = request.session.get('gl_oauth_facebook_state_ts')
        request.session.pop('gl_oauth_facebook_state', None)
        request.session.pop('gl_oauth_facebook_state_ts', None)

        if (not state or not expected_state or state != expected_state or
                not expires_at or int(time.time()) > int(expires_at)):
            _logger.warning("Facebook OAuth state inválido o expirado.")
            return redirect('/web?error=facebook_state_invalid')

        # Get AWS and Facebook credentials
        facebook_app_id = request.env['ir.config_parameter'].sudo().get_param('gl_facebook.app_id')
        facebook_secret = request.env['ir.config_parameter'].sudo().get_param('gl_facebook.secret')
        facebook_redirect = request.env['ir.config_parameter'].sudo().get_param('facebook_redirect')

        code = kw.get('code')
        if not code:
            _logger.warning("Facebook OAuth callback sin code.")
            return redirect('/web?error=facebook_missing_code')

        try:
            url = f"https://graph.facebook.com/{API_VERSION}/oauth/access_token"
            params = {
                'client_id': facebook_app_id,
                'client_secret': facebook_secret,
                'code': code,
                'redirect_uri': facebook_redirect,
            }

            response = requests.get(url, params=params, timeout=20)
            response.raise_for_status()
            access_token = response.json().get('access_token')
            if not access_token:
                _logger.error("Facebook OAuth sin access_token en respuesta: %s", response.text)
                return redirect('/web?error=facebook_token_missing')

            request.env['ir.config_parameter'].sudo().set_param('gl_facebook.api_key', access_token)

            return redirect('/odoo/settings?#GenioLibre')

        except requests.exceptions.RequestException as e:
            _logger.exception("Error HTTP al obtener token de Facebook: %s", str(e))
            return redirect('/web?error=facebook_token_failed')
        except ValueError as e:
            _logger.exception("Error al obtener token de Facebook: %s", str(e))
            return redirect('/web?error=facebook_token_failed')
