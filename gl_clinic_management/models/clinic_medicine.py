# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ClinicMedicine(models.Model):
    _name = "gl.clinic.medicine"
    _description = "Medicina"
    _order = "name"
    _check_company_auto = True

    code = fields.Char(string="Código", required=True, index=True)
    name = fields.Char(string="Nombre", required=True, index=True)
    notes = fields.Text(string="Notas")
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sql_constraints = [
        (
            "code_company_unique",
            "unique(code, company_id)",
            "El código de la medicina debe ser único por empresa.",
        ),
    ]

    @api.depends("name")
    def _compute_display_name(self):
        for medicine in self:
            medicine.display_name = medicine.name
