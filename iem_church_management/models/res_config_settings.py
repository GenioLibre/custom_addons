from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dni_api_token = fields.Char(
        string="Token API DNI",
        config_parameter="iem.dni_api_token",
    )
