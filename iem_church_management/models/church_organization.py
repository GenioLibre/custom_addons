from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IemChurchOrganizationMixin(models.AbstractModel):
    _name = "iem.church.organization.mixin"
    _description = "IEM Church Organization Mixin"

    def _member_dependency_message(self):
        self.ensure_one()
        return _("No se puede eliminar porque existen miembros registrados.")

    def _dependency_specs(self):
        return []

    def _check_unlink_dependencies(self):
        for rec in self:
            for model_name, field_name, message in rec._dependency_specs():
                if self.env[model_name].search_count([(field_name, "=", rec.id)]):
                    raise UserError(message or rec._member_dependency_message())


class IemChurchPredio(models.Model):
    _inherit = "iem.church.organization.mixin"
    _name = "iem.church.predio"
    _description = "IEM Church Predio"

    name = fields.Char(required=True, index=True)
    pastor_id = fields.Many2one("res.partner", string="Pastor(a)")
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

    def _dependency_specs(self):
        return [
            ("iem.church.red", "predio_id", _("No se puede eliminar el predio porque existen redes relacionadas.")),
            ("church.member", "predio_id", _("No se puede eliminar el predio porque existen miembros registrados.")),
            ("res.partner", "predio_id", _("No se puede eliminar el predio porque existen contactos registrados.")),
            ("iem.financial.contribution", "predio_id", _("No se puede eliminar el predio porque existen contribuciones registradas.")),
            ("iem.church.member.list", "predio_id", _("No se puede eliminar el predio porque existen listas relacionadas.")),
            ("academia.inscripcion.member", "predio_id", _("No se puede eliminar el predio porque existen inscripciones relacionadas.")),
            ("academia.asistencia.line", "predio_id", _("No se puede eliminar el predio porque existen asistencias relacionadas.")),
        ]

    def unlink(self):
        self._check_unlink_dependencies()
        return super().unlink()

    def action_view_map(self):
        self.ensure_one()
        if self.latitude is False or self.longitude is False:
            raise UserError(_("Debe definir latitud y longitud para ver el mapa."))
        url = f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}


class IemChurchRed(models.Model):
    _inherit = "iem.church.organization.mixin"
    _name = "iem.church.red"
    _description = "IEM Church Red"

    name = fields.Char(required=True, index=True)
    predio_id = fields.Many2one("iem.church.predio", required=True, ondelete="restrict")
    pastor_id = fields.Many2one("res.partner", string="Pastor(a) / Obrero(a)")
    active = fields.Boolean(default=True)

    def _dependency_specs(self):
        return [
            ("iem.church.discipulado", "red_id", _("No se puede eliminar la red porque existen discipulados relacionados.")),
            ("church.member", "red_id", _("No se puede eliminar la red porque existen miembros registrados.")),
            ("res.partner", "red_id", _("No se puede eliminar la red porque existen contactos registrados.")),
            ("iem.financial.contribution", "red_id", _("No se puede eliminar la red porque existen contribuciones registradas.")),
            ("iem.church.member.list", "red_id", _("No se puede eliminar la red porque existen listas relacionadas.")),
            ("academia.inscripcion.member", "red_id", _("No se puede eliminar la red porque existen inscripciones relacionadas.")),
            ("academia.asistencia.line", "red_id", _("No se puede eliminar la red porque existen asistencias relacionadas.")),
        ]

    def write(self, vals):
        res = super().write(vals)
        if "predio_id" in vals:
            for rec in self:
                celulas = self.env["iem.church.celula"].search(
                    [("discipulado_id.red_id", "=", rec.id)]
                )
                if celulas:
                    celulas.write({"form_predio_id": rec.predio_id.id})
                members = self.env["church.member"].search([("red_id", "=", rec.id)])
                if members:
                    members.write({"predio_id": rec.predio_id.id})
        return res

    def unlink(self):
        self._check_unlink_dependencies()
        return super().unlink()


class IemChurchDiscipulado(models.Model):
    _inherit = "iem.church.organization.mixin"
    _name = "iem.church.discipulado"
    _description = "IEM Church Discipulado"

    name = fields.Char(required=True, index=True)
    red_id = fields.Many2one("iem.church.red", required=True, ondelete="restrict")
    discipulador_id = fields.Many2one("res.partner", string="Discipulador(a)")
    active = fields.Boolean(default=True)

    def _dependency_specs(self):
        return [
            ("iem.church.celula", "discipulado_id", _("No se puede eliminar el discipulado porque existen células relacionadas.")),
            ("church.member", "discipulado_id", _("No se puede eliminar el discipulado porque existen miembros registrados.")),
            ("res.partner", "discipulado_id", _("No se puede eliminar el discipulado porque existen contactos registrados.")),
            ("iem.financial.contribution", "discipulado_id", _("No se puede eliminar el discipulado porque existen contribuciones registradas.")),
            ("iem.church.member.list", "discipulado_id", _("No se puede eliminar el discipulado porque existen listas relacionadas.")),
            ("academia.inscripcion.member", "discipulado_id", _("No se puede eliminar el discipulado porque existen inscripciones relacionadas.")),
            ("academia.asistencia.line", "discipulado_id", _("No se puede eliminar el discipulado porque existen asistencias relacionadas.")),
        ]

    def write(self, vals):
        res = super().write(vals)
        if "red_id" in vals:
            for rec in self:
                celulas = self.env["iem.church.celula"].search([("discipulado_id", "=", rec.id)])
                if celulas:
                    celulas.write(
                        {
                            "form_red_id": rec.red_id.id,
                            "form_predio_id": rec.red_id.predio_id.id,
                        }
                    )
                members = self.env["church.member"].search([("discipulado_id", "=", rec.id)])
                if members:
                    members.write(
                        {
                            "predio_id": rec.red_id.predio_id.id,
                            "red_id": rec.red_id.id,
                        }
                    )
        return res

    def unlink(self):
        self._check_unlink_dependencies()
        return super().unlink()


class IemChurchCelula(models.Model):
    _inherit = "iem.church.organization.mixin"
    _name = "iem.church.celula"
    _description = "IEM Church Célula"

    name = fields.Char(required=True, index=True)
    form_predio_id = fields.Many2one("iem.church.predio", string="Predio")
    form_red_id = fields.Many2one("iem.church.red", string="Red")
    discipulado_id = fields.Many2one("iem.church.discipulado", required=True, ondelete="restrict")
    lider_id = fields.Many2one("res.partner", string="Líder de Célula")

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

    @api.onchange("form_predio_id")
    def _onchange_form_predio_id(self):
        for rec in self:
            if rec.form_red_id and rec.form_red_id.predio_id != rec.form_predio_id:
                rec.form_red_id = False
            if rec.discipulado_id and rec.discipulado_id.red_id.predio_id != rec.form_predio_id:
                rec.discipulado_id = False

    @api.onchange("form_red_id")
    def _onchange_form_red_id(self):
        for rec in self:
            if rec.form_red_id and rec.form_predio_id != rec.form_red_id.predio_id:
                rec.form_predio_id = rec.form_red_id.predio_id
            if rec.discipulado_id and rec.discipulado_id.red_id != rec.form_red_id:
                rec.discipulado_id = False

    @api.onchange("discipulado_id")
    def _onchange_discipulado_id_sync_filters(self):
        for rec in self:
            if rec.discipulado_id:
                rec.form_red_id = rec.discipulado_id.red_id
                rec.form_predio_id = rec.discipulado_id.red_id.predio_id

    @api.constrains("discipulado_id", "form_red_id", "form_predio_id")
    def _check_structure_filters(self):
        for rec in self:
            if rec.form_red_id and rec.discipulado_id and rec.discipulado_id.red_id != rec.form_red_id:
                raise UserError(_("El discipulado no pertenece a la red seleccionada."))
            if (
                rec.form_predio_id
                and rec.discipulado_id
                and rec.discipulado_id.red_id.predio_id != rec.form_predio_id
            ):
                raise UserError(_("El discipulado no pertenece al predio seleccionado."))

    def _dependency_specs(self):
        return [
            ("church.member", "celula_id", _("No se puede eliminar la célula porque existen miembros registrados.")),
            ("res.partner", "celula_id", _("No se puede eliminar la célula porque existen contactos registrados.")),
            ("iem.church.member.list", "celula_id", _("No se puede eliminar la célula porque existen listas relacionadas.")),
        ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            discipulado_id = vals.get("discipulado_id")
            if discipulado_id:
                discipulado = self.env["iem.church.discipulado"].browse(discipulado_id)
                vals["form_red_id"] = discipulado.red_id.id
                vals["form_predio_id"] = discipulado.red_id.predio_id.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "discipulado_id" in vals:
            for rec in self:
                rec.form_red_id = rec.discipulado_id.red_id.id
                rec.form_predio_id = rec.discipulado_id.red_id.predio_id.id
                members = self.env["church.member"].search([("celula_id", "=", rec.id)])
                if members:
                    members.write(
                        {
                            "predio_id": rec.discipulado_id.red_id.predio_id.id,
                            "red_id": rec.discipulado_id.red_id.id,
                            "discipulado_id": rec.discipulado_id.id,
                        }
                    )
        return res

    def unlink(self):
        self._check_unlink_dependencies()
        return super().unlink()

    def action_view_map(self):
        self.ensure_one()
        if self.latitude is False or self.longitude is False:
            raise UserError(_("Debe definir latitud y longitud para ver el mapa."))
        url = f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}
