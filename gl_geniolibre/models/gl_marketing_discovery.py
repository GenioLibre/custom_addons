# -*- coding: utf-8 -*-
"""Descubrimiento documentado de videos y tendencias mediante fuentes oficiales.

No descarga videos, no usa scraping y no presume que un video corto sea viral.
"""
import hashlib
import logging
import re
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
GOOGLE_TRENDS_RSS = "https://trends.google.com/trending/rss"


def _safe_count(value):
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return 0


def _parse_google_trends(xml_bytes, region, keywords, limit):
    """Extrae títulos y enlaces del RSS oficial sin descargar las noticias enlazadas."""
    if len(xml_bytes) > 700000 or b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("Respuesta RSS no permitida o demasiado grande.")
    root = ElementTree.fromstring(xml_bytes)
    results = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        if not title or (keywords and not any(word in title.casefold() for word in keywords)):
            continue
        pub_date = (item.findtext("pubDate") or "").strip()
        published = False
        if pub_date:
            try:
                published = parsedate_to_datetime(pub_date).date()
            except (ValueError, TypeError, OverflowError):
                pass
        approx = ""
        for node in item:
            if node.tag.endswith("approx_traffic") and node.text:
                approx = node.text.strip()
                break
        link = (item.findtext("link") or "").strip()
        if not link.startswith("https://trends.google.com/"):
            link = "https://trends.google.com/trending?geo=%s" % region
        key = hashlib.sha256(("%s:%s" % (region, title.casefold())).encode("utf-8")).hexdigest()[:40]
        results.append({
            "external_id": key, "kind": "trend", "platform": "google",
            "name": title[:240], "url": link, "observed_on": published or fields.Date.today(),
            "notes": (
                "Google Trends (RSS público, región %s). Consulta en tendencia: %s."
                " Tráfico aproximado mostrado por la fuente: %s."
                " No demuestra relación con la marca ni crecimiento futuro."
            ) % (region, title, approx or "no disponible"),
            "source_origin": "google_trends",
        })
        if len(results) >= limit:
            break
    return results


class GlMarketingIntelligenceDiscovery(models.Model):
    _inherit = "gl.marketing.intelligence"

    discovery_sources = fields.Selection(
        [("youtube", "YouTube"), ("trends", "Google Trends"), ("both", "Ambas fuentes")],
        string="Fuentes para descubrir", default="both", required=True,
    )
    discovery_query = fields.Char(
        "Tema para buscar", help="Término para buscar en YouTube; si se deja vacío se usa el sector."
    )
    trends_keywords = fields.Char(
        "Palabras clave de tendencias",
        help="Separadas por comas. Solo guarda tendencias que coincidan con alguna; si se deja vacío usa el sector.",
    )
    youtube_channel_id = fields.Char(
        "ID de canal YouTube (opcional)", help="Identificador UC... del canal competidor, no su URL ni @usuario."
    )
    discovery_region = fields.Char("País (ISO 2 letras)", default="PE", required=True)
    discovery_limit = fields.Integer("Máximo por fuente", default=10, required=True)
    auto_collect = fields.Boolean(
        "Investigación semanal automática", default=False,
        help="Solo recopila fuentes mientras el informe está en Recopilando. "
             "El cron global se habilita manualmente por el administrador.",
    )
    last_collected_at = fields.Datetime("Última recopilación", readonly=True, copy=False)
    collection_summary = fields.Text("Resultado de recopilación", readonly=True, copy=False)

    @api.constrains("discovery_region", "discovery_limit", "youtube_channel_id")
    def _validate_discovery(self):
        for rec in self:
            region = (rec.discovery_region or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", region):
                raise ValidationError(_("El país debe ser un código de dos letras, por ejemplo PE, US o CR."))
            if not 1 <= rec.discovery_limit <= 20:
                raise ValidationError(_("El máximo por fuente debe estar entre 1 y 20."))
            channel = (rec.youtube_channel_id or "").strip()
            if channel and not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel):
                raise ValidationError(_("Introduce un ID de canal YouTube válido que empiece por UC."))

    @staticmethod
    def _fetch_json(url, params):
        try:
            result = requests.get(url, params=params, timeout=(5, 20), allow_redirects=False)
            if result.status_code != 200:
                raise UserError(
                    _("La API de YouTube respondió con HTTP %s. Revisa la clave, la cuota y los permisos.")
                    % result.status_code
                )
            data = result.json()
            if not isinstance(data, dict):
                raise ValueError("Respuesta inesperada")
            return data
        except (requests.RequestException, ValueError) as exc:
            _logger.warning("Fallo de comunicación con YouTube (%s)", type(exc).__name__)
            raise UserError(_("No se pudo consultar YouTube. Revisa la conexión y vuelve a intentarlo.")) from exc

    def _discover_youtube(self):
        self.ensure_one()
        key = (self.env["ir.config_parameter"].sudo().get_param("gl_marketing.youtube_api_key") or "").strip()
        if not key:
            raise UserError(
                _("Configura la clave YouTube Data API en Ajustes > GenioLibre para buscar videos.")
            )
        query = (self.discovery_query or self.industry or "").strip()
        if not query and not self.youtube_channel_id:
            raise ValidationError(_("Configura el tema de búsqueda o un ID de canal de YouTube."))
        region = self.discovery_region.strip().upper()
        params = {
            "key": key, "part": "snippet", "type": "video",
            "videoDuration": "short", "order": "viewCount",
            "regionCode": region, "maxResults": self.discovery_limit,
        }
        if query:
            params["q"] = query[:120]
        if self.youtube_channel_id:
            params["channelId"] = self.youtube_channel_id.strip()
        if self.date_start:
            params["publishedAfter"] = "%sT00:00:00Z" % fields.Date.to_string(self.date_start)
        else:
            params["publishedAfter"] = "%sT00:00:00Z" % fields.Date.to_string(
                fields.Date.today() - timedelta(days=30)
            )
        if self.date_end:
            params["publishedBefore"] = "%sT23:59:59Z" % fields.Date.to_string(self.date_end)
        search = self._fetch_json(YOUTUBE_SEARCH_URL, params)
        video_ids = list(dict.fromkeys(
            item.get("id", {}).get("videoId")
            for item in search.get("items", [])
            if isinstance(item.get("id"), dict) and item["id"].get("videoId")
        ))[:self.discovery_limit]
        if not video_ids:
            return []
        details = self._fetch_json(YOUTUBE_VIDEOS_URL, {
            "key": key, "part": "snippet,statistics,contentDetails", "id": ",".join(video_ids),
            "maxResults": self.discovery_limit,
        })
        found = []
        for item in details.get("items", []):
            video_id = item.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            title = (snippet.get("title") or "").strip()
            if not title:
                continue
            views = _safe_count(statistics.get("viewCount"))
            likes = _safe_count(statistics.get("likeCount"))
            comments = _safe_count(statistics.get("commentCount"))
            duration = item.get("contentDetails", {}).get("duration", "")
            published = (snippet.get("publishedAt") or "")[:10]
            try:
                observed = fields.Date.to_date(published) if published else fields.Date.today()
            except ValueError:
                observed = fields.Date.today()
            found.append({
                "external_id": video_id, "source_origin": "youtube_api",
                "kind": "viral", "platform": "youtube", "name": title[:240],
                "url": "https://www.youtube.com/watch?v=%s" % video_id,
                "observed_on": observed,
                "views_count": views, "engagement_count": likes + comments,
                "notes": (
                    "Metadatos públicos YouTube Data API. Canal: %s. "
                    "Publicado: %s. Duración informada: %s. "
                    "Visualizaciones: %s; likes: %s; comentarios: %s. "
                    "La API filtra videos de menos de 4 minutos; NO certifica que sea un Short "
                    "ni que sea viral. No se visualizó ni transcribió el video."
                ) % (
                    snippet.get("channelTitle", "No disponible"), published or "sin fecha",
                    duration or "sin datos", views, likes, comments,
                ),
            })
        return found

    def _discover_google_trends(self):
        self.ensure_one()
        region = self.discovery_region.strip().upper()
        values = self.trends_keywords or self.industry or ""
        keywords = [v.strip().casefold() for v in values.split(",") if len(v.strip()) >= 3]
        if not keywords:
            raise ValidationError(
                _("Indica palabras clave del sector para evitar tendencias irrelevantes.")
            )
        try:
            response = requests.get(
                GOOGLE_TRENDS_RSS, params={"geo": region}, timeout=(5, 20),
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise UserError(_("Google Trends RSS respondió con HTTP %s.") % response.status_code)
            return _parse_google_trends(response.content, region, keywords, self.discovery_limit)
        except (requests.RequestException, ValueError, ElementTree.ParseError) as exc:
            _logger.warning("No se pudo consultar Google Trends RSS (%s)", type(exc).__name__)
            raise UserError(_("No se pudo leer el RSS de Google Trends; comprueba disponibilidad.")) from exc

    def _save_discovery(self, values):
        """Actualiza solo referencias de origen automático, sin pisar notas manuales."""
        self.ensure_one()
        References = self.env["gl.marketing.reference"]
        created, refreshed = 0, 0
        for vals in values:
            src = vals["source_origin"]
            ext = vals["external_id"]
            existing = References.search([
                ("research_id", "=", self.id), ("platform", "=", vals["platform"]),
                ("external_id", "=", ext),
            ], limit=1)
            if not existing and src == "youtube_api":
                # Una URL de YouTube identifica un video; la URL general de Trends no
                # identifica una tendencia individual y no debe usarse para deduplicar.
                existing = References.search([
                    ("research_id", "=", self.id), ("platform", "=", vals["platform"]),
                    ("url", "=", vals["url"]),
                ], limit=1)
            if existing and existing.source_origin == "manual":
                continue
            payload = dict(vals)
            payload["synced_at"] = fields.Datetime.now()
            if existing:
                existing.write(payload)
                refreshed += 1
            else:
                References.create(dict(payload, research_id=self.id))
                created += 1
        return created, refreshed

    def _run_collection(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(
                _("Para recopilar nuevas fuentes reabre la investigación (estado Recopilando).")
            )
        if self.discovery_sources == "youtube":
            found = self._discover_youtube()
            source_note = "YouTube"
        elif self.discovery_sources == "trends":
            found = self._discover_google_trends()
            source_note = "Google Trends"
        else:
            key = self.env["ir.config_parameter"].sudo().get_param("gl_marketing.youtube_api_key")
            found = self._discover_google_trends()
            source_note = "Google Trends"
            if key:
                found += self._discover_youtube()
                source_note += " y YouTube"
            else:
                source_note += " (YouTube omitido: falta clave API)"
        created, refreshed = self._save_discovery(found)
        summary = "%s: %s nuevas; %s actualizadas; %s resultados elegibles." % (
            source_note, created, refreshed, len(found)
        )
        self.write({
            "last_collected_at": fields.Datetime.now(),
            "collection_summary": summary,
            "prompt": False, "response_json": False, "report": False,
            "evidence_signature": False, "analyzed_at": False,
        })
        return summary

    def action_collect_research(self):
        self.ensure_one()
        summary = self._run_collection()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {
                "title": _("Investigación actualizada"), "message": summary,
                "type": "success", "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    @api.model
    def _cron_collect_marketing_research(self):
        """El cron global también empieza desactivado; limitar trabajo por ejecución."""
        threshold = fields.Datetime.now() - timedelta(days=6)
        records = self.search([
            ("auto_collect", "=", True),
            ("state", "=", "draft"),
            "|", ("last_collected_at", "=", False), ("last_collected_at", "<", threshold),
        ], limit=10, order="last_collected_at asc, id asc")
        for rec in records:
            try:
                with self.env.cr.savepoint():
                    rec._run_collection()
            except Exception as exc:
                # No escribir la URL con ?key=..., ni incluir credenciales en logs.
                _logger.warning(
                    "Recopilación de investigación %s falló (%s)",
                    rec.id, type(exc).__name__,
                )


class GlMarketingReferenceOrigin(models.Model):
    _inherit = "gl.marketing.reference"

    source_origin = fields.Selection(
        [("manual", "Manual"), ("youtube_api", "YouTube Data API"),
         ("google_trends", "Google Trends RSS")],
        default="manual", required=True, string="Origen",
    )
    external_id = fields.Char("Identificador externo", index=True, copy=False)
    synced_at = fields.Datetime("Sincronizado el", readonly=True, copy=False)

    _sql_constraints = [
        ("uniq_research_source_external", "unique(research_id,platform,external_id)",
         "La referencia ya existe para esta investigación y plataforma."),
    ]
