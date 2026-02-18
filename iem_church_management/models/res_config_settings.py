from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dni_api_token = fields.Char(
        string="Token API DNI",
        config_parameter="iem.dni_api_token",
    )
    public_member_form_password = fields.Char(
        string="Clave formulario publico",
        config_parameter="iem.public_member_form_password",
    )
    public_member_form_rate_limit = fields.Integer(
        string="Limite de envios (segundos)",
        default=60,
        config_parameter="iem.public_member_form_rate_limit",
    )
