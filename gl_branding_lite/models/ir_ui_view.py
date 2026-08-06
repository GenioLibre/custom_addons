# -*- coding: utf-8 -*-

from odoo import api, models


class View(models.Model):
    _inherit = "ir.ui.view"

    @api.model
    def _render_template(self, template, values=None):
        if template in ["web.login", "web.webclient_bootstrap"]:
            values = dict(values or {})
            values["title"] = self.env["ir.config_parameter"].sudo().get_param("web.base.title", "")
        return super()._render_template(template, values)
