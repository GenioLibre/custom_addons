# -*- coding: utf-8 -*-:
import random, re, requests, base64, boto3, logging, html, time
import subprocess
import json
import tempfile
import base64
import botocore
import binascii
from urllib.parse import quote
from html.parser import HTMLParser
from PIL import Image, ImageOps

from io import BytesIO
from odoo.tools import html2plaintext
from odoo import models, fields, api
from datetime import datetime
from odoo.exceptions import ValidationError
from .res_config_settings import get_linkedin_api_version

import mimetypes

_logger = logging.getLogger(__name__)

API_VERSION = None
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB recomendado para vídeos
META_SYSTEM_USER_TOKEN_KEY = "gl_facebook.meta_system_user_access_token"
TIKTOK_PRIVACY_SELECTION = [
    ('PUBLIC_TO_EVERYONE', 'Publico'),
    ('MUTUAL_FOLLOW_FRIENDS', 'Amigos mutuos'),
    ('FOLLOWER_OF_CREATOR', 'Seguidores del creador'),
    ('SELF_ONLY', 'Solo yo'),
]


UNICODE_BOLD_MAP = {
    **{chr(ord('A') + i): chr(0x1D400 + i) for i in range(26)},
    **{chr(ord('a') + i): chr(0x1D41A + i) for i in range(26)},
    **{chr(ord('0') + i): chr(0x1D7CE + i) for i in range(10)},
}


def _to_unicode_bold(text):
    return "".join(UNICODE_BOLD_MAP.get(char, char) for char in (text or ""))


class PublishTextHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.bold_level = 0

    def _append(self, value):
        if value:
            self.parts.append(value)

    def _append_newline(self):
        if not self.parts:
            return
        if self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        tag = (tag or "").lower()
        if tag in ("strong", "b"):
            self.bold_level += 1
        elif tag == "br":
            self._append("\n")
        elif tag in ("p", "div", "section", "article", "ul", "ol", "tr"):
            self._append_newline()
        elif tag == "li":
            self._append_newline()
            self._append("• ")

    def handle_endtag(self, tag):
        tag = (tag or "").lower()
        if tag in ("strong", "b"):
            self.bold_level = max(0, self.bold_level - 1)
        elif tag in ("p", "div", "section", "article", "li", "ul", "ol", "tr"):
            self._append_newline()

    def handle_data(self, data):
        text = data or ""
        if self.bold_level:
            text = _to_unicode_bold(text)
        self._append(text)

    def get_text(self):
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class PublicMediaNotReady(Exception):
    """La URL publica del archivo aun no esta lista para que terceros la descarguen."""


class red_social(models.Model):
    _name = 'red.social'
    _description = 'Redes Sociales'
    name = fields.Char(string='Nombre', required=True)

    @api.model
    def _auto_init(self):
        """Crear redes sociales por defecto si faltan"""
        res = super()._auto_init()

        redes_por_defecto = [
            'Facebook',
            'Instagram',
            'LinkedIn',
            'TikTok',
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


class TikTokPrivacyOption(models.Model):
    _name = 'gl.tiktok.privacy.option'
    _description = 'TikTok Privacy Option'

    code = fields.Char(string='Codigo', required=True)
    name = fields.Char(string='Nombre', required=True)

    @api.model
    def _auto_init(self):
        res = super()._auto_init()

        existing_codes = set(self.search([]).mapped('code'))
        values_to_create = [
            {'code': code, 'name': label}
            for code, label in TIKTOK_PRIVACY_SELECTION
            if code not in existing_codes
        ]
        if values_to_create:
            self.create(values_to_create)

        return res


class ProjectTaskAttachmentLine(models.Model):
    _name = 'gl.project.task.attachment.line'
    _description = 'Project Task Attachment Order'
    _order = 'sequence, id'

    task_id = fields.Many2one('project.task', string='Tarea', required=True, ondelete='cascade')
    attachment_id = fields.Many2one('ir.attachment', string='Adjunto', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    attachment_name = fields.Char(related='attachment_id.name', string='Archivo', readonly=True)
    attachment_mimetype = fields.Char(related='attachment_id.mimetype', string='Tipo', readonly=True)

    _sql_constraints = [
        (
            'gl_task_attachment_line_unique',
            'unique(task_id, attachment_id)',
            'Cada adjunto solo puede aparecer una vez en el orden de la tarea.',
        ),
    ]


class project_task(models.Model):
    _inherit = "project.task"
    state = fields.Selection(tracking=True)  # track_visibility en versiones antiguas
    tag_ids = fields.Many2many(tracking=True)
    user_ids = fields.Many2many(tracking=True)

    fecha_publicacion = fields.Datetime("Fecha y hora de Publicación", tracking=True,
                                        default=lambda self: fields.Datetime.now())
    inicio_promocion = fields.Date("Inicio de Promoción", tracking=True)
    fin_promocion = fields.Date("Fin de Promoción", tracking=True)
    presupuesto = fields.Monetary("Presupuesto", currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Moneda')
    activar_publicidad_paga = fields.Boolean(string="Activar Publicidad Paga", tracking=True, copy=False)
    marketing_record_id = fields.Many2one('project.marketing', string="Registro Marketing", copy=False, readonly=True)
    marketing_state = fields.Selection(
        [
            ("por_publicitar", "Por publicar"),
            ("publicado", "Promocionado"),
            ("pausado", "Pausado"),
            ("terminado", "Terminado"),
        ],
        compute="_compute_marketing_state",
        string="Estado Publicidad Paga",
        readonly=True,
    )
    adjuntos_ids = fields.Many2many('ir.attachment', string='Archivos Adjuntos', tracking=True)
    attachment_line_ids = fields.One2many(
        'gl.project.task.attachment.line',
        'task_id',
        string='Orden de adjuntos',
        copy=False,
    )
    imagen_portada = fields.Image(string='Imagen de Portada')
    tipo = fields.Selection(selection=[
        ('feed', 'Feed'),
        ('video_stories', 'Historia'),
        ('video_reels', 'Reel'),
        ('otro', 'Otro')
    ], string='Tipo de Publicación', default='otro', required=True)
    red_social_ids = fields.Many2many('red.social', string='Redes Sociales', )
    hashtags = fields.Text(string="Hashtags")
    texto_en_diseno = fields.Html(string="Texto en diseño")
    objetivo = fields.Text(string="Objetivo del post")

    partner_id = fields.Many2one('res.partner')
    partner_page_access_token = fields.Char(related="partner_id.facebook_page_access_token")
    partner_facebook_page_id = fields.Char(related="partner_id.facebook_page_id")
    partner_instagram_page_id = fields.Char(related="partner_id.instagram_page_id")
    partner_tiktok_access_token = fields.Char(related="partner_id.tiktok_access_token")
    partner_linkedin_page_id = fields.Char(related="partner_id.id_linkedin_organization")

    post_estado = fields.Char(string="Estado de la Publicación", default="Pendiente")
    fb_post_id = fields.Char(string="Facebook Post ID")
    fb_post_url = fields.Char(string="Facebook URL")
    fb_video_id = fields.Char(string="Facebook Video ID")  # ------ Este se elimina
    fb_video_url = fields.Char(string="Facebook Video URL")  # ------ Este se elimina
    inst_post_id = fields.Char(string="Instagram Container/Post ID")
    inst_post_url = fields.Char(string="Instagram URL")
    linkedin_post_id = fields.Char(string="LinkedIn Post ID")
    linkedin_post_url = fields.Char(string="LinkedIn URL")
    tiktok_post_id = fields.Char(string="TikTok Post ID")
    tiktok_post_url = fields.Char(string="TikTok URL")

    has_facebook = fields.Boolean(compute="_compute_social_flags")
    has_instagram = fields.Boolean(compute="_compute_social_flags")
    has_tiktok = fields.Boolean(compute="_compute_social_flags")
    has_linkedin = fields.Boolean(compute="_compute_social_flags")

    def _get_instagram_access_tokens(self):
        self.ensure_one()
        system_token = (
            self.env["ir.config_parameter"].sudo().get_param(META_SYSTEM_USER_TOKEN_KEY) or ""
        ).strip()
        if system_token:
            return [("system", system_token)]
        partner_token = (self.partner_page_access_token or "").strip()
        return [("partner", partner_token)] if partner_token else []

    @api.depends('marketing_record_id.marketing_state')
    def _compute_marketing_state(self):
        for record in self:
            if record.marketing_record_id and record.marketing_record_id.marketing_state:
                record.marketing_state = record.marketing_record_id.marketing_state
            elif record.activar_publicidad_paga:
                record.marketing_state = "por_publicitar"
            else:
                record.marketing_state = False

    # ====================================================================================== Tiktok Requisitos#
    # PRIVACIDAD (obligatorio por API)
    tiktok_title = fields.Char(
        related='name',
        string='Titulo TikTok',
        readonly=True,
        help="TikTok usara el titulo actual de la tarea como referencia para la publicacion."
    )
    tiktok_creator_username = fields.Char(string="TikTok Username", readonly=True)
    tiktok_can_publish = fields.Boolean(string="Puede publicar en TikTok", readonly=True)
    tiktok_can_publish_reason = fields.Char(string="Motivo estado TikTok", readonly=True)
    tiktok_privacy_level_options = fields.Text(string="Opciones de privacidad TikTok", readonly=True)
    tiktok_comment_disabled = fields.Boolean(string="Comentarios deshabilitados por TikTok", readonly=True)
    tiktok_duet_disabled = fields.Boolean(string="Duet deshabilitado por TikTok", readonly=True)
    tiktok_stitch_disabled = fields.Boolean(string="Stitch deshabilitado por TikTok", readonly=True)
    tiktok_max_video_post_duration_sec = fields.Integer(string="Duracion maxima permitida TikTok", readonly=True)
    tiktok_declaration_text = fields.Text(string="Declaracion legal TikTok", readonly=True)
    tiktok_commercial_label_preview = fields.Char(string="Vista previa etiqueta comercial", readonly=True)
    tiktok_is_aigc = fields.Boolean(
        string="Contenido generado con IA",
        help="Marca este campo cuando el contenido compartido en TikTok haya sido generado o alterado con IA."
    )

    tiktok_privacy_level = fields.Selection(TIKTOK_PRIVACY_SELECTION, string="Privacidad TikTok")
    tiktok_allowed_privacy_option_ids = fields.Many2many(
        'gl.tiktok.privacy.option',
        string='Opciones de privacidad permitidas',
        compute='_compute_tiktok_allowed_privacy_option_ids',
        readonly=True,
    )
    tiktok_privacy_option_id = fields.Many2one(
        'gl.tiktok.privacy.option',
        string='Privacidad TikTok seleccionada',
        domain="[('id', 'in', tiktok_allowed_privacy_option_ids)]",
    )

    # INTERACCIONES
    tiktok_allow_comments = fields.Boolean(string="Permitir comentarios", default=False)
    tiktok_allow_duet = fields.Boolean(string="Permitir duet", default=False)
    tiktok_allow_stitch = fields.Boolean(string="Permitir stitch", default=False)

    # TOGGLE PRINCIPAL (off por defecto según TikTok)
    tiktok_is_commercial = fields.Boolean(string="¿Es contenido comercial?", default=False,
                                          help="Indica si este contenido promociona una marca, producto o servicio")

    # OPCIONES MÚLTIPLES (Your Brand y Branded Content)
    tiktok_commercial_your_brand = fields.Boolean(string="Your Brand", help="Estás promocionando tu propia marca o negocio")
    tiktok_commercial_branded = fields.Boolean(string="Branded Content", help="Estás promocionando otra marca o tercero")
    tiktok_commercial_label_info = fields.Char(string="Etiqueta Comercial", readonly=True,help="Información sobre cómo se etiquetará el contenido")
    tiktok_privacy_note = fields.Text(string="Nota Privacidad", readonly=True,help="Información sobre restricciones de privacidad")
    tiktok_legal_text = fields.Text(string="Texto Legal", readonly=True,
                                    help="Texto de conformidad legal requerido por TikTok")

    # Traer los campos del partner (solo lectura)
    tiktok_nickname = fields.Char(related='partner_id.tiktok_nickname', string='TikTok Nickname', readonly=True,
                                  store=False)
    tiktok_partner_username = fields.Char(
        related='partner_id.tiktok_username',
        string='TikTok Username (Partner)',
        readonly=True,
        store=False,
    )
    tiktok_avatar_url = fields.Char(related='partner_id.tiktok_avatar_url', string='TikTok Avatar URL', readonly=True,
                                    store=False)
    tiktok_avatar_proxy_url = fields.Char(string='TikTok Avatar', compute='_compute_tiktok_avatar_proxy_url', readonly=True)

    # Nuevo campo label para mensajes legales / restricciones de TikTok
    tiktok_creator_status_info = fields.Text(string="Estado del Creador (TikTok)", readonly=True, )
    tiktok_video_duration = fields.Integer(string="Duración del video (segundos)")

    fb_estado = fields.Char(string="Estado Facebook", default="Programado", tracking=True, copy=False)
    ig_estado = fields.Char(string="Estado Instagram", default="Programado", tracking=True, copy=False)
    tt_estado = fields.Char(string="Estado TikTok", default="Programado", tracking=True, copy=False)
    li_estado = fields.Char(string="Estado LinkedIn", default="Programado", tracking=True, copy=False)
    fb_error = fields.Text(string="Error Facebook", copy=False, tracking=True)
    ig_error = fields.Text(string="Error Instagram", copy=False, tracking=True)
    tt_error = fields.Text(string="Error TikTok", copy=False, tracking=True)
    li_error = fields.Text(string="Error LinkedIn", copy=False, tracking=True)

    @api.depends('tiktok_avatar_url')
    def _compute_tiktok_avatar_proxy_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        for rec in self:
            if rec.tiktok_avatar_url:
                proxy_path = "/gl_geniolibre/tiktok/image_proxy?url=%s" % quote(rec.tiktok_avatar_url, safe="")
                rec.tiktok_avatar_proxy_url = f"{base_url}{proxy_path}" if base_url else proxy_path
            else:
                rec.tiktok_avatar_proxy_url = False

    @api.depends('tiktok_privacy_level_options', 'tiktok_is_commercial', 'tiktok_commercial_branded')
    def _compute_tiktok_allowed_privacy_option_ids(self):
        privacy_model = self.env['gl.tiktok.privacy.option']
        for rec in self:
            codes = rec._get_effective_tiktok_privacy_options_list()
            if codes:
                rec.tiktok_allowed_privacy_option_ids = privacy_model.search([('code', 'in', codes)])
            else:
                rec.tiktok_allowed_privacy_option_ids = privacy_model.search([])

    @api.model
    def _get_tiktok_privacy_selection_map(self):
        return dict(TIKTOK_PRIVACY_SELECTION)

    @api.model
    def _get_dynamic_tiktok_privacy_selection(self, record=None):
        selection_map = self._get_tiktok_privacy_selection_map()
        if not record:
            return TIKTOK_PRIVACY_SELECTION

        privacy_options = [
            item for item in (record.tiktok_privacy_level_options or "").split(",") if item and item.strip()
        ]
        privacy_options = [item.strip() for item in privacy_options]
        if not privacy_options:
            return TIKTOK_PRIVACY_SELECTION

        return [(value, selection_map[value]) for value in privacy_options if value in selection_map]

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields=allfields, attributes=attributes)
        if allfields and "tiktok_privacy_level" not in allfields:
            return result
        if "tiktok_privacy_level" not in result:
            return result

        record = self.browse()
        active_id = self.env.context.get("active_id")
        params = self.env.context.get("params") or {}
        if not active_id and params.get("model") == "project.task":
            active_id = params.get("id")

        if active_id:
            record = self.browse(active_id).exists()

        result["tiktok_privacy_level"]["selection"] = self._get_dynamic_tiktok_privacy_selection(record)
        return result

    @api.depends("fb_estado", "ig_estado", "tt_estado", "li_estado")
    def _compute_post_estado_global(self):
        for rec in self:
            estados = [rec.fb_estado, rec.ig_estado, rec.tt_estado, rec.li_estado]
            estados_norm = [e.strip().lower() for e in estados if e]
            estados_validos = [e for e in estados_norm if e != "programado"]

            if not estados_validos:
                rec.post_estado_global = "Programado"
            elif "error" in estados_validos:
                rec.post_estado_global = "Error"
            elif all(e == "publicado" for e in estados_validos):
                rec.post_estado_global = "Publicado"
            elif "revisando" in estados_validos:
                rec.post_estado_global = "Revisando"
            elif "procesando" in estados_validos:
                rec.post_estado_global = "Procesando"
            else:
                rec.post_estado_global = "Programado"

    @api.onchange('red_social_ids', 'partner_id')
    def _onchange_red_social_ids_check_tiktok(self):
        """Sincroniza datos de TikTok al seleccionar la red social o cambiar el partner."""
        if not self.red_social_ids:
            self._clear_tiktok_account_data()
            return

        selected_networks = self.red_social_ids.mapped('name')

        if 'TikTok' in selected_networks:
            self.sync_tiktok_account_data()
        else:
            self._clear_tiktok_account_data()

    @api.onchange(
        'tiktok_is_commercial',
        'tiktok_commercial_your_brand',
        'tiktok_commercial_branded',
        'tiktok_is_aigc',
        'tiktok_privacy_level',
        'tiktok_privacy_level_options',
        'tiktok_comment_disabled',
        'tiktok_duet_disabled',
        'tiktok_stitch_disabled',
    )
    def _onchange_tiktok_guideline_fields(self):
        if self.has_tiktok or 'TikTok' in (self.red_social_ids.mapped('name') or []):
            if not self.tiktok_is_commercial:
                self.tiktok_commercial_your_brand = False
                self.tiktok_commercial_branded = False
            elif self.tiktok_privacy_level == 'SELF_ONLY' and self.tiktok_commercial_branded:
                self.tiktok_commercial_branded = False
            self._refresh_tiktok_guideline_fields()

    @api.onchange('tiktok_privacy_option_id')
    def _onchange_tiktok_privacy_option_id(self):
        for rec in self:
            rec.tiktok_privacy_level = rec.tiktok_privacy_option_id.code if rec.tiktok_privacy_option_id else False
            if rec.tiktok_privacy_level == 'SELF_ONLY' and rec.tiktok_commercial_branded:
                rec.tiktok_commercial_branded = False
                return {
                    'warning': {
                        'title': 'Restriccion de privacidad TikTok',
                        'message': "Branded content visibility cannot be set to private.",
                    }
                }

    @api.onchange('tiktok_privacy_level')
    def _onchange_tiktok_privacy_level_sync_option(self):
        privacy_model = self.env['gl.tiktok.privacy.option']
        for rec in self:
            if rec.tiktok_privacy_level:
                rec.tiktok_privacy_option_id = privacy_model.search(
                    [('code', '=', rec.tiktok_privacy_level)], limit=1
                )
            else:
                rec.tiktok_privacy_option_id = False

    @api.onchange('tiktok_commercial_branded')
    def _onchange_tiktok_commercial_branded_privacy(self):
        for rec in self:
            if not rec.tiktok_commercial_branded:
                continue

            if rec.tiktok_privacy_level == 'SELF_ONLY':
                non_private_options = [
                    code for code in rec._get_tiktok_privacy_options_list()
                    if code != 'SELF_ONLY'
                ]
                if non_private_options:
                    privacy_model = self.env['gl.tiktok.privacy.option']
                    rec.tiktok_privacy_level = non_private_options[0]
                    rec.tiktok_privacy_option_id = privacy_model.search(
                        [('code', '=', non_private_options[0])], limit=1
                    )
                else:
                    rec.tiktok_commercial_branded = False

                return {
                    'warning': {
                        'title': 'Restriccion de privacidad TikTok',
                        'message': "Branded content visibility cannot be set to private.",
                    }
                }

    @api.onchange('tiktok_is_commercial')
    def _onchange_tiktok_is_commercial_clear_flags(self):
        for rec in self:
            if not rec.tiktok_is_commercial:
                rec.tiktok_commercial_your_brand = False
                rec.tiktok_commercial_branded = False

    def _clear_tiktok_account_data(self):
        self.tiktok_privacy_option_id = False
        self.tiktok_creator_username = False
        self.tiktok_can_publish = False
        self.tiktok_can_publish_reason = False
        self.tiktok_privacy_level_options = False
        self.tiktok_comment_disabled = False
        self.tiktok_duet_disabled = False
        self.tiktok_stitch_disabled = False
        self.tiktok_max_video_post_duration_sec = 0
        self.tiktok_declaration_text = False
        self.tiktok_commercial_label_preview = False
        self.tiktok_privacy_note = False
        self.tiktok_legal_text = False
        self.tiktok_commercial_label_info = False
        self.tiktok_creator_status_info = False

    def _get_tiktok_account_clear_vals(self):
        return {
            "tiktok_privacy_option_id": False,
            "tiktok_creator_username": False,
            "tiktok_can_publish": False,
            "tiktok_can_publish_reason": False,
            "tiktok_privacy_level_options": False,
            "tiktok_comment_disabled": False,
            "tiktok_duet_disabled": False,
            "tiktok_stitch_disabled": False,
            "tiktok_max_video_post_duration_sec": 0,
            "tiktok_declaration_text": False,
            "tiktok_commercial_label_preview": False,
            "tiktok_privacy_note": False,
            "tiktok_legal_text": False,
            "tiktok_commercial_label_info": False,
            "tiktok_creator_status_info": False,
        }

    def _compute_tiktok_commercial_label_preview(self):
        self.ensure_one()
        if self.tiktok_commercial_branded:
            return "Paid partnership"
        if self.tiktok_commercial_your_brand:
            return "Promotional content"
        return False

    def _compute_tiktok_declaration_text(self):
        self.ensure_one()
        if self.tiktok_commercial_branded:
            return "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation."
        return "By posting, you agree to TikTok's Music Usage Confirmation."

    def _compute_tiktok_privacy_note(self):
        self.ensure_one()

        notes = []
        privacy_options = self._get_effective_tiktok_privacy_options_list()

        if privacy_options:
            notes.append(f"Visibilidades disponibles para esta cuenta: {', '.join(privacy_options)}.")
        if self.tiktok_privacy_level == "SELF_ONLY":
            notes.append("Con visibilidad 'Solo yo', la opcion 'Branded Content' no esta disponible.")
        if self.tiktok_commercial_branded:
            notes.append("Branded content visibility cannot be set to private.")
        if self.tiktok_comment_disabled:
            notes.append("TikTok deshabilito comentarios para esta cuenta.")
        if self.tiktok_duet_disabled:
            notes.append("TikTok deshabilito Duet para esta cuenta.")
        if self.tiktok_stitch_disabled:
            notes.append("TikTok deshabilito Stitch para esta cuenta.")

        return "\n".join(notes) if notes else False

    def _refresh_tiktok_guideline_fields(self):
        self.ensure_one()

        if self.tiktok_privacy_level == "SELF_ONLY" and self.tiktok_commercial_branded:
            non_private_options = [
                code for code in self._get_tiktok_privacy_options_list()
                if code != 'SELF_ONLY'
            ]
            if non_private_options:
                self.tiktok_privacy_level = non_private_options[0]
                self.tiktok_privacy_option_id = self.env['gl.tiktok.privacy.option'].search(
                    [('code', '=', non_private_options[0])], limit=1
                )
            else:
                self.tiktok_commercial_branded = False

        declaration_text = self._compute_tiktok_declaration_text()
        commercial_label = self._compute_tiktok_commercial_label_preview()
        privacy_note = self._compute_tiktok_privacy_note()

        legal_lines = [declaration_text]
        if commercial_label:
            legal_lines.append(f"Etiqueta comercial visible en TikTok: {commercial_label}.")
        if self.tiktok_is_aigc:
            legal_lines.append("Este contenido se marcara como AI-generated en TikTok.")

        self.update({
            "tiktok_declaration_text": declaration_text,
            "tiktok_legal_text": "\n".join(legal_lines),
            "tiktok_privacy_note": privacy_note,
            "tiktok_commercial_label_preview": commercial_label,
            "tiktok_commercial_label_info": commercial_label or False,
        })

    def _calculate_video_duration_from_attachments(self, attachments=None):
        self.ensure_one()

        attachments = attachments if attachments is not None else self._get_ordered_attachments()
        if not attachments or self.tipo not in ("video_stories", "video_reels"):
            return 0

        video_attachment = attachments[:1]
        if not video_attachment:
            return 0

        attachment = video_attachment[0]
        if attachment.mimetype != "video/mp4" or not attachment.datas:
            return 0

        return get_video_duration_ffprobe(attachment.datas)

    @api.onchange('adjuntos_ids', 'tipo')
    def _onchange_tiktok_video_duration(self):
        for rec in self:
            if rec.tipo in ("video_stories", "video_reels") and rec.adjuntos_ids:
                rec.tiktok_video_duration = rec._calculate_video_duration_from_attachments()
            elif rec.tipo not in ("video_stories", "video_reels"):
                rec.tiktok_video_duration = 0

    def _get_ordered_attachments(self, attachments=None):
        self.ensure_one()
        attachments = attachments if attachments is not None else self.adjuntos_ids
        if not attachments:
            return attachments

        if not hasattr(attachments, 'ids'):
            attachment_ids = [
                attachment.id
                for attachment in attachments
                if getattr(attachment, 'id', False)
            ]
            attachments = self.env['ir.attachment'].browse(attachment_ids)

        ordered_ids = []
        for line in self.attachment_line_ids.sorted(lambda line: (line.sequence, line.id)):
            attachment_id = line.attachment_id.id
            if attachment_id and attachment_id in attachments.ids:
                ordered_ids.append(attachment_id)

        missing_ids = [attachment.id for attachment in attachments if attachment.id not in ordered_ids]
        ordered_ids.extend(missing_ids)
        return self.env['ir.attachment'].browse(ordered_ids)

    def _build_attachment_order_from_commands(self, base_ids, commands):
        ordered_ids = list(base_ids or [])
        if not commands:
            return ordered_ids

        for command in commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue

            op_type = command[0]
            if op_type == 4 and len(command) > 1 and command[1]:
                attachment_id = command[1]
                if attachment_id in ordered_ids:
                    ordered_ids.remove(attachment_id)
                ordered_ids.append(attachment_id)
            elif op_type in (2, 3) and len(command) > 1 and command[1]:
                attachment_id = command[1]
                if attachment_id in ordered_ids:
                    ordered_ids.remove(attachment_id)
            elif op_type == 5:
                ordered_ids = []
            elif op_type == 6 and len(command) > 2:
                ordered_ids = list(command[2] or [])

        return ordered_ids

    def _resolve_attachment_order_from_commands(self, base_ids, final_ids, commands):
        ordered_ids = list(base_ids or [])
        final_ids = list(final_ids or [])
        if not commands:
            return final_ids or ordered_ids

        new_ids = [attachment_id for attachment_id in final_ids if attachment_id not in ordered_ids]
        new_ids.sort()
        new_idx = 0

        for command in commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue

            op_type = command[0]
            if op_type == 0:
                if new_idx >= len(new_ids):
                    continue
                attachment_id = new_ids[new_idx]
                new_idx += 1
                if attachment_id in ordered_ids:
                    ordered_ids.remove(attachment_id)
                ordered_ids.append(attachment_id)
            elif op_type == 4 and len(command) > 1 and command[1]:
                attachment_id = command[1]
                if attachment_id in ordered_ids:
                    ordered_ids.remove(attachment_id)
                ordered_ids.append(attachment_id)
            elif op_type in (2, 3) and len(command) > 1 and command[1]:
                attachment_id = command[1]
                if attachment_id in ordered_ids:
                    ordered_ids.remove(attachment_id)
            elif op_type == 5:
                ordered_ids = []
            elif op_type == 6 and len(command) > 2:
                ordered_ids = list(command[2] or [])

        missing_ids = [attachment_id for attachment_id in final_ids if attachment_id not in ordered_ids]
        ordered_ids.extend(missing_ids)
        return ordered_ids

    def _sync_attachment_lines(self, preferred_order_ids=None):
        line_model = self.env['gl.project.task.attachment.line']
        for rec in self:
            attachments = rec.adjuntos_ids
            existing_lines = rec.attachment_line_ids.sorted(lambda line: (line.sequence, line.id))
            existing_by_attachment = {
                line.attachment_id.id: line
                for line in existing_lines
                if line.attachment_id
            }
            attachment_ids = set(attachments.ids)

            lines_to_remove = existing_lines.filtered(
                lambda line: line.attachment_id.id not in attachment_ids
            )
            if lines_to_remove:
                lines_to_remove.unlink()

            desired_order = list(preferred_order_ids or [])
            if not desired_order:
                desired_order = [
                    line.attachment_id.id
                    for line in existing_lines
                    if line.attachment_id.id in attachment_ids
                ]

            desired_order.extend([
                attachment.id
                for attachment in attachments
                if attachment.id not in desired_order
            ])

            for index, attachment_id in enumerate(desired_order, start=1):
                if attachment_id not in attachment_ids:
                    continue

                line = existing_by_attachment.get(attachment_id)
                sequence = index * 10
                if line:
                    line.sequence = sequence
                else:
                    line_model.create({
                        'task_id': rec.id,
                        'attachment_id': attachment_id,
                        'sequence': sequence,
                    })

    def _get_tiktok_privacy_options_list(self):
        self.ensure_one()
        return [item.strip() for item in (self.tiktok_privacy_level_options or "").split(",") if item.strip()]

    def _get_effective_tiktok_privacy_options_list(self):
        self.ensure_one()
        privacy_options = self._get_tiktok_privacy_options_list()
        if self.tiktok_is_commercial and self.tiktok_commercial_branded:
            privacy_options = [code for code in privacy_options if code != 'SELF_ONLY']
        return privacy_options

    def _get_tiktok_caption_to_publish(self):
        self.ensure_one()
        return (self._prepare_text() or "").strip()

    @api.model
    def _normalize_tiktok_commercial_vals(self, vals):
        vals = dict(vals)
        if vals.get("tiktok_is_commercial") is False:
            vals["tiktok_commercial_your_brand"] = False
            vals["tiktok_commercial_branded"] = False
        return vals

    @api.model
    def _normalize_tiktok_privacy_vals(self, vals):
        vals = dict(vals)
        privacy_model = self.env['gl.tiktok.privacy.option']

        if vals.get("tiktok_privacy_option_id"):
            option = privacy_model.browse(vals["tiktok_privacy_option_id"]).exists()
            vals["tiktok_privacy_level"] = option.code if option else False
        elif "tiktok_privacy_option_id" in vals and not vals.get("tiktok_privacy_option_id"):
            vals["tiktok_privacy_level"] = False
        elif vals.get("tiktok_privacy_level") and "tiktok_privacy_option_id" not in vals:
            option = privacy_model.search([("code", "=", vals["tiktok_privacy_level"])], limit=1)
            vals["tiktok_privacy_option_id"] = option.id or False

        return vals

    def _get_tiktok_publish_state_from_error_code(self, error_code):
        self.ensure_one()

        mapping = {
            "ok": (True, "Puede publicar"),
            "spam_risk_user_banned_from_posting": (False, "No puede publicar por restriccion de cuenta"),
            "spam_risk_too_many_posts": (False, "No puede publicar ahora por limite diario"),
            "reached_active_user_cap": (False, "No puede publicar desde esta app por cupo del cliente"),
        }
        return mapping.get(error_code, (False, f"Estado TikTok no reconocido: {error_code}" if error_code else "Sin respuesta valida de TikTok"))

    def _validate_tiktok_business_rules(self):
        self.ensure_one()

        errors = []
        privacy_options = self._get_tiktok_privacy_options_list()

        if self.tipo != "video_reels":
            errors.append("TikTok solo esta habilitado para publicaciones tipo Reel.")

        if not self.partner_id:
            errors.append("Debes seleccionar un creador para publicar en TikTok.")
        elif not self.partner_id.tiktok_access_token:
            errors.append("El creador no tiene access token de TikTok configurado.")

        if not self.tiktok_privacy_level:
            errors.append("Debes seleccionar la privacidad de TikTok.")
        elif privacy_options and self.tiktok_privacy_level not in privacy_options:
            errors.append("La privacidad seleccionada no esta permitida por TikTok para esta cuenta.")

        if self.tiktok_can_publish is False:
            errors.append(self.tiktok_can_publish_reason or "TikTok indica que esta cuenta no puede publicar en este momento.")

        if self.tiktok_max_video_post_duration_sec and self.tiktok_video_duration:
            if self.tiktok_video_duration > self.tiktok_max_video_post_duration_sec:
                errors.append(
                    f"La duracion del video ({self.tiktok_video_duration}s) excede el maximo permitido por TikTok ({self.tiktok_max_video_post_duration_sec}s)."
                )

        if self.tiktok_comment_disabled and self.tiktok_allow_comments:
            errors.append("TikTok deshabilito comentarios para esta cuenta; no puedes habilitarlos.")
        if self.tiktok_duet_disabled and self.tiktok_allow_duet:
            errors.append("TikTok deshabilito Duet para esta cuenta; no puedes habilitarlo.")
        if self.tiktok_stitch_disabled and self.tiktok_allow_stitch:
            errors.append("TikTok deshabilito Stitch para esta cuenta; no puedes habilitarlo.")

        if not self.tiktok_is_commercial:
            if self.tiktok_commercial_your_brand or self.tiktok_commercial_branded:
                errors.append("Si marcas contenido comercial especifico, tambien debes activar 'Es contenido comercial'.")
        else:
            if not (self.tiktok_commercial_your_brand or self.tiktok_commercial_branded):
                errors.append("Si el contenido es comercial, debes seleccionar al menos 'Your Brand' o 'Branded Content'.")

        if self.tiktok_commercial_branded and self.tiktok_privacy_level == "SELF_ONLY":
            errors.append("Branded Content no puede publicarse con privacidad 'Solo yo'.")

        if errors:
            raise ValidationError("No se puede publicar en TikTok por estas razones:\n- " + "\n- ".join(errors))

    def _ensure_tiktok_privacy_selected(self):
        self.ensure_one()
        if 'TikTok' in (self.red_social_ids.mapped('name') or []) and not self.tiktok_privacy_level:
            raise ValidationError("Debes seleccionar la privacidad de TikTok antes de continuar.")

    def _fetch_tiktok_creator_info(self, access_token):
        url = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "fields": [
                "creator_avatar_url",
                "creator_nickname",
                "creator_username",
                "privacy_level_options",
                "comment_disabled",
                "duet_disabled",
                "stitch_disabled",
                "max_video_post_duration_sec",
                "can_publish",
            ]
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        response_json = response.json()
        return response_json

    def _fetch_tiktok_user_info(self, access_token):
        url = "https://open.tiktokapis.com/v2/user/info/"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        params = {
            "fields": "open_id,display_name,avatar_url,username",
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("data", {}).get("user", {})

    def _fetch_tiktok_video_share_url(self, access_token, video_id=None):
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        fields = "id,share_url,create_time,title"

        if video_id:
            query_url = "https://open.tiktokapis.com/v2/video/query/"
            query_payload = {
                "filters": {
                    "video_ids": [video_id],
                }
            }
            query_params = {
                "fields": fields,
            }
            try:
                query_resp = requests.post(query_url, headers=headers, params=query_params, json=query_payload, timeout=20)
                query_resp.raise_for_status()
                query_data = query_resp.json()
                videos = query_data.get("data", {}).get("videos") or query_data.get("data", {}).get("video_list") or []
                if videos and videos[0].get("share_url"):
                    return videos[0].get("share_url")
            except requests.exceptions.RequestException as err:
                _logger.warning("TikTok video/query fallo para task %s y video %s: %s", self.id, video_id, err)

        list_url = "https://open.tiktokapis.com/v2/video/list/"
        list_payload = {
            "max_count": 10,
        }
        list_params = {
            "fields": fields,
        }
        list_resp = requests.post(list_url, headers=headers, params=list_params, json=list_payload, timeout=20)
        list_resp.raise_for_status()
        list_data = list_resp.json()

        videos = list_data.get("data", {}).get("videos") or list_data.get("data", {}).get("video_list") or []
        if not videos:
            return False

        task_title = (self._get_tiktok_caption_to_publish() or self.tiktok_title or self.name or "").strip().lower()
        if task_title:
            for video in videos:
                if (video.get("title") or "").strip().lower() == task_title and video.get("share_url"):
                    return video.get("share_url")

        return videos[0].get("share_url") or False

    def sync_tiktok_account_data(self):
        self.ensure_one()
        current_privacy_level = self.tiktok_privacy_level
        privacy_model = self.env['gl.tiktok.privacy.option']

        if not self.partner_id:
            raise ValidationError("Debes seleccionar un creador antes de cargar los datos de TikTok.")

        access_token = self.partner_id.tiktok_access_token
        if not access_token:
            raise ValidationError("No existe access_token de TikTok para este creador.")

        creator_response = self._fetch_tiktok_creator_info(access_token)
        creator_data = creator_response.get("data", {})
        error_code = creator_response.get("error", {}).get("code")

        user_data = {}
        try:
            user_data = self._fetch_tiktok_user_info(access_token)
        except requests.exceptions.RequestException:
            _logger.info("No se pudo obtener user.info de TikTok para el partner %s", self.partner_id.id)

        privacy_options = creator_data.get("privacy_level_options") or []
        can_publish, can_publish_reason = self._get_tiktok_publish_state_from_error_code(error_code)
        comment_disabled = bool(creator_data.get("comment_disabled"))
        duet_disabled = bool(creator_data.get("duet_disabled"))
        stitch_disabled = bool(creator_data.get("stitch_disabled"))
        max_duration = creator_data.get("max_video_post_duration_sec") or 0

        creator_username = (
            creator_data.get("creator_username")
            or user_data.get("username")
            or self.partner_id.tiktok_username
            or False
        )
        creator_nickname = (
            creator_data.get("creator_nickname")
            or user_data.get("display_name")
            or self.partner_id.tiktok_nickname
            or False
        )
        creator_avatar = (
            creator_data.get("creator_avatar_url")
            or user_data.get("avatar_url")
            or self.partner_id.tiktok_avatar_url
            or False
        )
        declaration_lines = []
        if comment_disabled:
            declaration_lines.append("TikTok deshabilito los comentarios para esta cuenta.")
        if duet_disabled:
            declaration_lines.append("TikTok deshabilito Duet para esta cuenta.")
        if stitch_disabled:
            declaration_lines.append("TikTok deshabilito Stitch para esta cuenta.")

        status_lines = [
            f"Cuenta TikTok: {creator_nickname or 'Sin nickname'}",
            f"Username: {creator_username or 'Sin username'}",
            f"Puede publicar: {'Si' if can_publish else 'No'}",
        ]
        if can_publish_reason:
            status_lines.append(f"Motivo estado TikTok: {can_publish_reason}")
        if max_duration:
            status_lines.append(f"Duracion maxima permitida: {max_duration} segundos")
        if privacy_options:
            status_lines.append(f"Privacidades disponibles: {', '.join(privacy_options)}")

        self.update({
            "tiktok_creator_username": creator_username,
            "tiktok_can_publish": can_publish,
            "tiktok_can_publish_reason": can_publish_reason,
            "tiktok_privacy_level_options": ", ".join(privacy_options) if privacy_options else False,
            "tiktok_comment_disabled": comment_disabled,
            "tiktok_duet_disabled": duet_disabled,
            "tiktok_stitch_disabled": stitch_disabled,
            "tiktok_max_video_post_duration_sec": max_duration,
            "tiktok_declaration_text": "\n".join(declaration_lines) if declaration_lines else False,
            "tiktok_creator_status_info": "\n".join(status_lines),
        })

        if privacy_options:
            if current_privacy_level in privacy_options:
                self.tiktok_privacy_level = current_privacy_level
            elif self.tiktok_privacy_level not in privacy_options:
                self.tiktok_privacy_level = False
        self.tiktok_privacy_option_id = privacy_model.search(
            [('code', '=', self.tiktok_privacy_level)], limit=1
        ) if self.tiktok_privacy_level else False

        if comment_disabled:
            self.tiktok_allow_comments = False
        if duet_disabled:
            self.tiktok_allow_duet = False
        if stitch_disabled:
            self.tiktok_allow_stitch = False

        self._refresh_tiktok_guideline_fields()

        partner_vals = {}
        if creator_nickname and creator_nickname != self.partner_id.tiktok_nickname:
            partner_vals["tiktok_nickname"] = creator_nickname
        if creator_avatar and creator_avatar != self.partner_id.tiktok_avatar_url:
            partner_vals["tiktok_avatar_url"] = creator_avatar
        if creator_username and creator_username != self.partner_id.tiktok_username:
            partner_vals["tiktok_username"] = creator_username
        if user_data.get("open_id") and user_data.get("open_id") != self.partner_id.tiktok_open_id:
            partner_vals["tiktok_open_id"] = user_data.get("open_id")
        if partner_vals:
            self.partner_id.sudo().write(partner_vals)

    def _sync_tiktok_account_data_after_save(self):
        if self.env.context.get("skip_tiktok_sync"):
            return

        for rec in self:
            selected_networks = set(rec.red_social_ids.mapped('name') or [])

            if 'TikTok' not in selected_networks:
                rec.with_context(skip_tiktok_sync=True).write(rec._get_tiktok_account_clear_vals())
                continue

            if not rec.partner_id or not rec.partner_id.tiktok_access_token:
                rec.with_context(skip_tiktok_sync=True).write({
                    "tiktok_declaration_text": rec._compute_tiktok_declaration_text(),
                    "tiktok_legal_text": rec._compute_tiktok_declaration_text(),
                    "tiktok_privacy_note": False,
                    "tiktok_commercial_label_preview": rec._compute_tiktok_commercial_label_preview(),
                    "tiktok_commercial_label_info": rec._compute_tiktok_commercial_label_preview() or False,
                })
                continue

            try:
                rec.with_context(skip_tiktok_sync=True).sync_tiktok_account_data()
            except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as err:
                _logger.warning("No se pudo sincronizar TikTok despues de guardar la tarea %s: %s", rec.id, err)
                rec.with_context(skip_tiktok_sync=True).write({
                    "tiktok_declaration_text": rec._compute_tiktok_declaration_text(),
                    "tiktok_legal_text": rec._compute_tiktok_declaration_text(),
                    "tiktok_privacy_note": rec._compute_tiktok_privacy_note(),
                    "tiktok_commercial_label_preview": rec._compute_tiktok_commercial_label_preview(),
                    "tiktok_commercial_label_info": rec._compute_tiktok_commercial_label_preview() or False,
                })

    def action_refresh_tiktok_tab(self):
        self.ensure_one()

        if 'TikTok' not in (self.red_social_ids.mapped('name') or []):
            raise ValidationError("Debes seleccionar TikTok en redes sociales antes de actualizar este tab.")

        if self.partner_id and self.partner_id.tiktok_access_token:
            self.sync_tiktok_account_data()
        else:
            self._refresh_tiktok_guideline_fields()
            self.write({
                "tiktok_declaration_text": self.tiktok_declaration_text,
                "tiktok_legal_text": self.tiktok_legal_text,
                "tiktok_privacy_note": self.tiktok_privacy_note,
                "tiktok_commercial_label_preview": self.tiktok_commercial_label_preview,
                "tiktok_commercial_label_info": self.tiktok_commercial_label_info,
            })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "TikTok actualizado",
                "message": "Se recalcularon los datos y mensajes del tab de TikTok.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_open_tiktok_confirmation(self, action_type="publish"):
        self.ensure_one()

        if 'TikTok' not in (self.red_social_ids.mapped('name') or []):
            raise ValidationError("TikTok no esta seleccionado en redes sociales.")

        if self.partner_id and self.partner_id.tiktok_access_token:
            self.sync_tiktok_account_data()
        else:
            self._refresh_tiktok_guideline_fields()

        self._ensure_tiktok_privacy_selected()

        wizard = self.env["gl.tiktok.publish.confirm.wizard"].create({
            "task_id": self.id,
            "action_type": action_type,
        })

        return {
            "type": "ir.actions.act_window",
            "name": "Confirmar accion en TikTok",
            "res_model": "gl.tiktok.publish.confirm.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("gl_geniolibre.view_gl_tiktok_publish_confirm_wizard_form").id,
            "res_id": wizard.id,
            "target": "new",
        }

    @api.depends('red_social_ids')
    def _compute_social_flags(self):
        for rec in self:
            names = set((rec.red_social_ids.mapped('name') or []))
            rec.has_facebook = 'Facebook' in names
            rec.has_instagram = 'Instagram' in names
            rec.has_tiktok = 'TikTok' in names
            rec.has_linkedin = 'LinkedIn' in names

    def _send_admin_flow_failure_email(self, network, error_message, stage=None):
        self.ensure_one()

        admin_user = self.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            admin_user = self.env["res.users"].sudo().search([("login", "=", "admin")], limit=1)

        admin_email = admin_user.partner_id.email if admin_user and admin_user.partner_id else False
        if not admin_email:
            _logger.warning(
                "No se pudo enviar correo de error para la tarea %s porque el Administrador no tiene email.",
                self.id,
            )
            return False

        subject = f"[GenioLibre] Error en {network} para la tarea {self.display_name}"
        stage_label = stage or "flujo de publicacion"
        project_name = self.project_id.display_name if self.project_id else "Sin proyecto"
        partner_name = self.partner_id.display_name if self.partner_id else "Sin cliente"
        publish_date = self.fecha_publicacion or "Sin fecha"

        body_html = """
            <p>Se detecto un error en un flujo de publicacion.</p>
            <ul>
                <li><strong>Red:</strong> {network}</li>
                <li><strong>Etapa:</strong> {stage}</li>
                <li><strong>Tarea:</strong> {task}</li>
                <li><strong>Proyecto:</strong> {project}</li>
                <li><strong>Cliente:</strong> {partner}</li>
                <li><strong>Fecha de publicacion:</strong> {publish_date}</li>
            </ul>
            <p><strong>Detalle del error:</strong></p>
            <pre>{error}</pre>
        """.format(
            network=html.escape(str(network or "")),
            stage=html.escape(str(stage_label)),
            task=html.escape(str(self.display_name or self.name or self.id)),
            project=html.escape(str(project_name)),
            partner=html.escape(str(partner_name)),
            publish_date=html.escape(str(publish_date)),
            error=html.escape(str(error_message or "Error no especificado")),
        )

        mail_values = {
            "subject": subject,
            "email_to": admin_email,
            "body_html": body_html,
            "auto_delete": False,
        }
        self.env["mail.mail"].sudo().create(mail_values).send()
        return True

    def unlink(self):
        for task in self:
            if task.tag_ids.filtered(lambda tag: tag.name.lower() == 'plantilla'):
                raise ValidationError('No puedes eliminar tareas con la etiqueta "Plantilla".')
            if task.marketing_record_id:
                raise ValidationError(
                    'No puedes eliminar esta tarea mientras exista su registro en Project Marketing. '
                    'Elimínalo primero desde Project Marketing.'
                )
        return super(project_task, self).unlink()

    def copy(self, default=None):
        self.ensure_one()
        # Es más seguro comprobar si project_id existe antes de acceder a sus atributos
        if self.project_id and self.project_id.project_type == 'marketing':
            raise ValidationError("No se puede duplicar tareas de proyectos de tipo Marketing.")
        # Usar la sintaxis de super() preferida en Python 3
        return super().copy(default)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [
            self._normalize_tiktok_privacy_vals(self._normalize_tiktok_commercial_vals(vals))
            for vals in vals_list
        ]
        for vals in vals_list:
            if vals.get("activar_publicidad_paga") and vals.get("post_estado") != "Publicado":
                raise ValidationError("Solo puedes activar Publicidad Paga cuando el post ya está Publicado.")
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            preferred_order_ids = rec._resolve_attachment_order_from_commands(
                [],
                rec.adjuntos_ids.ids,
                vals.get('adjuntos_ids', []),
            )
            rec._sync_attachment_lines(preferred_order_ids=preferred_order_ids)
            if rec.tipo in ("video_stories", "video_reels") and rec.adjuntos_ids:
                rec.tiktok_video_duration = rec._calculate_video_duration_from_attachments()
            elif rec.tipo not in ("video_stories", "video_reels"):
                rec.tiktok_video_duration = 0
        records._sync_tiktok_account_data_after_save()
        for rec in records.filtered(lambda r: r.activar_publicidad_paga and r.post_estado == "Publicado"):
            rec.env['project.marketing'].sudo().sync_from_task(rec)
        return records

    def write(self, vals):  
        vals = self._normalize_tiktok_privacy_vals(self._normalize_tiktok_commercial_vals(vals))
        preferred_attachment_orders = {}
        records_to_unschedule = self.env['project.task']

        if 'stage_id' in vals or 'state' in vals:
            target_state = vals.get('state')
            for record in self:
                if record.post_estado != "Programado":
                    continue
                if 'stage_id' in vals or ('state' in vals and target_state != "03_approved"):
                    records_to_unschedule |= record

        if vals.get("activar_publicidad_paga"):
            target_state = vals.get("post_estado")
            if not target_state and any(record.post_estado != "Publicado" for record in self):
                raise ValidationError("Solo puedes activar Publicidad Paga cuando el post ya está Publicado.")
            if target_state and target_state != "Publicado":
                raise ValidationError("Solo puedes activar Publicidad Paga cuando el post ya está Publicado.")

        for record in self:
            current_tipo = vals.get('tipo', record.tipo)

            # Validación condicional para fecha_publicacion
            if current_tipo != "otro":
                # Verificar si fecha_publicacion está en vals o si ya tiene un valor en el registro
                fecha_publicacion_valor = vals.get('fecha_publicacion', record.fecha_publicacion)
                if not fecha_publicacion_valor:
                    raise ValidationError(
                        "La 'Fecha y hora de Publicación' es obligatoria cuando el tipo no es 'Otro'.")

            if record.state == "03_approved":
                if current_tipo == "otro":
                    continue

                if 'adjuntos_ids' in vals:
                    preferred_attachment_orders[record.id] = {
                        'base_ids': record._get_ordered_attachments().ids,
                        'commands': vals['adjuntos_ids'],
                    }
                    current_attachment_ids = set(record.adjuntos_ids.ids)
                    for command in vals['adjuntos_ids']:
                        op_type = command[0]
                        if op_type == 0:
                            pass
                        elif op_type == 1:
                            pass
                        elif op_type == 2:
                            if command[1]:
                                current_attachment_ids.discard(command[1])
                        elif op_type == 3:
                            if command[1]:
                                current_attachment_ids.discard(command[1])
                        elif op_type == 4:
                            if command[1]:
                                current_attachment_ids.add(command[1])
                        elif op_type == 5:
                            current_attachment_ids.clear()
                        elif op_type == 6:
                            current_attachment_ids = set(command[2])

                    current_attachments = record.env['ir.attachment'].browse(list(current_attachment_ids))
                else:
                    current_attachments = record.adjuntos_ids

                if not current_attachments:
                    raise ValidationError(
                        "Debe seleccionar al menos un archivo para publicar para el tipo '{}'.".format(current_tipo))

                if current_tipo != "feed":
                    if len(current_attachments) > 1:
                        raise ValidationError(
                            "Solo se acepta 1 archivo para el tipo de publicación '{}'.".format(current_tipo))
                    if current_tipo in [
                        "video_stories",
                        "video_reels"
                    ]:
                        for attachment in current_attachments:
                            if attachment.mimetype != "video/mp4":
                                raise ValidationError(
                                    "Solo se aceptan videos en formato MP4 para el tipo de publicación '{}'.".format(
                                        current_tipo))
                            else:

                                try:
                                    duration_seconds = get_video_duration_ffprobe(attachment.datas)
                                    vals['tiktok_video_duration'] = duration_seconds
                                except (ValidationError, ValueError, TypeError, OSError, subprocess.CalledProcessError, binascii.Error) as e:
                                    raise ValidationError(f"No se pudo analizar el video MP4: {e}")

                else:  # current_tipo == "feed"
                    for attachment in current_attachments:
                        if attachment.mimetype == "video/mp4":
                            raise ValidationError(
                                "Solo se aceptan imágenes para publicaciones de tipo 'Feed'. No se permiten videos MP4.")

        result = super().write(vals)

        if 'adjuntos_ids' in vals:
            for rec in self:
                order_data = preferred_attachment_orders.get(rec.id) or {}
                preferred_order_ids = rec._resolve_attachment_order_from_commands(
                    order_data.get('base_ids', []),
                    rec.adjuntos_ids.ids,
                    order_data.get('commands', []),
                )
                rec._sync_attachment_lines(preferred_order_ids=preferred_order_ids)

        if {'adjuntos_ids', 'tipo'} & set(vals.keys()):
            for rec in self:
                if rec.tipo in ("video_stories", "video_reels") and rec.adjuntos_ids:
                    rec.with_context(skip_tiktok_sync=True).write({
                        "tiktok_video_duration": rec._calculate_video_duration_from_attachments()
                    })
                elif rec.tipo not in ("video_stories", "video_reels"):
                    rec.with_context(skip_tiktok_sync=True).write({
                        "tiktok_video_duration": 0
                    })

        if {'red_social_ids', 'partner_id'} & set(vals.keys()):
            self._sync_tiktok_account_data_after_save()

        if not self.env.context.get("skip_marketing_sync") and (
            {'activar_publicidad_paga', 'post_estado', 'inicio_promocion', 'fin_promocion', 'presupuesto',
             'partner_id', 'currency_id', 'name'} & set(vals.keys())
        ):
            for rec in self:
                self.env['project.marketing'].sudo().sync_from_task(rec)

        if records_to_unschedule:
            records_to_unschedule.with_context(skip_marketing_sync=True).write({
                'post_estado': 'Pendiente'
            })

        return result

    @api.constrains('activar_publicidad_paga', 'post_estado')
    def _check_activar_publicidad_paga_requires_publicado(self):
        for record in self:
            if record.activar_publicidad_paga and record.post_estado != "Publicado":
                raise ValidationError("Solo puedes activar Publicidad Paga cuando el post ya está Publicado.")

    def programar_post(self):
        if (
            'TikTok' in self.red_social_ids.mapped('name')
            and not self.env.context.get("skip_tiktok_confirmation")
        ):
            return self.action_open_tiktok_confirmation(action_type="schedule")

        try:
            self.ensure_one()  # Asegurar que operamos sobre un único registro al principio

            if self.state != "03_approved":
                raise ValidationError("El estado de la Tarea debe ser 'Aprobado' para poder programar el post.")

            if not self.red_social_ids:
                raise ValidationError("Debe seleccionar al menos una red social para poder programar el post.")

            # Eliminar la siguiente línea: Odoo manejará el commit de la transacción.
            self.post_estado = "Programado"  # Opcional: Si este metodo se llama desde un botón y quieres dar feedback  # podrías devolver una acción de notificación, pero para la lógica del modelo  # simplemente cambiar el estado es suficiente.  # Mensaje simple

        except ValidationError:
            raise
        except (ValueError, TypeError) as e:
            _logger.error("Error en mi_funcion_critica: %s", e)
            raise ValidationError("Ocurrió un error inesperado. Revisa la notificación.")

    def cancelar_post(self):
        self.ensure_one()  # Asegura que solo hay un registro seleccionado
        self.post_estado = "Pendiente"

    def revisar_post(self, from_cron=False):
        for rec in self:
            rec._prepare_text()

            # Redes activas (seleccionadas)
            active = set((rec.red_social_ids.mapped('name') or []))

            # Ejecutar solo si está seleccionada
            if "Facebook" in active:
                rec._run_facebook_flow(from_cron)

            if "Instagram" in active:
                rec._run_instagram_flow(from_cron)

            if "TikTok" in active:
                rec._run_tiktok_flow(from_cron)

            if "LinkedIn" in active:
                rec._run_linkedin_flow(from_cron)

            # GLOBAL: si todas las redes activas están Publicado
            estados = []
            if "Facebook" in active:
                estados.append((rec.fb_estado or "").strip().lower())
            if "Instagram" in active:
                estados.append((rec.ig_estado or "").strip().lower())
            if "TikTok" in active:
                estados.append((rec.tt_estado or "").strip().lower())
            if "LinkedIn" in active:
                estados.append((rec.li_estado or "").strip().lower())

            if estados and all(e == "publicado" for e in estados):
                rec.post_estado = "Publicado"

        return True

    def _prepare_text(self):
        parser = PublishTextHTMLParser()
        parser.feed(self.description or '')
        plain_description = parser.get_text()
        plain_hashtags = html2plaintext(self.hashtags or '')
        paragraphs = [p.strip() for p in plain_description.split('\n') if p.strip()]
        formatted_description = '\n\n'.join(paragraphs)
        formatted_description = remove_duplicate_links(formatted_description).rstrip()
        combined_text = f"{formatted_description}\n\n{plain_hashtags}"
        return combined_text.replace('\u200b', '').replace('\t', '').strip()

    def _defer_publication_until_next_attempt(self, reason):
        self.ensure_one()
        active = set((self.red_social_ids.mapped('name') or []))
        vals = {'post_estado': 'Programado'}

        if 'Facebook' in active and self.fb_estado != 'Publicado':
            vals.update({'fb_estado': 'Programado', 'fb_error': False})
        if 'Instagram' in active and self.ig_estado != 'Publicado':
            vals.update({'ig_estado': 'Programado', 'ig_error': False})
        if 'TikTok' in active and self.tt_estado != 'Publicado':
            vals.update({'tt_estado': 'Programado', 'tt_error': False})
        if 'LinkedIn' in active and self.li_estado != 'Publicado':
            vals.update({'li_estado': 'Programado', 'li_error': False})

        self.write(vals)
        _logger.warning(
            "Post %s aplazado para el siguiente intento automatico: %s",
            self.id,
            reason,
        )

    def _get_facebook_pending_media_ids(self):
        self.ensure_one()
        try:
            value = (self.fb_post_id or "").strip()
            if not value.startswith("["):
                return []
            media_ids = json.loads(value)
            if isinstance(media_ids, list):
                return [str(media_id).strip() for media_id in media_ids if str(media_id).strip()]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return []

    def _get_facebook_effective_post_id(self):
        self.ensure_one()
        if self._get_facebook_pending_media_ids():
            return False
        return (self.fb_post_id or "").strip() or False

    def _run_facebook_flow(self, from_cron=False):

        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        base_url = f'https://graph.facebook.com/{API_VERSION}'
        error_messages = []

        # Texto ya preparado por rec._prepare_text() en revisar_post()
        combined_text = self._prepare_text()

        try:
            # VALIDACIÓN BASE
            if self.fb_estado == "Procesando":
                self.fb_estado = "Revisando"
                # NO retornar aquí
            # 2) FACEBOOK FEED (FOTOS)
            if self.fb_estado == "Revisando" and self.tipo == "feed" and self.fb_post_id and not self.fb_post_url:

                media_ids = self._get_facebook_pending_media_ids()

                if media_ids:
                    fb_feed_url = f"{base_url}/{self.partner_facebook_page_id}/feed"

                    payload = {
                        "access_token": self.partner_page_access_token,
                        "message": combined_text or "",
                        "attached_media": json.dumps([{"media_fbid": mid} for mid in media_ids]),
                        "published": True,
                    }

                    try:
                        resp = requests.post(fb_feed_url, data=payload, timeout=20)
                        resp.raise_for_status()
                        data = resp.json()
                    except requests.exceptions.RequestException as e:
                        self.fb_estado = "Error"
                        raise ValidationError(f"Facebook Feed: error de comunicación con la API. Detalle: {e}")

                    if data.get("id"):
                        self.fb_post_id = data["id"]
                        self.fb_estado = "Publicado"
                    else:
                        err = data.get("error", {})
                        if err.get("code") in (9007, 2207027):
                            if from_cron:
                                return True
                            return {
                                "type": "ir.actions.client",
                                "tag": "display_notification",
                                "params": {
                                    "title": "Procesando",
                                    "message": "Facebook aún está procesando las imágenes.",
                                    "type": "warning",
                                    "sticky": True,
                                    "next": {"type": "ir.actions.client", "tag": "reload"},
                                },
                            }

                        self.fb_estado = "Error"
                        raise ValidationError(f"Facebook Feed: error al publicar. Detalle: {data}")

            # URL Facebook Feed
            effective_fb_post_id = self._get_facebook_effective_post_id()
            if effective_fb_post_id and self.fb_estado == "Publicado" and not self.fb_post_url:
                self.fb_post_url = f"https://www.facebook.com/{effective_fb_post_id}"

            # 2.2) FACEBOOK STORIES (VIDEO)
            if self.tipo == "video_stories" and self.fb_post_id:
                self.fb_estado = "Publicado"

                if not self.fb_post_url:
                    self.fb_post_url = f"https://www.facebook.com/{self.partner_facebook_page_id}"

                if from_cron:
                    return True

                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Publicado",
                        "message": "Historia publicada correctamente (sin enlace público).",
                        "type": "success",
                        "sticky": False,
                        "next": {
                            "type": "ir.actions.client",
                            "tag": "reload"
                        },
                    },
                }

            # FACEBOOK REELS (VIDEO) – FLUJO POR ETAPAS
            if self.tipo == "video_reels":

                # PROCESANDO → REVISANDO (sin cortar ejecución)
                if self.fb_estado == "Procesando":
                    self.fb_estado = "Revisando"
                    return True

                # REVISANDO
                if self.fb_estado == "Revisando" and self.fb_video_id and not self.fb_post_id:

                    status_url = f"{base_url}/{self.fb_video_id}"
                    status_params = {
                        "access_token": self.partner_page_access_token,
                        "fields": "status",
                    }

                    resp = requests.get(status_url, params=status_params, timeout=20)
                    resp.raise_for_status()
                    sdata = resp.json()

                    st = sdata.get("status") or {}
                    video_status = st.get("video_status")  # ej: "processing"
                    uploading_ok = (st.get("uploading_phase") or {}).get("status") == "complete"
                    processing_state = (st.get("processing_phase") or {}).get("status")
                    publishing_state = (st.get("publishing_phase") or {}).get("status")

                    if not uploading_ok:
                        return True

                    publish_url = f"{base_url}/me/video_reels"
                    publish_params = {
                        "access_token": self.partner_page_access_token,
                        "video_id": self.fb_video_id,
                        "upload_phase": "finish",
                        "video_state": "PUBLISHED",
                        "description": combined_text or "",
                    }

                    resp = requests.post(publish_url, params=publish_params, timeout=20)
                    if resp.status_code >= 400:
                        raise ValidationError(
                            f"Facebook Reel finish error: {resp.status_code} {resp.text}"
                        )
                    pdata = resp.json()

                    post_id = pdata.get("post_id")
                    if not post_id:
                        raise ValidationError(f"Facebook Reel: no devolvió post_id. Detalle: {pdata}")

                    self.fb_post_id = post_id
                    self.fb_estado = "Revisando"
                    self.fb_error = "Facebook aun no devolvio el permalink final del reel. Se seguira revisando."

                    # Portada
                    if self.imagen_portada and self.fb_video_id:
                        # Asegura API_VERSION (si no existe arriba)
                        if not API_VERSION:
                            API_VERSION = self.env['ir.config_parameter'].sudo().get_param(
                                'gl_facebook.api_version')

                        image_data = base64.b64decode(self.imagen_portada)
                        image_file = BytesIO(image_data)
                        image_file.name = "miniatura.jpg"

                        thumb_url = f"https://graph.facebook.com/{API_VERSION}/{self.fb_video_id}/thumbnails"
                        files = {"source": ("miniatura.jpg", image_file, "image/jpeg")}
                        data = {
                            "access_token": self.partner_page_access_token,
                            "is_preferred": "true",
                        }

                        resp_thumb = requests.post(thumb_url, files=files, data=data, timeout=20)
                        if resp_thumb.status_code >= 400:
                            raise ValidationError(
                                f"FB thumbnails error: {resp_thumb.status_code} {resp_thumb.text}")

                # REVISANDO → URL REEL
                if self.fb_estado == "Revisando" and self.fb_post_id and not self.fb_post_url:
                    fallback_fb_url = f"https://www.facebook.com/{self.fb_post_id}"
                    try:
                        r = requests.get(
                            f"{base_url}/{self.fb_post_id}",
                            params={
                                "fields": "permalink_url",
                                "access_token": self.partner_page_access_token,
                            },
                            timeout=20,
                        )
                        r.raise_for_status()
                        self.fb_post_url = r.json().get("permalink_url") or fallback_fb_url
                        self.fb_estado = "Publicado"
                        self.fb_error = False
                    except requests.exceptions.RequestException as err:
                        self.fb_post_url = fallback_fb_url
                        self.fb_estado = "Publicado"
                        self.fb_error = (
                            "Facebook no devolvio permalink_url para el reel. "
                            f"Se guardo URL alternativa basada en el Post ID. Detalle: {err}"
                        )

                    return True if from_cron else {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Publicado",
                            "message": "Reel publicado correctamente.",
                            "type": "success",
                            "next": {"type": "ir.actions.client", "tag": "reload"},
                        },
                    }

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            _logger.error("Error en revisar_post (%s): %s", self.id, e)
            self.fb_estado = "Error"
            self.fb_error = str(e)
            self._send_admin_flow_failure_email("Facebook", str(e), stage="revision del flow")

            if from_cron:
                raise

            # self.post_estado = "Error"

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error inesperado",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def _run_instagram_flow(self, from_cron=False):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        base_url = f'https://graph.facebook.com/{API_VERSION}'
        instagram_tokens = self._get_instagram_access_tokens()

        # Texto por si lo necesitas en logs (caption ya se usó en el container)
        combined_text = self._prepare_text()

        try:
            # PROCESANDO → REVISANDO (etapa)
            if self.ig_estado == "Procesando":
                self.ig_estado = "Revisando"

            # REVISANDO → publicar cuando el contenedor esté listo
            if self.ig_estado == "Revisando" and self.inst_post_id and not self.inst_post_url:

                # 1) status del container
                status_url = f"{base_url}/{self.inst_post_id}"
                sdata = None
                last_http_error = None
                last_error_info = {}
                for token_source, instagram_access_token in instagram_tokens:
                    status_params = {
                        "access_token": instagram_access_token,
                        "fields": "status_code",
                    }
                    try:
                        resp = requests.get(status_url, params=status_params, timeout=20)
                        resp.raise_for_status()
                        sdata = resp.json()
                        break
                    except requests.exceptions.HTTPError as e:
                        last_http_error = e
                        link_url = f"{base_url}/{self.inst_post_id}"
                        link_params = {
                            "access_token": instagram_access_token,
                            "fields": "permalink",
                        }
                        link_resp = requests.get(link_url, params=link_params, timeout=20)
                        if link_resp.ok:
                            link_data = link_resp.json()
                            if link_data.get("permalink"):
                                self.inst_post_url = link_data["permalink"]
                                self.ig_estado = "Publicado"
                                self.ig_error = False
                                return True
                        try:
                            last_error_info = (resp.json() or {}).get("error") or {}
                        except ValueError:
                            last_error_info = {}

                if not sdata:
                    if last_error_info.get("code") == 100 and last_error_info.get("error_subcode") == 33:
                        self.ig_estado = "Revisando"
                        self.ig_error = (
                            "Instagram aun procesa el archivo o todavia no permite consultar el contenedor. "
                            "Se reintentara automaticamente."
                        )
                        return True
                    if last_http_error:
                        raise last_http_error

                status_code = sdata.get("status_code")

                # Si no hay status_code aún, o está en progreso → seguir esperando
                if not status_code or status_code in ("IN_PROGRESS", "PROCESSING"):
                    return True

                # Si el contenedor falló
                if status_code == "ERROR":
                    self.ig_estado = "Error"
                    self.ig_error = f"Container ERROR: {sdata}"
                    self._send_admin_flow_failure_email("Instagram", self.ig_error, stage="revision del flow")
                    if from_cron:
                        raise ValidationError(self.ig_error)
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Error Instagram",
                            "message": self.ig_error,
                            "type": "danger",
                            "sticky": True,
                        },
                    }

                # 2) media_publish
                publish_url = f"{base_url}/{self.partner_instagram_page_id}/media_publish"
                pdata = None
                last_publish_error = None
                for token_source, instagram_access_token in instagram_tokens:
                    publish_params = {
                        "access_token": instagram_access_token,
                        "creation_id": self.inst_post_id,
                    }
                    resp2 = requests.post(publish_url, params=publish_params, timeout=20)
                    if resp2.ok:
                        pdata = resp2.json()
                        break
                    last_publish_error = resp2
                if pdata is None:
                    if last_publish_error is not None:
                        if last_publish_error.status_code >= 500:
                            self.ig_estado = "Revisando"
                            self.ig_error = (
                                "Instagram devolvio un error temporal al publicar. "
                                "Se reintentara automaticamente."
                            )
                            return True
                        last_publish_error.raise_for_status()
                    pdata = {}

                ig_media_id = pdata.get("id")
                if not ig_media_id:
                    self.ig_estado = "Error"
                    self.ig_error = f"media_publish sin id: {pdata}"
                    self._send_admin_flow_failure_email("Instagram", self.ig_error, stage="publicacion del flow")
                    if from_cron:
                        raise ValidationError(self.ig_error)
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Error Instagram",
                            "message": self.ig_error,
                            "type": "danger",
                            "sticky": True,
                        },
                    }

                # 3) permalink (no siempre es inmediato, pero casi siempre sí)
                link_url = f"{base_url}/{ig_media_id}"
                ldata = {}
                for token_source, instagram_access_token in instagram_tokens:
                    link_params = {
                        "access_token": instagram_access_token,
                        "fields": "permalink",
                    }
                    resp3 = requests.get(link_url, params=link_params, timeout=20)
                    if resp3.ok:
                        ldata = resp3.json()
                        break

                self.inst_post_id = ig_media_id
                self.inst_post_url = ldata.get("permalink") or False
                self.ig_estado = "Publicado"
                self.ig_error = False

                return True if from_cron else {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Publicado",
                        "message": "Instagram publicado correctamente.",
                        "type": "success",
                        "next": {"type": "ir.actions.client", "tag": "reload"},
                    },
                }

            return True

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            self.ig_estado = "Error"
            self.ig_error = str(e)
            self._send_admin_flow_failure_email("Instagram", self.ig_error, stage="revision del flow")
            if from_cron:
                raise
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error Instagram",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def _run_tiktok_flow(self, from_cron=False):
        try:
            # PROCESANDO → REVISANDO
            if self.tt_estado == "Procesando":
                self.tt_estado = "Revisando"
                return True

            # REVISANDO / PUBLICADO SIN URL → consultar estado
            if self.tt_estado in ("Revisando", "Publicado") and self.tiktok_post_id and not self.tiktok_post_url:
                status_url = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
                headers = {
                    "Authorization": f"Bearer {self.partner_tiktok_access_token}",
                    "Content-Type": "application/json",
                }
                payload = {"publish_id": self.tiktok_post_id}
                resp = requests.post(status_url, headers=headers, json=payload, timeout=20)
                resp.raise_for_status()
                data = resp.json()

                status = data.get("data", {}).get("status")

                # Aún procesando
                if not status or status in ("IN_PROGRESS", "PROCESSING", "PUBLISHING"):
                    return True

                # Error en publicación
                if status in ("ERROR", "FAILED", "PUBLISH_FAILED"):
                    self.tt_estado = "Error"
                    self.tt_error = f"TikTok status error: {data}"
                    self._send_admin_flow_failure_email("TikTok", self.tt_error, stage="revision del flow")
                    if from_cron:
                        raise ValidationError(self.tt_error)
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Error TikTok",
                            "message": self.tt_error,
                            "type": "danger",
                            "sticky": True,
                        },
                    }

                # Publicado
                if status == "PUBLISH_COMPLETE":
                    video_id = data.get("data", {}).get("publicaly_available_post_id")
                    if not video_id:
                        video_id = data.get("data", {}).get("publicly_available_post_id")
                    if not video_id:
                        video_id = data.get("data", {}).get("post_id")
                    try:
                        share_url = self._fetch_tiktok_video_share_url(self.partner_tiktok_access_token, video_id)
                    except requests.exceptions.RequestException as err:
                        _logger.warning("TikTok no devolvio share_url aun para task %s: %s", self.id, err)
                        share_url = False
                    if share_url:
                        self.tiktok_post_url = share_url
                        self.tt_estado = "Publicado"
                        self.tt_error = False
                    else:
                        self.tt_estado = "Revisando"
                        self.tt_error = "TikTok publico el contenido, pero aun no devolvio un share_url para la URL final."

                    return True if from_cron else {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Publicado" if self.tiktok_post_url else "Procesando",
                            "message": "TikTok publicado correctamente." if self.tiktok_post_url else "TikTok aun no devolvio la URL final. Se seguira revisando.",
                            "type": "success" if self.tiktok_post_url else "warning",
                            "next": {"type": "ir.actions.client", "tag": "reload"},
                        },
                    }

            return True

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            self.tt_estado = "Error"
            self.tt_error = str(e)
            self._send_admin_flow_failure_email("TikTok", self.tt_error, stage="revision del flow")
            if from_cron:
                raise
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error TikTok",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def _run_linkedin_flow(self, from_cron=False):
        try:
            # PROCESANDO → REVISANDO
            if self.li_estado == "Procesando":
                self.li_estado = "Revisando"
                # no return: seguimos evaluando abajo por si ya hay URL

            # REVISANDO → completar URL si falta
            if self.li_estado == "Revisando" and self.linkedin_post_id:
                if not self.linkedin_post_url:
                    self.linkedin_post_url = f"https://www.linkedin.com/feed/update/{self.linkedin_post_id}/"
                self.li_estado = "Publicado"
                self.li_error = False

                return True if from_cron else {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Publicado",
                        "message": "LinkedIn publicado correctamente.",
                        "type": "success",
                        "next": {"type": "ir.actions.client", "tag": "reload"},
                    },
                }

            return True

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            self.li_estado = "Error"
            self.li_error = str(e)
            self._send_admin_flow_failure_email("LinkedIn", self.li_error, stage="revision del flow")
            if from_cron:
                raise
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error LinkedIn",
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def publish_on_facebook(self, media_urls, combined_text):
        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        BASE_URL_LOCAL = f'https://graph.facebook.com/{API_VERSION}'

        # ---- FEED (FOTOS) ----
        if self.tipo == "feed":

            photo_ids = []

            for photo_url in media_urls:
                upload_url = f"{BASE_URL_LOCAL}/{self.partner_facebook_page_id}/photos"
                params = {
                    "url": photo_url,  # URL pública (S3)
                    "published": "false",  # CLAVE: NO publicar aún (igual a tu lógica)
                    "access_token": self.partner_page_access_token,
                }
                resp = requests.post(upload_url, params=params)
                data = resp.json()
                if "id" not in data:
                    raise ValidationError(f"Error subiendo foto: {data}")

                photo_ids.append(data["id"])

            # Guardamos SOLO IDs reales de Facebook
            self.write({
                "fb_post_id": json.dumps(photo_ids),  # ["photo_id1","photo_id2",...]
                "fb_post_url": False,
                "fb_estado": "Procesando",
            })

            return True

        # =====================================================
        # 2) FACEBOOK STORIES (VIDEO) → PUBLICACIÓN DIRECTA
        # =====================================================
        if self.tipo == "video_stories":

            url = f"{BASE_URL_LOCAL}/{self.partner_facebook_page_id}/video_stories"

            # 1) start
            params = {
                "upload_phase": "start",
                "access_token": self.partner_page_access_token,
            }
            resp = requests.post(url, params=params)
            data = resp.json()

            if "video_id" not in data or "upload_url" not in data:
                raise ValidationError(f"Error iniciando upload Story FB: {data}")

            video_id = data["video_id"]
            upload_url = data["upload_url"]

            # Guardamos ID del video story
            self.write({
                "fb_video_id": video_id,
                "fb_post_id": False,
                "fb_estado": "Procesando",
            })

            # 2) upload file
            headers = {
                "Authorization": f"OAuth {self.partner_page_access_token}",
                "file_url": media_urls[0],
            }
            up = requests.post(upload_url, headers=headers)
            up_data = up.json()

            if "success" not in up_data:
                raise ValidationError(f"Error subiendo video Story FB: {up_data}")

            # 3) finish (requiere video_id)
            finish_params = {
                "upload_phase": "finish",
                "access_token": self.partner_page_access_token,
                "video_id": video_id,
            }

            fin = requests.post(url, params=finish_params)
            fin_data = fin.json()

            # Si devuelve post_id, guárdalo
            if fin_data.get("post_id"):
                self.write({
                    "fb_video_id": video_id,
                    "fb_post_id": fin_data.get("post_id"),
                    "fb_estado": "Publicado",
                })
            else:
                # aunque no haya post_id, tu flujo actual marca stories como publicado por fb_post_id existente en revisar
                # aquí lo dejamos como Procesando para que _run_facebook_flow lo cierre (o puedes poner Publicado si ya te funciona así)
                self.write({
                    "fb_video_id": video_id,
                    "fb_estado": "Procesando",
                })

            return True

        # =====================================================
        # 3) FACEBOOK REELS (VIDEO)
        # =====================================================
        if self.tipo == "video_reels":

            url = f"{BASE_URL_LOCAL}/{self.partner_facebook_page_id}/video_reels"

            # 1) start upload session
            params = {
                "upload_phase": "start",
                "access_token": self.partner_page_access_token,
            }
            resp = requests.post(url, params=params)
            data = resp.json()

            if "video_id" not in data or "upload_url" not in data:
                raise ValidationError(f"Error Starting session (Reel FB): {data}")

            video_id = data["video_id"]
            upload_url = data["upload_url"]

            self.write({
                "fb_video_id": video_id,
                "fb_post_id": False,
                "fb_post_url": False,
                "fb_estado": "Procesando",
            })

            # 2) upload file via file_url
            headers = {
                "Authorization": f"OAuth {self.partner_page_access_token}",
                "file_url": media_urls[0],
            }
            up = requests.post(upload_url, headers=headers)
            up_data = up.json()

            if "success" not in up_data:
                raise ValidationError(f"Error uploading Reel FB: {up_data}")

            # La publicacion final del reel se hace despues, cuando Facebook
            # confirme que la fase de upload ya termino por completo.
            return True

        return None

    def publish_on_instagram(self, media_urls, combined_text, cover_url=None):

        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        BASE_URL_LOCAL = f'https://graph.facebook.com/{API_VERSION}'
        container_url = f"{BASE_URL_LOCAL}/{self.partner_instagram_page_id}/media"
        carousel_ids = []
        instagram_tokens = self._get_instagram_access_tokens()

        try:
            # Validación: cover obligatorio para reels
            if self.tipo == "video_reels" and not cover_url:
                raise ValidationError("Instagram Reels: cover_url es obligatorio.")

            if len(media_urls) == 1:
                if self.tipo == "feed":
                    container_params = {
                        "caption": combined_text,
                        "image_url": media_urls[0],
                        "published": False,
                    }
                else:
                    if self.tipo == "video_stories":
                        container_params = {
                            "caption": combined_text,
                            "video_url": media_urls[0],
                            "published": False,
                            "media_type": "STORIES",
                        }
                    else:
                        # REELS
                        container_params = {
                            "caption": combined_text,
                            "video_url": media_urls[0],
                            "published": False,
                            "media_type": "REELS",
                            "cover_url": cover_url,  # ✅ obligatorio
                        }

                data = None
                last_container_error = None
                for token_source, instagram_access_token in instagram_tokens:
                    params_with_token = dict(container_params, access_token=instagram_access_token)
                    r = requests.post(container_url, params=params_with_token, timeout=20)
                    data = r.json()
                    if r.status_code == 200 and data.get("id"):
                        break
                    last_container_error = data
                    data = None
                if not data:
                    raise ValidationError(f"Error al crear contenedor IG: {last_container_error}")
                container_id = data["id"]

            else:
                # Carrusel (asumimos imágenes)
                for url in media_urls:
                    item_params = {
                        "is_carousel_item": "true",
                        "image_url": url,
                        "published": False,
                    }
                    d = None
                    last_item_error = None
                    for token_source, instagram_access_token in instagram_tokens:
                        params_with_token = dict(item_params, access_token=instagram_access_token)
                        rr = requests.post(container_url, params=params_with_token, timeout=20)
                        d = rr.json()
                        if rr.status_code == 200 and d.get("id"):
                            break
                        last_item_error = d
                        d = None
                    if not d:
                        raise ValidationError(f"Error item carrusel IG: {last_item_error}")
                    carousel_ids.append(d["id"])

                carousel_params = {
                    "media_type": "CAROUSEL",
                    "children": ",".join(carousel_ids),
                    "caption": combined_text,
                    "published": False,
                }
                data = None
                last_carousel_error = None
                for token_source, instagram_access_token in instagram_tokens:
                    params_with_token = dict(carousel_params, access_token=instagram_access_token)
                    r = requests.post(container_url, params=params_with_token, timeout=20)
                    data = r.json()
                    if r.status_code == 200 and data.get("id"):
                        break
                    last_carousel_error = data
                    data = None
                if not data:
                    raise ValidationError(f"Error contenedor carrusel IG: {last_carousel_error}")
                container_id = data["id"]

            self.write({
                "inst_post_id": container_id,
                "inst_post_url": False,
                "ig_estado": "Procesando",
                "ig_error": False,
            })

            return True

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            self.write({
                "ig_estado": "Error",
                "ig_error": str(e),
            })
            raise

    def publish_on_tiktok(self, media_urls, combined_text, cover_url=None):
        url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
        tiktok_caption = self._get_tiktok_caption_to_publish()
        self._ensure_tiktok_privacy_selected()
    
        headers = {
            "Authorization": f"Bearer {self.partner_tiktok_access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }
    
        data = {
            "post_info": {
                "title": tiktok_caption,
                "privacy_level": self.tiktok_privacy_level,
                "disable_duet": not self.tiktok_allow_duet,
                "disable_comment": not self.tiktok_allow_comments,
                "disable_stitch": not self.tiktok_allow_stitch,
                "video_cover_timestamp_ms": 0,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": media_urls[0],
            }
        }
        tiktok_response = requests.post(url, headers=headers, json=data)
        response_data = tiktok_response.json()
        if tiktok_response.status_code != 200:
            raise ValidationError(f"Error al Publicar el video en TIKTOK: {response_data}")
        # You can then check the response
        return response_data["data"]["publish_id"]
    
    def publish_on_linkedin(self, media_urls, combined_text, cover_url=None):
    
        self.ensure_one()
    
        # -------------------------------------------------- Validaciones básicas
        if not media_urls:
            raise ValidationError("No se proporcionaron URLs de medios")
    
        linkedin_access_token = (self.env["ir.config_parameter"].sudo().get_param("linkedin.access_token"))
        if not linkedin_access_token:
            raise ValidationError("Falta configurar linkedin.access_token")
    
        org_urn = f"urn:li:organization:{self.partner_linkedin_page_id}"
        headers = {
            "Authorization": f"Bearer {linkedin_access_token}",
            "LinkedIn-Version": get_linkedin_api_version(self.env),
            "X-RestLi-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        session = requests.Session()
        session.headers.update(headers)
    
        # Combinar título y descripción
    
        try:
            # ================================================= VIDEO (reel) ====
            if self.tipo == "video_reels":
                if len(media_urls) != 1:
                    raise ValidationError("Los Reels solo admiten un (1) video")
    
                # 1‑A  initializeUpload
                head_resp = requests.head(media_urls[0])
                head_resp.raise_for_status()
                size_bytes = int(head_resp.headers.get("Content-Length", 0))
                if size_bytes == 0:
                    raise ValidationError("No se pudo obtener el tamaño del video")
    
                # ¿Tenemos portada?
                has_thumbnail = bool(self.imagen_portada)
    
                init_payload = {
                    "initializeUploadRequest": {
                        "owner": org_urn,
                        "fileSizeBytes": size_bytes,
                        "uploadCaptions": False,
                        "uploadThumbnail": has_thumbnail  # ▶️ TRUE solo si hay portada
                    }
                }
    
                init_resp = session.post("https://api.linkedin.com/rest/videos?action=initializeUpload",
                                         json=init_payload)
    
                init_resp.raise_for_status()
                init_json = init_resp.json()
    
                video_urn = init_json["value"]["video"]
                upload_token = init_json["value"]["uploadToken"]
                upload_instructions = init_json["value"]["uploadInstructions"]
                thumbnail_url = init_json["value"].get("thumbnailUploadUrl")  # ← solo si pedimos thumbnail
    
                uploaded_etags = []
                for instruction in upload_instructions:
                    upload_url = instruction["uploadUrl"]
                    first_byte = instruction["firstByte"]
                    last_byte = instruction["lastByte"]
                    chunk_size = last_byte - first_byte + 1
                    range_header = f"bytes={first_byte}-{last_byte}"
    
                    # Descargar el chunk exacto
                    chunk_resp = requests.get(media_urls[0], headers={
                        "Range": range_header
                    }, stream=True)
    
                    chunk_resp.raise_for_status()
                    chunk_data = chunk_resp.content  # Leer contenido completo
    
                    put_headers = {
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(chunk_size)
                    }
    
                    # Subir a LinkedIn
                    upload_resp = session.put(upload_url, headers=put_headers, data=chunk_data, timeout=30)
                    upload_resp.raise_for_status()
    
                    etag = upload_resp.headers.get("ETag")
                    if not etag:
                        raise ValidationError("No se recibió ETag al subir parte del video")
                    uploaded_etags.append(etag)
    
                    # ------------------------------------------------------------------ 1‑C  subir la miniatura (si existe)
    
                if has_thumbnail and thumbnail_url:
                    thumb_bytes = base64.b64decode(self.imagen_portada)
                    session.put(thumbnail_url, headers={
                        "Content-Type": "image/jpeg"
                    },  # fijo, siempre JPG
                                data=thumb_bytes, timeout=15, ).raise_for_status()
    
                # 1‑C Finalizar la subida
                finalize_payload = {
                    "finalizeUploadRequest": {
                        "video": video_urn,
                        "uploadToken": upload_token,
                        "uploadedPartIds": uploaded_etags  # ❗ ETags, no partNumbers
                    }
                }
                finalize_resp = session.post("https://api.linkedin.com/rest/videos?action=finalizeUpload",
                                             json=finalize_payload)
                finalize_resp.raise_for_status()
    
                # Estado "procesando"
                self.post_estado = "Procesando"
                self.linkedin_post_id = video_urn
    
                # 1‑D Crear el post (reel) usando el video_urn
                post_data = {
                    "author": org_urn,
                    "commentary": combined_text,
                    "visibility": "PUBLIC",
                    "distribution": {
                        "feedDistribution": "MAIN_FEED",
                        "targetEntities": [],
                        "thirdPartyDistributionChannels": [],
                    },
                    "content": {
                        "media": {
                            "id": video_urn,
                        }
                    },
                    "lifecycleState": "PUBLISHED",
                    "isReshareDisabledByAuthor": False,
                }
    
            # =============================================== IMÁGENES / CARRUSEL
            elif self.tipo == "feed":
                media_urns = []
                for url in media_urls:
                    # 2‑A  initializeUpload por imagen
                    init_resp = session.post("https://api.linkedin.com/rest/images?action=initializeUpload", json={
                        "initializeUploadRequest": {
                            "owner": org_urn
                        }
                    })
                    init_resp.raise_for_status()
                    init_json = init_resp.json()
    
                    image_urn = init_json["value"]["image"]
                    upload_url = init_json["value"]["uploadUrl"]
                    mime, _ = mimetypes.guess_type(url)
    
                    # 2‑B  subir la imagen
                    img_content = requests.get(url).content
                    requests.put(upload_url, headers={
                        "Content-Type": mime or "application/octet-stream",
                    }, data=img_content).raise_for_status()
                    media_urns.append(image_urn)
    
                # 2‑C  crear post según 1 o varias imágenes
                post_data = {
                    "author": org_urn,
                    "commentary": combined_text,
                    "visibility": "PUBLIC",
                    "distribution": {
                        "feedDistribution": "MAIN_FEED",
                        "targetEntities": [],
                        "thirdPartyDistributionChannels": [],
                    },
                    "lifecycleState": "PUBLISHED",
                    "isReshareDisabledByAuthor": False,
                }
                if len(media_urns) == 1:
                    post_data["content"] = {
                        "media": {
                            "id": media_urns[0]
                        }
                    }
                else:
                    post_data["content"] = {
                        "multiImage": {
                            "images": [{
                                "id": u
                            } for u in media_urns]
                        }
                    }
    
            # ======================================================= Otros tipos
            else:
                raise ValidationError(f"Tipo de publicación no soportado: {self.tipo}")
    
            # =============================================== 3) Crear el post
            post_resp = session.post("https://api.linkedin.com/rest/posts", json=post_data)
    
            post_resp.raise_for_status()
    
            post_urn = post_resp.headers.get("X-RestLi-Id")
            if not post_urn:
                raise ValidationError("LinkedIn no devolvió un URN en X‑RestLi‑Id")
    
            # Solo si no es video, marcamos como publicado
            if self.tipo != "video_reels":
                self.post_estado = "Publicado"
    
            return {
                "post_id": post_urn,
                "post_url": f"https://www.linkedin.com/feed/update/{post_urn}/"
            }
    
        # ---------------------------------------------------- Manejo de errores
        except requests.exceptions.HTTPError as err:
            self.post_estado = "Error"
            error_msg = f"Error HTTP {err.response.status_code}"
            try:
                error_details = err.response.json()
                if 'message' in error_details:
                    error_msg += f": {error_details['message']}"
                elif 'error' in error_details:
                    error_msg += f": {error_details['error']}"
            except:
                error_msg += f": {err.response.text[:200]}"
    
            raise ValidationError(error_msg) from err
    
        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            self.post_estado = "Error"
            raise ValidationError(f"Error inesperado: {str(e)}") from e

    def publicar_post(self):
        self.ensure_one()

        if (
            'TikTok' in self.red_social_ids.mapped('name')
            and not self.env.context.get("from_cron")
            and not self.env.context.get("skip_tiktok_confirmation")
        ):
            return self.action_open_tiktok_confirmation(action_type="publish")

        API_VERSION = self.env['ir.config_parameter'].sudo().get_param('gl_facebook.api_version')
        BASE_URL = f'https://graph.facebook.com/{API_VERSION}'
        from_cron = bool(self.env.context.get("from_cron"))

        # Funciones
        def upload_images_to_facebook(attachment):

            image_bytes = base64.b64decode(attachment.datas)
            files = {
                'source': ("image.jpg", image_bytes, "image/jpeg")  # File name and MIME type
            }
            data = {
                "access_token": self.partner_page_access_token,
                "published": False,
                "temporary": True,
            }
            url = f"{BASE_URL}/{self.partner_facebook_page_id}/photos"
            response_upload = requests.post(url, files=files, data=data)
            if response_upload.status_code == 200:
                return response_upload.json().get('id')
            else:
                raise Exception(f"Error al subir una imagen en Facebook: {response_upload.json()}")

        # Validaciones iniciales (detienen todo el proceso si fallan)
        if not self.imagen_portada and self.tipo == "video_reels":
            raise ValidationError("Debe especificar una portada para el reel")

        if not self.fecha_publicacion:
            raise ValidationError("Debe seleccionar una fecha de publicación")

        if self.state != "03_approved":
            raise ValidationError("El estado de la Tarea debe ser 'Aprobado'")

        if not self.red_social_ids:
            raise ValidationError("Debe seleccionar al menos una red social")

        if 'TikTok' in self.red_social_ids.mapped('name') and self.tipo != "video_reels":
            raise ValidationError("TikTok solo admite publicaciones tipo Reel en este flujo.")

        try:
            # Configuración inicial
            parametros = self.env['ir.config_parameter'].sudo()
            aws_api = parametros.get_param('gl_aws.api_key')
            aws_secret = parametros.get_param('gl_aws.secret')
            aws_bucket = parametros.get_param('gl_aws.bucket') or 'odoo-geniolibre'
            aws_public_domain = parametros.get_param('gl_aws.public_domain') or 'https://s3.geniolibredev.com'

            combined_text = self._prepare_text()

            # Validación de credenciales por red social
            credential_errors = []
            if 'Facebook' in self.red_social_ids.mapped('name') and not self.partner_facebook_page_id:
                credential_errors.append("Facebook")
            if 'Instagram' in self.red_social_ids.mapped('name') and not self.partner_instagram_page_id:
                credential_errors.append("Instagram")
            if 'TikTok' in self.red_social_ids.mapped('name') and not self.partner_tiktok_access_token:
                credential_errors.append("TikTok")
            if 'LinkedIn' in self.red_social_ids.mapped('name') and not self.partner_linkedin_page_id:
                credential_errors.append("LinkedIn")

            if credential_errors:
                raise ValidationError(
                    f"Los datos de acceso no fueron configurados para: {', '.join(credential_errors)}")

            # Subir archivos a S3 (única operación que debe fallar completamente si hay error)
            self._sync_attachment_lines()
            ordered_attachments = self._get_ordered_attachments()
            media_urls_native = upload_files_to_s3(
                ordered_attachments, aws_api, aws_secret, aws_bucket, aws_public_domain, url_mode="native"
            )
            media_urls_custom = upload_files_to_s3(
                ordered_attachments, aws_api, aws_secret, aws_bucket, aws_public_domain, url_mode="custom"
            )
            _logger.info(f"Archivos subidos a S3. URLs nativas obtenidas: {media_urls_native}")
            _logger.info(f"Archivos subidos a S3. URLs custom obtenidas: {media_urls_custom}")

            cover_url_native = None
            cover_url_custom = None
            if self.imagen_portada and self.tipo == "video_reels":
                cover_url_native = upload_files_to_s3(
                    [("portada.jpg", self.imagen_portada)],
                    aws_api,
                    aws_secret,
                    aws_bucket,
                    aws_public_domain,
                    url_mode="native",
                )[0]
                cover_url_custom = upload_files_to_s3(
                    [("portada.jpg", self.imagen_portada)],
                    aws_api,
                    aws_secret,
                    aws_bucket,
                    aws_public_domain,
                    url_mode="custom",
                )[0]

            active_networks = set(self.red_social_ids.mapped('name') or [])
            meta_networks = {'Facebook', 'Instagram', 'LinkedIn'}
            if active_networks & meta_networks:
                urls_to_verify = list(media_urls_native)
                if cover_url_native:
                    urls_to_verify.append(cover_url_native)

                for media_url in urls_to_verify:
                    is_ready, detail = verify_public_media_url(media_url)
                    if not is_ready:
                        reason = (
                            "La URL publica del archivo aun no esta disponible para Meta. "
                            f"URL: {media_url}. Detalle: {detail}"
                        )
                        self._defer_publication_until_next_attempt(reason)
                        if from_cron:
                            return False
                        return {
                            "type": "ir.actions.client",
                            "tag": "display_notification",
                            "params": {
                                "title": "Archivo en preparacion",
                                "message": "El archivo aun no esta listo para Meta. Se intentara nuevamente.",
                                "type": "warning",
                                "sticky": True,
                                "next": {"type": "ir.actions.client", "tag": "reload"},
                            },
                        }

            # Publicación en redes sociales con gestión de errores individual
            errors = []
            success_messages = []
            published_on = []

            procesando = False
            # Facebook
            if 'Facebook' in self.red_social_ids.mapped('name'):
                try:
                    # marcar inicio
                    self.write({"fb_estado": "Procesando", "fb_error": False})
                    self.publish_on_facebook(media_urls_native, combined_text)
                    success_messages.append("Facebook: Publicación en proceso")
                    published_on.append("Facebook")
                except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
                    self.write({"fb_estado": "Error", "fb_error": str(e)})
                    self._send_admin_flow_failure_email("Facebook", str(e), stage="inicio de publicacion")
                    errors.append(f"Facebook: {str(e)}")

            # Instagram
            if 'Instagram' in self.red_social_ids.mapped('name'):
                try:
                    # marcar inicio
                    self.write({"ig_estado": "Procesando", "ig_error": False})
                    self.publish_on_instagram(media_urls_native, combined_text, cover_url_native)
                    success_messages.append("Instagram: Publicación en proceso")
                    published_on.append("Instagram")
                except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
                    self.write({"ig_estado": "Error", "ig_error": str(e)})
                    self._send_admin_flow_failure_email("Instagram", str(e), stage="inicio de publicacion")
                    errors.append(f"Instagram: {str(e)}")

            # TikTok
            if 'TikTok' in self.red_social_ids.mapped('name') and self.tipo == "video_reels":
                try:
                    self._refresh_tiktok_guideline_fields()
                    self._validate_tiktok_business_rules()
                    self.write({"tt_estado": "Procesando", "tt_error": False})
                    tik_response = self.publish_on_tiktok(media_urls_custom, combined_text, cover_url_custom)
                    if tik_response:
                        self.write({
                            "tiktok_post_id": tik_response,
                        })
                        success_messages.append("TikTok: Publicación en proceso")
                        published_on.append("TikTok")
                    else:
                        self.write({"tt_estado": "Error", "tt_error": "No se recibió respuesta del servidor"})
                        self._send_admin_flow_failure_email("TikTok", "No se recibió respuesta del servidor", stage="inicio de publicacion")
                        errors.append("TikTok: No se recibió respuesta del servidor")
                except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
                    self.write({"tt_estado": "Error", "tt_error": str(e)})
                    self._send_admin_flow_failure_email("TikTok", str(e), stage="inicio de publicacion")
                    errors.append(f"TikTok: {str(e)}")

            # LinkedIn
            if 'LinkedIn' in self.red_social_ids.mapped('name'):
                try:
                    self.write({"li_estado": "Procesando", "li_error": False})
                    linkedin_response = self.publish_on_linkedin(media_urls_native, combined_text, cover_url_native)
                    if linkedin_response:
                        self.write({
                            "linkedin_post_id": linkedin_response["post_id"],
                            "linkedin_post_url": linkedin_response["post_url"],
                        })
                        success_messages.append("LinkedIn: Publicación en proceso")
                        published_on.append("LinkedIn")
                    else:
                        self.write({"li_estado": "Error", "li_error": "No se recibió respuesta del servidor"})
                        self._send_admin_flow_failure_email("LinkedIn", "No se recibió respuesta del servidor", stage="inicio de publicacion")
                        errors.append("LinkedIn: No se recibió respuesta del servidor")
                except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
                    self.write({"li_estado": "Error", "li_error": str(e)})
                    self._send_admin_flow_failure_email("LinkedIn", str(e), stage="inicio de publicacion")
                    errors.append(f"LinkedIn: {str(e)}")

            # Resultado final
            if published_on:

                self.write({
                    'post_estado': 'Procesando'
                })

                if errors:
                    # Publicación parcialmente exitosa
                    error_detalle = "\n".join(errors)
                    _logger.error("Error en publicar_post: %s", error_detalle)

                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Proceso con observaciones",
                            "message": '\n'.join(success_messages + [
                                "Errores:"
                            ] + errors),
                            "type": "danger",
                            "sticky": True,
                        },
                    }

                else:
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Proceso en curso",
                            "message": f"Contenido enviado a procesamiento en: {', '.join(published_on)}",
                            "type": "success",
                            "sticky": False,
                            "next": {
                                "type": "ir.actions.client",
                                "tag": "reload",
                            }
                        },
                    }

            else:
                # Todo falló
                error_detalle = "\n".join(errors) if errors else "Error no especificado"
                _logger.error("Error en publicar_post: %s", error_detalle)

                self.write({
                    'post_estado': 'Procesando'
                })
                selected = set(self.red_social_ids.mapped('name'))
                update_vals = {}
                if 'Facebook' in selected:
                    update_vals.update({"fb_estado": "Error", "fb_error": error_detalle})
                if 'Instagram' in selected:
                    update_vals.update({"ig_estado": "Error", "ig_error": error_detalle})
                if 'TikTok' in selected:
                    update_vals.update({"tt_estado": "Error", "tt_error": error_detalle})
                if update_vals:
                    self.write(update_vals)
                self._send_admin_flow_failure_email("Multiples redes", error_detalle, stage="inicio de publicacion")

                raise ValidationError("No se pudo iniciar el proceso en ninguna red social:\n" + error_detalle)

        except (requests.exceptions.RequestException, ValidationError, ValueError, TypeError, KeyError) as e:
            _logger.error("Error en mi_funcion_critica: %s", e)
            error_detalle = str(e)
            selected = set(self.red_social_ids.mapped('name'))
            update_vals = {}
            if 'Facebook' in selected:
                update_vals.update({"fb_estado": "Error", "fb_error": error_detalle})
            if 'Instagram' in selected:
                update_vals.update({"ig_estado": "Error", "ig_error": error_detalle})
            if 'TikTok' in selected:
                update_vals.update({"tt_estado": "Error", "tt_error": error_detalle})
            if update_vals:
                self.write(update_vals)
            self._send_admin_flow_failure_email("Multiples redes", error_detalle, stage="proceso de publicacion")
            raise ValidationError(f"Error en el proceso de publicación: {str(e)}")


    def check_tiktok_creator_status(self):
        self.ensure_one()
        self.sync_tiktok_account_data()

        # ----------------------------
        # 1) VERIFICAR SI PUEDE PUBLICAR
        # ----------------------------
        can_publish = self.tiktok_can_publish

        if can_publish is False:
            msg = "El creador ha alcanzado el limite de publicaciones. No puede publicar en este momento."
            self.tiktok_creator_status_info = msg
            raise ValidationError(msg)

        # ----------------------------
        # 2) VERIFICAR DURACIÓN PERMITIDA
        # ----------------------------
        max_duration = self.tiktok_max_video_post_duration_sec

        if max_duration and self.tiktok_video_duration:
            if self.tiktok_video_duration > max_duration:
                msg = (f"El video excede la duracion maxima permitida.\n"
                       f"Duración del video: {self.tiktok_video_duration} s\n"
                       f"Maximo permitido por TikTok: {max_duration} s")
                self.tiktok_creator_status_info = msg
                raise ValidationError(msg)

        # ----------------------------
        # SI TODO OK → MENSAJE POSITIVO
        # ----------------------------
        ok_msg = (f"El creador puede publicar.\n"
                  f"Duracion maxima permitida: {max_duration} segundos.\n"
                  f"Duracion del video a publicar: {self.tiktok_video_duration} segundos.")
        self.tiktok_creator_status_info = ok_msg

        return True


def upload_files_to_s3(files, aws_api, aws_secret, aws_bucket, aws_public_domain, url_mode="native"):
    """Sube archivos (imágenes o videos) a AWS S3 y devuelve sus URLs públicas."""
    aws_access_key_id = aws_api
    aws_secret_access_key = aws_secret
    bucket_name = aws_bucket or 'odoo-geniolibre'
    public_domain = (aws_public_domain or 'https://s3.geniolibredev.com').rstrip('/')
    region_name = 'us-east-2'

    _logger.info("AWS S3 configuración inicial")

    if not aws_access_key_id or not aws_secret_access_key:
        raise ValidationError("No se configuró correctamente el servicio de AWS.")
    if not bucket_name:
        raise ValidationError("No se configuró correctamente el bucket de AWS.")

    # Crear cliente con timeout seguro
    try:
        _logger.info("Iniciando conexión con AWS S3...")
        s3_client = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key,
                                 region_name=region_name,
                                 config=botocore.config.Config(connect_timeout=5, read_timeout=15), )
        _logger.info("Cliente AWS S3 creado correctamente.")
    except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError, ValueError, TypeError) as e:
        _logger.exception("Error al crear el cliente AWS S3")
        raise ValidationError(f"Error al crear el cliente AWS S3: {e}")

    if not files:
        raise ValidationError("No se encontraron archivos adjuntos o imágenes.")

    # Normalizar a lista
    if hasattr(files, 'ids'):
        files = list(files)
    elif isinstance(files, (tuple, list)):
        files = list(files)
    else:
        files = [
            files
        ]

    allowed_extensions = {
        'jpg',
        'jpeg',
        'mp4'
    }
    uploaded_urls = []

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_digits = ''.join(random.choices('0123456789', k=5))

    for idx, item in enumerate(files, start=1):

        try:
            # Detectar tipo de objeto
            if hasattr(item, 'datas') and hasattr(item, 'name'):  # ir.attachment
                file_name_raw = item.name
                file_data = item.datas
            elif isinstance(item, (tuple, list)) and len(item) == 2:  # (name, data)
                file_name_raw, file_data = item
            elif isinstance(item, str):  # base64 string
                file_name_raw = f"upload_{timestamp}_{random_digits}-{idx}.jpg"
                file_data = item
            else:
                raise ValidationError("Formato de archivo no soportado o inválido.")

            file_ext = file_name_raw.split('.')[-1].lower()
            if file_ext not in allowed_extensions:
                raise ValidationError(f"Tipo de archivo '{file_ext}' no permitido. Solo JPG, JPEG o MP4.")

            file_name = f"media_{timestamp}_{random_digits}-{idx}.{file_ext}"
            _logger.info(f"Preparando archivo {file_name_raw} para subida ({file_ext})...")

            # Decodificar y subir
            file_bytes = base64.b64decode(file_data)

            if file_ext in ['jpg', 'jpeg']:
                file_bytes = normalize_image_for_meta(file_bytes, file_name_raw)

            _logger.info(f"Subiendo {file_name} ({len(file_bytes)} bytes) a S3...")

            s3_client.put_object(Bucket=bucket_name, Key=file_name, Body=file_bytes,
                                 ContentType='image/jpeg' if file_ext in [
                                     'jpg',
                                     'jpeg'
                                 ] else 'video/mp4', )

            if url_mode == "custom":
                file_url = f"{public_domain}/{file_name}"
            else:
                file_url = f"https://{bucket_name}.s3.{region_name}.amazonaws.com/{file_name}"
            uploaded_urls.append(file_url)

            _logger.info(f"Archivo subido correctamente: {file_url}")

        except (ValidationError, binascii.Error, botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError, ValueError, TypeError) as e:
            _logger.exception(f"Error al subir {file_name_raw} a S3")
            raise ValidationError(f"Error al subir archivo {file_name_raw}: {str(e)}")

    _logger.info(f"Todos los archivos subidos correctamente. Total: {len(uploaded_urls)}")
    return uploaded_urls


def verify_public_media_url(url, attempts=3, delay_seconds=2, timeout=10):
    """Valida que la URL publica ya responda de forma util para terceros como Meta."""
    last_error = "sin respuesta"

    for attempt in range(1, attempts + 1):
        for method in ("HEAD", "GET"):
            response = None
            try:
                if method == "HEAD":
                    response = requests.head(url, allow_redirects=True, timeout=timeout)
                else:
                    response = requests.get(url, allow_redirects=True, stream=True, timeout=timeout)

                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if response.status_code == 200 and (
                    not content_type
                    or content_type.startswith(("image/", "video/", "application/octet-stream"))
                ):
                    response.close()
                    return True, None

                last_error = f"{method} {response.status_code} content-type={content_type or 'n/a'}"
            except requests.exceptions.RequestException as err:
                last_error = f"{method} {err}"
            finally:
                if response is not None:
                    response.close()

        if attempt < attempts:
            time.sleep(delay_seconds)

    return False, last_error


def normalize_image_for_meta(file_bytes, file_name="image.jpg"):
    """Reencodea imágenes a JPEG RGB baseline para mejorar compatibilidad con Meta."""
    try:
        with Image.open(BytesIO(file_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB",):
                img = img.convert("RGB")

            output = BytesIO()
            img.save(
                output,
                format="JPEG",
                quality=95,
                optimize=True,
                progressive=False,
            )
            normalized = output.getvalue()
            _logger.info(
                "Imagen normalizada para Meta: %s | bytes originales=%s | bytes finales=%s",
                file_name,
                len(file_bytes),
                len(normalized),
            )
            return normalized
    except Exception as e:
        _logger.warning("No se pudo normalizar imagen %s para Meta: %s", file_name, e)
        return file_bytes


def get_video_duration_ffprobe(base64_data):
    import subprocess, json, tempfile, base64
    from odoo.exceptions import ValidationError

    try:
        with tempfile.NamedTemporaryFile(delete=True, suffix=".mp4") as tmp:
            tmp.write(base64.b64decode(base64_data))
            tmp.flush()

            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                tmp.name
            ]

            # 🔥 timeout de 3 segundos → evita loops infinitos
            output = subprocess.check_output(cmd, timeout=3)
            info = json.loads(output.decode("utf-8"))

            duration = float(info["format"]["duration"])
            return int(duration)

    except subprocess.TimeoutExpired:
        raise ValidationError("ffprobe demoró demasiado y fue detenido. El archivo puede estar corrupto.")

    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError, TypeError, binascii.Error) as e:
        raise ValidationError(f"No se pudo obtener la duración del video usando ffprobe: {e}")


def remove_duplicate_links(text):
    seen_urls = set()

    def replace_link(match):
        url = match.group(0)
        if url in seen_urls:
            return ''
        seen_urls.add(url)
        return url

    # Eliminar enlaces duplicados
    text_without_duplicates = re.sub(r'https?://\S+', replace_link, text)
    text_cleaned = re.sub(r'\[\d+\]', '', text_without_duplicates)

    return text_cleaned
