# -*- coding: utf-8 -*-:
import urllib.parse
import secrets
import time
from datetime import datetime, timedelta

import boto3
import botocore
import requests
from odoo.exceptions import ValidationError
from odoo import fields, models, api
from odoo.http import request

API_VERSION = None
OAUTH_STATE_TTL = 600
META_SYSTEM_USER_TOKEN_KEY = "gl_facebook.meta_system_user_access_token"
META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY = "gl_facebook.meta_system_user_token_expires_at"
META_SYSTEM_USER_TOKEN_LAST_CHECK_KEY = "gl_facebook.meta_system_user_token_last_check"
META_SYSTEM_USER_TOKEN_STATE_KEY = "gl_facebook.meta_system_user_token_state"
META_SYSTEM_USER_TOKEN_LAST_ERROR_KEY = "gl_facebook.meta_system_user_token_last_error"
LINKEDIN_API_VERSION_KEY = "linkedin.api_version"
DEFAULT_LINKEDIN_API_VERSION = "202504"


def get_linkedin_api_version(env):
    version = (env["ir.config_parameter"].sudo().get_param(LINKEDIN_API_VERSION_KEY) or "").strip()
    return version or DEFAULT_LINKEDIN_API_VERSION


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    user_access_token = fields.Char(string="Facebook Access Token", config_parameter="gl_facebook.api_key")
    facebook_app_id = fields.Char(string="Facebook API Key", config_parameter="gl_facebook.app_id")
    facebook_app_secret = fields.Char(string="Facebook APP Secret", config_parameter="gl_facebook.secret")
    facebook_redirect_uri = fields.Char(string="Facebook Redirect URI", config_parameter="facebook_redirect", default="http://localhost:8018/facebook-auth/")
    facebook_api_version = fields.Char(string="Facebook API Version", config_parameter="gl_facebook.api_version")
    meta_system_user_access_token = fields.Char(
        string="Meta System User Access Token",
        config_parameter=META_SYSTEM_USER_TOKEN_KEY,
    )
    meta_system_user_token_expires_at = fields.Datetime(
        string="Meta System User Expira",
        config_parameter=META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY,
    )
    meta_system_user_token_last_check = fields.Datetime(
        string="Ultima revision token Meta System User",
        config_parameter=META_SYSTEM_USER_TOKEN_LAST_CHECK_KEY,
        readonly=True,
    )
    meta_system_user_token_state = fields.Char(
        string="Estado token Meta System User",
        config_parameter=META_SYSTEM_USER_TOKEN_STATE_KEY,
        readonly=True,
    )
    meta_system_user_token_last_error = fields.Char(
        string="Ultimo error token Meta System User",
        config_parameter=META_SYSTEM_USER_TOKEN_LAST_ERROR_KEY,
        readonly=True,
    )
    meta_system_user_token_status = fields.Char(
        string="Resumen token Meta System User",
        compute="_compute_meta_system_user_token_status",
    )

    aws_access_key = fields.Char(string="AWS Clave de acceso", config_parameter="gl_aws.api_key")
    aws_secret = fields.Char(string="AWS Clave de acceso secreta", config_parameter="gl_aws.secret")
    aws_bucket = fields.Char(string="AWS Bucket", config_parameter="gl_aws.bucket", default="odoo-geniolibre")
    aws_public_domain = fields.Char(
        string="AWS Dominio publico",
        config_parameter="gl_aws.public_domain",
        default="https://s3.geniolibredev.com",
    )

    tiktok_client = fields.Char(string="TikTok Clave de cliente", config_parameter="tiktok_key")
    tiktok_secret = fields.Char(string="TikTok Clave secreta", config_parameter="tiktok_secret")
    tiktok_redirect_uri = fields.Char(string="TikTok Redirect URI", config_parameter="tiktok_redirect", default="http://localhost:8018/tiktok-auth/")

    google_developer_token = fields.Char(string="Google Developer Token", config_parameter="gl_google.developer_token")
    google_client_id = fields.Char(string="Google Client ID", config_parameter="gl_google.client_id")
    google_client_secret = fields.Char(string="Google Client Secret", config_parameter="gl_google.client_secret")
    google_redirect_uri = fields.Char(string="Google Redirect URI", config_parameter="gl_google.redirect_uri", default="http://localhost:8018/google-auth/")
    google_access_token = fields.Char("Google Access Token", config_parameter="gl_google.access_token")
    google_refresh_token = fields.Char("Google Refresh Token", config_parameter="gl_google.refresh_token")
    google_login_customer_id = fields.Char(string="Google Ads Manager Account (Login Customer ID)", config_parameter="gl_google.login_customer_id")

    linkedin_client_id = fields.Char("LinkedIn Client ID", config_parameter="linkedin.client_id")
    linkedin_client_secret = fields.Char("LinkedIn Client Secret", config_parameter="linkedin.client_secret")
    linkedin_redirect_uri = fields.Char("LinkedIn Redirect URI", config_parameter="linkedin.redirect_uri", default="http://localhost:8018/linkedin-oauth/")
    linkedin_access_token = fields.Char(string="LinkedIn Access Token", config_parameter='linkedin.access_token')
    linkedin_token_expiry = fields.Char(string="Token Expiry", config_parameter='linkedin.token_expiry')
    linkedin_api_version = fields.Char(
        string="LinkedIn API Version",
        config_parameter=LINKEDIN_API_VERSION_KEY,
        default=DEFAULT_LINKEDIN_API_VERSION,
    )

    chatgpt_api_key = fields.Char("ChatGPT API Key", config_parameter="chatgpt.api_key")
    chatgpt_base_url = fields.Char("ChatGPT Base URL", config_parameter="chatgpt.base_url", default="https://api.openai.com/v1")
    chatgpt_model = fields.Char("ChatGPT Modelo", config_parameter="chatgpt.model", default="gpt-4.1-mini")

    @api.depends(
        "meta_system_user_access_token",
        "meta_system_user_token_expires_at",
        "meta_system_user_token_last_check",
        "meta_system_user_token_state",
        "meta_system_user_token_last_error",
    )
    def _compute_meta_system_user_token_status(self):
        now = datetime.utcnow()
        for rec in self:
            if not rec.meta_system_user_access_token:
                rec.meta_system_user_token_status = "No configurado"
                continue

            expires_at = fields.Datetime.to_datetime(rec.meta_system_user_token_expires_at)
            state = (rec.meta_system_user_token_state or "").strip().lower()

            if state == "invalid":
                rec.meta_system_user_token_status = "Invalido: revisa permisos, app o token"
            elif expires_at:
                if expires_at <= now:
                    rec.meta_system_user_token_status = "Vencido"
                else:
                    remaining = expires_at - now
                    days_left = max(0, remaining.days)
                    if days_left <= 7:
                        rec.meta_system_user_token_status = f"Por vencer: {days_left} dias restantes"
                    else:
                        rec.meta_system_user_token_status = f"Vigente: {days_left} dias restantes"
            else:
                rec.meta_system_user_token_status = "Configurado sin fecha de expiracion"

    def set_values(self):
        icp = self.env["ir.config_parameter"].sudo()
        previous_token = icp.get_param(META_SYSTEM_USER_TOKEN_KEY)
        super().set_values()

        current_token = (self.meta_system_user_access_token or "").strip()
        current_expiry = self.meta_system_user_token_expires_at

        if not current_token:
            icp.set_param(META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY, "")
            icp.set_param(META_SYSTEM_USER_TOKEN_LAST_CHECK_KEY, "")
            icp.set_param(META_SYSTEM_USER_TOKEN_STATE_KEY, "")
            icp.set_param(META_SYSTEM_USER_TOKEN_LAST_ERROR_KEY, "")
            return

        if current_token != (previous_token or "").strip() and not current_expiry:
            expires_at = datetime.utcnow() + timedelta(days=60)
            icp.set_param(META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY, fields.Datetime.to_string(expires_at))
            self.meta_system_user_token_expires_at = expires_at

    @api.model
    def _cron_meta_system_user_token_maintenance(self):
        icp = self.env["ir.config_parameter"].sudo()
        token = (icp.get_param(META_SYSTEM_USER_TOKEN_KEY) or "").strip()
        now = datetime.utcnow()

        if not token:
            icp.set_param(META_SYSTEM_USER_TOKEN_STATE_KEY, "missing")
            icp.set_param(META_SYSTEM_USER_TOKEN_LAST_CHECK_KEY, fields.Datetime.to_string(now))
            icp.set_param(META_SYSTEM_USER_TOKEN_LAST_ERROR_KEY, "")
            return True

        expires_at_raw = icp.get_param(META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY)
        expires_at = fields.Datetime.to_datetime(expires_at_raw) if expires_at_raw else False

        if not expires_at:
            expires_at = now + timedelta(days=60)
            icp.set_param(META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY, fields.Datetime.to_string(expires_at))

        state = "valid"
        error_message = ""

        if expires_at <= now:
            state = "expired"
        elif expires_at <= (now + timedelta(days=7)):
            state = "expiring_soon"

        app_id = (icp.get_param("gl_facebook.app_id") or "").strip()
        app_secret = (icp.get_param("gl_facebook.secret") or "").strip()
        if app_id and app_secret:
            try:
                debug_response = requests.get(
                    "https://graph.facebook.com/debug_token",
                    params={
                        "input_token": token,
                        "access_token": f"{app_id}|{app_secret}",
                    },
                    timeout=20,
                )
                debug_data = debug_response.json()
                if debug_response.status_code == 200:
                    token_data = debug_data.get("data") or {}
                    if token_data.get("is_valid") is False:
                        state = "invalid"
                        error_message = "Meta indico que el token ya no es valido."
                    elif token_data.get("expires_at"):
                        meta_expires_at = datetime.utcfromtimestamp(int(token_data["expires_at"]))
                        expires_at = meta_expires_at
                        icp.set_param(
                            META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY,
                            fields.Datetime.to_string(meta_expires_at),
                        )
                        if meta_expires_at <= now:
                            state = "expired"
                        elif meta_expires_at <= (now + timedelta(days=7)):
                            state = "expiring_soon"
                        else:
                            state = "valid"
                else:
                    error_message = f"No se pudo validar el token con Meta: {debug_data}"
            except requests.exceptions.RequestException as err:
                error_message = f"Error validando token Meta: {err}"

        icp.set_param(META_SYSTEM_USER_TOKEN_STATE_KEY, state)
        icp.set_param(META_SYSTEM_USER_TOKEN_LAST_CHECK_KEY, fields.Datetime.to_string(now))
        icp.set_param(META_SYSTEM_USER_TOKEN_LAST_ERROR_KEY, error_message)
        return True

    def _create_oauth_state(self, provider):
        if not request or not request.session:
            raise ValidationError("No se encontró una sesión HTTP activa para iniciar OAuth.")
        state = secrets.token_urlsafe(32)
        request.session[f'gl_oauth_{provider}_state'] = state
        request.session[f'gl_oauth_{provider}_state_ts'] = int(time.time()) + OAUTH_STATE_TTL
        return state

    def action_test_aws_connection(self):
        """Probar conexión con AWS S3 (muestra popup visual en Odoo)"""
        self.ensure_one()

        access_key = self.aws_access_key or self.env['ir.config_parameter'].sudo().get_param('gl_aws.api_key')
        secret_key = self.aws_secret or self.env['ir.config_parameter'].sudo().get_param('gl_aws.secret')

        if not access_key or not secret_key:
            raise ValidationError("Debes configurar las claves de AWS antes de probar la conexión.")

        try:
            s3_client = boto3.client('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name='us-east-2', )

            response = s3_client.list_buckets()
            bucket_names = [b['Name'] for b in response.get('Buckets', [])]
            bucket_text = ', '.join(bucket_names) or 'ninguno encontrado'

            msg = f"✅ Conexión exitosa con AWS S3.\nBuckets disponibles: {bucket_text}"

            # Mostrar popup visual (bus message)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexión Exitosa',
                    'message': msg,
                    'type': 'success',
                    'sticky': False,
                }
            }

        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError, ValueError, TypeError) as e:
            error_msg = f"No se pudo conectar con AWS S3:\n{str(e)}"
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error en la Conexión',
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def conectar_facebook(self):
        scopes_list = [
            "pages_read_user_content",
            "ads_read",
            "ads_management",
            "publish_video",
            "business_management",
            "pages_show_list",
            "instagram_basic",
            "instagram_content_publish",
            "pages_read_engagement",
            "pages_manage_posts",
            "public_profile",
            "read_insights",
            "instagram_manage_insights"
        ]

        scopes = ",".join(scopes_list)
        state = self._create_oauth_state('facebook')
        auth_url = (f"https://www.facebook.com/dialog/oauth"
                    f"?client_id={self.facebook_app_id}"
                    f"&redirect_uri={self.facebook_redirect_uri}"
                    f"&scope={scopes}"
                    f"&state={state}"
                    f"&config_id=843300575254898")
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def conectar_google(self):
        scopes_list = [
            "https://www.googleapis.com/auth/adwords",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/analytics.readonly",
        ]

        scopes = " ".join(scopes_list)
        state = self._create_oauth_state('google')
        query = urllib.parse.urlencode({
            'client_id': self.google_client_id,
            'redirect_uri': self.google_redirect_uri,
            'response_type': 'code',
            'scope': scopes,
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
        }, safe=':/')
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def conectar_linkedin(self):
        self.ensure_one()

        # 1. Configuración base
        base_url = "https://www.linkedin.com/oauth/v2/authorization"
        client_id = self.env['ir.config_parameter'].sudo().get_param("linkedin.client_id")
        redirect_uri = self.env['ir.config_parameter'].sudo().get_param("linkedin.redirect_uri")

        # 2. Scopes actualizados (2024)
        scope = [
            "w_member_social",
            "w_organization_social",
            "r_organization_admin",
            "r_organization_social",
            "rw_organization_admin"
        ]

        # 3. Parámetros de la solicitud
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scope),  # Espacios normales (urlencode se encargará)
            "state": self._create_oauth_state('linkedin'),
        }

        # 4. Construcción de la URL con codificación correcta
        query_string = urllib.parse.urlencode(params, safe='', quote_via=urllib.parse.quote)
        url = f"{base_url}?{query_string}"

        # 6. Retorno de la acción
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new'  # 'new' es mejor que 'blank' para Odoo
        }
