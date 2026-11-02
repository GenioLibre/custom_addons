# -*- coding: utf-8 -*-
"""Prioridad Facebook/Instagram/TikTok/LinkedIn e importación de reportes propios.

No atribuye acceso a métricas de competidores ni consulta APIs sin permisos.
"""
import hashlib
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

SOCIAL_NETWORKS = ("facebook", "instagram", "tiktok", "linkedin")
METRIC_WORDS = (
    "reach", "impression", "view", "follow", "like", "comment", "share",
    "click", "engag", "interaction", "save", "play", "watch",
    "alcance", "impresion", "vista", "seguido", "me_gusta",
    "comentario", "compart", "interaccion", "reproduccion",
)
PLATFORM_KEYS = {
    "facebook": "facebook", "fb": "facebook",
    "instagram": "instagram", "ig": "instagram",
    "tiktok": "tiktok", "tik_tok": "tiktok",
    "linkedin": "linkedin", "linked_in": "linkedin",
}


def _social_sections(payload):
    """Extraer únicamente objetos identificados explícitamente por red social."""
    if not isinstance(payload, (dict, list)):
        return {}
    found = {}
    containers = [payload]
    if isinstance(payload, dict):
        for key in ("redes", "networks", "platforms", "social", "redes_sociales"):
            child = payload.get(key)
            if isinstance(child, (dict, list)):
                containers.append(child)
    for root in containers:
        if isinstance(root, dict):
            for key, value in root.items():
                network = PLATFORM_KEYS.get(str(key).strip().lower().replace(" ", "_"))
                if network and isinstance(value, (dict, list)):
                    found[network] = value
        elif isinstance(root, list):
            for item in root:
                if not isinstance(item, dict):
                    continue
                label = (item.get("red") or item.get("platform") or item.get("network") or "")
                network = PLATFORM_KEYS.get(str(label).strip().lower().replace(" ", "_"))
                if network:
                    found[network] = item
    return found


def _numeric_metrics(payload):
    """Lista limitada de métricas NUMÉRICAS; descartar IDs, usuarios y textos personales."""
    values = {}
    def walk(value, depth=0):
        if depth > 3 or len(values) >= 30:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                key_normal = str(key).lower().replace("-", "_").replace(" ", "_")
                if key_normal.endswith(("_id", "_token", "_phone", "_email")) or key_normal in ("id", "token", "phone", "email"):
                    continue
                if any(term in key_normal for term in METRIC_WORDS):
                    if isinstance(item, (int, float)) and not isinstance(item, bool):
                        values[key_normal[:80]] = item
                    elif isinstance(item, dict) and isinstance(item.get("value"), (int, float)) and not isinstance(item["value"], bool):
                        values[key_normal[:80]] = item["value"]
                if isinstance(item, (dict, list)):
                    walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:30]:
                walk(item, depth + 1)
    walk(payload)
    return dict(list(values.items())[:30])


class GlMarketingIntelligenceSocial(models.Model):
    _inherit = "gl.marketing.intelligence"

    social_facebook = fields.Boolean("Facebook", default=True)
    social_instagram = fields.Boolean("Instagram", default=True)
    social_tiktok = fields.Boolean("TikTok", default=True)
    social_linkedin = fields.Boolean("LinkedIn", default=True)

    discovery_sources = fields.Selection(
        selection_add=[("owned", "Métricas propias registradas en Odoo")],
        ondelete={"owned": "set default"}, default="owned",
    )
    imported_social_at = fields.Datetime("Última importación de reportes", readonly=True)

    def _active_social_networks(self):
        self.ensure_one()
        return [
            name for name in SOCIAL_NETWORKS
            if getattr(self, "social_%s" % name)
        ]

    def _fingerprint(self):
        self.ensure_one()
        context = json.dumps(self._active_social_networks(), sort_keys=True)
        return hashlib.sha256((super()._fingerprint() + context).encode("utf-8")).hexdigest()

    def _build_prompt(self):
        self.ensure_one()
        selected = self._active_social_networks()
        if not selected:
            raise ValidationError(_("Activa al menos una red social para analizar."))
        return super()._build_prompt() + (
            "\n\nREDES DEL CLIENTE: %s. Prioriza estas plataformas. "
            "Las referencias de YouTube y Google Trends son SOLO complementarias. "
            "Las métricas propias proceden de reportes guardados previamente en Odoo: "
            "no equivalen a una consulta en vivo ni a métricas públicas de competidores. "
            "No inventes información de publicaciones no incluida en las evidencias. "
            "Crea ideas originales específicas para las redes activadas."
        ) % ", ".join(selected)

    def _run_collection(self):
        self.ensure_one()
        if self.discovery_sources != "owned":
            return super()._run_collection()
        if self.state != "draft":
            raise ValidationError(_("Reabre la investigación antes de recopilar datos."))
        selected = self._active_social_networks()
        if not selected:
            raise ValidationError(_("Selecciona al menos una red social."))
        domain = [("partner_id", "=", self.partner_id.id), ("data_json", "!=", False)]
        if self.date_start:
            domain += ["|", ("date_end", "=", False), ("date_end", ">=", self.date_start)]
        if self.date_end:
            domain += ["|", ("date_start", "=", False), ("date_start", "<=", self.date_end)]
        reports = self.env["gl.social.reports"].search(domain, order="date_end desc, id desc", limit=24)
        discovered = []
        for report in reports:
            try:
                payload = json.loads(report.data_json)
            except (ValueError, TypeError):
                _logger.info("Reporte social %s omitido: JSON inválido", report.id)
                continue
            sections = _social_sections(payload)
            for platform in selected:
                if platform not in sections:
                    continue
                metrics = _numeric_metrics(sections[platform])
                if not metrics:
                    continue
                observed = report.date_end or report.date_start or fields.Date.today()
                start = fields.Date.to_string(report.date_start) if report.date_start else "sin fecha"
                end = fields.Date.to_string(report.date_end) if report.date_end else "sin fecha"
                discovered.append({
                    "source_origin": "odoo_social_report",
                    "external_id": "odoo-report:%s:%s" % (report.id, platform),
                    "kind": "internal", "platform": platform,
                    "name": "Métricas propias %s (%s a %s)" % (platform.title(), start, end),
                    "url": False, "observed_on": observed,
                    "notes": "Origen: reporte interno Odoo ID %s, cliente %s, periodo %s - %s. "
                             "Datos reportados; no se consultaron APIs ahora. Métricas: %s"
                             % (report.id, self.partner_id.name, start, end,
                                json.dumps(metrics, ensure_ascii=False, sort_keys=True)),
                })
        created, refreshed = self._save_discovery(discovered)
        summary = (
            "Reportes Odoo: %s referencias nuevas, %s actualizadas; "
            "%s métricas por red encontradas en %s reportes. "
            "Las cuentas de competidores se documentan mediante enlaces y observaciones."
        ) % (created, refreshed, len(discovered), len(reports))
        self.write({
            "imported_social_at": fields.Datetime.now(),
            "last_collected_at": fields.Datetime.now(),
            "collection_summary": summary,
            "prompt": False, "response_json": False, "report": False,
            "evidence_signature": False, "analyzed_at": False,
        })
        return summary


class GlMarketingReferenceSocial(models.Model):
    _inherit = "gl.marketing.reference"

    source_origin = fields.Selection(
        selection_add=[("odoo_social_report", "Reporte social Odoo")],
        ondelete={"odoo_social_report": "set default"},
    )
