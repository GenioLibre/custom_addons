from odoo import fields, models


class IemChurchRole(models.Model):
    _name = "iem.church.role"
    _description = "IEM Church Role"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True, readonly=True, copy=False)
    active = fields.Boolean(default=True)
