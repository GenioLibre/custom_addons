# -*- coding: utf-8 -*-
"""Investigación de marketing sustentada en referencias aportadas por el equipo."""
import hashlib
import json
from urllib.parse import urlparse

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GlMarketingIntelligence(models.Model):
    _name = "gl.marketing.intelligence"
    _description = "Inteligencia de Marketing"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char("Investigación", required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True, tracking=True)
    project_id = fields.Many2one("project.project", string="Proyecto", domain="[('partner_id', '=', partner_id)]")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    industry = fields.Char("Sector")
    audience = fields.Text("Público objetivo")
    goal = fields.Text("Objetivo")
    date_start = fields.Date("Desde")
    date_end = fields.Date("Hasta")
    reference_ids = fields.One2many("gl.marketing.reference", "research_id", string="Fuentes y referencias")
    state = fields.Selection(
        [("draft", "Recopilando"), ("analyzed", "Analizado"), ("approved", "Aprobado")],
        default="draft", required=True, tracking=True, string="Estado",
    )
    prompt = fields.Text("Prompt para IA", copy=False)
    response_json = fields.Text("Respuesta JSON de IA", copy=False)
    report = fields.Text("Informe estratégico", copy=False, readonly=True)
    evidence_signature = fields.Char(readonly=True, copy=False)
    analyzed_at = fields.Datetime("Fecha de análisis", readonly=True, copy=False)
    direct_ai = fields.Boolean(compute="_compute_direct_ai")

    def _compute_direct_ai(self):
        raw = self.env["ir.config_parameter"].sudo().get_param("chatgpt.conexion_directa", "False")
        enabled = str(raw).lower() in ("true", "1", "on", "yes")
        for record in self:
            record.direct_ai = enabled

    @api.constrains("project_id", "partner_id", "company_id", "date_start", "date_end")
    def _check_scope(self):
        for record in self:
            if record.project_id and record.project_id.partner_id and record.project_id.partner_id != record.partner_id:
                raise ValidationError(_("El proyecto pertenece a otro cliente."))
            if record.project_id and record.project_id.company_id and record.project_id.company_id != record.company_id:
                raise ValidationError(_("El proyecto pertenece a otra compañía."))
            if record.date_start and record.date_end and record.date_start > record.date_end:
                raise ValidationError(_("El periodo de investigación es incorrecto."))

    def _evidence(self):
        self.ensure_one()
        return [
            {
                "id": ref.id, "tipo": ref.kind, "plataforma": ref.platform,
                "titulo": ref.name, "url": ref.url or "",
                "fecha_observada": fields.Date.to_string(ref.observed_on) if ref.observed_on else "",
                "observacion": ref.notes or "",
                "visualizaciones_reportadas": ref.views_count or None,
                "interacciones_reportadas": ref.engagement_count or None,
            }
            for ref in self.reference_ids.sorted("id")
        ]

    def _fingerprint(self):
        self.ensure_one()
        context = {
            "cliente": self.partner_id.id, "proyecto": self.project_id.id,
            "sector": self.industry or "", "audiencia": self.audience or "",
            "objetivo": self.goal or "",
            "desde": fields.Date.to_string(self.date_start) if self.date_start else "",
            "hasta": fields.Date.to_string(self.date_end) if self.date_end else "",
            "fuentes": self._evidence(),
        }
        return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _build_prompt(self):
        self.ensure_one()
        if not self.reference_ids or not any((r.notes or "").strip() for r in self.reference_ids):
            raise ValidationError(_("Agrega referencias con observaciones antes de investigar."))
        data = {
            "cliente": self.partner_id.name, "sector": self.industry or "",
            "audiencia": self.audience or "", "objetivo": self.goal or "",
            "fuentes": self._evidence(),
        }
        return (
            "Eres analista de marketing para GenioLibre. Usa EXCLUSIVAMENTE las observaciones "
            "aportadas. Los enlaces son referencias: NO digas que abriste URLs, que viste videos "
            "ni que verificaste sus cifras. No inventes datos ni copies contenido de competidores. "
            "Distingue hechos documentados de hipótesis.\n\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + '\n\nResponde SOLO un objeto JSON con "resumen" (texto), "hallazgos", '
            '"oportunidades" y "recomendaciones" (listas). Cada elemento de las listas '
            'debe ser {"texto": "descripción", "fuentes": [IDs numéricos existentes]}. '
            "Las listas pueden estar vacías, pero cada elemento debe citar fuentes aportadas."
        )

    def action_prepare_prompt(self):
        for record in self:
            if record.state == "approved":
                raise ValidationError(_("Reabre la investigación antes de actualizar el prompt."))
            record.prompt = record._build_prompt()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Prompt preparado"), "message": _("Copia el prompt y pega la respuesta JSON."),
                       "type": "success", "next": {"type": "ir.actions.client", "tag": "reload"}},
        }

    def action_analyze_ai(self):
        for record in self:
            if not record.direct_ai:
                raise ValidationError(_("Activa Conexión directa con IA en Ajustes de GenioLibre."))
            if record.state == "approved":
                raise ValidationError(_("Reabre la investigación antes de volver a analizarla."))
            prompt = record._build_prompt()
            answer = self.env["gl.contenido.flujo"]._call_openai_chat_completion(
                prompt=prompt,
                system_prompt="Eres analista de marketing. No tienes acceso web. Usa solo las fuentes aportadas; devuelve solo JSON.",
                temperature=0.2, timeout=120,
            )
            record.write({"prompt": prompt, "response_json": answer})
            record.action_apply_report()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Investigación analizada"), "message": _("Revisa el informe antes de aprobarlo."),
                       "type": "success", "next": {"type": "ir.actions.client", "tag": "reload"}},
        }

    def action_apply_report(self):
        for record in self:
            if record.state == "approved":
                raise ValidationError(_("Reabre la investigación antes de aplicar una respuesta."))
            if not record.reference_ids:
                raise ValidationError(_("No hay fuentes para contrastar la respuesta."))
            raw = (record.response_json or "").strip()
            if raw.startswith("\x60\x60\x60"):
                raw = raw.split("\n", 1)[-1].rsplit("\x60\x60\x60", 1)[0].strip()
            try:
                data = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("Respuesta JSON inválida: %s") % exc)
            if not isinstance(data, dict) or not isinstance(data.get("resumen"), str) or not data["resumen"].strip():
                raise ValidationError(_("La respuesta debe incluir un resumen en texto."))
            allowed = {ref.id: ref for ref in record.reference_ids}
            output = ["RESUMEN", data["resumen"].strip()]
            for key, heading in (("hallazgos", "HALLAZGOS"), ("oportunidades", "OPORTUNIDADES"), ("recomendaciones", "RECOMENDACIONES")):
                items = data.get(key)
                if not isinstance(items, list):
                    raise ValidationError(_("El campo %s debe ser una lista.") % key)
                output.extend(["", heading])
                for idx, item in enumerate(items, 1):
                    if not isinstance(item, dict) or not isinstance(item.get("texto"), str) or not item["texto"].strip():
                        raise ValidationError(_("Entrada de %s inválida.") % key)
                    source_ids = item.get("fuentes")
                    if not isinstance(source_ids, list) or not source_ids:
                        raise ValidationError(_("Cada conclusión debe citar al menos una fuente."))
                    if any(type(sid) is not int or sid not in allowed for sid in source_ids):
                        raise ValidationError(_("El informe incluye IDs de fuentes ajenas o inexistentes."))
                    urls = [allowed[sid].url or "Fuente %s" % sid for sid in dict.fromkeys(source_ids)]
                    output.append("%s. %s [Fuentes: %s]" % (idx, item["texto"].strip(), "; ".join(urls)))
            record.write({
                "report": "\n".join(output),
                "evidence_signature": record._fingerprint(),
                "analyzed_at": fields.Datetime.now(),
                "state": "analyzed",
            })
        return True

    def action_approve(self):
        for record in self:
            if record.state != "analyzed" or not record.report:
                raise ValidationError(_("Primero analiza y valida la investigación."))
            if record.evidence_signature != record._fingerprint():
                raise ValidationError(_("Las evidencias cambiaron; vuelve a analizar antes de aprobar."))
            record.state = "approved"
        return True

    def action_reopen(self):
        for record in self:
            record.state = "draft"
        return True

    def get_strategy_context(self, partner, project=False):
        self.ensure_one()
        if self.state != "approved" or self.partner_id != partner:
            raise ValidationError(_("Selecciona una investigación aprobada del mismo cliente."))
        if self.project_id and self.project_id != project:
            raise ValidationError(_("Esta investigación pertenece a otro proyecto."))
        if self.evidence_signature != self._fingerprint():
            raise ValidationError(_("Las evidencias cambiaron; reanaliza y aprueba nuevamente."))
        return {"investigacion": self.name, "informe": self.report,
                "nota": "Basar ideas en evidencias con fuentes, sin copiar competidores ni inventar datos."}


class GlMarketingReference(models.Model):
    _name = "gl.marketing.reference"
    _description = "Fuente de Investigación de Marketing"
    _order = "observed_on desc, id desc"

    research_id = fields.Many2one(
        "gl.marketing.intelligence", required=True, ondelete="cascade", index=True, string="Investigación",
    )
    company_id = fields.Many2one("res.company", related="research_id.company_id", store=True, readonly=True)
    name = fields.Char("Título / competidor", required=True)
    kind = fields.Selection(
        [("competitor", "Competidor"), ("viral", "Video destacado"), ("trend", "Tendencia"),
         ("audience", "Pregunta o comentario"), ("internal", "Métrica propia")],
        required=True, default="competitor", string="Tipo",
    )
    platform = fields.Selection(
        [("instagram", "Instagram"), ("tiktok", "TikTok"), ("youtube", "YouTube"),
         ("facebook", "Facebook"), ("linkedin", "LinkedIn"), ("google", "Google"),
         ("web", "Web"), ("other", "Otra")],
        required=True, default="instagram", string="Plataforma",
    )
    url = fields.Char("URL de referencia")
    observed_on = fields.Date("Fecha observada", default=fields.Date.context_today)
    notes = fields.Text("Observación comprobable", required=True)
    views_count = fields.Integer("Visualizaciones reportadas")
    engagement_count = fields.Integer("Interacciones reportadas")

    @api.constrains("url", "kind", "views_count", "engagement_count")
    def _check_reference(self):
        for record in self:
            if record.kind != "internal" and not (record.url or "").strip():
                raise ValidationError(_("Las referencias externas necesitan una URL."))
            if record.url:
                u = urlparse(record.url.strip())
                if u.scheme not in ("http", "https") or not u.netloc:
                    raise ValidationError(_("Escribe una URL http(s) válida."))
            if record.views_count < 0 or record.engagement_count < 0:
                raise ValidationError(_("Las métricas no pueden ser negativas."))
