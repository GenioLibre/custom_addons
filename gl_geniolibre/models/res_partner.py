# -*- coding: utf-8 -*-:
import base64
import hashlib
import random
import secrets
import time
import requests

from datetime import datetime
from google.ads.googleads.client import GoogleAdsClient
from odoo import models, fields, api
from odoo.exceptions import ValidationError

LinkedIn_Version = "202505"
API_VERSION = None


class GoogleAdsAccount(models.Model):
    _name = 'google.ads.account'
    _description = 'Cuenta de Google Ads'

    name = fields.Char("Nombre")
    account_id = fields.Char("ID de Cuenta", required=True)


class FacebookAdAccount(models.Model):
    _name = 'facebook.ad.account'
    _description = 'Facebook Ad Account'

    name = fields.Char('Name')
    account_id = fields.Char('Account ID')


class LinkedInOrganization(models.Model):
    _name = 'linkedin.organization'
    _description = 'LinkedIn Organization'

    name = fields.Char('Nombre de la Organización')
    account_id = fields.Char('ID de la Organización')  # Solo el ID numérico (ej: "105978413")
    full_urn = fields.Char('URN Completo')  # Campo técnico: "urn:li:organization:105978413"


class Partner(models.Model):
    _inherit = "res.partner"
    credenciales = fields.One2many('gl.credentials', 'credenciales_id')
    code_verifier = fields.Char(readonly=True)
    code_challenge = fields.Char(readonly=True)
    plan_descripcion = fields.Char(string="Plan", tracking=True)
    plan_post = fields.Integer(string="Número de Posts", tracking=True)
    plan_historia = fields.Integer(string="Número de Historias", tracking=True)
    plan_reel = fields.Integer(string="Número de Reels", tracking=True)
    monto = fields.Float(string="Monto a Cobrar", tracking=True)
    publicidad = fields.Float(string="Presupuesto Publicidad", tracking=True)
    moneda = fields.Many2one('res.currency', tracking=True)

    # Facebook
    id_facebook_ad_account = fields.Char(string="ID Cuenta Publicitaria", related='facebook_ad_account.account_id', readonly=True, store=True, )
    facebook_ad_account = fields.Many2one('facebook.ad.account', string='Cuenta publicitaria de Facebook')
    facebook_page_id = fields.Char(string="Facebook Page id", tracking=True)
    facebook_page_access_token = fields.Char(readonly=True)
    instagram_page_id = fields.Char(readonly=True)

    # TikTok
    tiktok_auth_code = fields.Char(string="TikTok Auth Code", tracking=True)
    tiktok_access_token = fields.Char(string="TikTok Page id", tracking=True)
    tiktok_refresh_token = fields.Char()
    tiktok_expires_in = fields.Integer()
    tiktok_refresh_expires_in = fields.Integer()
    tiktok_issued_at = fields.Integer()
    tiktok_nickname = fields.Char(string='TikTok Nickname')
    tiktok_username = fields.Char(string='TikTok Username')
    tiktok_avatar_url = fields.Char(string='TikTok Avatar URL')
    tiktok_open_id = fields.Char(string='TikTok Open ID')
    tiktok_oauth_state = fields.Char(copy=False)
    tiktok_oauth_state_expiry = fields.Integer(copy=False)

    # Google Ads
    google_ads_account = fields.Many2one('google.ads.account', string='Cuenta de Google Ads')
    id_google_ads_account = fields.Char(string="ID Cuenta Google Ads", related='google_ads_account.account_id', readonly=True, store=True)

    # LinkeIn
    linkedin_organization = fields.Many2one('linkedin.organization', string='Organización de LinkedIn')
    id_linkedin_organization = fields.Char(string="ID Organización LinkedIn", related='linkedin_organization.account_id', readonly=True, store=True)

    def facebook_obtener_datos(self):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        def fetch_facebook_accounts():
            access_token = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_key')

            if not access_token:
                return

            url = f"https://graph.facebook.com/{API_VERSION}/me/adaccounts"
            params = {
                'access_token': access_token,
                'fields': 'name,account_id'
            }

            response = requests.get(url, params=params)
            response.raise_for_status()
            accounts = response.json().get('data', [])

            AdAccount = self.env['facebook.ad.account'].sudo()
            api_ids = [acc['account_id'] for acc in accounts]

            # 1) Actualizar o crear
            for acc in accounts:
                existing = AdAccount.search([
                    ('account_id', '=', acc['account_id'])
                ], limit=1)
                if existing:
                    if existing.name != acc['name']:
                        existing.write({
                            'name': acc['name']
                        })
                else:
                    AdAccount.create({
                        'name': acc['name'],
                        'account_id': acc['account_id'],
                    })

            # 2) Eliminar las cuentas que ya no existen en Facebook
            stale = AdAccount.search([
                ('account_id', 'not in', api_ids)
            ])
            if stale:
                stale.unlink()

        if self.facebook_page_id:
            access_token = self.env['ir.config_parameter'].sudo()
            page_access_token = access_token.get_param('gl_facebook.api_key')
            # api_url_token = f'https://graph.facebook.com/{version}/{self.facebook_page_id}?fields=access_token&access_token={page_access_token}'

            params = {
                'fields': 'access_token,instagram_business_account',
                'access_token': page_access_token,
            }
            url = f'https://graph.facebook.com/{API_VERSION}/{self.facebook_page_id}'
            fetch_facebook_accounts()

            try:
                response = requests.get(url, params=params)
                response.raise_for_status()  # Raise an exception if the request returns an HTTP error
                data = response.json()
                self.write({
                    'facebook_page_access_token': data['access_token'],
                })

                if 'instagram_business_account' in data:
                    self.write({

                        'instagram_page_id': data['instagram_business_account']['id'],
                    })



            except requests.exceptions.RequestException as e:
                raise ValidationError(f"Error al obtener Tokens de Facebook: {response.json()}")

    def tiktok_get_auth_code(self):
        self.ensure_one()
        parametros = self.env['ir.config_parameter'].sudo()
        tiktok_client = parametros.get_param('tiktok_key')
        tiktok_secret = parametros.get_param('tiktok_secret')
        tiktok_redirect = parametros.get_param('tiktok_redirect')
        if not tiktok_client or not tiktok_secret:
            raise ValidationError("No se configuraron las claves de de TikTok")

        # Usage example:
        codigos = generate_code_challenge()
        oauth_state = secrets.token_urlsafe(24)
        self.write({
            'code_verifier': codigos[0],
            'code_challenge': codigos[1],
            'tiktok_oauth_state': oauth_state,
            'tiktok_oauth_state_expiry': int(time.time()) + 600,
        })

        def get_auth_url():
            """ Return the URL to start OAuth flow """
            self.ensure_one()
            base_url = "https://www.tiktok.com/v2/auth/authorize/"
            params = {
                'client_key': tiktok_client,
                'response_type': 'code',
                'scope': 'user.info.basic,video.upload,video.publish,video.list,user.info.stats,user.info.profile',
                'redirect_uri': tiktok_redirect,
                'state': f"{self.id}:{oauth_state}",
                'code_challenge': self.code_challenge,
                'code_challenge_method': 'S256',
                'force_web': 'true'
            }

            auth_url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
            return auth_url

        auth_url = get_auth_url()
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }


    def tiktok_renew_token(self):
        parametros = self.env['ir.config_parameter'].sudo()
        tiktok_client = parametros.get_param('tiktok_key')
        tiktok_secret = parametros.get_param('tiktok_secret')

        # Supongamos que guardaste el tiempo en que se emitió y la duración en segundos
        issued_at = self.tiktok_issued_at
        expires_in = self.tiktok_expires_in
        days = 86400 * 1  # 3 días en segundos

        # Calcula el tiempo de expiración y el umbral de renovación
        expiration_time = issued_at + expires_in
        renewal_threshold = expiration_time - days
        # Verifica si ya se necesita renovar
        if time.time() >= renewal_threshold:
            url = "https://open.tiktokapis.com/v2/oauth/token/"

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache"
            }

            data = {
                "client_key": tiktok_client,
                "client_secret": tiktok_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.tiktok_refresh_token
            }
            response = requests.post(url, headers=headers, data=data)
            response_data = response.json()
            if response.status_code == 200:
                data = response.json()
                self.write({
                    'tiktok_access_token': data.get('access_token'),
                    'tiktok_expires_in': data.get('expires_in'),
                    'tiktok_refresh_expires_in': data.get('refresh_expires_in'),
                    'tiktok_refresh_token': data.get('refresh_token'),
                    'tiktok_issued_at': int(datetime.now().timestamp()),
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "El token ha sido actualizado",
                        'type': 'success',
                        'next': {
                            'type': 'ir.actions.act_window_close'
                        },
                    }
                }
            else:
                raise ValidationError(f"Error al publicar Feed en Facebook: {response_data}")
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "El token aún es válido.",
                    'type': 'success',
                    'next': {
                        'type': 'ir.actions.act_window_close'
                    },
                }
            }

    def _get_google_ads_client(self):
        config_param = self.env["ir.config_parameter"].sudo()
        config = {
            "developer_token": config_param.get_param("gl_google.developer_token"),
            "client_id": config_param.get_param("gl_google.client_id"),
            "client_secret": config_param.get_param("gl_google.client_secret"),
            "refresh_token": config_param.get_param("gl_google.refresh_token"),
            "login_customer_id": config_param.get_param("gl_google.login_customer_id"),  # ← ahora dinámico
            "use_proto_plus": True,
        }
        return GoogleAdsClient.load_from_dict(config)

    def google_obtener_datos(self):
        client = self._get_google_ads_client()
        ga_service = client.get_service("GoogleAdsService")

        query = """
                    SELECT
                        customer_client.client_customer,
                        customer_client.descriptive_name,
                        customer_client.level,
                        customer_client.status
                    FROM customer_client
                    WHERE customer_client.level = 1
                      AND customer_client.status = 'ENABLED'
                """

        login_customer_id = self.env["ir.config_parameter"].sudo().get_param("gl_google.login_customer_id")
        response = ga_service.search(customer_id=login_customer_id, query=query)

        account_model = self.env["google.ads.account"].sudo()
        api_ids = []
        for row in response:
            customer = row.customer_client
            customer_id = customer.client_customer.split("/")[-1]
            name = customer.descriptive_name
            api_ids.append(customer_id)
            existing = account_model.search([
                ("account_id", "=", customer_id)
            ], limit=1)
            if existing:
                if existing.name != (name or f"Cuenta {customer_id}"):
                    existing.write({
                        "name": name or f"Cuenta {customer_id}",
                    })
            else:
                account_model.create({
                    "name": name or f"Cuenta {customer_id}",
                    "account_id": customer_id,
                })
        # opcional: limpiar obsoletas
        # account_model.search([('account_id', 'not in', api_ids)]).unlink()

    def update_linkedin_organizations(self):
        """Actualiza las organizaciones de LinkedIn desde la API"""
        LinkedInOrg = self.env['linkedin.organization']
        access_token = self.env['ir.config_parameter'].sudo().get_param('linkedin.access_token')

        def _get_linkedin_org_name(org_id, headers):
            """Obtiene el nombre de la organización con manejo robusto de respuestas"""
            url = f"https://api.linkedin.com/rest/organizations/{org_id}"
            try:
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()  # Lanza excepción para códigos 4XX/5XX

                data = response.json()
                # Extraer nombre de la estructura estándar
                localized_name = data.get('localizedName')
                vanity_name = data.get('vanityName')

                if localized_name:
                    return localized_name
                if vanity_name:
                    return vanity_name
                if data.get('name'):
                    return data['name']
                if data.get('website'):
                    from urllib.parse import urlparse
                    domain = urlparse(data['website']).netloc
                    if domain:
                        return domain.split('.')[0].capitalize()

                # Opción 4: ID como último recurso
                return f"Organización {org_id}"

            except requests.exceptions.RequestException as e:
                return f"Organización {org_id}"

        ######################### Validaciones #################################

        if not access_token:
            raise ValidationError("Token de acceso de LinkedIn no configurado. Por favor configure el parámetro 'linkedin_access_token' en Ajustes Técnicos.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
            "LinkedIn-Version": LinkedIn_Version
        }

        ######################### Lógica Principal #################################

        # 1. Obtener organizaciones donde el usuario es ADMINISTRADOR
        base_url = "https://api.linkedin.com/rest/organizationAcls"
        params = {
            "q": "roleAssignee",
            "role": "ADMINISTRATOR",
            "state": "APPROVED",
            "start": 0,
            "count": 100
        }

        try:
            # Primera solicitud para obtener datos iniciales
            response = requests.get(base_url, headers=headers, params=params, timeout=15)
            # Manejo específico del error 426
            if response.status_code == 426:
                raise ValidationError("""
                    Verifique que estos encabezados estén presentes en la solicitud.
                """)

            response.raise_for_status()
            orgs_data = response.json()

            # Manejo de paginación (si existe)
            elements = orgs_data.get('elements', [])
            while orgs_data.get('paging', {}).get('links', []):
                next_url = next((link['href'] for link in orgs_data['paging']['links'] if link['rel'] == 'next'), None)
                if not next_url:
                    break

                response = requests.get(next_url, headers=headers, timeout=15)
                response.raise_for_status()
                orgs_data = response.json()
                elements.extend(orgs_data.get('elements', []))

        except requests.exceptions.RequestException as e:
            error_msg = f"Error en API de LinkedIn: {str(e)}"
            raise ValidationError(error_msg)

        api_org_ids = []

        # 3. Crear nuevos registros
        created_count = 0
        for org in elements:
            org_urn = org.get('organization', '')
            if not org_urn:
                continue

            org_id = org_urn.split(':')[-1]

            # Obtener nombre de la organización
            org_name = _get_linkedin_org_name(org_id, headers)
            # Crear registro con manejo de errores
            try:
                api_org_ids.append(org_id)
                vals = {
                    'name': org_name,
                    'account_id': org_id,
                    'full_urn': org_urn,
                }
                existing = LinkedInOrg.search([('account_id', '=', org_id)], limit=1)
                if existing:
                    existing.write(vals)
                else:
                    LinkedInOrg.create(vals)
                created_count += 1
            except (ValidationError, ValueError, TypeError) as e:
                raise ValidationError(f"Error al crear organización {org_id}: {str(e)}")
                continue
        # opcional: limpiar obsoletas
        # if api_org_ids:
        #     LinkedInOrg.search([('account_id', 'not in', api_org_ids)]).unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Éxito' if created_count else 'Advertencia',
                'message': f'Se actualizaron {created_count} organizaciones de LinkedIn' if created_count else 'No se encontraron organizaciones para actualizar',
                'sticky': False,
                'type': 'success' if created_count else 'warning',
            }
        }


def generate_random_string(length):
    characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
    return ''.join(random.choice(characters) for _ in range(length))


def generate_code_challenge():
    code_verifier = generate_random_string(60)
    sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = sha256_hash.hex()  # Convert to hex string
    return code_verifier, code_challenge
