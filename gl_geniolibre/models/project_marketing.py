# -*- coding: utf-8 -*-

import json
import logging
import re
from datetime import datetime, time, timezone
from urllib.parse import parse_qs, urlparse

import requests

from odoo import api, fields, models, tools
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
META_SYSTEM_USER_TOKEN_KEY = "gl_facebook.meta_system_user_access_token"
META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY = "gl_facebook.meta_system_user_token_expires_at"
META_PERSONAL_TOKEN_KEY = "gl_facebook.api_key"


def _get_meta_marketing_access_token(env):
    icp = env["ir.config_parameter"].sudo()
    token = (icp.get_param(META_SYSTEM_USER_TOKEN_KEY) or "").strip()
    if not token:
        raise ValidationError(
            "No existe un Meta System User Access Token configurado para project.marketing."
        )

    expires_at_raw = icp.get_param(META_SYSTEM_USER_TOKEN_EXPIRES_AT_KEY)
    expires_at = fields.Datetime.to_datetime(expires_at_raw) if expires_at_raw else False
    if expires_at and expires_at <= datetime.utcnow():
        raise ValidationError(
            "El Meta System User Access Token configurado para project.marketing esta vencido."
        )
    return token


def _get_meta_personal_access_token(env):
    icp = env["ir.config_parameter"].sudo()
    token = (icp.get_param(META_PERSONAL_TOKEN_KEY) or "").strip()
    if not token:
        raise ValidationError(
            "No existe un Facebook Access Token personal configurado para operaciones de escritura."
        )
    return token


def _raise_meta_write_disabled():
    raise ValidationError(
        "La escritura hacia Meta/Facebook esta temporalmente deshabilitada. "
        "Por ahora este modulo solo importa y consulta datos."
    )


def _extract_meta_creative_destinations(creative):
    object_story_spec = creative.get("object_story_spec") or {}
    asset_feed_spec = creative.get("asset_feed_spec") or {}
    candidates = [
        object_story_spec.get("link_data") or {},
        object_story_spec.get("video_data") or {},
        object_story_spec.get("template_data") or {},
        object_story_spec.get("photo_data") or {},
    ]
    call_to_action = False
    destination_url = False
    message_destination = False
    whatsapp_number = False
    primary_text = False
    headline = False
    description = False

    for block in candidates:
        cta = block.get("call_to_action") or {}
        if not call_to_action:
            call_to_action = cta.get("type")
        if not primary_text:
            primary_text = block.get("message")
        if not headline:
            headline = block.get("name") or block.get("title")
        if not description:
            description = block.get("description")
        cta_value = cta.get("value") or {}
        if not destination_url:
            destination_url = (
                cta_value.get("link")
                or block.get("link")
                or cta_value.get("website_url")
            )
        if not whatsapp_number:
            possible_number = (
                cta_value.get("phone_number")
                or cta_value.get("whatsapp_number")
            )
            if possible_number:
                normalized = str(possible_number).replace("+", "").replace(" ", "").replace("-", "")
                if normalized.isdigit():
                    whatsapp_number = possible_number

    if not primary_text:
        primary_text = creative.get("body")
    if not headline:
        headline = creative.get("title") or creative.get("name")
    if not destination_url:
        destination_url = creative.get("link_url")

    if asset_feed_spec:
        bodies = asset_feed_spec.get("bodies") or []
        titles = asset_feed_spec.get("titles") or []
        descriptions = asset_feed_spec.get("descriptions") or []
        link_urls = asset_feed_spec.get("link_urls") or []
        call_to_actions = asset_feed_spec.get("call_to_actions") or []

        if not primary_text and bodies:
            primary_text = (bodies[0] or {}).get("text")
        if not headline and titles:
            headline = (titles[0] or {}).get("text")
        if not description and descriptions:
            description = (descriptions[0] or {}).get("text")
        if not destination_url and link_urls:
            destination_url = (link_urls[0] or {}).get("website_url") or (link_urls[0] or {}).get("link")
        if not call_to_action and call_to_actions:
            call_to_action = (call_to_actions[0] or {}).get("type")

    if not whatsapp_number and destination_url:
        parsed = urlparse(destination_url)
        query = parse_qs(parsed.query or "")
        phone_from_query = (
            query.get("phone", [False])[0]
            or query.get("app_absent", [False])[0]
            or False
        )
        path = (parsed.path or "").strip("/")
        phone_from_path = False
        if "wa.me" in (parsed.netloc or "") and path:
            phone_from_path = path.split("/")[0]
        for candidate in (phone_from_query, phone_from_path):
            if candidate:
                normalized = str(candidate).replace("+", "").replace(" ", "").replace("-", "")
                if normalized.isdigit():
                    whatsapp_number = candidate
                    break

    if not whatsapp_number:
        searchable_text = " ".join(
            value for value in (
                primary_text,
                description,
                headline,
                creative.get("body"),
                creative.get("name"),
                creative.get("title"),
            ) if value
        )
        match = re.search(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\+?\d{7,15})", searchable_text)
        if match:
            whatsapp_number = match.group(1)
        else:
            generic_match = re.search(r"(?<!\d)(?:\+?\d[\d\s-]{7,16}\d)(?!\d)", searchable_text)
            if generic_match:
                candidate = generic_match.group(0).strip()
                normalized = candidate.replace("+", "").replace(" ", "").replace("-", "")
                if normalized.isdigit() and 7 <= len(normalized) <= 15:
                    whatsapp_number = candidate

    if description and primary_text and description.strip() == primary_text.strip():
        description = False

    if call_to_action == "WHATSAPP_MESSAGE" or whatsapp_number:
        message_destination = "WhatsApp"
    elif object_story_spec.get("page_id") or object_story_spec.get("instagram_actor_id"):
        message_destination = "Messenger/Instagram"

    return {
        "call_to_action": call_to_action,
        "destination_url": destination_url,
        "message_destination": message_destination,
        "whatsapp_number": whatsapp_number,
        "primary_text": primary_text,
        "headline": headline,
        "description": description,
    }


def _pick_campaign_result_metrics(actions, cost_per_action_type):
    priority = [
        "onsite_conversion.total_messaging_connection",
        "onsite_conversion.messaging_conversation_started_7d",
        "onsite_conversion.messaging_first_reply",
        "onsite_conversion.messaging_user_depth_2_message_send",
        "purchase",
        "offsite_conversion.fb_pixel_purchase",
        "lead",
        "link_click",
    ]
    action_map = {item.get("action_type"): item for item in actions if item.get("action_type")}
    cost_map = {item.get("action_type"): item for item in cost_per_action_type if item.get("action_type")}

    selected_type = False
    for action_type in priority:
        if action_type in action_map:
            selected_type = action_type
            break
    if not selected_type and actions:
        selected_type = actions[0].get("action_type")

    result_value = 0.0
    cost_value = 0.0
    if selected_type:
        result_value = float((action_map.get(selected_type) or {}).get("value") or 0.0)
        cost_value = float((cost_map.get(selected_type) or {}).get("value") or 0.0)

    return {
        "result_action_type": selected_type or False,
        "results": result_value,
        "cost_per_result": cost_value,
    }


def _prepare_meta_campaign_metrics_vals(item):
    insights = ((item.get("insights") or {}).get("data") or [{}])[0]
    actions = insights.get("actions") or []
    cost_per_action_type = insights.get("cost_per_action_type") or []
    result_metrics = _pick_campaign_result_metrics(actions, cost_per_action_type)
    return {
        "spend": float(insights.get("spend") or 0.0),
        "reach": int(float(insights.get("reach") or 0)),
        "impressions": int(float(insights.get("impressions") or 0)),
        "frequency": float(insights.get("frequency") or 0.0),
        "result_action_type": result_metrics.get("result_action_type"),
        "results": result_metrics.get("results") or 0.0,
        "cost_per_result": result_metrics.get("cost_per_result") or 0.0,
        "clicks": int(float(insights.get("clicks") or 0)),
        "ctr": float(insights.get("ctr") or 0.0),
        "cpc": float(insights.get("cpc") or 0.0),
        "cpm": float(insights.get("cpm") or 0.0),
        "actions_json": json.dumps(actions),
        "cost_per_action_type_json": json.dumps(cost_per_action_type),
    }


def _is_meta_creative_payload_incomplete(creative):
    creative = creative or {}
    object_story_spec = creative.get("object_story_spec") or {}
    return not any(
        object_story_spec.get(key)
        for key in ("link_data", "video_data", "template_data", "photo_data")
    )


def _safe_json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _parse_meta_datetime(value):
    if not value:
        return False
    raw_value = str(value).strip()
    candidates = [raw_value]
    if re.match(r".*[+-]\d{4}$", raw_value):
        candidates.append("%s:%s" % (raw_value[:-2], raw_value[-2:]))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw_value, fmt)
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return False


class MarketingMetaCampaign(models.Model):
    _name = "marketing.meta.campaign"
    _description = "Campaña"
    _order = "name, id"
    _rec_name = "name"

    provider = fields.Selection(
        [
            ("meta", "META"),
        ],
        string="Proveedor",
        default="meta",
        required=True,
    )
    name = fields.Char(required=True)
    external_id = fields.Char(string="External ID", required=True, index=True)
    account_id = fields.Many2one("facebook.ad.account", required=True, ondelete="cascade")
    configured_status = fields.Char(string="Estado Configurado")
    effective_status = fields.Char(string="Estado Efectivo")
    buying_type = fields.Char(string="Tipo de Compra")
    objective = fields.Char(string="Objetivo")
    start_time = fields.Char(string="Start Time")
    stop_time = fields.Char(string="Stop Time")
    special_ad_categories = fields.Char(string="Special Ad Categories")
    budget_strategy = fields.Char(string="Budget Strategy")
    budget_mode = fields.Char(string="Budget Mode")
    daily_budget = fields.Char(string="Daily Budget")
    lifetime_budget = fields.Char(string="Lifetime Budget")
    bid_strategy = fields.Char(string="Bid Strategy")
    spend = fields.Float(string="Spend")
    reach = fields.Integer(string="Reach")
    impressions = fields.Integer(string="Impressions")
    frequency = fields.Float(string="Frequency")
    result_action_type = fields.Char(string="Result Action Type")
    results = fields.Float(string="Results")
    cost_per_result = fields.Float(string="Cost Per Result")
    clicks = fields.Integer(string="Clicks")
    ctr = fields.Float(string="CTR")
    cpc = fields.Float(string="CPC")
    cpm = fields.Float(string="CPM")
    actions_json = fields.Text(string="Actions JSON")
    cost_per_action_type_json = fields.Text(string="Cost Per Action Type JSON")
    recommendations_json = fields.Text(string="Recommendations JSON")
    issues_info_json = fields.Text(string="Issues Info JSON")
    status = fields.Char(string="Estado", compute="_compute_status", store=False)
    marketing_record_ids = fields.One2many("project.marketing", "campaign_id", string="Registros Marketing")
    has_active_marketing_record = fields.Boolean(
        string="Tiene registro activo",
        compute="_compute_has_active_marketing_record",
        store=True,
    )
    raw_payload = fields.Text(string="Payload")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "marketing_meta_campaign_unique",
            "unique(external_id, account_id)",
            "La campaña ya existe para esta cuenta publicitaria.",
        ),
    ]

    @api.depends("effective_status", "configured_status")
    def _compute_status(self):
        for record in self:
            record.status = record.effective_status or record.configured_status or "Sin estado"

    @api.depends("marketing_record_ids.active")
    def _compute_has_active_marketing_record(self):
        for record in self:
            record.has_active_marketing_record = any(record.marketing_record_ids.mapped("active"))

    def _write_meta_status(self, configured_status):
        _raise_meta_write_disabled()

    def action_pause(self):
        self._write_meta_status("PAUSED")

    def action_resume(self):
        self._write_meta_status("ACTIVE")


class MarketingMetaAdset(models.Model):
    _name = "marketing.meta.adset"
    _description = "Meta Ad Set"
    _order = "name, id"
    _rec_name = "name"

    name = fields.Char(required=True)
    external_id = fields.Char(required=True, index=True)
    campaign_id = fields.Many2one("marketing.meta.campaign", required=True, ondelete="cascade")
    account_id = fields.Many2one("facebook.ad.account", required=True, ondelete="cascade")
    configured_status = fields.Char(string="Estado Configurado")
    effective_status = fields.Char(string="Estado Efectivo")
    daily_budget = fields.Char(string="Daily Budget")
    budget_type = fields.Char(string="Budget Type")
    lifetime_budget = fields.Char(string="Lifetime Budget")
    start_time = fields.Char(string="Start Time")
    end_time = fields.Char(string="End Time")
    optimization_goal = fields.Char(string="Optimization Goal")
    billing_event = fields.Char(string="Billing Event")
    bid_strategy = fields.Char(string="Bid Strategy")
    destination_type = fields.Char(string="Destination Type")
    promoted_object_json = fields.Text(string="Promoted Object JSON")
    geo_summary = fields.Char(string="Country/City/Radius")
    places_summary = fields.Text(string="Lugares")
    detailed_targeting = fields.Text(string="Segmentacion Detallada")
    targeting_json = fields.Text(string="JSON de segmentacion")
    age_min = fields.Integer(string="Age Min")
    age_max = fields.Integer(string="Age Max")
    placement_mode = fields.Char(string="Placement Mode")
    recommendations_json = fields.Text(string="Recommendations JSON")
    issues_info_json = fields.Text(string="Issues Info JSON")
    learning_stage_info_json = fields.Text(string="Learning Stage Info JSON")
    raw_payload = fields.Text(string="Payload")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "marketing_meta_adset_unique",
            "unique(external_id, campaign_id)",
            "El conjunto ya existe para esta campaña.",
        ),
    ]

    def _write_meta_status(self, configured_status):
        _raise_meta_write_disabled()

    def action_pause(self):
        self._write_meta_status("PAUSED")

    def action_resume(self):
        self._write_meta_status("ACTIVE")


class MarketingMetaAd(models.Model):
    _name = "marketing.meta.ad"
    _description = "Meta Ad"
    _order = "name, id"
    _rec_name = "name"

    name = fields.Char(required=True)
    external_id = fields.Char(required=True, index=True)
    adset_id = fields.Many2one("marketing.meta.adset", required=True, ondelete="cascade")
    campaign_id = fields.Many2one("marketing.meta.campaign", required=True, ondelete="cascade")
    account_id = fields.Many2one("facebook.ad.account", required=True, ondelete="cascade")
    configured_status = fields.Char(string="Estado Configurado")
    effective_status = fields.Char(string="Estado Efectivo")
    status = fields.Char(string="Estado", compute="_compute_status", store=False)
    existing_post_id = fields.Char(string="ID del Post Existente")
    creative_id = fields.Char(string="Creative ID")
    primary_text = fields.Text(string="Texto Principal")
    headline = fields.Char(string="Titular")
    description = fields.Text(string="Descripcion")
    call_to_action = fields.Char(string="Call To Action")
    destination_url = fields.Char(string="URL de Destino")
    message_destination = fields.Char(string="Destino de mensajes")
    whatsapp_number = fields.Char(string="Numero de WhatsApp")
    image_url = fields.Char(string="Image URL")
    preview_url = fields.Char(string="Preview URL")
    recommendations_json = fields.Text(string="Recommendations JSON")
    issues_info_json = fields.Text(string="Issues Info JSON")
    ad_review_feedback_json = fields.Text(string="Ad Review Feedback JSON")
    raw_payload = fields.Text(string="Payload")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "marketing_meta_ad_unique",
            "unique(external_id, adset_id)",
            "El anuncio ya existe para este conjunto.",
        ),
    ]

    def _write_meta_status(self, configured_status):
        api_version = self.env["ir.config_parameter"].sudo().get_param("gl_facebook.api_version")
        if not api_version:
            raise ValidationError("No se configuró la versión del API de Meta/Facebook.")

        token = _get_meta_personal_access_token(self.env)
        for record in self:
            response = requests.post(
                f"https://graph.facebook.com/{api_version}/{record.external_id}",
                data={
                    "access_token": token,
                    "status": configured_status,
                },
                timeout=20,
            )
            data = response.json()
            if response.status_code != 200:
                raise ValidationError(f"No se pudo actualizar el anuncio en Meta: {data}")
            record.write({
                "configured_status": configured_status,
                "effective_status": data.get("effective_status") or configured_status,
                "raw_payload": json.dumps(data),
            })

    @api.depends("effective_status", "configured_status")
    def _compute_status(self):
        for record in self:
            record.status = record.effective_status or record.configured_status or "Sin estado"

    def action_pause(self):
        self._write_meta_status("PAUSED")

    def action_resume(self):
        self._write_meta_status("ACTIVE")


class ProjectMarketing(models.Model):
    _name = "project.marketing"
    _description = "Publicaciones Paga"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_activation desc, id desc"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    color = fields.Integer()
    imported_from_meta = fields.Boolean(string="Importado desde Meta", default=False, copy=False, tracking=True)
    task_id = fields.Many2one("project.task", string="Tarea", ondelete="restrict", tracking=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True, tracking=True)
    company_id = fields.Many2one("res.company", string="Compañía", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", string="Moneda")
    budget = fields.Monetary(string="Monto", currency_field="currency_id", tracking=True)
    start_date = fields.Date(string="Inicio", tracking=True)
    end_date = fields.Date(string="Fin", tracking=True)
    scheduled_activation = fields.Datetime(string="Activación Programada", tracking=True)
    marketing_state = fields.Selection(
        [
            ("por_publicitar", "Por publicar"),
            ("publicado", "Promocionado"),
            ("pausado", "Pausado"),
            ("terminado", "Terminado"),
        ],
        string="Estado",
        default="por_publicitar",
        tracking=True,
    )
    platform = fields.Selection(
        [
            ("meta", "Meta Ads"),
            ("linkedin", "LinkedIn Ads"),
            ("tiktok", "TikTok Ads"),
        ],
        default="meta",
        tracking=True,
        required=True,
    )
    ad_account_id = fields.Many2one("facebook.ad.account", string="Cuenta Publicitaria", tracking=True)
    campaign_id = fields.Many2one(
        "marketing.meta.campaign",
        string="Campaña",
        domain="[('account_id', '=', ad_account_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        tracking=True,
    )
    campaign_name_edit = fields.Char(string="Nombre de Campaña", tracking=True)
    campaign_status_manual = fields.Selection(
        [
            ("ACTIVE", "Activa"),
            ("PAUSED", "Pausada"),
            ("DRAFT", "Borrador"),
        ],
        string="Estado de Campaña",
        tracking=True,
    )
    campaign_account_ref = fields.Many2one(related="campaign_id.account_id", string="Ad Account ID", readonly=True)
    campaign_name_meta = fields.Char(related="campaign_id.name", string="Nombre de la campana", readonly=True)
    campaign_buying_type = fields.Char(related="campaign_id.buying_type", string="Buying Type", readonly=True)
    campaign_objective = fields.Char(related="campaign_id.objective", string="Objective", readonly=True)
    campaign_status = fields.Char(related="campaign_id.status", string="Status", readonly=True)
    campaign_start_time = fields.Char(related="campaign_id.start_time", string="Start Time Campaña", readonly=True)
    campaign_stop_time = fields.Char(related="campaign_id.stop_time", string="Stop Time Campaña", readonly=True)
    campaign_special_ad_categories = fields.Char(related="campaign_id.special_ad_categories", string="Special Ad Categories", readonly=True)
    campaign_budget_strategy = fields.Char(related="campaign_id.budget_strategy", string="Budget Strategy", readonly=True)
    campaign_budget_mode = fields.Char(related="campaign_id.budget_mode", string="Budget Mode", readonly=True)
    campaign_daily_budget = fields.Char(related="campaign_id.daily_budget", string="Daily Budget", readonly=True)
    campaign_lifetime_budget = fields.Char(related="campaign_id.lifetime_budget", string="Lifetime Budget", readonly=True)
    campaign_bid_strategy = fields.Char(related="campaign_id.bid_strategy", string="Bid Strategy", readonly=True)
    campaign_spend = fields.Float(related="campaign_id.spend", string="Spend", readonly=True)
    campaign_reach = fields.Integer(related="campaign_id.reach", string="Reach", readonly=True)
    campaign_impressions = fields.Integer(related="campaign_id.impressions", string="Impressions", readonly=True)
    campaign_frequency = fields.Float(related="campaign_id.frequency", string="Frequency", readonly=True)
    campaign_result_action_type = fields.Char(related="campaign_id.result_action_type", string="Tipo de resultado", readonly=True)
    campaign_results = fields.Float(related="campaign_id.results", string="Results", readonly=True)
    campaign_cost_per_result = fields.Float(related="campaign_id.cost_per_result", string="Cost Per Result", readonly=True)
    campaign_clicks = fields.Integer(related="campaign_id.clicks", string="Clicks", readonly=True)
    campaign_ctr = fields.Float(related="campaign_id.ctr", string="CTR", readonly=True)
    campaign_cpc = fields.Float(related="campaign_id.cpc", string="CPC", readonly=True)
    campaign_cpm = fields.Float(related="campaign_id.cpm", string="CPM", readonly=True)
    campaign_actions_json = fields.Text(related="campaign_id.actions_json", string="Actions JSON", readonly=True)
    campaign_cost_per_action_type_json = fields.Text(related="campaign_id.cost_per_action_type_json", string="Cost Per Action Type JSON", readonly=True)
    campaign_notes = fields.Text(string="Notas de Campaña")
    adset_id = fields.Many2one(
        "marketing.meta.adset",
        string="Conjunto",
        domain="[('campaign_id', '=', campaign_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        tracking=True,
    )
    adset_name_edit = fields.Char(string="Nombre del Adset", tracking=True)
    adset_daily_budget = fields.Monetary(string="Presupuesto del Conjunto", currency_field="currency_id", tracking=True)
    adset_bid_strategy = fields.Char(string="Estrategia de Puja", tracking=True)
    adset_campaign_ref = fields.Many2one(related="adset_id.campaign_id", string="Campaign ID", readonly=True)
    adset_name_meta = fields.Char(related="adset_id.name", string="Nombre del ad set", readonly=True)
    adset_daily_budget_meta = fields.Char(related="adset_id.daily_budget", string="Daily Budget Ad Set", readonly=True)
    adset_budget_type = fields.Char(related="adset_id.budget_type", string="Budget Type", readonly=True)
    adset_lifetime_budget = fields.Char(related="adset_id.lifetime_budget", string="Lifetime Budget Ad Set", readonly=True)
    adset_start_time = fields.Char(related="adset_id.start_time", string="Start Time", readonly=True)
    adset_end_time = fields.Char(related="adset_id.end_time", string="End Time", readonly=True)
    adset_optimization_goal = fields.Char(related="adset_id.optimization_goal", string="Optimization Goal", readonly=True)
    adset_billing_event = fields.Char(related="adset_id.billing_event", string="Billing Event", readonly=True)
    adset_bid_strategy_meta = fields.Char(related="adset_id.bid_strategy", string="Bid Strategy Ad Set", readonly=True)
    adset_destination_type = fields.Char(related="adset_id.destination_type", string="Destination Type", readonly=True)
    adset_places_summary = fields.Text(related="adset_id.places_summary", string="Lugares", readonly=True)
    adset_detailed_targeting = fields.Text(related="adset_id.detailed_targeting", string="Segmentacion detallada", readonly=True)
    adset_targeting_summary = fields.Text(related="adset_id.targeting_json", string="JSON de segmentacion", readonly=True)
    adset_age_min = fields.Integer(related="adset_id.age_min", string="Age Min", readonly=True)
    adset_age_max = fields.Integer(related="adset_id.age_max", string="Age Max", readonly=True)
    adset_placements = fields.Char(related="adset_id.placement_mode", string="Placement Mode", readonly=True)
    meta_ad_id = fields.Many2one(
        "marketing.meta.ad",
        string="Anuncio",
        domain="[('adset_id', '=', adset_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        tracking=True,
    )
    ad_name = fields.Char(string="Nombre del Anuncio", tracking=True)
    ad_name_meta = fields.Char(related="meta_ad_id.name", string="Nombre del anuncio", readonly=True)
    ad_existing_post_id = fields.Char(related="meta_ad_id.existing_post_id", string="ID del post existente", readonly=True)
    ad_status = fields.Char(related="meta_ad_id.status", string="Estado del anuncio", readonly=True)
    ad_message_destination = fields.Char(related="meta_ad_id.message_destination", string="Destino de mensajes", readonly=True)
    ad_whatsapp_number = fields.Char(related="meta_ad_id.whatsapp_number", string="Numero de WhatsApp", readonly=True)
    ad_primary_text = fields.Text(related="meta_ad_id.primary_text", string="Texto Principal", readonly=True)
    ad_headline = fields.Char(related="meta_ad_id.headline", string="Titular", readonly=True)
    ad_description = fields.Text(related="meta_ad_id.description", string="Descripcion del Anuncio", readonly=True)
    ad_call_to_action = fields.Char(related="meta_ad_id.call_to_action", string="Call To Action", readonly=True)
    ad_destination_url = fields.Char(related="meta_ad_id.destination_url", string="URL de Destino", readonly=True)
    ad_preview_url = fields.Char(string="Preview URL", related="meta_ad_id.preview_url", readonly=True)
    ad_image_url = fields.Char(related="meta_ad_id.image_url", string="Image URL", readonly=True)
    ad_image_preview = fields.Html(string="Imagen del anuncio", compute="_compute_ad_image_preview", sanitize=False)
    delivery_status_detail = fields.Char(string="Entrega", compute="_compute_delivery_status_detail")
    source_post_type = fields.Selection(
        [
            ("facebook_post", "Facebook Post"),
            ("instagram_media", "Instagram Media"),
        ],
        string="Origen del Post",
        compute="_compute_source_post_data",
        store=True,
    )
    source_post_id = fields.Char(string="ID del Post", compute="_compute_source_post_data", store=True)
    sync_date = fields.Datetime(string="Última Sincronización", tracking=True)
    error_message = fields.Text(string="Error", tracking=True, copy=False)
    notes = fields.Text(string="Notas")

    _sql_constraints = [
        (
            "project_marketing_task_unique",
            "unique(task_id)",
            "La tarea ya tiene un registro en Publicaciones Paga.",
        ),
    ]

    @api.depends("task_id.fb_post_id", "task_id.inst_post_id")
    def _compute_source_post_data(self):
        for record in self:
            facebook_post_id = record.task_id._get_facebook_effective_post_id() if record.task_id else False
            if facebook_post_id:
                record.source_post_type = "facebook_post"
                record.source_post_id = facebook_post_id
            elif record.task_id.inst_post_id:
                record.source_post_type = "instagram_media"
                record.source_post_id = record.task_id.inst_post_id
            else:
                record.source_post_type = False
                record.source_post_id = False

    @api.depends("ad_image_url")
    def _compute_ad_image_preview(self):
        for record in self:
            if record.ad_image_url:
                record.ad_image_preview = '<img src="%s" style="max-width: 320px; max-height: 320px; border-radius: 8px;"/>' % record.ad_image_url
            else:
                record.ad_image_preview = False

    @api.onchange("campaign_id")
    def _onchange_campaign_id(self):
        self.adset_id = False
        self.meta_ad_id = False

    @api.onchange("ad_account_id")
    def _onchange_ad_account_id(self):
        self.campaign_id = False
        self.adset_id = False
        self.meta_ad_id = False
        if not self.ad_account_id:
            return
        self.action_sync_campaigns()

    @api.onchange("adset_id")
    def _onchange_adset_id(self):
        self.meta_ad_id = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.task_id and not self.env.context.get("skip_task_marketing_link"):
                record.task_id.with_context(skip_marketing_sync=True).write({
                    "marketing_record_id": record.id,
                })
        return records

    def write(self, vals):
        refs_before = {
            record.id: {
                "campaign_id": record.campaign_id.id,
                "adset_id": record.adset_id.id,
                "meta_ad_id": record.meta_ad_id.id,
            }
            for record in self
        }
        result = super().write(vals)
        if "task_id" in vals and not self.env.context.get("skip_task_marketing_link"):
            for record in self:
                if record.task_id:
                    record.task_id.with_context(skip_marketing_sync=True).write({
                        "marketing_record_id": record.id,
                    })
        if {"campaign_id", "adset_id", "meta_ad_id"} & set(vals.keys()):
            self._cleanup_removed_meta_links(refs_before)
        return result

    def unlink(self):
        tasks = self.mapped("task_id")
        refs_before = [
            {
                "campaign_id": record.campaign_id.id,
                "adset_id": record.adset_id.id,
                "meta_ad_id": record.meta_ad_id.id,
            }
            for record in self
        ]
        res = super().unlink()
        for task in tasks.filtered(lambda t: t.exists()):
            task.with_context(skip_marketing_sync=True).write({
                "marketing_record_id": False,
                "activar_publicidad_paga": False,
            })
        self._cleanup_removed_meta_links(refs_before)
        return res

    def init(self):
        if not tools.sql.table_exists(self.env.cr, self._table):
            return
        self.env.cr.execute(
            """
            UPDATE project_marketing
               SET marketing_state = CASE
                   WHEN marketing_state IN ('programado', 'procesando', 'revisando', 'error') THEN 'por_publicitar'
                   ELSE marketing_state
               END
             WHERE marketing_state IN ('programado', 'procesando', 'revisando', 'error')
            """
        )

    @api.model
    def _cleanup_removed_meta_links(self, refs_before):
        if isinstance(refs_before, dict):
            refs_iterable = list(refs_before.values())
        else:
            refs_iterable = refs_before or []

        Campaign = self.env["marketing.meta.campaign"].sudo().with_context(active_test=False)
        Adset = self.env["marketing.meta.adset"].sudo().with_context(active_test=False)
        Ad = self.env["marketing.meta.ad"].sudo().with_context(active_test=False)
        Marketing = self.env["project.marketing"].sudo().with_context(active_test=False)

        campaign_ids = {ref.get("campaign_id") for ref in refs_iterable if ref.get("campaign_id")}
        adset_ids = {ref.get("adset_id") for ref in refs_iterable if ref.get("adset_id")}
        ad_ids = {ref.get("meta_ad_id") for ref in refs_iterable if ref.get("meta_ad_id")}

        for ad in Ad.browse(list(ad_ids)).exists():
            if Marketing.search_count([("meta_ad_id", "=", ad.id)]) == 0:
                ad.unlink()

        for adset in Adset.browse(list(adset_ids)).exists():
            if Marketing.search_count([("adset_id", "=", adset.id)]) == 0 and Ad.search_count([("adset_id", "=", adset.id)]) == 0:
                adset.unlink()

        for campaign in Campaign.browse(list(campaign_ids)).exists():
            if Marketing.search_count([("campaign_id", "=", campaign.id)]) == 0 and Adset.search_count([("campaign_id", "=", campaign.id)]) == 0:
                campaign.unlink()

    def _get_meta_api_version(self):
        api_version = self.env["ir.config_parameter"].sudo().get_param("gl_facebook.api_version")
        if not api_version:
            raise ValidationError("No se configuró la versión del API de Meta/Facebook.")
        return api_version

    def action_open_import_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Importar desde Meta",
            "res_model": "project.marketing.import.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("gl_geniolibre.view_project_marketing_import_wizard_form").id,
            "target": "new",
            "context": {
                "default_marketing_id": self.id,
                "default_name": self.name,
                "default_partner_id": self.partner_id.id,
                "default_task_id": self.task_id.id,
                "default_ad_account_id": self.ad_account_id.id,
                "default_campaign_id": self.campaign_id.id,
                "default_adset_id": self.adset_id.id,
                "default_meta_ad_id": self.meta_ad_id.id,
            },
        }

    def _get_meta_access_token(self):
        return _get_meta_marketing_access_token(self.env)

    def _get_meta_entity_state(self, configured_status, effective_status, start_time=False, end_time=False):
        configured_status = (configured_status or "").upper()
        effective_status = (effective_status or "").upper()
        now = fields.Datetime.now()
        parsed_start = _parse_meta_datetime(start_time)
        parsed_end = _parse_meta_datetime(end_time)
        if parsed_end and parsed_end <= now:
            return "terminado"
        if configured_status in ("ARCHIVED", "DELETED", "COMPLETED") or effective_status in ("ARCHIVED", "DELETED", "COMPLETED"):
            return "terminado"
        if configured_status == "PAUSED" or effective_status in ("PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"):
            return "pausado"
        if effective_status == "DISAPPROVED":
            return "por_publicitar"
        if parsed_start and parsed_start > now:
            return "por_publicitar"
        if effective_status == "ACTIVE":
            return "publicado"
        return "por_publicitar"

    def _get_marketing_state_from_meta_status(self, configured_status, effective_status, start_time=False, end_time=False):
        return self._get_meta_entity_state(
            configured_status,
            effective_status,
            start_time=start_time,
            end_time=end_time,
        )

    def _get_marketing_state_from_meta_nodes(self, campaign_data=None, adset_data=None, ad_data=None):
        adset_state = self._get_meta_entity_state(
            (adset_data or {}).get("configured_status"),
            (adset_data or {}).get("effective_status"),
            (adset_data or {}).get("start_time"),
            (adset_data or {}).get("end_time"),
        ) if adset_data else False
        ad_state = self._get_meta_entity_state(
            (ad_data or {}).get("configured_status"),
            (ad_data or {}).get("effective_status"),
        ) if ad_data else False
        if "terminado" in (adset_state, ad_state):
            return "terminado"
        if "pausado" in (adset_state, ad_state):
            return "pausado"
        if adset_state == "por_publicitar":
            return "por_publicitar"
        if ad_state == "publicado":
            return "publicado"
        return ad_state or adset_state or "por_publicitar"

    @api.depends(
        "adset_id.configured_status",
        "adset_id.effective_status",
        "adset_id.start_time",
        "adset_id.end_time",
        "meta_ad_id.configured_status",
        "meta_ad_id.effective_status",
    )
    def _compute_delivery_status_detail(self):
        now = fields.Datetime.now()
        for record in self:
            adset_end = _parse_meta_datetime(record.adset_id.end_time)
            adset_start = _parse_meta_datetime(record.adset_id.start_time)
            ad_effective = (record.meta_ad_id.effective_status or "").upper()
            adset_effective = (record.adset_id.effective_status or "").upper()
            ad_configured = (record.meta_ad_id.configured_status or "").upper()
            adset_configured = (record.adset_id.configured_status or "").upper()

            if adset_end and adset_end <= now:
                record.delivery_status_detail = "Finalizado por fecha del conjunto"
            elif "DISAPPROVED" in (ad_effective, adset_effective):
                record.delivery_status_detail = "Rechazado por Meta"
            elif "PENDING_REVIEW" in (ad_effective, adset_effective):
                record.delivery_status_detail = "En revisión por Meta"
            elif adset_configured == "PAUSED" or adset_effective in ("PAUSED", "ADSET_PAUSED"):
                record.delivery_status_detail = "Pausado por conjunto"
            elif ad_configured == "PAUSED" or ad_effective == "PAUSED":
                record.delivery_status_detail = "Anuncio pausado"
            elif adset_start and adset_start > now:
                record.delivery_status_detail = "Programado por conjunto"
            elif ad_effective == "ACTIVE":
                record.delivery_status_detail = "Entrega activa"
            elif record.meta_ad_id:
                record.delivery_status_detail = "Sin entrega activa"
            else:
                record.delivery_status_detail = False

    def action_review_meta_status(self):
        for record in self.filtered(lambda r: r.platform == "meta" and r.meta_ad_id and r.meta_ad_id.external_id):
            token = record._get_meta_access_token()
            api_version = record._get_meta_api_version()
            url = f"https://graph.facebook.com/{api_version}/{record.meta_ad_id.external_id}"
            params = {
                "access_token": token,
                "fields": "id,name,status,configured_status,effective_status,recommendations,issues_info,ad_review_feedback,campaign{id,status,configured_status,effective_status,start_time,stop_time,recommendations,issues_info},adset{id,status,configured_status,effective_status,start_time,end_time,recommendations,issues_info,learning_stage_info}",
            }
            response = requests.get(url, params=params, timeout=20)
            data = response.json()
            if response.status_code != 200:
                record.error_message = str(data)
                continue

            campaign_data = data.get("campaign") or {}
            adset_data = data.get("adset") or {}

            if record.campaign_id and campaign_data:
                record.campaign_id.sudo().write({
                    "configured_status": campaign_data.get("configured_status"),
                    "effective_status": campaign_data.get("effective_status"),
                    "start_time": campaign_data.get("start_time") or False,
                    "stop_time": campaign_data.get("stop_time") or False,
                    "recommendations_json": json.dumps(campaign_data.get("recommendations"), ensure_ascii=False) if campaign_data.get("recommendations") else False,
                    "issues_info_json": json.dumps(campaign_data.get("issues_info"), ensure_ascii=False) if campaign_data.get("issues_info") else False,
                })
            if record.adset_id and adset_data:
                record.adset_id.sudo().write({
                    "configured_status": adset_data.get("configured_status"),
                    "effective_status": adset_data.get("effective_status"),
                    "start_time": adset_data.get("start_time") or False,
                    "end_time": adset_data.get("end_time") or False,
                    "recommendations_json": json.dumps(adset_data.get("recommendations"), ensure_ascii=False) if adset_data.get("recommendations") else False,
                    "issues_info_json": json.dumps(adset_data.get("issues_info"), ensure_ascii=False) if adset_data.get("issues_info") else False,
                    "learning_stage_info_json": json.dumps(adset_data.get("learning_stage_info"), ensure_ascii=False) if adset_data.get("learning_stage_info") else False,
                })
            if record.meta_ad_id:
                record.meta_ad_id.sudo().write({
                    "name": data.get("name") or record.meta_ad_id.name,
                    "configured_status": data.get("configured_status"),
                    "effective_status": data.get("effective_status"),
                    "recommendations_json": json.dumps(data.get("recommendations"), ensure_ascii=False) if data.get("recommendations") else False,
                    "issues_info_json": json.dumps(data.get("issues_info"), ensure_ascii=False) if data.get("issues_info") else False,
                    "ad_review_feedback_json": json.dumps(data.get("ad_review_feedback"), ensure_ascii=False) if data.get("ad_review_feedback") else False,
                })
            record.marketing_state = record._get_marketing_state_from_meta_nodes(
                campaign_data=campaign_data,
                adset_data=adset_data,
                ad_data=data,
            )

            record.error_message = False
            record.sync_date = fields.Datetime.now()
        return True

    def _fetch_meta_creative_details(self, creative_id):
        self.ensure_one()
        if not creative_id:
            return {}

        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/{creative_id}"
        params = {
            "access_token": token,
            "fields": "id,object_story_id,effective_object_story_id,thumbnail_url,image_url,object_story_spec,asset_feed_spec,object_type,title,body,url_tags,link_url,name",
        }
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        if response.status_code != 200:
            _logger.warning("No se pudo obtener el creative %s: %s", creative_id, data)
            return {}
        return data

    def action_open_meta_ads_manager(self):
        self.ensure_one()
        if not self.ad_account_id or not self.campaign_id or not self.adset_id or not self.meta_ad_id:
            raise ValidationError("Debes seleccionar cuenta, campaña, adset y anuncio para abrirlo en Meta.")

        url = (
            "https://adsmanager.facebook.com/adsmanager/manage/ads"
            "?act=%s&selected_campaign_ids=%s&selected_adset_ids=%s&selected_ad_ids=%s"
        ) % (
            self.ad_account_id.account_id,
            self.campaign_id.external_id,
            self.adset_id.external_id,
            self.meta_ad_id.external_id,
        )
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def action_print_marketing_report(self):
        self.ensure_one()

        since = self.start_date or fields.Date.context_today(self)
        until = self.end_date or since
        actions_map = {
            item.get("action_type"): item.get("value")
            for item in _safe_json_loads(self.campaign_actions_json, [])
            if isinstance(item, dict) and item.get("action_type")
        }
        thumbnail_url = self.ad_image_url or "/gl_geniolibre/static/src/img/banner_meta_ads.jpg"

        meta_campaign = {
            "name": self.campaign_name_meta or self.name,
            "thumbnail_url": thumbnail_url,
            "impressions": self.campaign_impressions or 0,
            "reach": self.campaign_reach or 0,
            "clicks": self.campaign_clicks or 0,
            "spend": self.campaign_spend or 0.0,
            "ctr": self.campaign_ctr or 0.0,
            "cpc": self.campaign_cpc or 0.0,
            "cpm": self.campaign_cpm or 0.0,
            "cpp": round((self.campaign_spend / self.campaign_reach), 2) if self.campaign_reach else 0.0,
            "actions": actions_map,
        }
        meta_summary = {
            "total_campaigns": 1 if self.campaign_id else 0,
            "account_currency": (self.currency_id.name or "").upper(),
            "impressions": self.campaign_impressions or 0,
            "clicks": self.campaign_clicks or 0,
            "reach": self.campaign_reach or 0,
            "spend": self.campaign_spend or 0.0,
            "ctr": self.campaign_ctr or 0.0,
            "cpc": self.campaign_cpc or 0.0,
            "cpm": self.campaign_cpm or 0.0,
            "cpp": meta_campaign["cpp"],
            "frequency": self.campaign_frequency or 0.0,
            "total_conversaciones": self.campaign_results or 0.0,
        }
        data = {
            "partner_id": self.partner_id.id,
            "report_period": {
                "since": fields.Date.to_string(since),
                "until": fields.Date.to_string(until),
            },
            "facebook_data": False,
            "instagram_data": False,
            "tiktok_data": False,
            "google_ads_data": False,
            "linkedin_data": False,
            "meta_ads_data": {
                "summary": meta_summary,
                "campaigns": [meta_campaign],
            },
        }
        return self.env.ref("gl_geniolibre.gl_print_marketing_report").report_action(self, data={"data": data})

    def _ensure_meta_ready(self):
        self.ensure_one()
        if self.platform != "meta":
            raise ValidationError("Esta versión solo soporta automatización de Meta Ads.")
        if not self.task_id or self.task_id.post_estado != "Publicado":
            raise ValidationError("La tarea debe estar publicada antes de activar publicidad paga.")
        if not self.ad_account_id:
            raise ValidationError("Debes seleccionar una cuenta publicitaria.")
        if not self.campaign_id:
            raise ValidationError("Debes seleccionar una campaña.")
        if not self.adset_id:
            raise ValidationError("Debes seleccionar un conjunto de anuncios.")
        if not self.source_post_id:
            raise ValidationError("La tarea no tiene un post publicado utilizable para publicidad.")

    def _ensure_meta_ad_create_ready(self):
        self.ensure_one()
        if self.platform != "meta":
            raise ValidationError("Esta versión solo soporta automatización de Meta Ads.")
        if self.imported_from_meta:
            raise ValidationError("La creación de anuncios solo está permitida para registros nuevos de Publicaciones Paga.")
        if self.meta_ad_id:
            raise ValidationError("Este registro ya tiene un anuncio creado.")
        if not self.ad_account_id:
            raise ValidationError("Debes seleccionar una cuenta publicitaria.")
        if not self.campaign_id:
            raise ValidationError("Debes seleccionar una campaña.")
        if not self.adset_id or not self.adset_id.external_id:
            raise ValidationError("Debes seleccionar un conjunto de anuncios válido.")
        if not self.task_id or self.task_id.post_estado != "Publicado":
            raise ValidationError("La tarea debe estar publicada antes de crear el anuncio.")
        if not self.source_post_id:
            raise ValidationError("La tarea no tiene un post publicado utilizable para publicidad.")

    def _ensure_meta_adset_duplicate_ready(self):
        self.ensure_one()
        if self.platform != "meta":
            raise ValidationError("Esta versión solo soporta automatización de Meta Ads.")
        if not self.ad_account_id:
            raise ValidationError("Debes seleccionar una cuenta publicitaria.")
        if not self.campaign_id or not self.campaign_id.external_id:
            raise ValidationError("Debes seleccionar una campaña válida.")
        if not self.adset_id or not self.adset_id.external_id:
            raise ValidationError("Debes seleccionar un conjunto de anuncios válido.")
        if not self.adset_id.raw_payload:
            raise ValidationError("Primero sincroniza los conjuntos para poder duplicar este adset.")

    def _prepare_whatsapp_adset_payload(self):
        self.ensure_one()
        source_payload = json.loads(self.adset_id.raw_payload or "{}")
        targeting = source_payload.get("targeting") or {}
        promoted_object = source_payload.get("promoted_object") or {}
        adset_name = self.adset_name_edit or "%s - WhatsApp" % (self.adset_id.name or self.name)

        payload = {
            "name": adset_name,
            "campaign_id": self.campaign_id.external_id,
            "status": "PAUSED",
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "IMPRESSIONS",
            "targeting": json.dumps(targeting),
        }
        if source_payload.get("start_time"):
            payload["start_time"] = source_payload.get("start_time")
        if source_payload.get("end_time"):
            payload["end_time"] = source_payload.get("end_time")
        if source_payload.get("bid_strategy"):
            payload["bid_strategy"] = source_payload.get("bid_strategy")
        if source_payload.get("destination_type"):
            payload["destination_type"] = source_payload.get("destination_type")
        else:
            payload["destination_type"] = "WHATSAPP"
        if promoted_object:
            payload["promoted_object"] = json.dumps(promoted_object)
        if source_payload.get("daily_budget"):
            payload["daily_budget"] = source_payload.get("daily_budget")
        elif source_payload.get("lifetime_budget"):
            payload["lifetime_budget"] = source_payload.get("lifetime_budget")
        else:
            raise ValidationError("El adset origen no tiene presupuesto importado para poder duplicarlo.")
        return payload

    def action_sync_accounts(self):
        self.ensure_one()
        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/me/adaccounts"
        params = {
            "access_token": token,
            "fields": "name,account_id",
            "limit": 500,
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if response.status_code != 200:
            raise ValidationError(f"No se pudieron sincronizar las cuentas publicitarias: {data}")

        AdAccount = self.env["facebook.ad.account"].sudo()
        api_ids = []
        for item in data.get("data", []):
            account_id = item.get("account_id")
            if not account_id:
                continue
            api_ids.append(account_id)
            vals = {
                "name": item.get("name") or account_id,
                "account_id": account_id,
            }
            existing = AdAccount.search([("account_id", "=", account_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                AdAccount.create(vals)

        stale_accounts = AdAccount.search([("account_id", "not in", api_ids)]) if api_ids else AdAccount.search([])
        for stale in stale_accounts:
            is_referenced = bool(
                self.env["res.partner"].sudo().search_count([("facebook_ad_account", "=", stale.id)], limit=1)
                or self.env["project.marketing"].sudo().search_count([("ad_account_id", "=", stale.id)], limit=1)
                or self.env["marketing.meta.campaign"].sudo().search_count([("account_id", "=", stale.id)], limit=1)
                or self.env["marketing.meta.adset"].sudo().search_count([("account_id", "=", stale.id)], limit=1)
                or self.env["marketing.meta.ad"].sudo().search_count([("account_id", "=", stale.id)], limit=1)
            )
            if not is_referenced:
                stale.unlink()

        if self.ad_account_id and self.ad_account_id.account_id not in api_ids:
            self.ad_account_id = False
            self.campaign_id = False
            self.adset_id = False
            self.meta_ad_id = False

        self.sync_date = fields.Datetime.now()
        return True

    def action_sync_campaigns(self):
        self.ensure_one()
        if not self.ad_account_id:
            raise ValidationError("Selecciona primero una cuenta publicitaria.")

        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/act_{self.ad_account_id.account_id}/campaigns"
        params = {
            "access_token": token,
            "fields": "id,name,status,configured_status,effective_status,buying_type,objective,special_ad_categories,daily_budget,lifetime_budget,bid_strategy,start_time,stop_time,recommendations,issues_info,insights.date_preset(maximum){spend,reach,impressions,frequency,clicks,ctr,cpc,cpm,actions,cost_per_action_type}",
            "limit": 500,
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if response.status_code != 200:
            raise ValidationError(f"No se pudieron sincronizar campañas: {data}")

        Campaign = self.env["marketing.meta.campaign"].sudo()
        for item in data.get("data", []):
            external_id = item.get("id") or item.get("campaign_id")
            if not external_id:
                _logger.warning("Campana Meta omitida por no tener external_id: %s", item)
                continue
            special_ad_categories = item.get("special_ad_categories") or []
            daily_budget = item.get("daily_budget")
            lifetime_budget = item.get("lifetime_budget")
            vals = {
                "provider": "meta",
                "name": item.get("name") or external_id,
                "external_id": external_id,
                "account_id": self.ad_account_id.id,
                "configured_status": item.get("configured_status"),
                "effective_status": item.get("effective_status"),
                "buying_type": item.get("buying_type"),
                "objective": item.get("objective"),
                "start_time": item.get("start_time") or False,
                "stop_time": item.get("stop_time") or False,
                "special_ad_categories": ", ".join(special_ad_categories) if isinstance(special_ad_categories, list) else str(special_ad_categories),
                "budget_strategy": "daily" if daily_budget else ("lifetime" if lifetime_budget else "adset_budget"),
                "budget_mode": "campaign_level" if (daily_budget or lifetime_budget) else "adset_level",
                "daily_budget": daily_budget or False,
                "lifetime_budget": lifetime_budget or False,
                "bid_strategy": item.get("bid_strategy"),
                "recommendations_json": json.dumps(item.get("recommendations"), ensure_ascii=False) if item.get("recommendations") else False,
                "issues_info_json": json.dumps(item.get("issues_info"), ensure_ascii=False) if item.get("issues_info") else False,
                "raw_payload": json.dumps(item),
            }
            vals.update(_prepare_meta_campaign_metrics_vals(item))
            existing = Campaign.search([
                ("external_id", "=", external_id),
                ("account_id", "=", self.ad_account_id.id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Campaign.create(vals)

            if self.campaign_id and self.campaign_id.external_id == external_id:
                self.campaign_status_manual = item.get("configured_status") or False

        self.sync_date = fields.Datetime.now()
        return True

    def action_sync_campaign_metrics(self):
        self.ensure_one()
        if not self.ad_account_id or not self.campaign_id or not self.campaign_id.external_id:
            raise ValidationError("Selecciona primero una campaña válida.")

        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/{self.campaign_id.external_id}"
        params = {
            "access_token": token,
            "fields": "id,insights.date_preset(maximum){spend,reach,impressions,frequency,clicks,ctr,cpc,cpm,actions,cost_per_action_type}",
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if response.status_code != 200:
            raise ValidationError(f"No se pudieron actualizar las métricas: {data}")

        self.campaign_id.sudo().write(_prepare_meta_campaign_metrics_vals(data))
        self.sync_date = fields.Datetime.now()
        return True

    def _sync_meta_data_on_open(self):
        for record in self.filtered(lambda r: r.imported_from_meta and r.platform == "meta" and r.ad_account_id and r.campaign_id):
            try:
                record.action_sync_campaigns()
            except Exception as exc:
                _logger.warning("No se pudo sincronizar la campaña Meta al abrir %s: %s", record.id, exc)
            if record.adset_id:
                try:
                    record.action_sync_adsets()
                except Exception as exc:
                    _logger.warning("No se pudo sincronizar el adset Meta al abrir %s: %s", record.id, exc)

    def action_sync_adsets(self):
        self.ensure_one()
        if not self.campaign_id:
            raise ValidationError("Selecciona primero una campaña.")

        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/{self.campaign_id.external_id}/adsets"
        params = {
            "access_token": token,
            "fields": "id,name,status,configured_status,effective_status,campaign_id,daily_budget,lifetime_budget,start_time,end_time,optimization_goal,billing_event,bid_strategy,destination_type,promoted_object,recommendations,issues_info,learning_stage_info,targeting{age_min,age_max,geo_locations{countries,cities,custom_locations},publisher_platforms,facebook_positions,instagram_positions,audience_network_positions,messenger_positions,interests,behaviors,life_events,flexible_spec,exclusions}",
            "limit": 500,
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if response.status_code != 200:
            raise ValidationError(f"No se pudieron sincronizar conjuntos: {data}")

        Adset = self.env["marketing.meta.adset"].sudo()
        for item in data.get("data", []):
            targeting = item.get("targeting") or {}
            geo_locations = targeting.get("geo_locations") or {}
            countries = geo_locations.get("countries") or []
            cities = geo_locations.get("cities") or []
            custom_locations = geo_locations.get("custom_locations") or []
            location_bits = []
            detailed_bits = []
            if countries:
                location_bits.append("Countries: %s" % ", ".join(countries))
            if cities:
                location_bits.append(
                    "Cities: %s" % ", ".join(
                        str(city.get("name") or city.get("key")) for city in cities if city.get("name") or city.get("key")
                    )
                )
            if custom_locations:
                location_bits.append(
                    "Radius: %s" % ", ".join(
                        "%s (%s %s)" % (
                            loc.get("name") or loc.get("key") or "location",
                            loc.get("radius") or "",
                            loc.get("distance_unit") or "",
                        )
                        for loc in custom_locations
                    )
                )
            for key, label in (
                ("interests", "Interests"),
                ("behaviors", "Behaviors"),
                ("life_events", "Life Events"),
            ):
                values = targeting.get(key) or []
                names = [str(v.get("name") or v.get("id")) for v in values if v.get("name") or v.get("id")]
                if names:
                    detailed_bits.append("%s: %s" % (label, ", ".join(names)))
            flexible_spec = targeting.get("flexible_spec") or []
            if flexible_spec:
                flex_chunks = []
                for chunk in flexible_spec:
                    chunk_parts = []
                    for key, label in (
                        ("interests", "Interests"),
                        ("behaviors", "Behaviors"),
                    ):
                        values = chunk.get(key) or []
                        names = [str(v.get("name") or v.get("id")) for v in values if v.get("name") or v.get("id")]
                        if names:
                            chunk_parts.append("%s: %s" % (label, ", ".join(names)))
                    if chunk_parts:
                        flex_chunks.append(" OR ".join(chunk_parts))
                if flex_chunks:
                    detailed_bits.append("Flexible Spec: %s" % " ; ".join(flex_chunks))
            exclusions = targeting.get("exclusions") or {}
            if exclusions:
                exclusion_parts = []
                for key, label in (
                    ("interests", "Interests"),
                    ("behaviors", "Behaviors"),
                ):
                    values = exclusions.get(key) or []
                    names = [str(v.get("name") or v.get("id")) for v in values if v.get("name") or v.get("id")]
                    if names:
                        exclusion_parts.append("%s: %s" % (label, ", ".join(names)))
                if exclusion_parts:
                    detailed_bits.append("Exclusions: %s" % " | ".join(exclusion_parts))
            vals = {
                "name": item.get("name") or item.get("id"),
                "external_id": item.get("id"),
                "campaign_id": self.campaign_id.id,
                "account_id": self.ad_account_id.id,
                "configured_status": item.get("configured_status"),
                "effective_status": item.get("effective_status"),
                "daily_budget": item.get("daily_budget") or False,
                "budget_type": "lifetime" if item.get("lifetime_budget") else ("daily" if item.get("daily_budget") else False),
                "lifetime_budget": item.get("lifetime_budget") or False,
                "start_time": item.get("start_time") or False,
                "end_time": item.get("end_time") or False,
                "optimization_goal": item.get("optimization_goal") or False,
                "billing_event": item.get("billing_event") or False,
                "bid_strategy": item.get("bid_strategy") or False,
                "destination_type": item.get("destination_type") or False,
                "promoted_object_json": json.dumps(item.get("promoted_object"), indent=2, ensure_ascii=False) if item.get("promoted_object") else False,
                "geo_summary": " | ".join(bit for bit in location_bits if bit) or False,
                "places_summary": "\n".join(bit for bit in location_bits if bit) or False,
                "detailed_targeting": "\n".join(bit for bit in detailed_bits if bit) or False,
                "targeting_json": json.dumps(targeting, indent=2, ensure_ascii=False) if targeting else False,
                "age_min": targeting.get("age_min") or 0,
                "age_max": targeting.get("age_max") or 0,
                "placement_mode": "manual" if any(
                    targeting.get(key)
                    for key in (
                        "publisher_platforms",
                        "facebook_positions",
                        "instagram_positions",
                        "audience_network_positions",
                        "messenger_positions",
                    )
                ) else "automatic",
                "recommendations_json": json.dumps(item.get("recommendations"), indent=2, ensure_ascii=False) if item.get("recommendations") else False,
                "issues_info_json": json.dumps(item.get("issues_info"), indent=2, ensure_ascii=False) if item.get("issues_info") else False,
                "learning_stage_info_json": json.dumps(item.get("learning_stage_info"), indent=2, ensure_ascii=False) if item.get("learning_stage_info") else False,
                "raw_payload": json.dumps(item),
            }
            existing = Adset.search([
                ("external_id", "=", item.get("id")),
                ("campaign_id", "=", self.campaign_id.id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Adset.create(vals)

        self.sync_date = fields.Datetime.now()
        return True

    def action_duplicate_adset_whatsapp(self):
        for record in self:
            record._ensure_meta_adset_duplicate_ready()

            token = _get_meta_personal_access_token(record.env)
            api_version = record._get_meta_api_version()
            payload = record._prepare_whatsapp_adset_payload()
            url = f"https://graph.facebook.com/{api_version}/act_{record.ad_account_id.account_id}/adsets"
            request_data = {
                "access_token": token,
                **payload,
            }
            response = requests.post(url, data=request_data, timeout=30)
            data = response.json()
            if response.status_code != 200:
                raise ValidationError(f"No se pudo duplicar el adset en Meta: {data}")

            adset_external_id = data.get("id")
            if not adset_external_id:
                raise ValidationError(f"Meta no devolvió el ID del adset duplicado: {data}")

            record.action_sync_adsets()
            new_adset = self.env["marketing.meta.adset"].sudo().search([
                ("external_id", "=", adset_external_id),
                ("campaign_id", "=", record.campaign_id.id),
            ], limit=1)
            if not new_adset:
                new_adset = self.env["marketing.meta.adset"].sudo().create({
                    "name": payload.get("name"),
                    "external_id": adset_external_id,
                    "campaign_id": record.campaign_id.id,
                    "account_id": record.ad_account_id.id,
                    "configured_status": "PAUSED",
                    "effective_status": "PAUSED",
                    "daily_budget": payload.get("daily_budget") or False,
                    "budget_type": "lifetime" if payload.get("lifetime_budget") else ("daily" if payload.get("daily_budget") else False),
                    "lifetime_budget": payload.get("lifetime_budget") or False,
                    "start_time": payload.get("start_time") or False,
                    "end_time": payload.get("end_time") or False,
                    "optimization_goal": payload.get("optimization_goal") or False,
                    "billing_event": payload.get("billing_event") or False,
                    "bid_strategy": payload.get("bid_strategy") or False,
                    "destination_type": payload.get("destination_type") or False,
                    "promoted_object_json": payload.get("promoted_object") or False,
                    "targeting_json": payload.get("targeting") or False,
                    "raw_payload": json.dumps(data),
                })

            record.write({
                "adset_id": new_adset.id,
                "meta_ad_id": False,
                "error_message": False,
                "sync_date": fields.Datetime.now(),
            })
        return True

    def action_sync_ads(self):
        self.ensure_one()
        if not self.adset_id:
            raise ValidationError("Selecciona primero un conjunto de anuncios.")

        token = self._get_meta_access_token()
        api_version = self._get_meta_api_version()
        url = f"https://graph.facebook.com/{api_version}/{self.adset_id.external_id}/ads"
        params = {
            "access_token": token,
            "fields": "id,name,status,configured_status,effective_status,recommendations,issues_info,ad_review_feedback,creative{id,object_story_id,effective_object_story_id,thumbnail_url,image_url,object_story_spec},preview_shareable_link,campaign{id}",
            "limit": 500,
        }
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if response.status_code != 200:
            raise ValidationError(f"No se pudieron sincronizar anuncios: {data}")

        Ad = self.env["marketing.meta.ad"].sudo()
        for item in data.get("data", []):
            creative = item.get("creative") or {}
            if creative.get("id") and _is_meta_creative_payload_incomplete(creative):
                fetched_creative = self._fetch_meta_creative_details(creative.get("id"))
                if fetched_creative:
                    creative = {
                        **creative,
                        **fetched_creative,
                    }
            creative_data = _extract_meta_creative_destinations(creative)
            vals = {
                "name": item.get("name") or item.get("id"),
                "external_id": item.get("id"),
                "adset_id": self.adset_id.id,
                "campaign_id": self.campaign_id.id,
                "account_id": self.ad_account_id.id,
                "configured_status": item.get("configured_status"),
                "effective_status": item.get("effective_status"),
                "existing_post_id": creative.get("effective_object_story_id") or creative.get("object_story_id"),
                "creative_id": creative.get("id"),
                "primary_text": creative_data.get("primary_text"),
                "headline": creative_data.get("headline"),
                "description": creative_data.get("description"),
                "call_to_action": creative_data.get("call_to_action"),
                "destination_url": creative_data.get("destination_url"),
                "message_destination": creative_data.get("message_destination"),
                "whatsapp_number": creative_data.get("whatsapp_number"),
                "image_url": creative.get("image_url") or creative.get("thumbnail_url"),
                "preview_url": item.get("preview_shareable_link"),
                "recommendations_json": json.dumps(item.get("recommendations"), ensure_ascii=False) if item.get("recommendations") else False,
                "issues_info_json": json.dumps(item.get("issues_info"), ensure_ascii=False) if item.get("issues_info") else False,
                "ad_review_feedback_json": json.dumps(item.get("ad_review_feedback"), ensure_ascii=False) if item.get("ad_review_feedback") else False,
                "raw_payload": json.dumps(item),
            }
            existing = Ad.search([
                ("external_id", "=", item.get("id")),
                ("adset_id", "=", self.adset_id.id),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                Ad.create(vals)

        self.sync_date = fields.Datetime.now()
        return True

    def action_create_ad(self):
        for record in self:
            record._ensure_meta_ad_create_ready()

            token = _get_meta_personal_access_token(record.env)
            api_version = record._get_meta_api_version()
            ad_name = record.ad_name or record.task_id.name or record.name

            creative_url = f"https://graph.facebook.com/{api_version}/act_{record.ad_account_id.account_id}/adcreatives"
            creative_request_data = {
                "access_token": token,
                "name": ad_name,
                "object_story_id": record.source_post_id,
            }
            creative_response = requests.post(creative_url, data=creative_request_data, timeout=30)
            creative_data = creative_response.json()
            if creative_response.status_code != 200:
                raise ValidationError(f"No se pudo crear el creative en Meta: {creative_data}")

            creative_external_id = creative_data.get("id")
            if not creative_external_id:
                raise ValidationError(f"Meta no devolvió el ID del creative: {creative_data}")

            ad_url = f"https://graph.facebook.com/{api_version}/act_{record.ad_account_id.account_id}/ads"
            ad_request_data = {
                "access_token": token,
                "name": ad_name,
                "adset_id": record.adset_id.external_id,
                "creative": json.dumps({"creative_id": creative_external_id}),
                "status": "PAUSED",
            }
            ad_response = requests.post(ad_url, data=ad_request_data, timeout=30)
            ad_data = ad_response.json()
            if ad_response.status_code != 200:
                raise ValidationError(f"No se pudo crear el anuncio en Meta: {ad_data}")

            ad_external_id = ad_data.get("id")
            if not ad_external_id:
                raise ValidationError(f"Meta no devolvió el ID del anuncio: {ad_data}")

            meta_ad = self.env["marketing.meta.ad"].sudo().create({
                "name": ad_name,
                "external_id": ad_external_id,
                "adset_id": record.adset_id.id,
                "campaign_id": record.campaign_id.id,
                "account_id": record.ad_account_id.id,
                "configured_status": "PAUSED",
                "effective_status": "PAUSED",
                "creative_id": creative_external_id,
                "raw_payload": json.dumps(ad_data),
            })

            record.write({
                "meta_ad_id": meta_ad.id,
                "ad_name": ad_name,
                "marketing_state": "pausado",
                "error_message": False,
                "sync_date": fields.Datetime.now(),
            })
            record.action_revisar()
        return True

    def action_programar(self):
        _raise_meta_write_disabled()

    def action_cancelar_programacion(self):
        _raise_meta_write_disabled()

    def _create_meta_creative_from_post(self):
        _raise_meta_write_disabled()

    def _activate_existing_meta_ad(self, configured_status="ACTIVE"):
        _raise_meta_write_disabled()

    def action_activate_now(self):
        _raise_meta_write_disabled()

    def action_revisar(self):
        for record in self:
            if not record.meta_ad_id:
                raise ValidationError("No existe un anuncio para revisar.")

            token = record._get_meta_access_token()
            api_version = record._get_meta_api_version()
            url = f"https://graph.facebook.com/{api_version}/{record.meta_ad_id.external_id}"
            params = {
                "access_token": token,
                "fields": "id,name,status,configured_status,effective_status,recommendations,issues_info,ad_review_feedback,campaign{id,status,configured_status,effective_status,start_time,stop_time,recommendations,issues_info},adset{id,status,configured_status,effective_status,start_time,end_time,recommendations,issues_info,learning_stage_info},creative{id,object_story_id,effective_object_story_id,thumbnail_url,image_url,object_story_spec},preview_shareable_link",
            }
            response = requests.get(url, params=params, timeout=20)
            data = response.json()
            if response.status_code != 200:
                record.marketing_state = "por_publicitar"
                record.error_message = str(data)
                raise ValidationError(f"No se pudo revisar el anuncio: {data}")

            campaign_data = data.get("campaign") or {}
            adset_data = data.get("adset") or {}
            creative = data.get("creative") or {}
            if creative.get("id") and _is_meta_creative_payload_incomplete(creative):
                fetched_creative = record._fetch_meta_creative_details(creative.get("id"))
                if fetched_creative:
                    creative = {
                        **creative,
                        **fetched_creative,
                    }
            creative_data = _extract_meta_creative_destinations(creative)
            if record.campaign_id and campaign_data:
                record.campaign_id.sudo().write({
                    "configured_status": campaign_data.get("configured_status"),
                    "effective_status": campaign_data.get("effective_status"),
                    "start_time": campaign_data.get("start_time") or False,
                    "stop_time": campaign_data.get("stop_time") or False,
                    "recommendations_json": json.dumps(campaign_data.get("recommendations"), ensure_ascii=False) if campaign_data.get("recommendations") else False,
                    "issues_info_json": json.dumps(campaign_data.get("issues_info"), ensure_ascii=False) if campaign_data.get("issues_info") else False,
                })
            if record.adset_id and adset_data:
                record.adset_id.sudo().write({
                    "configured_status": adset_data.get("configured_status"),
                    "effective_status": adset_data.get("effective_status"),
                    "start_time": adset_data.get("start_time") or False,
                    "end_time": adset_data.get("end_time") or False,
                    "recommendations_json": json.dumps(adset_data.get("recommendations"), ensure_ascii=False) if adset_data.get("recommendations") else False,
                    "issues_info_json": json.dumps(adset_data.get("issues_info"), ensure_ascii=False) if adset_data.get("issues_info") else False,
                    "learning_stage_info_json": json.dumps(adset_data.get("learning_stage_info"), ensure_ascii=False) if adset_data.get("learning_stage_info") else False,
                })
            record.meta_ad_id.write({
                "name": data.get("name") or record.meta_ad_id.name,
                "configured_status": data.get("configured_status"),
                "effective_status": data.get("effective_status"),
                "existing_post_id": creative.get("effective_object_story_id") or creative.get("object_story_id") or record.meta_ad_id.existing_post_id,
                "creative_id": creative.get("id") or record.meta_ad_id.creative_id,
                "primary_text": creative_data.get("primary_text") or record.meta_ad_id.primary_text,
                "headline": creative_data.get("headline") or record.meta_ad_id.headline,
                "description": creative_data.get("description") or record.meta_ad_id.description,
                "call_to_action": creative_data.get("call_to_action") or record.meta_ad_id.call_to_action,
                "destination_url": creative_data.get("destination_url") or record.meta_ad_id.destination_url,
                "message_destination": creative_data.get("message_destination") or record.meta_ad_id.message_destination,
                "whatsapp_number": creative_data.get("whatsapp_number") or record.meta_ad_id.whatsapp_number,
                "image_url": creative.get("image_url") or creative.get("thumbnail_url") or record.meta_ad_id.image_url,
                "preview_url": data.get("preview_shareable_link") or record.meta_ad_id.preview_url,
                "recommendations_json": json.dumps(data.get("recommendations"), ensure_ascii=False) if data.get("recommendations") else False,
                "issues_info_json": json.dumps(data.get("issues_info"), ensure_ascii=False) if data.get("issues_info") else False,
                "ad_review_feedback_json": json.dumps(data.get("ad_review_feedback"), ensure_ascii=False) if data.get("ad_review_feedback") else False,
                "raw_payload": json.dumps(data),
            })
            record.marketing_state = record._get_marketing_state_from_meta_nodes(
                campaign_data=campaign_data,
                adset_data=adset_data,
                ad_data=data,
            )
            record.error_message = False
            record.sync_date = fields.Datetime.now()
        return True

    def action_pause(self):
        _raise_meta_write_disabled()

    def action_resume(self):
        _raise_meta_write_disabled()

    def action_pause_ad(self):
        for record in self:
            if not record.meta_ad_id:
                raise ValidationError("No existe un anuncio para pausar.")
            record.meta_ad_id.action_pause()
            record.marketing_state = "pausado"
            record.sync_date = fields.Datetime.now()
        return True

    @api.model
    def _cron_activate_scheduled_marketing(self):
        _logger.info("Cron de activacion omitido: la escritura hacia Meta/Facebook esta deshabilitada.")
        return True

    @api.model
    def _task_marketing_vals(self, task):
        activation_dt = False
        if task.inicio_promocion:
            activation_dt = datetime.combine(task.inicio_promocion, time(hour=9, minute=0))
        return {
            "name": f"{task.name} - Publicidad",
            "task_id": task.id,
            "partner_id": task.partner_id.id,
            "company_id": task.company_id.id or self.env.company.id,
            "currency_id": task.currency_id.id,
            "budget": task.presupuesto,
            "campaign_name_edit": task.name,
            "adset_name_edit": task.name,
            "adset_daily_budget": task.presupuesto,
            "ad_name": task.name,
            "start_date": task.inicio_promocion,
            "end_date": task.fin_promocion,
            "scheduled_activation": activation_dt,
            "marketing_state": "por_publicitar",
            "platform": "meta",
            "ad_name": task.name,
        }

    @api.model
    def sync_from_task(self, task):
        if not task or not task.id:
            return False

        existing = self.search([("task_id", "=", task.id)], limit=1)
        if task.activar_publicidad_paga and task.post_estado == "Publicado":
            vals = self._task_marketing_vals(task)
            if existing:
                existing.with_context(skip_task_marketing_link=True).write(vals)
                marketing = existing
            else:
                marketing = self.with_context(skip_task_marketing_link=True).create(vals)
            if task.marketing_record_id != marketing:
                task.with_context(skip_marketing_sync=True).write({"marketing_record_id": marketing.id})
            return marketing
        return existing


class ProjectMarketingDashboard(models.Model):
    _name = "project.marketing.dashboard"
    _description = "Dashboard de Publicaciones Paga"
    _auto = False
    _order = "stage, campaign_name"

    provider = fields.Selection(
        [
            ("meta", "META"),
            ("google", "Google"),
            ("linkedin", "LinkedIn"),
            ("tiktok", "TikTok"),
        ],
        string="Proveedor",
        readonly=True,
    )
    marketing_record_id = fields.Many2one("project.marketing", string="Registro Marketing", readonly=True)
    campaign_id = fields.Many2one("marketing.meta.campaign", string="Campaña Meta", readonly=True)
    campaign_name = fields.Char(string="Nombre de la Campaña", readonly=True)
    task_id = fields.Many2one("project.task", string="Tarea", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", readonly=True)
    total_budget = fields.Monetary(string="Monto Total", readonly=True)
    total_spend = fields.Monetary(string="Monto Gastado", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Moneda", readonly=True)
    running_ads_count = fields.Integer(string="Ads Corriendo", readonly=True)
    state = fields.Char(string="Estado", readonly=True)
    stage = fields.Selection(
        [
            ("por_publicitar", "Por publicar"),
            ("publicado", "Promocionado"),
            ("pausado", "Pausado"),
            ("terminado", "Terminado"),
        ],
        string="Etapa",
        readonly=True,
        group_expand="_group_expand_stage",
    )
    marketing_records_count = fields.Integer(string="Registros", readonly=True)

    def action_open_marketing_form(self):
        self.ensure_one()
        marketing_record = self.marketing_record_id
        if not marketing_record:
            marketing_record = self.env["project.marketing"].search([
                ("id", "=", self.id),
                ("active", "=", True),
            ], limit=1)
        if not marketing_record:
            raise ValidationError("No se encontró un registro activo de Publicaciones Paga para esta campaña.")

        return {
            "type": "ir.actions.act_window",
            "name": "Publicaciones Paga",
            "res_model": "project.marketing",
            "view_mode": "form",
            "res_id": marketing_record.id,
            "views": [(self.env.ref("gl_geniolibre.view_project_marketing_form").id, "form")],
            "target": "current",
        }

    @api.model
    def action_open_import_wizard(self, *args):
        return {
            "type": "ir.actions.act_window",
            "name": "Importar desde Meta",
            "res_model": "project.marketing.import.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("gl_geniolibre.view_project_marketing_import_wizard_form").id,
            "target": "new",
        }

    @api.model
    def action_review_marketing_statuses(self, *args):
        self.env["project.marketing"].search([
            ("active", "=", True),
            ("platform", "=", "meta"),
            ("meta_ad_id", "!=", False),
        ]).action_review_meta_status()
        return {
            "type": "ir.actions.act_window",
            "name": "Dashboard",
            "res_model": "project.marketing.dashboard",
            "view_mode": "kanban,list",
            "target": "current",
        }

    @api.model
    def _group_expand_stage(self, stages, domain, order=None):
        return [
            "por_publicitar",
            "publicado",
            "pausado",
            "terminado",
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    pm.id AS id,
                    pm.platform AS provider,
                    pm.id AS marketing_record_id,
                    pm.campaign_id AS campaign_id,
                    COALESCE(mc.name, pm.name) AS campaign_name,
                    pm.task_id AS task_id,
                    pm.partner_id AS partner_id,
                    COALESCE(pm.budget, 0) AS total_budget,
                    COALESCE(mc.spend, 0) AS total_spend,
                    pm.currency_id AS currency_id,
                    CASE WHEN pm.marketing_state = 'publicado' THEN 1 ELSE 0 END AS running_ads_count,
                    CASE
                        WHEN pm.marketing_state IN ('programado', 'procesando', 'revisando', 'error') THEN 'por_publicitar'
                        ELSE pm.marketing_state
                    END AS stage,
                    COALESCE(
                        NULLIF(mc.effective_status, ''),
                        NULLIF(mc.configured_status, ''),
                        CASE
                            WHEN pm.marketing_state = 'publicado' THEN 'ACTIVE'
                            WHEN pm.marketing_state = 'pausado' THEN 'PAUSED'
                            WHEN pm.marketing_state = 'terminado' THEN 'TERMINADO'
                            WHEN pm.marketing_state = 'por_publicitar' THEN 'PENDIENTE'
                            ELSE 'SIN ESTADO'
                        END
                    ) AS state,
                    1 AS marketing_records_count
                FROM project_marketing pm
                LEFT JOIN marketing_meta_campaign mc
                    ON mc.id = pm.campaign_id
                WHERE pm.active = TRUE
            )
            """
            % self._table
        )


class ProjectMarketingImportWizard(models.TransientModel):
    _name = "project.marketing.import.wizard"
    _description = "Importar cadena de Meta"

    marketing_id = fields.Many2one("project.marketing", string="Publicacion Paga")
    name = fields.Char(string="Nombre", required=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True)
    task_id = fields.Many2one("project.task", string="Tarea")
    ad_account_id = fields.Many2one("facebook.ad.account", string="Cuenta Publicitaria", required=True)
    campaign_id = fields.Many2one(
        "marketing.meta.campaign",
        string="Campaña",
        domain="[('account_id', '=', ad_account_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        required=True,
    )
    adset_id = fields.Many2one(
        "marketing.meta.adset",
        string="Conjunto",
        domain="[('campaign_id', '=', campaign_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        required=True,
    )
    meta_ad_id = fields.Many2one(
        "marketing.meta.ad",
        string="Anuncio",
        domain="[('adset_id', '=', adset_id), ('active', '=', True), ('effective_status', '=', 'ACTIVE')]",
        required=True,
    )
    import_notes = fields.Text(string="Notas")

    def _build_marketing_sync_proxy(self):
        self.ensure_one()
        return self.env["project.marketing"].new({
            "name": self.name or "Importación Meta",
            "partner_id": self.partner_id.id,
            "task_id": self.task_id.id,
            "platform": "meta",
            "ad_account_id": self.ad_account_id.id,
            "campaign_id": self.campaign_id.id,
            "adset_id": self.adset_id.id,
        })

    @api.onchange("ad_account_id")
    def _onchange_ad_account_id(self):
        self.campaign_id = False
        self.adset_id = False
        self.meta_ad_id = False
        if self.ad_account_id:
            self._build_marketing_sync_proxy().action_sync_campaigns()

    @api.onchange("task_id")
    def _onchange_task_id(self):
        if self.task_id:
            self.name = self.name or self.task_id.name
            self.partner_id = self.partner_id or self.task_id.partner_id

    @api.onchange("campaign_id")
    def _onchange_campaign_id(self):
        self.adset_id = False
        self.meta_ad_id = False
        if self.campaign_id and not self.name:
            self.name = self.campaign_id.name
        if self.campaign_id:
            self._build_marketing_sync_proxy().action_sync_adsets()

    @api.onchange("adset_id")
    def _onchange_adset_id(self):
        self.meta_ad_id = False
        if self.adset_id and not self.name:
            self.name = self.adset_id.name
        if self.adset_id:
            self._build_marketing_sync_proxy().action_sync_ads()

    @api.onchange("meta_ad_id")
    def _onchange_meta_ad_id(self):
        if self.meta_ad_id:
            self.name = self.name or self.meta_ad_id.name

    def action_import_chain(self):
        self.ensure_one()
        if self.marketing_id:
            marketing = self.marketing_id
        else:
            marketing = self.env["project.marketing"].create({
                "name": self.name,
                "partner_id": self.partner_id.id,
                "task_id": self.task_id.id,
                "platform": "meta",
                "imported_from_meta": True,
            })
        vals = {
            "ad_account_id": self.ad_account_id.id,
            "campaign_id": self.campaign_id.id,
            "campaign_name_edit": self.campaign_id.name,
            "campaign_status_manual": self.campaign_id.configured_status or False,
            "task_id": self.task_id.id or False,
            "adset_id": self.adset_id.id,
            "adset_name_edit": self.adset_id.name,
            "meta_ad_id": self.meta_ad_id.id,
            "ad_name": self.meta_ad_id.name if self.meta_ad_id else False,
            "notes": self.import_notes or marketing.notes,
            "imported_from_meta": True,
            "marketing_state": marketing._get_marketing_state_from_meta_status(
                self.meta_ad_id.configured_status,
                self.meta_ad_id.effective_status,
            ),
        }
        marketing.write(vals)
        marketing._sync_meta_data_on_open()
        return {
            "type": "ir.actions.act_window",
            "name": "Publicaciones Paga",
            "res_model": "project.marketing",
            "view_mode": "form",
            "res_id": marketing.id,
            "views": [(self.env.ref("gl_geniolibre.view_project_marketing_form").id, "form")],
            "target": "current",
        }
