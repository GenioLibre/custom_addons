from odoo import fields, models


class IemChurchPredio(models.Model):
    _name = "iem.church.predio"
    _description = "IEM Church Predio"

    name = fields.Char(required=True, index=True)
    pastor_id = fields.Many2one("res.partner", string="Pastor")
    phone = fields.Char()
    email = fields.Char()

    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_id = fields.Many2one("res.country.state")
    zip = fields.Char()
    country_id = fields.Many2one(
        "res.country",
        default=lambda self: self.env.company.country_id,
    )
    latitude = fields.Float(string="Latitud", digits=(10, 7))
    longitude = fields.Float(string="Longitud", digits=(10, 7))

    active = fields.Boolean(default=True)


class IemChurchRed(models.Model):
    _name = "iem.church.red"
    _description = "IEM Church Red"

    name = fields.Char(required=True, index=True)
    predio_id = fields.Many2one("iem.church.predio", required=True, ondelete="restrict")
    pastor_id = fields.Many2one("res.partner", string="Pastor / Obrero")
    active = fields.Boolean(default=True)


class IemChurchDiscipulado(models.Model):
    _name = "iem.church.discipulado"
    _description = "IEM Church Discipulado"

    name = fields.Char(required=True, index=True)
    red_id = fields.Many2one("iem.church.red", required=True, ondelete="restrict")
    discipulador_id = fields.Many2one("res.partner", string="Discipulador")
    active = fields.Boolean(default=True)


class IemChurchCelula(models.Model):
    _name = "iem.church.celula"
    _description = "IEM Church Celula"

    name = fields.Char(required=True, index=True)
    discipulado_id = fields.Many2one("iem.church.discipulado", required=True, ondelete="restrict")
    lider_id = fields.Many2one("res.partner", string="Lider de Celula")

    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_id = fields.Many2one("res.country.state")
    zip = fields.Char()
    country_id = fields.Many2one(
        "res.country",
        default=lambda self: self.env.company.country_id,
    )
    latitude = fields.Float(string="Latitud", digits=(10, 7))
    longitude = fields.Float(string="Longitud", digits=(10, 7))

    active = fields.Boolean(default=True)
