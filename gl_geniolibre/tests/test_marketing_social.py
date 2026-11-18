# -*- coding: utf-8 -*-
"""Pruebas de prioridad de redes y prompts copiables sin realizar llamadas externas."""
import json

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGlMarketingSocial(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Cliente de prueba GL"})
        self.other_partner = self.env["res.partner"].create({"name": "Otro cliente GL"})
        self.research = self.env["gl.marketing.intelligence"].create({
            "name": "Investigación social", "partner_id": self.partner.id,
            "industry": "Educación vial",
        })

    def test_imports_only_owned_reports_and_selected_networks(self):
        Reports = self.env["gl.social.reports"]
        Reports.create({
            "partner_id": self.partner.id,
            "date_start": fields.Date.today(), "date_end": fields.Date.today(),
            "report_generated": True,
            "data_json": json.dumps({
                "redes": {
                    "facebook": {"reach": 1300, "impressions": 2100},
                    "instagram": {"followers": 250, "views": 400},
                    "tiktok": {"views": 1500},
                    "linkedin": {"clicks": 25},
                },
                "customer_phone": "555-1234",
            }),
        })
        Reports.create({
            "partner_id": self.other_partner.id,
            "data_json": json.dumps({"facebook": {"reach": 999999}}),
        })
        self.research.write({
            "discovery_sources": "owned", "social_facebook": True,
            "social_instagram": True, "social_tiktok": False, "social_linkedin": False,
        })
        first = self.research._run_collection()
        self.assertIn("2 referencias nuevas", first)
        refs = self.research.reference_ids
        self.assertEqual(set(refs.mapped("platform")), {"facebook", "instagram"})
        self.assertNotIn("999999", "\n".join(refs.mapped("notes")))
        self.assertNotIn("555-1234", "\n".join(refs.mapped("notes")))
        second = self.research._run_collection()
        self.assertIn("2 actualizadas", second)
        self.assertEqual(len(self.research.reference_ids), 2)

    def test_manual_prompt_and_social_scope_approval(self):
        reference = self.env["gl.marketing.reference"].create({
            "research_id": self.research.id,
            "name": "Reel Instagram",
            "kind": "competitor",
            "platform": "instagram",
            "url": "https://www.instagram.com/",
            "notes": "Portada con pregunta, observada por el equipo.",
        })
        self.research.action_prepare_prompt()
        self.assertIn("facebook, instagram, tiktok, linkedin", self.research.prompt)
        self.research.response_json = json.dumps({
            "resumen": "Una sola referencia; evidencia insuficiente para generalizar.",
            "hallazgos": [{"texto": "Referencia con pregunta en portada.", "fuentes": [reference.id]}],
            "oportunidades": [], "recomendaciones": [],
        })
        self.research.action_apply_report()
        self.research.action_approve()
        self.research.get_strategy_context(self.partner)
        self.research.social_tiktok = False
        with self.assertRaises(ValidationError):
            self.research.get_strategy_context(self.partner)

    def test_manual_prompts_remain_visible_in_both_modes(self):
        ResearchView = self.env.ref("gl_geniolibre.view_gl_marketing_intelligence_form")
        content = ResearchView.arch_db
        self.assertIn('name="action_prepare_prompt"', content)
        self.assertIn('name="action_apply_report"', content)
        self.assertIn('name="action_prepare_video_prompt"', content)
        self.assertIn('name="action_apply_video_analysis"', content)
        self.assertNotIn('invisible="direct_ai or state', content)
        self.assertNotIn('invisible="research_state != \'draft\' or direct_ai"', content)
