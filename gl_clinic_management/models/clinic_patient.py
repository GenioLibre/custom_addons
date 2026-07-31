# -*- coding: utf-8 -*-

import re
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ClinicPatient(models.Model):
    _name = "gl.clinic.patient"
    _description = "Paciente"
    _order = "last_name, first_name"
    _check_company_auto = True

    internal_number = fields.Char(
        string="Número interno",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("Nuevo"),
        index=True,
    )
    first_name = fields.Char(string="Nombres", required=True)
    last_name = fields.Char(string="Apellidos", required=True)
    full_name = fields.Char(
        string="Nombre completo",
        compute="_compute_full_name",
        store=True,
        index=True,
    )
    document_number = fields.Char(
        string="DNI o documento de identidad",
        required=True,
        index=True,
    )
    birth_date = fields.Date(string="Fecha de nacimiento")
    age = fields.Integer(string="Edad", compute="_compute_age")
    phone = fields.Char(string="Teléfono")
    sex = fields.Selection(
        [
            ("male", "Masculino"),
            ("female", "Femenino"),
            ("other", "Otro"),
        ],
        string="Sexo",
    )
    district = fields.Char(string="Dirección", index=True)
    occupation = fields.Char(string="Ocupación")
    photo = fields.Image(string="Fotografía", max_width=1024, max_height=1024)
    active = fields.Boolean(string="Activo", default=True)
    registration_date = fields.Date(
        string="Fecha de registro",
        default=fields.Date.context_today,
        required=True,
        index=True,
    )
    medical_history_ids = fields.One2many(
        "gl.clinic.medical.history",
        "patient_id",
        string="Historias clínicas",
    )
    medical_history_count = fields.Integer(
        string="Cantidad de historias clínicas",
        compute="_compute_history_stats",
        store=True,
    )
    last_attention_date = fields.Datetime(
        string="Última fecha de atención",
        compute="_compute_history_stats",
        store=True,
    )
    internal_notes = fields.Text(string="Notas internas")
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    create_user_id = fields.Many2one(
        "res.users",
        string="Usuario que realizó el registro",
        default=lambda self: self.env.user,
        readonly=True,
    )

    _sql_constraints = [
        (
            "document_company_unique",
            "unique(document_number, company_id)",
            "Ya existe un paciente con este DNI o documento en la empresa.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("internal_number", _("Nuevo")) == _("Nuevo"):
                vals["internal_number"] = sequence.next_by_code(
                    "gl.clinic.patient"
                ) or _("Nuevo")
        return super().create(vals_list)

    @api.depends("first_name", "last_name")
    def _compute_full_name(self):
        for patient in self:
            patient.full_name = " ".join(
                part for part in [patient.first_name, patient.last_name] if part
            )

    @api.depends("birth_date")
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for patient in self:
            patient.age = (
                relativedelta(today, patient.birth_date).years
                if patient.birth_date
                else 0
            )

    @api.depends("medical_history_ids", "medical_history_ids.attention_date")
    def _compute_history_stats(self):
        for patient in self:
            histories = patient.medical_history_ids
            patient.medical_history_count = len(histories)
            patient.last_attention_date = histories[:1].attention_date if histories else False

    @api.constrains("birth_date")
    def _check_birth_date(self):
        today = fields.Date.context_today(self)
        for patient in self:
            if patient.birth_date and patient.birth_date > today:
                raise ValidationError(
                    _("La fecha de nacimiento no puede ser posterior a la fecha actual.")
                )

    @api.constrains("phone")
    def _check_phone(self):
        pattern = re.compile(r"^[0-9+\-\s()]*$")
        for patient in self:
            if patient.phone and not pattern.match(patient.phone):
                raise ValidationError(
                    _("El teléfono solo puede contener números, espacios, +, guiones y paréntesis.")
                )

    @api.depends("last_name", "first_name", "document_number")
    def _compute_display_name(self):
        for patient in self:
            name = "%s, %s" % (patient.last_name or "", patient.first_name or "")
            patient.display_name = "%s - %s" % (name.strip(", "), patient.document_number or "")

    def action_view_histories(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Historias clínicas de %s") % self.full_name,
            "res_model": "gl.clinic.medical.history",
            "view_mode": "list,form,calendar",
            "domain": [("patient_id", "=", self.id)],
            "context": {"default_patient_id": self.id},
        }

    def action_new_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Nueva historia clínica"),
            "res_model": "gl.clinic.medical.history",
            "view_mode": "form",
            "target": "current",
            "context": {"default_patient_id": self.id},
        }

    def action_open_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Paciente"),
            "res_model": "gl.clinic.patient",
            "view_mode": "form",
            "res_id": self.id,
        }
