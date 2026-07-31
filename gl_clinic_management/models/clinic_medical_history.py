# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicMedicalHistory(models.Model):
    _name = "gl.clinic.medical.history"
    _description = "Historia clínica"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "attention_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Número de historia",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("Nuevo"),
        tracking=True,
        index=True,
    )
    patient_id = fields.Many2one(
        "gl.clinic.patient",
        string="Paciente",
        required=True,
        tracking=True,
        index=True,
        check_company=True,
    )
    patient_document_number = fields.Char(
        string="DNI",
        related="patient_id.document_number",
        store=True,
        index=True,
    )
    attention_date = fields.Datetime(
        string="Fecha y hora de atención",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        index=True,
    )
    doctor_id = fields.Many2one(
        "res.users",
        string="Médico responsable",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    height = fields.Float(string="Talla en metros", required=True, tracking=True)
    weight = fields.Float(string="Peso en kilogramos", required=True, tracking=True)
    bmi = fields.Float(string="IMC", compute="_compute_bmi", store=True)
    bmi_classification = fields.Char(
        string="Clasificación del IMC",
        compute="_compute_bmi",
        store=True,
    )
    consultation_reason = fields.Text(string="Motivo de la consulta", tracking=True)
    current_illness = fields.Text(string="Historia actual de la enfermedad", tracking=True)
    physical_exam = fields.Text(string="Examen físico", tracking=True)
    tests_results = fields.Text(string="Exámenes, imágenes y resultados", tracking=True)
    diagnosis = fields.Text(string="Diagnóstico", tracking=True)
    treatment_plan = fields.Text(string="Plan o tratamiento", tracking=True)
    medicine_ids = fields.Many2many(
        "gl.clinic.medicine",
        "gl_clinic_history_medicine_rel",
        "history_id",
        "medicine_id",
        string="Medicinas",
        tracking=True,
        check_company=True,
    )
    additional_notes = fields.Text(string="Notas adicionales")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "gl_clinic_history_ir_attachment_rel",
        "history_id",
        "attachment_id",
        string="Archivos adjuntos",
        copy=False,
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmada"),
            ("cancelled", "Cancelada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    confirmed_by_id = fields.Many2one(
        "res.users",
        string="Confirmada por",
        readonly=True,
        copy=False,
    )
    confirmed_at = fields.Datetime(
        string="Fecha de confirmación",
        readonly=True,
        copy=False,
    )
    diagnosis_summary = fields.Char(
        string="Diagnóstico resumido",
        compute="_compute_diagnosis_summary",
    )

    def _is_clinic_admin(self):
        return self.env.user.has_group(
            "gl_clinic_management.group_gl_clinic_admin"
        )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = sequence.next_by_code(
                    "gl.clinic.medical.history"
                ) or _("Nuevo")
        return super().create(vals_list)

    def write(self, vals):
        if (
            self.env.user.has_group("gl_clinic_management.group_gl_clinic_doctor")
            and not self._is_clinic_admin()
            and any(record.doctor_id != self.env.user for record in self)
        ):
            raise UserError(_("Solo puede editar historias asignadas a usted."))
        protected = self.filtered(lambda rec: rec.state == "confirmed")
        if protected and not self._is_clinic_admin():
            allowed = {"activity_ids", "message_follower_ids", "message_ids"}
            if set(vals) - allowed:
                raise UserError(
                    _("No puede editar una historia confirmada. Solicite permiso de administrador clínico.")
                )
        return super().write(vals)

    def unlink(self):
        if any(record.state == "confirmed" for record in self):
            raise UserError(_("No se pueden eliminar historias clínicas confirmadas."))
        return super().unlink()

    @api.depends("height", "weight")
    def _compute_bmi(self):
        for history in self:
            if history.height and history.weight:
                history.bmi = history.weight / (history.height ** 2)
                if history.bmi < 18.5:
                    history.bmi_classification = _("Bajo peso")
                elif history.bmi < 25:
                    history.bmi_classification = _("Normal")
                elif history.bmi < 30:
                    history.bmi_classification = _("Sobrepeso")
                else:
                    history.bmi_classification = _("Obesidad")
            else:
                history.bmi = 0.0
                history.bmi_classification = False

    @api.depends("diagnosis")
    def _compute_diagnosis_summary(self):
        for history in self:
            text = (history.diagnosis or "").strip().replace("\n", " ")
            history.diagnosis_summary = text[:80]

    @api.constrains("height", "weight")
    def _check_vital_values(self):
        for history in self:
            if history.height <= 0:
                raise ValidationError(_("La talla debe ser mayor que cero."))
            if history.weight <= 0:
                raise ValidationError(_("El peso debe ser mayor que cero."))

    def action_confirm(self):
        if not (
            self.env.user.has_group("gl_clinic_management.group_gl_clinic_doctor")
            or self._is_clinic_admin()
        ):
            raise UserError(_("Solo un médico o administrador clínico puede confirmar historias."))
        for history in self:
            if history.state != "draft":
                continue
            history.write({
                "state": "confirmed",
                "confirmed_by_id": self.env.user.id,
                "confirmed_at": fields.Datetime.now(),
            })

    def action_reset_to_draft(self):
        if not self._is_clinic_admin():
            raise UserError(_("Solo el administrador clínico puede volver historias a borrador."))
        self.write({"state": "draft", "confirmed_by_id": False, "confirmed_at": False})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_view_patient(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Paciente"),
            "res_model": "gl.clinic.patient",
            "view_mode": "form",
            "res_id": self.patient_id.id,
        }

    def _action_neighbor_history(self, operator, order):
        self.ensure_one()
        record = self.search(
            [
                ("patient_id", "=", self.patient_id.id),
                ("attention_date", operator, self.attention_date),
            ],
            order=order,
            limit=1,
        )
        if not record:
            raise UserError(_("No hay otra historia clínica para este paciente."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Historia clínica"),
            "res_model": "gl.clinic.medical.history",
            "view_mode": "form",
            "res_id": record.id,
        }

    def action_previous_history(self):
        return self._action_neighbor_history("<", "attention_date desc, id desc")

    def action_next_history(self):
        return self._action_neighbor_history(">", "attention_date asc, id asc")
