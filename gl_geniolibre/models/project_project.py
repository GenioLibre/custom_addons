# -*- coding: utf-8 -*-:
import datetime, time, pytz, requests

import json

from odoo import models, fields, api
from odoo.exceptions import ValidationError
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
from datetime import datetime, timedelta, timezone, time
from collections import defaultdict
from google.ads.googleads.client import GoogleAdsClient

API_VERSION = None
LinkedIn_Version = "202505"


class GlJsonViewerWizard(models.TransientModel):
    _name = 'gl.json.viewer.wizard'
    _description = 'JSON Viewer'

    json_content = fields.Text(string="Resultado", readonly=True)


class red_social_reporte(models.Model):
    _name = 'red.social_reporte'
    _description = 'Redes Sociales para reporte'
    name = fields.Char(string='Nombre', required=True)

    @api.model
    def _auto_init(self):
        """Crear redes sociales por defecto si faltan"""
        res = super()._auto_init()

        redes_por_defecto = [
            'Facebook',
            'MetaAds',
            'Instagram',
            'LinkedIn',
            'TikTok',
            'GoogleAds',
        ]

        # Buscar nombres ya existentes (case insensitive por si acaso)
        existentes = self.search([]).mapped('name')
        existentes = [nombre.strip().lower() for nombre in existentes]

        redes_a_crear = [{
            'name': nombre
        } for nombre in redes_por_defecto if nombre.lower() not in existentes]

        if redes_a_crear:
            self.create(redes_a_crear)

        return res


class GoogleAdCampaign(models.Model):
    _name = 'google.ad.campaigns'
    _description = 'Google Ad Campaigns'
    _sql_constraints = [
        ('campaign_id_unique', 'unique(campaign_id)', 'La campaña ya existe.'),
    ]

    name = fields.Char('Nombre')
    campaign_id = fields.Char('ID de Campaña', required=True)
    account_id = fields.Char('ID Cuenta Google Ads')
    project_id = fields.Many2one('project.project', string='Proyecto')


class FacebookAdCampaigns(models.Model):
    _name = 'facebook.ad.campaigns'
    _description = 'Facebook Ad Campaigns'
    _sql_constraints = [
        ('campaign_id_unique', 'unique(campaign_id)', 'La campaña ya existe.'),
    ]

    name = fields.Char('Nombre')
    campaign_id = fields.Char('ID de Campaña', required=True)
    account_id = fields.Char('ID Cuenta Publicitaria')
    project_id = fields.Many2one('project.project', string='Proyecto', required=True, ondelete='cascade')


class project_project(models.Model):
    _inherit = "project.project"
    partner_id = fields.Many2one('res.partner')
    partner_plan_descripcion = fields.Char(related="partner_id.plan_descripcion")
    partner_plan_post = fields.Integer(string="Posts", related="partner_id.plan_post")
    partner_plan_historia = fields.Integer(string="Historias", related="partner_id.plan_historia")
    partner_plan_reel = fields.Integer(string="Reels", related="partner_id.plan_reel")

    post_progress = fields.Char(string="Posts Publicados", compute="_compute_publication_counts", store=False)
    historia_progress = fields.Char(string="Historias Publicadas", compute="_compute_publication_counts", store=False)
    reel_progress = fields.Char(string="Reels Publicados", compute="_compute_publication_counts", store=False)

    # Este es el nuevo campo que se relaciona con tu modelo 'red.social'
    red_social_report_ids = fields.Many2many('red.social_reporte',  # El _name de tu modelo ya existente
                                             relation='project_project_red_social_relation',
                                             # Nombre de la tabla de relación (buena práctica)
                                             string='Generar reporte para:')

    project_type = fields.Selection(selection=[
        ('marketing', 'Marketing'),
        ('web', 'Web'),
        ('branding', 'Branding'),
        ('onboarding', 'On Boarding'),
        ('otro', 'Otro')
    ], string='Tipo de Proyecto', required=True, default='marketing')
    partner_page_access_token = fields.Char(related="partner_id.facebook_page_access_token")
    partner_facebook_page_id = fields.Char(related="partner_id.facebook_page_id")
    partner_instagram_page_id = fields.Char(related="partner_id.instagram_page_id")
    partner_tiktok_access_token = fields.Char(related="partner_id.tiktok_access_token")

    partner_id_facebook_ad_account = fields.Char(related="partner_id.id_facebook_ad_account")
    facebook_ad_campaigns_ids = fields.One2many('facebook.ad.campaigns', 'project_id', string='Campañas de Facebook')

    partner_id_google_ads_account = fields.Char(related="partner_id.id_google_ads_account")
    google_ad_campaigns_ids = fields.One2many('google.ad.campaigns', 'project_id', string='Campañas de Google Ads')

    @api.depends('task_ids.post_estado', 'task_ids.tipo', 'partner_plan_post', 'partner_plan_historia',
                 'partner_plan_reel')
    def _compute_publication_counts(self):  # optimizado
        for project in self:
            # Usar el ORM de Odoo para calcular cantidades directamente en la búsqueda
            tasks_data = self.env['project.task'].read_group(domain=[
                ('project_id', '=', project.id)
            ], fields=[
                'tipo'
            ], groupby=[
                'tipo'
            ])

            # Inicializar contadores a 0
            post_count = 0
            historia_count = 0
            reel_count = 0

            # Mapear resultados del read_group
            for data in tasks_data:
                tipo = data['tipo']
                count = data['tipo_count']
                if tipo == 'feed':
                    post_count = count
                elif tipo == 'video_stories':
                    historia_count = count
                elif tipo == 'video_reels':
                    reel_count = count

            # Actualizar campos de progreso utilizando los valores calculados
            project.post_progress = f"{post_count} de {project.partner_plan_post or 0} posts"
            project.historia_progress = f"{historia_count} de {project.partner_plan_historia or 0} historias"
            project.reel_progress = f"{reel_count} de {project.partner_plan_reel or 0} reels"

    @api.model_create_multi
    def create(self, vals_list):  # optimizado
        """
        Validar duplicados de 'partner_id' y 'project_type' para evitar la creación de proyectos repetidos.
        """
        for vals in vals_list:
            partner_id = vals.get('partner_id')
            project_type = vals.get('project_type')

            # Comprobamos si ya existe un proyecto para este cliente y tipo,
            # pero solo si el tipo es "marketing"
            if partner_id and project_type == "marketing":
                existing_project = self.sudo().search([
                    ('partner_id', '=', partner_id),
                    ('project_type', '=', project_type)
                ], limit=1)

                if existing_project:
                    partner_name = self.env['res.partner'].browse(partner_id).name
                    project_type_label = dict(
                        self.fields_get()['project_type']['selection']).get(project_type, project_type)
                    raise ValidationError(
                        f"Ya existe un proyecto para el cliente '{partner_name}' con el tipo '{project_type_label}'.")

        # Creamos los registros utilizando la lógica estándar
        return super(project_project, self).create(vals_list)

    def write(self, vals):  # optimizado
        """
        Validar que no existan duplicados de tipo de proyecto y cliente al actualizar registros.
        """
        # Obtener nuevos valores asignados o valores actuales del registro
        partner_id = vals.get('partner_id')
        project_type = vals.get('project_type')

        # Si no hay cambios relevantes, continúa
        if not partner_id and not project_type:
            return super(project_project, self).write(vals)

        for record in self:
            # Asignar valores "actuales" en caso de no estar en 'vals'
            # if not self.google_ad_campaigns_ids:
            #     if record.date_start and record.date:
            #         if (record.date - record.date_start).days > 30:
            #             raise ValidationError("El rango entre fechas no puede ser mayor a 30 días.")

            updated_partner_id = partner_id or record.partner_id.id
            updated_project_type = project_type or record.project_type

            # Buscar proyectos existentes que coincidan con las condiciones
            duplicate_project = self.sudo().search([
                ('id', '!=', record.id),  # Evitar comparar con el mismo registro
                ('partner_id', '=', updated_partner_id),
                ('project_type', '=', updated_project_type)
            ], limit=1)

            if duplicate_project:
                partner_name = self.env['res.partner'].browse(updated_partner_id).name
                project_type_label = dict(
                    self.fields_get()['project_type']['selection']).get(updated_project_type, updated_project_type)
                raise ValidationError(
                    f"Otro proyecto del cliente '{partner_name}' con el tipo '{project_type_label}' ya existe.")

        # Aplicar la escritura de los valores
        return super(project_project, self).write(vals)

    def fetch_campaigns(self):
        """Método del botón: ejecuta la descarga de campañas Google y Facebook
           pero solo si las redes están seleccionadas
        """
        self.ensure_one()

        FacebookCampaign = self.env['facebook.ad.campaigns'].sudo()

        if not self.partner_id_facebook_ad_account:
            # 🔥 No existe cuenta Facebook → borrar TODO
            FacebookCampaign.search([]).unlink()
        else:
            # Existe cuenta Facebook → ejecutar Google
            self.fetch_google_campaigns()

        # =========================
        # GOOGLE ADS
        # =========================
        GoogleCampaign = self.env['google.ad.campaigns'].sudo()

        if not self.partner_id_google_ads_account:
            # 🔥 No existe cuenta Google → borrar TODO
            GoogleCampaign.search([]).unlink()
        else:
            # Existe cuenta Google → ejecutar Facebook
            self.fetch_facebook_campaigns()

        return True

    def fetch_facebook_campaigns(self):
        self.ensure_one()

        # 1. Validar cuenta
        if not self.partner_id_facebook_ad_account:
            return

        Campaign = self.env['facebook.ad.campaigns'].sudo()

        # 2. Borrar SOLO campañas de este proyecto
        Campaign.search([]).unlink()

        # 3. Token
        access_token = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_key')
        if not access_token:
            raise ValidationError("No existe un token válido")

        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')

        # 4. Fechas
        since_date = self.date_start
        until_date = self.date
        if isinstance(since_date, datetime):
            since_date = since_date.date()
        if isinstance(until_date, datetime):
            until_date = until_date.date()

        # 5. API
        url = f"https://graph.facebook.com/{API_VERSION}/act_{self.partner_id_facebook_ad_account}/campaigns"
        params = {
            'access_token': access_token,
            'fields': 'name,id,start_time,stop_time',
            'effective_status': '["ACTIVE"]',
            'limit': 1000,
        }

        response = requests.get(url, params=params)
        if response.status_code != 200:
            error = response.json().get('error', {}).get('message', 'Error desconocido')
            raise ValidationError(f"Error al obtener campañas: {error}")

        campaigns = response.json().get('data', [])
        if not campaigns:
            return

        filtered_campaigns = [c for c in campaigns if self._is_campaign_within_range(c, since_date, until_date)]

        # 6. Crear campañas del proyecto
        for campaign in filtered_campaigns:
            Campaign.create({
                'name': campaign['name'],
                'campaign_id': campaign['id'],
                'account_id': self.partner_id_facebook_ad_account,
                'project_id': self.id,
            })

    def fetch_google_campaigns(self):
        self.ensure_one()
        CampaignGA = self.env['google.ad.campaigns'].sudo()

        # 🔥 6. Limpiar campañas previas del proyecto
        CampaignGA.search([]).unlink()

        # 1. Obtener configuración técnica
        cfg = self.env['ir.config_parameter'].sudo()
        credenciales = {
            'developer_token': cfg.get_param('gl_google.developer_token'),
            'client_id': cfg.get_param('gl_google.client_id'),
            'client_secret': cfg.get_param('gl_google.client_secret'),
            'refresh_token': cfg.get_param('gl_google.refresh_token'),
            'login_customer_id': cfg.get_param('gl_google.login_customer_id'),
        }

        # 2. Validar credenciales
        if not all(credenciales.values()):
            missing = ", ".join(k for k, v in credenciales.items() if not v)
            raise ValidationError(f"Faltan las siguientes credenciales en la configuración técnica: {missing}")

        # 3. Validar cuenta Google Ads
        account = self.partner_id_google_ads_account
        if not account:
            raise ValidationError("El proyecto no tiene una cuenta de Google Ads asignada.")

        # 4. Validar fechas
        since_date = self.date_start
        until_date = self.date
        if not since_date or not until_date:
            raise ValidationError("Por favor define las fechas de inicio y fin del proyecto.")

        since_str = since_date.strftime('%Y-%m-%d')
        until_str = until_date.strftime('%Y-%m-%d')

        # 5. Configurar cliente Google Ads
        client = GoogleAdsClient.load_from_dict({
            **credenciales,
            'use_proto_plus': True,
        })
        service = client.get_service('GoogleAdsService')

        # 7. Query: campañas con impresiones en el rango
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                metrics.impressions
            FROM campaign
            WHERE
                segments.date BETWEEN '{since_str}' AND '{until_str}'
                AND metrics.impressions > 0
        """

        # 8. Ejecutar query y crear campañas
        response = service.search(customer_id=account, query=query)

        for row in response:
            CampaignGA.create({
                'campaign_id': str(row.campaign.id),
                'name': row.campaign.name,
                'account_id': account,
                'project_id': self.id,
            })

    def _is_campaign_within_range(self, campaign, since_date, until_date):  # optimizado
        """Valida que la campaña esté dentro del rango de fechas."""
        start_str = campaign.get('start_time')
        end_str = campaign.get('stop_time')
        start_date = fields.Date.from_string(start_str) if start_str else None
        end_date = fields.Date.from_string(end_str) if end_str else None

        # Verificar superposición
        return ((start_date is None or start_date <= until_date) and (end_date is None or end_date >= since_date))

    def get_facebook_data(self, since, until):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{self.partner_facebook_page_id}"
        # ==========================
        # 📊 MÉTRICAS DE PÁGINA (v24)
        # ==========================
        page_metrics = [
            'page_media_view',  # reemplaza impressions
            'page_post_engagements',
            'page_follows',  # reemplaza page_fans
            'page_views_total',  # sigue siendo válida
        ]

        params = {
            'metric': ','.join(page_metrics),
            'since': since,
            'until': until,
            'period': 'day',
            'access_token': self.partner_page_access_token,
        }

        all_data = []
        url = f"{BASE_URL}/insights"
        original_until = int(until)

        while url:
            response = requests.get(url, params=params if '?' not in url else {}, timeout=15)
            response.raise_for_status()
            result = response.json()

            all_data.extend(result.get('data', []))

            next_url = result.get('paging', {}).get('next')
            if next_url:
                parsed_url = urlparse(next_url)
                query = parse_qs(parsed_url.query)
                next_until = int(query.get('until', [9999999999])[0])
                if next_until > original_until:
                    break
                url = next_url
                params = {}
            else:
                url = None

        # 🔹 valores crudos por métrica
        totals = {m['name']: m.get('values', []) for m in all_data}

        # ==========================
        # 🧾 POSTS + INSIGHTS (v24)
        # ==========================
        post_url = f"{BASE_URL}/feed"
        post_params = {
            'fields': ('id,message,shares,attachments,created_time,full_picture,'
                       'comments.metric(total_count),'
                       'insights.metric('
                       'post_media_view,'  # reemplaza impressions
                       'post_reactions_by_type_total'
                       '),'
                       'is_published'),
            'since': since,
            'until': until,
            'access_token': self.partner_page_access_token,
        }

        posts_matrix = []
        post_type_data = defaultdict(lambda: {
            'posts': 0,
            'views': 0,
            'reactions': 0,
            'comments': 0,
            'shares': 0,
        })

        page_count = 0
        max_pages = 50

        while post_url and page_count < max_pages:
            post_response = requests.get(post_url, params=post_params, timeout=20)
            post_response.raise_for_status()
            post_result = post_response.json()

            posts = post_result.get('data', [])
            for post in posts:
                attachments = post.get('attachments', {}).get('data', [
                    {}
                ])
                post_type = attachments[0].get('type', 'post').lower() if attachments else 'post'

                insights = post.get('insights', {}).get('data', [])
                insights_dict = {i['name']: i['values'][0]['value'] for i in insights if i.get('values')}

                views = insights_dict.get('post_media_view', 0)
                reactions_by_type = insights_dict.get('post_reactions_by_type_total', {})
                total_reactions = sum(reactions_by_type.values()) if isinstance(reactions_by_type, dict) else 0

                total_comments = post.get('comments', {}).get('summary', {}).get('total_count', 0)
                total_shares = post.get('shares', {}).get('count', 0)

                posts_matrix.append({
                    'type': post_type,
                    'views': views,
                    'reactions': total_reactions,
                    'reactions_by_type': reactions_by_type,
                    'picture_url': post.get('full_picture', ''),
                    'message': (post.get('message', '') or '')[:100],
                    'created_time': post.get('created_time', ''),
                    'post_id': post.get('id', ''),
                    'comments': total_comments,
                    'shares': total_shares,
                })

                post_type_data[post_type]['posts'] += 1
                post_type_data[post_type]['views'] += views
                post_type_data[post_type]['reactions'] += total_reactions
                post_type_data[post_type]['comments'] += total_comments
                post_type_data[post_type]['shares'] += total_shares

            post_url = post_result.get('paging', {}).get('next')
            post_params = {}
            page_count += 1

        resumen_por_tipo = dict(post_type_data)
        return {
            'totals': totals,
            'post_type_summary': resumen_por_tipo,
            'top_posts': posts_matrix,
        }

    def get_instagram_data(self, since, until):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')

        """
        Devuelve los datos crudos de Instagram: métricas generales y posts.
        """
        import requests

        # 1️⃣ Métricas de cuenta
        account_metrics = requests.get(f"https://graph.facebook.com/{API_VERSION}/{self.partner_instagram_page_id}",
                                       params={
                                           'access_token': self.partner_page_access_token,
                                           'fields': 'followers_count,media_count'
                                       }, timeout=15).json()

        # 2️⃣ Métricas por día
        metrics_keys = [
            'reach',
            'profile_views',
            'accounts_engaged',
            'total_interactions',
            'likes',
            'comments',
            'shares',
            'saves',
            'replies',
            'follows_and_unfollows',
            'views',
            'profile_links_taps'
        ]
        base_url = f"https://graph.facebook.com/{API_VERSION}/{self.partner_instagram_page_id}/insights"
        params = {
            'access_token': self.partner_page_access_token,
            'metric': ','.join(metrics_keys),
            'period': 'day',
            'metric_type': 'total_value',
            'since': since,
            'until': until
        }
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        result = response.json()

        # Función de paginación
        def paginate_results(initial_result):
            yield initial_result
            next_url = initial_result.get('paging', {}).get('next')
            while next_url:
                response = requests.get(next_url, timeout=15)
                response.raise_for_status()
                result = response.json()
                yield result
                next_url = result.get('paging', {}).get('next')

        metrics = dict.fromkeys(metrics_keys, 0)
        for page in paginate_results(result):
            for metric in page.get('data', []):
                name = metric.get('name')
                if name in metrics:
                    values = metric.get('values') or metric.get('total_value', {})
                    if isinstance(values, list):
                        metrics[name] += sum(entry.get('value', 0) for entry in values)
                    else:
                        metrics[name] += values.get('value', 0)

        # 3️⃣ Datos de posts
        media_url = f"https://graph.facebook.com/{API_VERSION}/{self.partner_instagram_page_id}/media"
        media_params = {
            'access_token': self.partner_page_access_token,
            'fields': ('id,media_type,permalink,media_url,thumbnail_url,caption,timestamp,'
                       'insights.metric('
                       'impressions,reach,views,total_interactions,likes,comments,shares,'
                       'saved,video_views,plays,ig_reels_video_view_total_time,profile_visits'
                       ').period(day)'),
            'since': since,
            'until': until,
            'limit': 100,
        }

        def paginate_media(url, params):
            while url:
                response = requests.get(url, params, timeout=15)
                response.raise_for_status()
                result = response.json()
                yield result.get('data', [])
                url = result.get('paging', {}).get('next')
                params = {}

        posts = []
        for data in paginate_media(media_url, media_params):
            for post in data:
                insights = {i['name']: i['values'][0]['value'] for i in post.get('insights', {}).get('data', [])}
                posts.append({
                    'id': post.get('id'),
                    'media_type': post.get('media_type'),
                    'thumbnail_url': post.get('thumbnail_url'),
                    'permalink': post.get('permalink'),
                    'media_url': post.get('media_url'),
                    'caption': post.get('caption', '')[:100],
                    'created_at': post.get('timestamp'),
                    'reach': insights.get('reach', 0),
                    'impressions': insights.get('impressions', 0),
                    'total_interactions': insights.get('total_interactions', 0),
                    'likes': insights.get('likes', 0),
                    'comments': insights.get('comments', 0),
                    'shares': insights.get('shares', 0),
                    'saved': insights.get('saved', 0),
                    'video_views': insights.get('video_views', 0),
                    'plays': insights.get('plays', 0),
                    'views': insights.get('views', 0),
                })

        # 4️⃣ Demográficos (edad/género + ciudades + actividad por hora)
        demo_url = f"https://graph.facebook.com/{API_VERSION}/{self.partner_instagram_page_id}/insights"
        demo_params = {
            'access_token': self.partner_page_access_token,
            'metric': 'audience_gender_age,audience_city,online_followers',
            'period': 'lifetime'
        }

        demo_response = requests.get(demo_url, params=demo_params, timeout=15).json()
        demographics = {}
        for metric in demo_response.get("data", []):
            name = metric.get("name")
            values = metric.get("values", [])
            if values:
                demographics[name] = values[0].get("value", {})

        # 🔚 Return extendido
        return {
            'account_metrics': account_metrics,
            'totals': metrics,
            'posts': posts,
            'demographics': {
                'gender_age': demographics.get('audience_gender_age', {}),
                'city': demographics.get('audience_city', {}),
                'online_followers': demographics.get('online_followers', {})
            }
        }

    def get_meta_ads_data(self, since, until):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')

        """
        Obtiene datos crudos de campañas de Meta Ads (Facebook) en el rango indicado.
        No calcula métricas agregadas; estas se calculan en merge_final_metaads_data.
        """
        import json
        from datetime import datetime, timezone
        import requests

        self.ensure_one()

        def _get_ad_creative_image(campaign_id):
            """Obtiene la URL de la imagen del primer anuncio de la campaña."""
            ads_url = f"https://graph.facebook.com/{API_VERSION}/{campaign_id}/ads"
            ads_params = {
                'access_token': self.partner_page_access_token,
                'fields': 'creative',
            }
            try:
                ads_response = requests.get(ads_url, params=ads_params).json()
                ads_data = ads_response.get('data', [])
                if not ads_data:
                    return None

                creative_id = ads_data[0].get('creative', {}).get('id')
                if not creative_id:
                    return None

                creative_url = f"https://graph.facebook.com/{API_VERSION}/{creative_id}"
                creative_params = {
                    'access_token': self.partner_page_access_token,
                    'fields': 'object_story_spec,thumbnail_url,image_url'
                }
                creative_response = requests.get(creative_url, params=creative_params).json()
                return creative_response.get('thumbnail_url')
            except Exception:
                return None

        if not self.partner_page_access_token:
            raise ValidationError("No hay Access Token configurado para esta página.")
        if not self.facebook_ad_campaigns_ids:
            raise ValidationError("Debe seleccionar al menos una campaña de Facebook para continuar.")

        all_campaigns_data = []

        # Convertir timestamps a fechas para la API
        since_date = datetime.fromtimestamp(int(since), tz=timezone.utc).strftime('%Y-%m-%d')
        until_date = datetime.fromtimestamp(int(until), tz=timezone.utc).strftime('%Y-%m-%d')

        for campaign in self.facebook_ad_campaigns_ids:
            if not campaign.campaign_id:
                continue

            url = f"https://graph.facebook.com/{API_VERSION}/{campaign.campaign_id}"
            time_range_str = f'{{"since":"{since_date}","until":"{until_date}"}}'
            params = {
                'access_token': self.partner_page_access_token,
                'fields': f'id,name,status,effective_status,insights.time_range({time_range_str}){{impressions,clicks,spend,reach,frequency,actions,cost_per_conversion,account_currency}}',
            }

            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                insights = data.get('insights', {}).get('data', [{}])[0]

                campaign_data = {
                    'campaign_id': data.get('id', ''),
                    'name': data.get('name', ''),
                    'thumbnail_url': _get_ad_creative_image(campaign.campaign_id),
                    'status': data.get('status', ''),
                    'effective_status': data.get('effective_status', ''),
                    'account_currency': insights.get('account_currency', 'PEN'),
                    'impressions': insights.get('impressions', 0),
                    'clicks': insights.get('clicks', 0),
                    'spend': insights.get('spend', 0),
                    'reach': insights.get('reach', 0),
                    'frequency': insights.get('frequency', 0),
                    'cost_per_conversion': insights.get('cost_per_conversion', 0),
                    'actions': insights.get('actions', []),
                }

                # 🔽 Llamadas adicionales: breakdowns válidos
                campaign_data['breakdowns'] = {}

                valid_breakdowns = {
                    'age_gender': 'age,gender',
                    'platform_device': 'publisher_platform,impression_device'
                }

                for key, bd in valid_breakdowns.items():
                    try:
                        insights_url = f"https://graph.facebook.com/{API_VERSION}/{campaign.campaign_id}/insights"
                        insights_params = {
                            'access_token': self.partner_page_access_token,
                            'time_range': time_range_str,
                            'fields': 'impressions,clicks,spend,reach,frequency,actions',
                            'breakdowns': bd
                        }
                        resp = requests.get(insights_url, params=insights_params, timeout=15).json()
                        campaign_data['breakdowns'][key] = resp.get('data', [])
                    except Exception:
                        campaign_data['breakdowns'][key] = []

                all_campaigns_data.append(campaign_data)

            except Exception:
                continue

        return {
            'campaigns': all_campaigns_data
        }

    def get_google_ads_data(self, since, until):  # optimizado
        """Obtiene datos de Google Ads para los proyectos especificados."""
        cfg = self.env['ir.config_parameter'].sudo()
        required_credentials = [
            'gl_google.developer_token',
            'gl_google.client_id',
            'gl_google.client_secret',
            'gl_google.refresh_token',
            'gl_google.login_customer_id'
        ]

        # Obtener y validar credenciales
        credentials = {cred: cfg.get_param(cred) for cred in required_credentials}
        missing = [cred for cred, val in credentials.items() if not val]
        if missing:  # Solo mostramos un error si falta alguna credencial
            raise ValidationError(f"Faltan credenciales en la configuración técnica: {', '.join(missing)}")

        # Resultados generales
        results = {}

        for project in self:
            try:
                # Validar cuenta de Google Ads y fechas del proyecto
                account = project.partner_id_google_ads_account
                if not account:
                    raise ValidationError(f"El proyecto {project.name} no tiene una cuenta de Google Ads asignada.")

                since_date = datetime.fromtimestamp(since, tz=timezone.utc)
                until_date = datetime.fromtimestamp(until, tz=timezone.utc)

                if not since_date or not until_date:
                    raise ValidationError(f"Define las fechas de inicio y fin para el proyecto {project.name}.")

                # Inicializar cliente de Google Ads
                client = GoogleAdsClient.load_from_dict({
                    'developer_token': credentials['gl_google.developer_token'],
                    'client_id': credentials['gl_google.client_id'],
                    'client_secret': credentials['gl_google.client_secret'],
                    'refresh_token': credentials['gl_google.refresh_token'],
                    'login_customer_id': credentials['gl_google.login_customer_id'],
                    'use_proto_plus': True,
                })
                service = client.get_service('GoogleAdsService')

                # Formatear fechas
                since_str, until_str = since_date.strftime('%Y-%m-%d'), until_date.strftime('%Y-%m-%d')

                # Obtener IDs de campañas
                campaign_ids = [str(c.campaign_id) for c in project.google_ad_campaigns_ids]
                if not campaign_ids:
                    continue

                # Consultar datos de campañas
                campaigns_filter = ', '.join(campaign_ids)
                campaign_query = f"""
                    SELECT
                      campaign.id,
                      campaign.name,
                      metrics.impressions,
                      metrics.clicks,
                      metrics.cost_micros,
                      metrics.ctr,
                      metrics.average_cpc,
                      metrics.conversions_from_interactions_rate,
                      metrics.interaction_rate,
                      metrics.all_conversions,
                      metrics.cost_per_all_conversions
                    FROM campaign
                    WHERE campaign.id IN ({campaigns_filter})
                      AND segments.date BETWEEN '{since_str}' AND '{until_str}'
                """

                # Procesar respuesta en un generador (sin listas acumulativas innecesarias)
                def fetch_campaign_data():
                    response = service.search(customer_id=account, query=campaign_query)
                    for row in response:
                        yield {
                            'id': str(row.campaign.id),
                            'name': row.campaign.name,
                            'impressions': row.metrics.impressions,
                            'clicks': row.metrics.clicks,
                            'cost': round(float(row.metrics.cost_micros or 0) / 1_000_000, 2),
                            'ctr': round(float(row.metrics.ctr or 0), 2),
                            'average_cpc': round(float(row.metrics.average_cpc or 0) / 1_000_000, 2),
                            'conversion_rate': round(100 * float(row.metrics.conversions_from_interactions_rate or 0),
                                                     2),
                            'all_conversions': float(row.metrics.all_conversions or 0),
                            'cost_per_all_conversions': round(
                                float(row.metrics.cost_per_all_conversions or 0) / 1_000_000, 2),
                            'interaction_rate': round(float(row.metrics.interaction_rate or 0), 2),
                        }

                campaigns = list(fetch_campaign_data())

                # Consultar top palabras clave
                keyword_query = f"""
                    SELECT
                        ad_group_criterion.keyword.text,
                        metrics.impressions,
                        metrics.clicks,
                        metrics.cost_micros,
                        metrics.conversions,
                        metrics.average_cpc
                    FROM keyword_view
                    WHERE segments.date BETWEEN '{since_str}' AND '{until_str}'
                      AND ad_group_criterion.status = 'ENABLED'
                      AND campaign.id IN ({campaigns_filter})
                      AND ad_group_criterion.keyword.text != ''
                    ORDER BY metrics.clicks DESC
                    LIMIT 10
                """

                # Procesar palabras clave en un paso único
                def fetch_keywords_data():
                    response = service.search(customer_id=account, query=keyword_query)
                    for row in response:
                        keyword_text = row.ad_group_criterion.keyword.text
                        if not keyword_text:  # Solo procesar palabras clave válidas
                            continue

                        conversions = row.metrics.conversions or 0.0
                        cost = float(row.metrics.cost_micros or 0) / 1_000_000
                        yield {
                            'keyword': keyword_text,
                            'clicks': row.metrics.clicks,
                            'impressions': row.metrics.impressions,
                            'conversions': conversions,
                            'cost': round(cost, 2),
                            'cost_per_conversion': round(cost / conversions, 2) if conversions else 0.0,
                            'average_cpc': round(float(row.metrics.average_cpc or 0) / 1_000_000, 2),
                        }

                keywords_summary = list(fetch_keywords_data())

                # Calcular resumen general dinámico
                total_clicks = sum(c.get('clicks', 0) for c in campaigns)
                total_impressions = sum(c.get('impressions', 0) for c in campaigns)
                total_cost = sum(c.get('cost', 0) for c in campaigns)
                total_conversions = sum(c.get('all_conversions', 0) for c in campaigns)

                summary = {
                    'total_campaigns': len(campaigns),
                    'account_currency': 'USD',  # Cambiar si es necesario
                    'impressions': total_impressions,
                    'clicks': total_clicks,
                    'spend': round(total_cost, 2),
                    'ctr': round((total_clicks / total_impressions * 100), 2) if total_impressions else 0.0,
                    'cpc': round(total_cost / total_clicks, 2) if total_clicks else 0.0,
                    'conversions': total_conversions,
                    'cost_per_conversion': round(total_cost / total_conversions, 2) if total_conversions else 0.0,
                }

                # Guardar en resultados
                results = {
                    'summary': summary,
                    'campaigns': campaigns,
                    'keywords_summary': keywords_summary,
                }
            except Exception as e:
                # Registrar error pero continuar
                raise ValidationError(f"Error al obtener datos de Google Ads para el proyecto {project.name}: {str(e)}")

        return results

    def get_tiktok_data(self, since, until):
        try:
            headers = {
                "Authorization": f"Bearer {self.partner_tiktok_access_token}",
                "Content-Type": "application/json"
            }

            # 1️⃣ Obtener info de usuario
            user_url = "https://open.tiktokapis.com/v2/user/info/"
            user_fields = "video_count,profile_deep_link,username,display_name,avatar_url,follower_count,following_count,likes_count"
            user_resp = requests.get(user_url, headers=headers, params={
                "fields": user_fields
            })
            user_data = user_resp.json().get("data", {}).get("user", {})
            if not user_data:
                raise ValueError("❌ No se pudo obtener información del usuario.")

            # 2️⃣ Obtener videos en el rango solicitado
            video_url = "https://open.tiktokapis.com/v2/video/list/"
            all_videos = []

            # Convertir timestamps a milisegundos para la API (TikTok usa ms)
            since_ms = since * 1000  # since en segundos → milisegundos
            until_ms = until * 1000  # until en segundos → milisegundos

            # Para la paginación de TikTok (cursor) necesitas milisegundos
            cursor = until_ms  # Usar until_ms en lugar de until_ts * 1000

            all_videos = []
            has_more = True

            while has_more:
                try:
                    payload = {
                        "max_count": 20,
                        "cursor": cursor
                    }
                    params = {
                        "fields": "cover_image_url,id,title,create_time,share_url,video_description,like_count,comment_count,share_count,view_count"
                    }

                    resp = requests.post(video_url, headers=headers, params=params, json=payload)
                    if resp.status_code != 200:
                        raise ValueError(f"❌ Error HTTP {resp.status_code}: {resp.text}")

                    data = resp.json().get("data", {})
                    videos = data.get("videos", [])

                    # Filtrar por rango de fechas - TikTok create_time está en SEGUNDOS
                    page_filtered = [v for v in videos if since <= v.get("create_time", 0) <= until
                                     # ← ¡CORRECCIÓN IMPORTANTE!
                                     ]

                    all_videos.extend(page_filtered)

                    has_more = data.get("has_more", False)
                    next_cursor = data.get("cursor")

                    # Verificar si debemos continuar
                    if not has_more or not next_cursor:
                        break

                    # Verificar que el cursor esté avanzando (debe ser menor que el actual)
                    if next_cursor >= cursor:
                        break

                    cursor = next_cursor

                except Exception as e:
                    break

            # 3️⃣ Crear resumen
            resumen_videos = {
                "total_videos": len(all_videos),
                "total_views": sum(v.get("view_count", 0) for v in all_videos),
                "total_likes": sum(v.get("like_count", 0) for v in all_videos),
                "total_comments": sum(v.get("comment_count", 0) for v in all_videos),
                "total_shares": sum(v.get("share_count", 0) for v in all_videos),
            }

            top_5_videos = sorted(all_videos, key=lambda v: v.get("view_count", 0), reverse=True)[:5]

            return {
                "user": user_data,
                "resumen": resumen_videos,
                "top_5_videos": top_5_videos
            }

        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error inesperado",
                    "message": f"❌ {str(e)}",
                    "type": "danger",
                    "sticky": True,
                },
            }

    def get_linkedin_data(self, since, until):
        self.ensure_one()
        access_token = (self.env["ir.config_parameter"].sudo().get_param("linkedin.access_token"))
        org_id_raw = self.partner_id.id_linkedin_organization
        since_ms = int(since) * 1000
        until_ms = int(until) * 1000

        if not access_token:
            raise ValidationError("Falta el Access Token de LinkedIn en Configuración General.")
        if not org_id_raw:
            raise ValidationError("Falta el ID de Organización de LinkedIn en el cliente.")

        org_urn = f"urn%3Ali%3Aorganization%3A{org_id_raw}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": LinkedIn_Version,
            "X-RestLi-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        # ================================================
        # 1️⃣ OBTENER SHARES (máximo 100 publicaciones)
        # ================================================
        print("ORG RAW:", repr(org_id_raw))

        # url_shares = f"https://api.linkedin.com/rest/shares?q=owners&owners=List(urn:li:organization:{org_id_raw})&count=100"
        # url = f"https://api.linkedin.com/rest/organizations/{org_urn}"
        # print(url)
        # try:
        #     r = requests.get(url, headers=headers, timeout=20)
        #     print(r.json())
        #     # Ignorar 404 (no hay posts)
        #     if r.status_code == 404:
        #         return []
        #
        #     r.raise_for_status()
        #     data = r.json()
        #
        # except Exception as e:
        #     print("SHARES error:", e)
        #     return []
        #
        # from datetime import datetime
        #
        # posts = []
        #
        # for el in data.get("elements", []):
        #     created = el.get("created", {}).get("time", 0)
        #
        #     # Rango de fechas
        #     if not (since_ms <= created <= until_ms):
        #         continue
        #
        #     # Fecha legible
        #     created_dt = datetime.utcfromtimestamp(created / 1000)
        #
        #     # Texto del post
        #     text = el.get("text", {}).get("text", "")
        #
        #     # Media (imágenes, videos, links)
        #     media = el.get("content", {}).get("contentEntities", [])
        #
        #     posts.append({
        #         "type": "SHARE",
        #         "urn": el.get("id", ""),
        #         "created_timestamp": created,
        #         "created_date": str(created_dt),
        #         "text": text,
        #         "media": media,
        #     })
        #
        # print(posts)

        # --- 1. organizationPageStatistics ---
        page_views_total = 0
        page_unique_views_total = 0
        page_custom_button_clicks = 0
        try:
            url = (f"https://api.linkedin.com/rest/organizationPageStatistics"
                   f"?q=organization&organization={org_urn}"
                   f"&timeIntervals=(timeRange:(start:{since_ms},end:{until_ms + 86400}),timeGranularityType:DAY)")
            resp = requests.get(url, headers=headers, timeout=20)
            print(resp)
            resp.raise_for_status()
            data = resp.json()
            print(data)
            for el in data.get("elements", []):
                total_stats = el.get("totalPageStatistics", {})

                views = total_stats.get("views", {})
                all_views = views.get("allPageViews", {}) or {}
                page_views_total += int(all_views.get("pageViews", 0) or 0)
                page_unique_views_total += int(all_views.get("uniquePageViews", 0) or 0)

                clicks = total_stats.get("clicks", {}) or {}
                for btn in clicks.get("desktopCustomButtonClickCounts", []) or []:
                    page_custom_button_clicks += int(btn.get("clicks", 0) or 0)
                for btn in clicks.get("mobileCustomButtonClickCounts", []) or []:
                    page_custom_button_clicks += int(btn.get("clicks", 0) or 0)

        except Exception as e:
            print(f"⚠️ No se pudo obtener organizationPageStatistics: {e}")

        # --- 2. organizationalEntityShareStatistics ---
        share_data = {}
        try:
            url_shares = (f"https://api.linkedin.com/rest/organizationalEntityShareStatistics"
                          f"?q=organizationalEntity&organizationalEntity={org_urn}"
                          f"&timeIntervals=(timeRange:(start:{since_ms},end:{until_ms + 86400}),timeGranularityType:DAY)")
            resp_shares = requests.get(url_shares, headers=headers, timeout=20)
            resp_shares.raise_for_status()
            share_data = resp_shares.json()
        except Exception as e:
            print(f"⚠️ No se pudo obtener organizationalEntityShareStatistics: {e}")
            share_data = {}

        # --- 3. Followers: período ---
        total_followers = 0
        new_followers_period = 0
        unfollows_period = 0

        try:
            url_follow_period = (f"https://api.linkedin.com/rest/organizationalEntityFollowerStatistics"
                                 f"?q=organizationalEntity&organizationalEntity={org_urn}"
                                 f"&timeIntervals=(timeRange:(start:{since_ms},end:{until_ms + 86400}),timeGranularityType:DAY)")
            resp_period = requests.get(url_follow_period, headers=headers, timeout=20)
            resp_period.raise_for_status()
            period_data = resp_period.json()
            for el in period_data.get("elements", []):
                gains = el.get("followerGains", {}) or {}
                counts = el.get("followerCounts", {}) or {}

                new_followers_period += int(gains.get("organicFollowerGain", 0) or 0)
                new_followers_period += int(gains.get("paidFollowerGain", 0) or 0)
                new_followers_period += int(counts.get("newFollowerCount", 0) or 0)
                unfollows_period += int(counts.get("unfollowCount", 0) or 0)

        except Exception as e:
            print(f"⚠️ No se pudo obtener seguidores del período: {e}")

        # --- 4. Followers: totales ---
        try:
            url_follow_total = (f"https://api.linkedin.com/rest/organizationalEntityFollowerStatistics"
                                f"?q=organizationalEntity&organizationalEntity={org_urn}")
            resp_total = requests.get(url_follow_total, headers=headers, timeout=20)
            resp_total.raise_for_status()
            total_data = resp_total.json()

            total_followers = 0
            for el in total_data.get("elements", []):
                countries = el.get("followerCountsByGeoCountry", [])
                for c in countries:
                    total_followers += int(c.get("followerCounts", {}).get("organicFollowerCount", 0) or 0)

        except Exception as e:
            print(f"⚠️ No se pudo obtener followers totales: {e}")

        # =====================================================================
        # 2️⃣ OPERACIONES Y PROCESAMIENTO
        # =====================================================================

        total_impressions = 0
        total_clicks = 0
        total_engagement = 0.0
        total_reach = 0
        tipo_publicaciones = {}
        posts = []

        elements = share_data.get("elements", [])
        for el in elements:
            stats = el.get("totalShareStatistics", {})
            share_urn = el.get("share", "")
            ugc_urn = ""
            type_name = "Post"

            value_obj = el.get("value") or el.get("reference") or el.get("activity") or {}
            if isinstance(value_obj, dict):
                possible_urn = value_obj.get("urn") or value_obj.get("entity") or ""
                if "ugcPost" in str(possible_urn):
                    ugc_urn = possible_urn

            media_type = (el.get("shareMediaCategory") or el.get("content", {}).get("shareMediaCategory") or "").lower()

            if media_type:
                if "video" in media_type:
                    type_name = "Video"
                elif "image" in media_type:
                    type_name = "Imagen"
                elif "carousel" in media_type or "document" in media_type:
                    type_name = "Carrusel"
                elif "article" in media_type:
                    type_name = "Documento"
                elif "link" in media_type:
                    type_name = "Enlace"

            time_range = el.get("timeRange", {})
            unique_impressions = stats.get("uniqueImpressionsCount", 0)
            click_count = stats.get("clickCount", 0)
            engagement_rate = stats.get("engagement", 0.0)

            total_impressions += stats.get("impressionCount", 0)
            total_clicks += click_count
            total_engagement += engagement_rate
            total_reach += stats.get("impressionCount", 0)

            tipo_publicaciones.setdefault(type_name, {
                "posts": 0,
                "reach": 0,
                "organic_reach": 0,
                "paid_reach": 0,
                "unique_impressions": 0,
                "reactions": 0,
                "comments": 0,
                "shares": 0,
                "clicks": 0,
                "engagement_total": 0.0,
            })
            tipo_publicaciones[type_name]["posts"] += 1
            tipo_publicaciones[type_name]["reach"] += stats.get("impressionCount", 0)
            tipo_publicaciones[type_name]["reactions"] += stats.get("likeCount", 0)
            tipo_publicaciones[type_name]["comments"] += stats.get("commentCount", 0)
            tipo_publicaciones[type_name]["shares"] += stats.get("shareCount", 0)
            tipo_publicaciones[type_name]["clicks"] += click_count
            tipo_publicaciones[type_name]["engagement_total"] += engagement_rate
            tipo_publicaciones[type_name]["organic_reach"] += stats.get("impressionCount", 0)
            tipo_publicaciones[type_name]["paid_reach"] += 0
            tipo_publicaciones[type_name]["unique_impressions"] += unique_impressions

            posts.append({
                "content": f"Publicación {share_urn[-8:] if share_urn else ''}",
                "type": type_name,
                "reach": stats.get("impressionCount", 0),
                "organic_reach": stats.get("impressionCount", 0),
                "paid_reach": 0,
                "reactions": stats.get("likeCount", 0),
                "comments": stats.get("commentCount", 0),
                "shares": stats.get("shareCount", 0),
                "clicks": click_count,
                "unique_impressions": unique_impressions,
                "engagement": engagement_rate,
                "picture_url": "",
                "message": f"Post {share_urn[-8:] if share_urn else ''}",
                "timeRange": time_range,
                "share_urn": share_urn,
                "ugc_urn": ugc_urn,
            })

        total_impressions += page_views_total

        for el in share_data.get("elements", []):
            stats = el.get("totalShareStatistics", {}) or {}
            reaction_counts = stats.get("reactionTypeCounts", {}) or {}
            for val in reaction_counts.values():
                tipo_publicaciones["Post"]["reactions"] += int(val or 0)

        # =====================================================================
        # 3️⃣ ESTRUCTURA FINAL
        # =====================================================================

        linkedin_data = {
            "totals": {
                "page_impressions": total_impressions,
                "page_views_total": page_views_total,
                "page_views_unique": page_unique_views_total,
                "page_followers": total_followers,
                "page_new_followers": new_followers_period,
                "page_unfollows": unfollows_period,
                "page_impressions_unique": page_unique_views_total,
                "page_post_engagements": round(total_engagement, 2),
                "page_posts_impressions": total_impressions,
                "page_custom_button_clicks": page_custom_button_clicks,
                "page_clicks_total_from_shares": total_clicks,
            },
            "post_type_summary": tipo_publicaciones,
            "posts": posts,
            "organization_id": org_id_raw,
            "time_range": {
                "since_ms": since_ms,
                "until_ms": until_ms,
            }
        }
        return linkedin_data

    def action_generate_iareport(self):
        self.ensure_one()

        try:
            # ⚡ Llamar a la función normal de reporte pero en modo JSON
            result = self.with_context(raw_json=True).action_generate_report()
            print(result)
            data = {}
            if isinstance(result, dict) and "data" in result:
                data = result["data"]

            if not data:
                raise ValidationError("No se generaron datos en el reporte IA.")

            # 🔎 Resumir usando la función estática
            resumen = resumir_reporte(data)

            json_text = json.dumps(resumen, indent=2, ensure_ascii=False)

            # 📋 Acción cliente → copiar al portapapeles
            wizard = self.env['gl.json.viewer.wizard'].create({
                'json_content': json_text
            })

            return {
                'type': 'ir.actions.act_window',
                'name': 'Resultado JSON',
                'res_model': 'gl.json.viewer.wizard',
                'view_mode': 'form',
                'res_id': wizard.id,
                'target': 'new',  # 👈 modal
            }

        except ValidationError:
            # ⛔ errores funcionales conocidos → se relanzan tal cual
            raise

        except Exception as e:
            # 🧨 cualquier otro error inesperado
            error_detalle = str(e)

            # (opcional) si quieres ver el traceback completo en el error
            # error_detalle = traceback.format_exc()

            raise ValidationError(f"Error al generar el reporte IA:\n\n{error_detalle}")

    def action_generate_report(self):
        self.ensure_one()
        # Redes desde contexto (flujo) o desde el propio proyecto
        redes = self.red_social_report_ids.mapped("name")

        if not redes:
            raise ValidationError("Debe seleccionar al menos una red social para generar el reporte.")

        # ========================
        # 🔎 Validación dinámica
        # ========================
        for red in redes:
            if red == "Facebook":
                if not self.partner_facebook_page_id or not self.partner_page_access_token:
                    raise ValidationError("Faltan credenciales de Facebook (Page ID o Access Token).")

            elif red == "Instagram":
                if not self.partner_instagram_page_id:
                    raise ValidationError("Falta el Instagram Page ID.")

            elif red == "MetaAds":
                if not self.partner_id_facebook_ad_account or not self.facebook_ad_campaigns_ids:
                    raise ValidationError("Faltan credenciales de Meta Ads (Cuenta Publicitaria o campañas).")

            elif red == "TikTok":
                if not self.partner_tiktok_access_token:
                    raise ValidationError("Falta el Access Token de TikTok.")

            elif red == "GoogleAds":
                if not self.partner_id_google_ads_account or not self.google_ad_campaigns_ids:
                    raise ValidationError("Faltan credenciales de Google Ads (Cuenta o campañas).")

            elif red == "LinkedIn":
                if not getattr(self.partner_id, "id_linkedin_organization", False):
                    raise ValidationError("Falta el ID de la Organización de LinkedIn.")

        MAX_DAYS = 30
        SECONDS_IN_DAY = 86400

        # Mapeo entre modelo red.social.name y las claves de data_sources
        source_map = {
            'Facebook': [
                'facebook_data',
            ],
            'MetaAds': [
                'meta_ads_data'
            ],
            'Instagram': [
                'instagram_data'
            ],
            'GoogleAds': [
                'google_ads_data'
            ],
            'TikTok': [
                'tiktok_data'
            ],
            'LinkedIn': [
                'linkedin_data',
            ],
        }

        # Lista completa de posibles fuentes
        data_sources = [
            {
                'name': 'Facebook',
                'check': self.partner_facebook_page_id,
                'fetch_method': self.get_facebook_data,
                'data_key': 'facebook_data',
            },
            {
                'name': 'Instagram',
                'check': self.partner_facebook_page_id,
                'fetch_method': self.get_instagram_data,
                'data_key': 'instagram_data',
            },
            {
                'name': 'MetaAds',
                'check': self.partner_facebook_page_id and self.facebook_ad_campaigns_ids,
                'fetch_method': self.get_meta_ads_data,
                'data_key': 'meta_ads_data',
            },
            {
                'name': 'GoogleAds',
                'check': self.partner_id.id_google_ads_account and self.google_ad_campaigns_ids,
                'fetch_method': self.get_google_ads_data,
                'data_key': 'google_ads_data',
            },
            {
                'name': 'TikTok',
                'check': self.partner_tiktok_access_token,
                'fetch_method': self.get_tiktok_data,
                'data_key': 'tiktok_data',
            },
            {
                'name': 'LinkedIn',
                'check': self.partner_id.id_linkedin_organization,
                'fetch_method': self.get_linkedin_data,
                'data_key': 'linkedin_data',
            },
        ]

        selected_sources = [ds for ds in data_sources if
                            any(ds['data_key'] in source_map.get(r.name, []) for r in self.red_social_report_ids)]

        data = {
            'facebook_data': {},
            'instagram_data': {},
            'meta_ads_data': {},
            'google_ads_data': {},
            'tiktok_data': {},
            'linkedin_data': {},
            'report_period': {
                'since': self.date_start.strftime('%Y-%m-%d'),
                'until': self.date.strftime('%Y-%m-%d'),
            },
            'partner_name': self.partner_id.name,
            'partner_id': self.partner_id.id,
        }

        messages = []
        has_errors = False

        try:
            if not selected_sources:
                raise ValidationError(
                    "Debe seleccionar al menos una Red Social en el campo 'Redes a incluir en el reporte'")

            # Rango completo en fechas
            since_dt = self.date_start
            until_dt = self.date
            delta_days = (until_dt - since_dt).days
            chunks = []
            utc = pytz.UTC

            for i in range(0, delta_days + 1, MAX_DAYS):
                chunk_start = since_dt + timedelta(days=i)
                chunk_end = min(since_dt + timedelta(days=i + MAX_DAYS - 1), until_dt)

                # Crear datetime en UTC directamente
                chunk_start_dt = datetime(chunk_start.year, chunk_start.month, chunk_start.day, 0, 0, 0, tzinfo=utc)
                chunk_end_dt = datetime(chunk_end.year, chunk_end.month, chunk_end.day, 23, 59, 59, tzinfo=utc)

                chunk_start_ts = int(chunk_start_dt.timestamp())
                chunk_end_ts = int(chunk_end_dt.timestamp())

                chunks.append((chunk_start_ts, chunk_end_ts))
                print("fechas en chunk", chunk_start_ts, chunk_end_ts)

            # Iterar sobre las fuentes seleccionadas
            for source in selected_sources:
                if not source['check']:
                    continue
                use_chunks = len(chunks) > 1

                try:
                    if use_chunks:
                        chunk_results = []

                        for start_ts, end_ts in chunks:
                            fetched_data = source['fetch_method'](start_ts, end_ts)
                            if fetched_data:
                                chunk_results.append(fetched_data)
                        if chunk_results:
                            if source['data_key'] == 'google_ads_data':
                                data[source['data_key']] = merge_final_google_ads_data(chunk_results)
                            elif source['data_key'] == 'tiktok_data':
                                data[source['data_key']] = merge_final_tiktok_data(chunk_results)
                            elif source['data_key'] == 'facebook_data':
                                data[source['data_key']] = merge_final_facebook_data(chunk_results)
                            elif source['data_key'] == 'meta_ads_data':
                                data[source['data_key']] = merge_final_metaads_data(chunk_results)
                            elif source['data_key'] == 'instagram_data':
                                data[source['data_key']] = merge_final_instagram_data(chunk_results)
                            elif source['data_key'] == 'linkedin_data':  # LINKEDIN
                                data[source['data_key']] = merge_final_linkedin_data(chunk_results)
                            messages.append(f"✅ {source['name']}: datos obtenidos en chunks.")
                        else:
                            messages.append(f"⚠️ {source['name']}: sin datos en los bloques.")
                    else:
                        start_ts, end_ts = chunks[0]
                        fetched_data = source['fetch_method'](start_ts, end_ts)
                        if fetched_data:
                            merger_map = {
                                "google_ads_data": merge_final_google_ads_data,
                                "tiktok_data": merge_final_tiktok_data,
                                "facebook_data": merge_final_facebook_data,
                                "meta_ads_data": merge_final_metaads_data,
                                "instagram_data": merge_final_instagram_data,
                                "linkedin_data": merge_final_linkedin_data,  #
                            }
                            if source['data_key'] in merger_map:
                                data[source['data_key']] = merger_map[source['data_key']]([
                                    fetched_data
                                ])
                            else:
                                data[source['data_key']] = fetched_data
                            messages.append(f"✅ {source['name']}: datos obtenidos.")
                        else:
                            messages.append(f"⚠️ {source['name']}: sin datos en el período.")
                except Exception as e:
                    has_errors = True
                    messages.append(f"❌ {source['name']}: error - {str(e)}")

            if has_errors:
                if has_errors:
                    if self.env.context.get("raw_json"):
                        raise ValidationError("\n".join(messages))
                    else:
                        return {
                            'type': 'ir.actions.client',
                            'tag': 'display_notification',
                            'params': {
                                'title': "Reporte generado con advertencias",
                                'message': "\n\n".join(messages),
                                'type': 'warning',
                                'sticky': True,
                            },
                        }
            print("data",data)
            if self.env.context.get("raw_json"):
                return {
                    "data": data
                }
            return self.env.ref('gl_geniolibre.gl_print_marketing_report').report_action(self, data={
                'data': data
            })


        except Exception as e:
            if self.env.context.get("raw_json"):
                raise

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error inesperado",
                    "message": f"❌ {str(e)}",
                    "type": "danger",
                    "sticky": True,
                },
            }


def resumir_reporte(data: dict) -> dict:
    """
    Compacta el reporte final para IA.
    Usa estructuras generadas por:
    - merge_final_facebook_data
    - merge_final_instagram_data
    - merge_final_metaads_data
    - merge_final_google_ads_data
    """

    resumen = {
        "Cliente": data.get("partner_name"),
        "Periodo": data.get("report_period"),
    }

    # =========================
    # 📘 FACEBOOK
    # =========================
    fb = data.get("facebook_data", {})
    if fb:
        totals = fb.get("totals", {})

        resumen["Facebook"] = {
            "Views": totals.get("page_media_view", 0),
            "Engagements": totals.get("page_post_engagements", 0),
            "Followers": totals.get("page_follows", 0),
            "Followers Diff": totals.get("followers_diff", 0),
            "Engagement Rate (%)": totals.get("engagement_rate", 0),
            "Posts": sum(v.get("posts", 0) for v in fb.get("post_type_summary", {}).values()),
        }

        resumen["Facebook"]["Top Posts"] = [{
            "Tipo": p.get("type"),
            "Views": p.get("views"),
            "Reacciones": p.get("reactions"),
            "Comentarios": p.get("comments"),
            "Shares": p.get("shares"),
            "Texto": (p.get("message") or "")[:80],
            "URL": p.get("permalink"),
        } for p in fb.get("top_posts", [])[:5]]

    # =========================
    # 📸 INSTAGRAM
    # =========================
    ig = data.get("instagram_data", {})
    if ig:
        totals = ig.get("totals", {})
        account = ig.get("account_metrics", {})

        resumen["Instagram"] = {
            "Reach": totals.get("reach", 0),
            "Interacciones": totals.get("total_interactions", 0),
            "Cuentas Comprometidas": totals.get("accounts_engaged", 0),
            "Followers": account.get("followers_count", 0),
            "Posts": account.get("media_count", 0),
        }

        resumen["Instagram"]["Top Posts"] = [{
            "Tipo": p.get("media_type"),
            "Reach": p.get("reach"),
            "Interacciones": p.get("total_interactions"),
            "Likes": p.get("likes"),
            "Texto": (p.get("caption") or "")[:80],
            "URL": p.get("permalink"),
        } for p in ig.get("top_posts", [])[:5]]

    # =========================
    # 📢 META ADS
    # =========================
    meta = data.get("meta_ads_data", {})
    if meta:
        summary = meta.get("summary", {})

        resumen["Meta Ads"] = {
            "Campañas": summary.get("total_campaigns", 0),
            "Impresiones": summary.get("impressions", 0),
            "Clicks": summary.get("clicks", 0),
            "Reach": summary.get("reach", 0),
            "Gasto": summary.get("spend", 0),
            "CTR (%)": summary.get("ctr", 0),
            "CPC": summary.get("cpc", 0),
            "CPM": summary.get("cpm", 0),
            "Conversaciones": summary.get("total_conversaciones", 0),
        }

        resumen["Meta Ads"]["Top Campaigns"] = [{
            "Nombre": c.get("name"),
            "Estado": c.get("status"),
            "Impresiones": c.get("impressions"),
            "Clicks": c.get("clicks"),
            "Reach": c.get("reach"),
            "Gasto": c.get("spend"),
            "CTR (%)": c.get("ctr"),
            "CPC": c.get("cpc"),
        } for c in meta.get("campaigns", [])[:5]]

    # =========================
    # 🔍 GOOGLE ADS
    # =========================
    ga = data.get("google_ads_data", {})
    if ga:
        summary = ga.get("summary", {})

        resumen["Google Ads"] = {
            "Campañas": summary.get("total_campaigns", 0),
            "Impresiones": summary.get("impressions", 0),
            "Clicks": summary.get("clicks", 0),
            "Gasto": summary.get("spend", 0),
            "CTR (%)": summary.get("ctr", 0),
            "CPC": summary.get("cpc", 0),
            "Conversiones": summary.get("conversions", 0),
            "Costo por Conversión": summary.get("cost_per_conversion", 0),
        }

        resumen["Google Ads"]["Top Keywords"] = [{
            "Keyword": k.get("keyword"),
            "Clicks": k.get("clicks"),
            "Impresiones": k.get("impressions"),
            "Conversiones": k.get("conversions"),
            "Costo": k.get("cost"),
            "Costo/Conv": k.get("cost_per_conversion"),
        } for k in ga.get("keywords_summary", [])[:5]]

    return resumen


def merge_final_google_ads_data(data_list):
    merged = {
        'summary': {
            'total_campaigns': 0,
            'account_currency': 'USD',
            'impressions': 0,
            'clicks': 0,
            'spend': 0.0,
            'ctr': 0.0,
            'cpc': 0.0,
            'conversions': 0.0,
            'cost_per_conversion': 0.0,
        },
        'campaigns': [],
        'keywords_summary': []
    }

    # Diccionarios temporales para evitar duplicados
    campaign_map = {}
    keyword_map = {}

    for data in data_list:
        summary = data.get('summary', {})
        merged['summary']['impressions'] += summary.get('impressions', 0)
        merged['summary']['clicks'] += summary.get('clicks', 0)
        merged['summary']['spend'] += summary.get('spend', 0.0)
        merged['summary']['conversions'] += summary.get('conversions', 0.0)

        # Campaigns
        for camp in data.get('campaigns', []):
            cid = camp['id']
            if cid in campaign_map:
                for k in [
                    'impressions',
                    'clicks',
                    'cost',
                    'all_conversions'
                ]:
                    campaign_map[cid][k] += camp.get(k, 0)
            else:
                campaign_map[cid] = camp.copy()

        # Keywords
        for kw in data.get('keywords_summary', []):
            text = kw['keyword']
            if text in keyword_map:
                for k in [
                    'clicks',
                    'impressions',
                    'conversions',
                    'cost'
                ]:
                    keyword_map[text][k] += kw.get(k, 0)
            else:
                keyword_map[text] = kw.copy()

    # ✅ Ahora total_campaigns es el número de campañas únicas
    merged['summary']['total_campaigns'] = len(campaign_map)

    # Recalcular métricas derivadas en base a acumulados totales
    if merged['summary']['impressions']:
        merged['summary']['ctr'] = round((merged['summary']['clicks'] / merged['summary']['impressions']) * 100, 2)
    if merged['summary']['clicks']:
        merged['summary']['cpc'] = round(merged['summary']['spend'] / merged['summary']['clicks'], 2)
    if merged['summary']['conversions']:
        merged['summary']['cost_per_conversion'] = round(
            merged['summary']['spend'] / merged['summary']['conversions'], 2)

    # Finalizar campañas
    merged['campaigns'] = list(campaign_map.values())

    # Calcular cost_per_conversion individualmente en keywords
    for kw in keyword_map.values():
        conversions = kw.get('conversions', 0)
        cost = kw.get('cost', 0.0)

        # ✅ Redondear conversions a 2 decimales
        kw['conversions'] = round(conversions, 2)

        # ✅ Calcular costo por conversión con conversions ya redondeado
        kw['cost_per_conversion'] = round(cost / conversions, 2) if conversions else 0.0

        # ✅ Redondear también cost a 2 decimales
        kw['cost'] = round(cost, 2)

    merged['keywords_summary'] = list(keyword_map.values())

    # ✅ Redondear valores monetarios al final
    merged['summary']['spend'] = round(merged['summary']['spend'], 2)
    for camp in merged['campaigns']:
        camp['cost'] = round(camp.get('cost', 0.0), 2)
    for kw in merged['keywords_summary']:
        kw['cost'] = round(kw.get('cost', 0.0), 2)

    return merged


def merge_final_tiktok_data(chunk_results):
    print(chunk_results)
    try:
        if not chunk_results:
            return {}

        # Tomar datos de usuario del primer bloque (no cambian)
        user_data = chunk_results[0].get("user", {})

        # Acumular métricas de todos los chunks
        total_videos = sum(res["resumen"]["total_videos"] for res in chunk_results if "resumen" in res)
        total_views = sum(res["resumen"]["total_views"] for res in chunk_results if "resumen" in res)
        total_likes = sum(res["resumen"]["total_likes"] for res in chunk_results if "resumen" in res)
        total_comments = sum(res["resumen"]["total_comments"] for res in chunk_results if "resumen" in res)
        total_shares = sum(res["resumen"]["total_shares"] for res in chunk_results if "resumen" in res)

        # Combinar todos los videos y sacar el top 5 global
        all_videos = []
        for res in chunk_results:
            all_videos.extend(res.get("top_5_videos", []))

        top_5_videos = sorted(all_videos, key=lambda v: v.get("view_count", 0), reverse=True)[:5]

        merged = {
            "user": user_data,
            "resumen": {
                "total_videos": total_videos,
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
            },
            "top_5_videos": top_5_videos
        }

        return merged

    except Exception as e:
        return {
            "error": f"❌ Error al combinar datos de TikTok: {str(e)}"
        }


def merge_final_metaads_data(chunks):
    """
    Combina múltiples bloques de datos de MetaAds en un solo dict.
    Calcula métricas agregadas y métricas derivadas por campaña.
    Convierte las acciones a dict para que encajen en el XML.
    Filtra campañas vacías.
    """
    import json
    # Solo para depuración
    all_campaigns = []
    total_impressions = total_clicks = total_spend = total_reach = total_cost_per_conversion = 0
    total_conversaciones = 0
    account_currency = 'PEN'

    for chunk in chunks:
        campaigns = chunk.get('campaigns', [])
        for c in campaigns:
            # Filtrar campañas vacías
            if (not c.get('impressions') or float(c.get('impressions', 0)) == 0) and (
                    not c.get('clicks') or float(c.get('clicks', 0)) == 0):
                continue

            # Convertir valores a float/int
            c['impressions'] = float(c.get('impressions', 0))
            c['clicks'] = float(c.get('clicks', 0))
            c['spend'] = float(c.get('spend', 0))
            c['reach'] = float(c.get('reach', 0))
            c['frequency'] = float(c.get('frequency', 0))
            c['cost_per_conversion'] = float(c.get('cost_per_conversion', 0))

            # Calcular métricas por campaña
            c['ctr'] = round((c['clicks'] / c['impressions'] * 100) if c['impressions'] else 0, 2)
            c['cpc'] = round((c['spend'] / c['clicks']) if c['clicks'] else 0, 2)
            c['cpm'] = round((c['spend'] / c['impressions'] * 1000) if c['impressions'] else 0, 2)
            c['cpp'] = round((c['spend'] / c['reach']) if c['reach'] else 0, 2)
            c['frequency'] = round(c['frequency'], 2)

            # Convertir actions a dict (para el XML)
            c['actions'] = {a.get('action_type', ''): a.get('value', 0) for a in c.get('actions', [])}

            # Sumar totales
            total_impressions += c['impressions']
            total_clicks += c['clicks']
            total_spend += c['spend']
            total_reach += c['reach']
            total_cost_per_conversion += c['cost_per_conversion']

            # Contar conversaciones iniciadas
            total_conversaciones += int(c['actions'].get('onsite_conversion.messaging_conversation_started_7d', 0))

            # Guardar moneda
            if not account_currency and c.get('account_currency'):
                account_currency = c['account_currency']

            all_campaigns.append(c)

    # Calcular métricas agregadas (summary)
    summary = {
        'total_campaigns': len(all_campaigns),
        'account_currency': account_currency,
        'impressions': int(total_impressions),
        'clicks': int(total_clicks),
        'reach': int(total_reach),
        'spend': round(total_spend, 2),
        'ctr': round((total_clicks / total_impressions * 100) if total_impressions else 0, 2),
        'cpc': round((total_spend / total_clicks) if total_clicks else 0, 2),
        'cpm': round((total_spend / total_impressions * 1000) if total_impressions else 0, 2),
        'cpp': round((total_spend / total_reach) if total_reach else 0, 2),
        'frequency': round((total_impressions / total_reach) if total_reach else 0, 2),
        'total_conversaciones': total_conversaciones,
    }

    return {
        'summary': summary,
        'campaigns': all_campaigns
    }


def merge_final_facebook_data(chunks):
    from datetime import datetime

    merged = {
        'totals': {
            'page_media_view': 0,
            'page_views_total': 0,
            'page_post_engagements': 0,
            'page_follows': 0,  # reemplaza page_fans
        },
        'post_type_summary': {},
        'top_posts': []
    }

    all_page_follows = []  # para quedarnos con el último valor

    for chunk in chunks:
        totals = chunk.get('totals', {})

        # ==========================
        # 📊 TOTALES DE PÁGINA
        # ==========================
        for key in [
            'page_media_view',
            'page_views_total',
            'page_post_engagements',
        ]:
            values = totals.get(key, [])
            for v in values:
                merged['totals'][key] += v.get('value', 0)

        # page_follows → tomar último valor cronológico
        follows_values = totals.get('page_follows', [])
        for f in follows_values:
            value = f.get('value', 0)
            end_time = f.get('end_time')
            if end_time:
                try:
                    dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                except Exception:
                    dt = datetime.min
            else:
                dt = datetime.min
            all_page_follows.append((dt, value))

        # ==========================
        # 🧾 RESUMEN POR TIPO DE POST
        # ==========================
        for post_type, stats in chunk.get('post_type_summary', {}).items():
            if post_type not in merged['post_type_summary']:
                merged['post_type_summary'][post_type] = {
                    'posts': 0,
                    'views': 0,
                    'reactions': 0,
                    'comments': 0,
                    'shares': 0
                }

            for k in merged['post_type_summary'][post_type]:
                merged['post_type_summary'][post_type][k] += stats.get(k, 0)

        # ==========================
        # ⭐ TOP POSTS (sin duplicar)
        # ==========================
        existing_ids = {p.get('post_id') for p in merged['top_posts']}

        for post in chunk.get('top_posts', []):
            post_id = post.get('post_id')
            if post_id and post_id not in existing_ids:
                merged['top_posts'].append(post)
                existing_ids.add(post_id)

    # ==========================
    # 📌 ÚLTIMO VALOR DE FOLLOWERS
    # ==========================
    if all_page_follows:
        all_page_follows.sort(key=lambda x: x[0])
        merged['totals']['page_follows'] = all_page_follows[-1][1]

    # ==========================
    # 🏆 TOP 5 POSTS POR VIEWS
    # ==========================
    merged['top_posts'] = sorted(merged['top_posts'], key=lambda x: x.get('views', 0), reverse=True)[:5]

    def calculate_followers_diff(page_follows_values):
        """
        page_follows_values = [
            {'value': 1200, 'end_time': '...'},
            ...
        ]
        """
        if not page_follows_values:
            return 0

        # ordenar por fecha
        sorted_values = sorted(page_follows_values, key=lambda x: x.get('end_time', ''))

        start_value = sorted_values[0].get('value', 0)
        end_value = sorted_values[-1].get('value', 0)

        return end_value - start_value

    followers_values = totals.get('page_follows', [])
    followers_diff = calculate_followers_diff(followers_values)

    merged['totals']['followers_diff'] = followers_diff
    # ==========================
    # 📈 ENGAGEMENT RATE
    # ==========================
    media_views = merged['totals'].get('page_media_view', 0)
    engagements = merged['totals'].get('page_post_engagements', 0)

    if media_views > 0:
        engagement_rate = round((engagements / media_views) * 100, 2)
    else:
        engagement_rate = 0.0

    merged['totals']['engagement_rate'] = engagement_rate
    return merged


def merge_final_instagram_data(chunks):
    """
    Combina múltiples resultados crudos de Instagram y calcula métricas agregadas.
    chunks: lista de dicts devueltos por get_instagram_data.
    """
    all_posts = []

    # Inicializar totals
    totals = {
        'reach': 0,
        'profile_views': 0,
        'accounts_engaged': 0,
        'total_interactions': 0,
        'likes': 0,
        'comments': 0,
        'shares': 0,
        'saves': 0,
        'replies': 0,
        'follows_and_unfollows': 0,
        'views': 0,
        'profile_links_taps': 0
    }

    # Inicializar account_metrics
    account_metrics = {
        'followers_count': 0,
        'media_count': 0
    }

    # Inicializar summary_by_type
    media_types = [
        'IMAGE',
        'VIDEO',
        'CAROUSEL',
        'REEL',
        'STORY',
        'CAROUSEL_ALBUM'
    ]
    summary_by_type = {}
    for t in media_types:
        summary_by_type[t] = {
            'views': 0,
            'reach': 0,
            'total_interactions': 0,
            'video_views': 0
        }

    for chunk in chunks:
        # Totales
        chunk_totals = chunk.get('totals', {})
        for key in totals:
            totals[key] += chunk_totals.get(key, 0)

        # Posts
        posts = chunk.get('posts', [])
        all_posts.extend(posts)

        # Account metrics - tomar el último valor (no sumar)
        if 'account_metrics' in chunk:
            # Para followers_count y media_count, tomamos el valor más reciente
            account_metrics['followers_count'] = chunk['account_metrics'].get('followers_count',
                                                                              account_metrics['followers_count'])
            account_metrics['media_count'] = chunk['account_metrics'].get('media_count', account_metrics['media_count'])

        # Summary por tipo - calcular desde los posts
        for post in posts:
            media_type = post.get('media_type', '')
            if media_type not in summary_by_type:
                summary_by_type[media_type] = {
                    'views': 0,
                    'reach': 0,
                    'total_interactions': 0,
                    'video_views': 0
                }

            summary_by_type[media_type]['views'] += post.get('views', 0)
            summary_by_type[media_type]['reach'] += post.get('reach', 0)
            summary_by_type[media_type]['total_interactions'] += post.get('total_interactions', 0)
            summary_by_type[media_type]['video_views'] += post.get('video_views', post.get('plays', 0))

    # Calcular top posts (por alcance)
    top_posts = sorted(all_posts, key=lambda x: x.get('reach', 0), reverse=True)[:5]

    # Filtrar summary_by_type para mantener solo tipos con datos
    summary_by_type = {k: v for k, v in summary_by_type.items() if any(vv != 0 for vv in v.values())}

    # Debug bonito

    return {
        'totals': totals,
        'account_metrics': account_metrics,
        'summary_by_type': summary_by_type,
        'top_posts': top_posts,
    }


def merge_final_linkedin_data(chunk_results):
    """
    Merge seguro para LinkedIn:
    - Suma totals numéricos
    - Deep-merge de post_type_summary (dict de dicts)
    - Conserva organization_id
    - Conserva el último time_range
    """
    final = {
        "totals": {},
        "post_type_summary": {},
    }
    last_time_range = None
    organization_id = None

    for chunk in (chunk_results or []):
        if not chunk:
            continue

        # meta
        if chunk.get("time_range"):
            last_time_range = chunk["time_range"]
        if chunk.get("organization_id"):
            organization_id = chunk["organization_id"]

        # totals
        totals = chunk.get("totals") or {}
        for k, v in totals.items():
            if isinstance(v, (int, float)):
                final["totals"][k] = final["totals"].get(k, 0) + v
            else:
                final["totals"][k] = v

        # post_type_summary: dict -> dict -> metrics
        pts = chunk.get("post_type_summary") or {}
        for type_name, metrics in pts.items():
            final["post_type_summary"].setdefault(type_name, {})
            for mk, mv in (metrics or {}).items():
                if isinstance(mv, (int, float)):
                    final["post_type_summary"][type_name][mk] = final["post_type_summary"][type_name].get(mk, 0) + mv
                else:
                    final["post_type_summary"][type_name][mk] = mv

    # limpiar si no hay nada
    if not final["totals"] and not final["post_type_summary"]:
        return {}

    if organization_id:
        final["organization_id"] = organization_id
    if last_time_range:
        final["time_range"] = last_time_range

    return final
