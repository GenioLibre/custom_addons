# -*- coding: utf-8 -*-

from odoo import api, fields, models


CONFIG_PARAM_WEB_WINDOW_TITLE = "web.base.title"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    web_window_title = fields.Char("Window Title")

    @api.model
    def get_values(self):
        res = super().get_values()
        web_window_title = self.env["ir.config_parameter"].sudo().get_param(
            CONFIG_PARAM_WEB_WINDOW_TITLE,
            default="",
        )
        res.update(web_window_title=web_window_title)
        return res

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            CONFIG_PARAM_WEB_WINDOW_TITLE,
            self.web_window_title or "",
        )
