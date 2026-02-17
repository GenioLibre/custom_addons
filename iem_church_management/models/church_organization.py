from odoo import fields, models, api


class IemChurchPredio(models.Model):
    _name = "iem.church.predio"
    _description = "IEM Church Predio"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True, readonly=True, copy=False)
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

    _sql_constraints = [
        ("iem_church_predio_code_uniq", "unique(code)", "El codigo del predio debe ser unico."),
    ]

    @api.model
    def _next_code(self):
        count = self.search_count([])
        return f"P{count + 1:02d}"

    def _ensure_code(self):
        for predio in self:
            if not predio.code:
                predio.code = predio._next_code()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self._next_code()
        return super().create(vals_list)


class IemChurchRed(models.Model):
    _name = "iem.church.red"
    _description = "IEM Church Red"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True, readonly=True, copy=False)
    predio_id = fields.Many2one("iem.church.predio", required=True, ondelete="restrict")
    pastor_id = fields.Many2one("res.partner", string="Pastor / Obrero")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("iem_church_red_code_uniq", "unique(code)", "El codigo de la red debe ser unico."),
    ]

    def _next_code(self, predio):
        count = self.search_count([("predio_id", "=", predio.id)])
        return f"{predio.code}R{count + 1:02d}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("predio_id") and not vals.get("code"):
                predio = self.env["iem.church.predio"].browse(vals["predio_id"])
                predio._ensure_code()
                vals["code"] = self._next_code(predio)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "predio_id" in vals:
            for red in self.filtered(lambda r: not r.code and r.predio_id):
                red.predio_id._ensure_code()
                red.code = red._next_code(red.predio_id)
        return res


class IemChurchDiscipulado(models.Model):
    _name = "iem.church.discipulado"
    _description = "IEM Church Discipulado"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True, readonly=True, copy=False)
    red_id = fields.Many2one("iem.church.red", required=True, ondelete="restrict")
    discipulador_id = fields.Many2one("res.partner", string="Discipulador")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "iem_church_discipulado_code_uniq",
            "unique(code)",
            "El codigo del discipulado debe ser unico.",
        ),
    ]

    def _next_code(self, red):
        count = self.search_count([("red_id", "=", red.id)])
        return f"{red.code}D{count + 1:02d}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("red_id") and not vals.get("code"):
                red = self.env["iem.church.red"].browse(vals["red_id"])
                if not red.code and red.predio_id:
                    red.predio_id._ensure_code()
                    red.code = red._next_code(red.predio_id)
                vals["code"] = self._next_code(red)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "red_id" in vals:
            for discipulado in self.filtered(lambda d: not d.code and d.red_id):
                red = discipulado.red_id
                if not red.code and red.predio_id:
                    red.predio_id._ensure_code()
                    red.code = red._next_code(red.predio_id)
                discipulado.code = discipulado._next_code(red)
        return res


class IemChurchCelula(models.Model):
    _name = "iem.church.celula"
    _description = "IEM Church Celula"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True, readonly=True, copy=False)
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

    _sql_constraints = [
        ("iem_church_celula_code_uniq", "unique(code)", "El codigo de la celula debe ser unico."),
    ]

    def _next_code(self, discipulado):
        count = self.search_count([("discipulado_id", "=", discipulado.id)])
        return f"{discipulado.code}C{count + 1:02d}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("discipulado_id") and not vals.get("code"):
                discipulado = self.env["iem.church.discipulado"].browse(vals["discipulado_id"])
                if not discipulado.code and discipulado.red_id:
                    red = discipulado.red_id
                    if not red.code and red.predio_id:
                        red.predio_id._ensure_code()
                        red.code = red._next_code(red.predio_id)
                    discipulado.code = discipulado._next_code(red)
                vals["code"] = self._next_code(discipulado)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "discipulado_id" in vals:
            for celula in self.filtered(lambda c: not c.code and c.discipulado_id):
                discipulado = celula.discipulado_id
                if not discipulado.code and discipulado.red_id:
                    red = discipulado.red_id
                    if not red.code and red.predio_id:
                        red.predio_id._ensure_code()
                        red.code = red._next_code(red.predio_id)
                    discipulado.code = discipulado._next_code(red)
                celula.code = celula._next_code(discipulado)
        return res
