from urllib.parse import quote_plus

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    _sql_constraints = [
        (
            "unique_document_type_vat",
            "unique(l10n_latam_identification_type_id, vat)",
            "El documento ya esta registrado en otro contacto.",
        ),
    ]

    country_id = fields.Many2one(
        "res.country",
        default=lambda self: self.env["res.country"].search([("code", "=", "PE")], limit=1)
        or self.env.company.country_id,
    )
    is_member = fields.Boolean(string="Es Miembro de la Iglesia")
    gender = fields.Selection(
        [
            ("male", "Masculino"),
            ("female", "Femenino"),
        ],
        string="Sexo",
    )
    def unlink(self):
        if not self.env.context.get("skip_church_member_partner_cleanup"):
            members = self.env["church.member"].search([("partner_id", "in", self.ids)])
            if members:
                members.with_context(skip_church_member_partner_cleanup=True).unlink()
        return super().unlink()
    role_id = fields.Many2one("iem.church.role", string="Rol/Cargo")
    predio_id = fields.Many2one("iem.church.predio", string="Predio")
    red_id = fields.Many2one("iem.church.red", string="Red")
    discipulado_id = fields.Many2one("iem.church.discipulado", string="Discipulado")
    celula_id = fields.Many2one("iem.church.celula", string="Celula")
    membership_date = fields.Date(string="Fecha ingreso")
    district = fields.Char(string="Distrito")
    maps_url = fields.Char(
        string="Mapa",
        compute="_compute_maps_url",
        inverse="_inverse_maps_url",
        store=True,
    )
    maps_url_manual = fields.Boolean(default=False)

    def _compute_maps_url(self):
        for partner in self:
            if partner.maps_url_manual and partner.maps_url:
                continue
            parts = [
                partner.street,
                partner.city,
                partner.district,
                partner.state_id and partner.state_id.name or None,
                partner.country_id and partner.country_id.name or None,
            ]
            address = ", ".join([part for part in parts if part])
            partner.maps_url = (
                f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}"
                if address
                else False
            )

    def _inverse_maps_url(self):
        for partner in self:
            if partner.maps_url:
                partner.maps_url_manual = True

    @api.constrains("predio_id", "red_id", "discipulado_id", "celula_id")
    def _check_membership_chain(self):
        for partner in self:
            if partner.red_id and partner.predio_id and partner.red_id.predio_id != partner.predio_id:
                raise ValidationError(_("La Red no pertenece al Predio seleccionado."))
            if (
                partner.discipulado_id
                and partner.red_id
                and partner.discipulado_id.red_id != partner.red_id
            ):
                raise ValidationError(_("El Discipulado no pertenece a la Red seleccionada."))
            if (
                partner.celula_id
                and partner.discipulado_id
                and partner.celula_id.discipulado_id != partner.discipulado_id
            ):
                raise ValidationError(_("La Celula no pertenece al Discipulado seleccionado."))
