from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademiaAsistencia(models.Model):
    _name = "academia.asistencia"
    _description = "Academia Asistencia"
    _order = "attendance_date desc, id desc"

    name = fields.Char(string="Referencia", readonly=True, copy=False)
    attendance_date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today)

    inscripcion_id = fields.Many2one(
        "academia.inscripcion",
        string="Inscripción",
        required=True,
        ondelete="restrict",
        domain="[('stage', '=', 'en_curso')]",
    )
    curso_id = fields.Many2one("academia.cursos", string="Curso", related="inscripcion_id.curso_id", store=True, readonly=True)
    materia_id = fields.Many2one(
        "academia.materia",
        string="Materia",
        required=True,
        ondelete="restrict",
        domain="[('curso_id', '=', curso_id)]",
    )
    clase_id = fields.Many2one(
        "academia.materia.clase",
        string="Clase",
        required=True,
        ondelete="restrict",
        domain="[('materia_id', '=', materia_id)]",
    )

    line_ids = fields.One2many("academia.asistencia.line", "asistencia_id", string="Asistencia")

    _sql_constraints = [
        (
            "academia_asistencia_unique_session",
            "unique(inscripcion_id, materia_id, clase_id)",
            "Ya existe un cuadro de asistencia para esta inscripción, materia y clase.",
        )
    ]

    @api.constrains("inscripcion_id", "materia_id", "clase_id")
    def _check_integrity_and_hierarchy(self):
        for rec in self:
            if rec.inscripcion_id.stage != "en_curso":
                raise ValidationError(_("Solo se puede crear asistencia para cursos en etapa 'En curso'."))

            if rec.materia_id.curso_id != rec.curso_id:
                raise ValidationError(_("La materia no corresponde al curso seleccionado."))

            if rec.clase_id.materia_id != rec.materia_id:
                raise ValidationError(_("La clase no corresponde a la materia seleccionada."))

            ordered_class_ids = rec.materia_id.class_ids.sorted("id").ids
            if rec.clase_id.id not in ordered_class_ids:
                raise ValidationError(_("La clase seleccionada no pertenece a la materia."))

            target_pos = ordered_class_ids.index(rec.clase_id.id)

            previous = self.search(
                [
                    ("id", "!=", rec.id),
                    ("inscripcion_id", "=", rec.inscripcion_id.id),
                    ("materia_id", "=", rec.materia_id.id),
                ]
            )
            if previous:
                max_pos = max(
                    ordered_class_ids.index(prev.clase_id.id)
                    for prev in previous
                    if prev.clase_id.id in ordered_class_ids
                )
                expected_pos = max_pos + 1
            else:
                expected_pos = 0

            if target_pos != expected_pos:
                expected_class = rec.materia_id.class_ids.sorted("id")[expected_pos]
                raise ValidationError(
                    _(
                        "Secuencia inválida. La siguiente clase permitida para esta materia es: %(class)s"
                    )
                    % {"class": expected_class.name}
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name:
                rec.name = _("%s - %s - %s") % (
                    rec.curso_id.name,
                    rec.materia_id.name,
                    rec.clase_id.name,
                )

            if not rec.line_ids and rec.inscripcion_id.line_ids:
                lines = [
                    (
                        0,
                        0,
                        {
                            "member_id": line.member_id.id,
                        },
                    )
                    for line in rec.inscripcion_id.line_ids
                ]
                rec.write({"line_ids": lines})

        return records


class AcademiaAsistenciaLine(models.Model):
    _name = "academia.asistencia.line"
    _description = "Academia Asistencia Línea"
    _order = "id"

    asistencia_id = fields.Many2one("academia.asistencia", string="Cuadro", required=True, ondelete="cascade")
    member_id = fields.Many2one("church.member", string="Miembro", required=True, ondelete="restrict")

    predio_id = fields.Many2one("iem.church.predio", string="Predio", related="member_id.predio_id", store=True, readonly=True)
    red_id = fields.Many2one("iem.church.red", string="Red", related="member_id.red_id", store=True, readonly=True)
    discipulado_id = fields.Many2one(
        "iem.church.discipulado", string="Discipulado", related="member_id.discipulado_id", store=True, readonly=True
    )

    present = fields.Boolean(string="Asistió")
    note = fields.Char(string="Observación")

    _sql_constraints = [
        (
            "academia_asistencia_line_unique_member",
            "unique(asistencia_id, member_id)",
            "El miembro ya está registrado en este cuadro de asistencia.",
        )
    ]
