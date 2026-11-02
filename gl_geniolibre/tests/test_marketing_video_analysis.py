# -*- coding: utf-8 -*-
"""Pruebas de análisis sin acceso a APIs de terceros."""
import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGlMarketingVideoAnalysis(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Marca de prueba"})
        self.research = self.env["gl.marketing.intelligence"].create({
            "name": "Investigación integrada", "partner_id": self.partner.id,
            "industry": "Educación de conductores",
        })
        self.ref = self.env["gl.marketing.reference"].create({
            "research_id": self.research.id, "name": "Video de referencia A",
            "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            "kind": "viral", "platform": "youtube",
            "notes": "El título contiene una pregunta sobre conducción.",
            "views_count": 500, "engagement_count": 15,
        })
        self.competitor = self.env["gl.marketing.reference"].create({
            "research_id": self.research.id, "name": "Competidor B",
            "url": "https://www.youtube.com/watch?v=BBBBBBBBBBB",
            "kind": "competitor", "platform": "youtube",
            "notes": "Descripción del canal aportada por un miembro del equipo.",
        })
        self.valid_analysis = {
            "resumen": "Evidencia limitada al título.",
            "hook": "Pregunta en el título; no se ha observado el inicio real.",
            "estructura": "No disponible con la evidencia actual.",
            "cta": "No disponible con la evidencia actual.",
            "formato": "Video público de YouTube; edición no verificada.",
            "oportunidad": "Probar un video original con una pregunta distinta.",
            "limitaciones": "No hay transcripción ni observación visual.",
        }

    def _analyze_manually(self):
        self.ref.action_prepare_video_prompt()
        self.assertIn("No accediste al enlace", self.ref.video_prompt)
        self.ref.video_response_json = json.dumps(self.valid_analysis, ensure_ascii=False)
        self.ref.action_apply_video_analysis()

    def test_reference_analysis_reaches_research_prompt(self):
        self._analyze_manually()
        self.assertTrue(self.ref.video_analysis_current)
        self.assertEqual(self.ref.video_analysis_state, "analyzed")
        prompt = self.research._build_prompt()
        self.assertIn("analisis_estructurado", prompt)
        self.assertIn("Probar un video original", prompt)

    def test_comparison_keeps_source_links_and_limitations(self):
        self._analyze_manually()
        self.research.action_compare_references()
        self.assertTrue(self.research.comparison_current)
        self.assertIn(self.ref.url, self.research.comparison_report)
        self.assertIn(self.competitor.url, self.research.comparison_report)
        self.assertIn("indicador descriptivo", self.research.comparison_report)
        self.competitor.notes = "Nueva información observada"
        self.assertFalse(self.research.comparison_current)

    def test_direct_ai_mode_with_mocked_api(self):
        params = self.env["ir.config_parameter"].sudo()
        previous = params.get_param("chatgpt.conexion_directa", "False")
        params.set_param("chatgpt.conexion_directa", "True")
        self.research.invalidate_recordset(["direct_ai"])
        try:
            assistant = type(self.env["gl.contenido.flujo"])
            with patch.object(
                assistant, "_call_openai_chat_completion",
                return_value=json.dumps(self.valid_analysis, ensure_ascii=False),
            ) as mocked:
                self.ref.action_analyze_video_ai()
                mocked.assert_called_once()
            self.assertTrue(self.ref.video_analysis_current)
            self.assertIn("Oportunidad original", self.ref.video_analysis_report)
        finally:
            params.set_param("chatgpt.conexion_directa", previous)
            self.research.invalidate_recordset(["direct_ai"])

    def test_invalid_json_rejected(self):
        missing_key = dict(self.valid_analysis)
        missing_key.pop("limitaciones")
        self.ref.video_response_json = json.dumps(missing_key)
        with self.assertRaises(ValidationError):
            self.ref.action_apply_video_analysis()
        self.assertEqual(self.ref.video_analysis_state, "pending")

    def test_approved_report_invalidates_when_transcript_changes(self):
        self._analyze_manually()
        self.research.response_json = json.dumps({
            "resumen": "Muestra pequeña; no demuestra viralidad.",
            "hallazgos": [{"texto": "El título contiene una pregunta.", "fuentes": [self.ref.id]}],
            "oportunidades": [{"texto": "Probar otro hook original.", "fuentes": [self.ref.id]}],
            "recomendaciones": [{"texto": "Revisar la respuesta de la audiencia.", "fuentes": [self.ref.id]}],
        }, ensure_ascii=False)
        self.research.action_apply_report()
        self.research.action_approve()
        self.assertIn("Muestra pequeña", self.research.get_strategy_context(self.partner)["informe"])
        self.ref.transcript_text = "Transcripción distinta añadida después de aprobar."
        self.assertFalse(self.ref.video_analysis_current)
        with self.assertRaises(ValidationError):
            self.research.get_strategy_context(self.partner)

    def test_cannot_analyze_approved_research(self):
        self.research.response_json = json.dumps({
            "resumen": "Solo metadatos disponibles.",
            "hallazgos": [], "oportunidades": [], "recomendaciones": [],
        })
        self.research.action_apply_report()
        self.research.action_approve()
        with self.assertRaises(ValidationError):
            self.ref.action_prepare_video_prompt()
