# -*- coding: utf-8 -*-
"""Pruebas sin red para la recopilación de tendencias y deduplicación."""
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.gl_geniolibre.models.gl_marketing_discovery import _parse_google_trends


@tagged("post_install", "-at_install")
class TestGlMarketingDiscovery(TransactionCase):

    def test_rss_requires_relevant_keyword(self):
        rss = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss><channel>
          <item><title>escuela de manejo</title>
          <link>https://trends.google.com/trending?geo=PE</link></item>
          <item><title>receta de cocina</title>
          <link>https://trends.google.com/trending?geo=PE</link></item>
        </channel></rss>"""
        result = _parse_google_trends(rss, "PE", ["manejo"], 10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "escuela de manejo")
        self.assertEqual(result[0]["source_origin"], "google_trends")

    def test_distinct_trends_can_share_trends_page_url(self):
        partner = self.env["res.partner"].create({"name": "Cliente de tendencias"})
        research = self.env["gl.marketing.intelligence"].create({
            "name": "Radar RSS", "partner_id": partner.id,
        })
        base = {
            "source_origin": "google_trends", "kind": "trend", "platform": "google",
            "url": "https://trends.google.com/trending?geo=PE",
            "observed_on": fields.Date.today(), "notes": "RSS público.",
        }
        created, refreshed = research._save_discovery([
            dict(base, external_id="a", name="tendencia uno"),
            dict(base, external_id="b", name="tendencia dos"),
        ])
        self.assertEqual((created, refreshed), (2, 0))
        self.assertEqual(len(research.reference_ids), 2)
        created, refreshed = research._save_discovery([
            dict(base, external_id="a", name="tendencia uno actualizada"),
        ])
        self.assertEqual((created, refreshed), (0, 1))
        self.assertEqual(len(research.reference_ids), 2)

    def test_weekly_collection_targets_research_model(self):
        cron = self.env.ref("gl_geniolibre.ir_cron_gl_marketing_discovery_weekly")
        self.assertIn("_cron_collect_marketing_research", cron.code)
