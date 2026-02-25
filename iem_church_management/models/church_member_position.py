from odoo import fields, models


class IemChurchMemberPositionOption(models.Model):
    _name = "iem.church.member.position.option"
    _description = "IEM Member Position Option"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True)
    code = fields.Char(string="Codigo", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("iem_member_position_option_code_uniq", "unique(code)", "El codigo del cargo debe ser unico."),
    ]
