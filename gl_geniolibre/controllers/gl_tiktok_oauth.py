import datetime

import requests

from odoo import http
from odoo.http import request
from werkzeug.utils import redirect
from datetime import datetime

import logging

_logger = logging.getLogger(__name__)
from odoo.exceptions import ValidationError


class gl_tiktok_oauth_controller(http.Controller):

    @http.route('/tiktok-auth', type='http', auth='public', website=True, csrf=False)
    def tiktok_auth_callback(self, **kw):
        """ Handle TikTok OAuth callback """

        code = kw.get('code')
        error = kw.get('error')
        raw_state = kw.get('state') or ''

        if error:
            _logger.error("TikTok OAuth error: %s - %s", error, kw.get('error_description', ''))
            return redirect('/web?error=tiktok_auth_failed')

        if not code:
            return redirect('/web?error=tiktok_missing_code')

        if ':' not in raw_state:
            _logger.warning("TikTok OAuth state inválido.")
            return redirect('/web?error=tiktok_state_invalid')

        partner_id_str, oauth_state = raw_state.split(':', 1)
        if not partner_id_str.isdigit():
            _logger.warning("TikTok OAuth state con partner inválido.")
            return redirect('/web?error=tiktok_state_invalid')
        partner_id = int(partner_id_str)

        # Store the auth code in the TikTok account
        res_partner = request.env['res.partner'].search([('id', '=', partner_id)], limit=1)

        if res_partner:
            if (not res_partner.tiktok_oauth_state or
                    oauth_state != res_partner.tiktok_oauth_state or
                    not res_partner.tiktok_oauth_state_expiry or
                    int(datetime.now().timestamp()) > int(res_partner.tiktok_oauth_state_expiry)):
                _logger.warning("TikTok OAuth state inválido o expirado para partner %s", partner_id)
                return redirect('/web?error=tiktok_state_invalid')

            base_url = "https://open.tiktokapis.com/v2/oauth/token/"
            parametros = request.env['ir.config_parameter'].sudo()
            tiktok_client = parametros.get_param('tiktok_key')
            tiktok_secret = parametros.get_param('tiktok_secret')
            tiktok_redirect = parametros.get_param('tiktok_redirect')

            verifier = res_partner.code_verifier
            payload = {
                'client_key': tiktok_client,
                'client_secret': tiktok_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': tiktok_redirect,
                'code_verifier': verifier,

            }
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-cache'
            }
            response = requests.post(base_url, headers=headers, data=payload, timeout=20)
            response.raise_for_status()  # Raises exception for 4XX/5XX errors
            data = response.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in')
            refresh_token = data.get('refresh_token')
            open_id = data.get('open_id')  # Obtener el open_id de la respuesta

            # Escribir todos los datos en una sola operación
            res_partner.write({
                'tiktok_auth_code': code,
                'tiktok_access_token': access_token,
                'tiktok_expires_in': expires_in,
                'tiktok_refresh_token': refresh_token,
                'tiktok_issued_at': int(datetime.now().timestamp()),
                'tiktok_open_id': open_id,
                'tiktok_oauth_state': False,
                'tiktok_oauth_state_expiry': 0,
            })

            self.tiktok_get_nickname(res_partner, access_token)

            _logger.info("Successfully received TikTok auth code")

            return redirect(f'/web#id={partner_id}&model=res.partner&view_type=form')

        return redirect('/web?error=tiktok_partner_missing')

    def tiktok_get_nickname(self, partner, access_token):

        user_url = "https://open.tiktokapis.com/v2/user/info/"
        user_headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        user_params = {
            'fields': 'open_id,avatar_url,display_name'
        }

        user_response = requests.get(user_url, headers=user_headers, params=user_params)
        user_result = user_response.json()

        if 'data' in user_result and 'user' in user_result['data']:
            user_data = user_result['data']['user']

            # CORREGIDO: Usar partner.write() en lugar de self.write()
            partner.write({
                'tiktok_nickname': user_data.get('display_name', ''),
                'tiktok_avatar_url': user_data.get('avatar_url', ''),
            })

            _logger.info("Successfully obtained TikTok user info: %s", user_data.get('display_name', ''))

            return {
                'nickname': user_data.get('display_name', ''),
                'avatar_url': user_data.get('avatar_url', ''),
            }
        else:
            raise ValidationError(f"Error obteniendo información del usuario: {user_result}")
