from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademiaCursos(models.Model):
    _name = "academia.cursos"
    _description = "Academia Cursos"
    _order = "name"

    name = fields.Char(string="Nombre del curso", required=True)

    prerequisite_course_id = fields.Many2one(
        "academia.cursos",
        string="Prerequisito",
        domain="[('id', '!=', id)]",
    )

    duration_hours = fields.Integer(string="Duración (horas)")
    total_class_count = fields.Integer(string="Número de clases", compute="_compute_total_class_count")
    description = fields.Text(string="Descripción")

    materia_ids = fields.One2many("academia.materia", "curso_id", string="Materias")

    @api.depends("materia_ids.class_ids")
    def _compute_total_class_count(self):
        for rec in self:
            rec.total_class_count = sum(len(materia.class_ids) for materia in rec.materia_ids)

    @api.constrains("prerequisite_course_id")
    def _check_prerequisite_course(self):
        for rec in self:
            if rec.prerequisite_course_id and rec.prerequisite_course_id == rec:
                raise ValidationError(_("El prerequisito no puede ser el mismo curso."))

            visited = set()
            current = rec.prerequisite_course_id
            while current:
                if current.id in visited:
                    raise ValidationError(_("La cadena de prerequisitos tiene un ciclo."))
                visited.add(current.id)
                if current == rec:
                    raise ValidationError(_("La cadena de prerequisitos no puede volver al curso actual."))
                current = current.prerequisite_course_id

    @api.constrains("duration_hours")
    def _check_positive_values(self):
        for rec in self:
            if rec.duration_hours and rec.duration_hours < 0:
                raise ValidationError(_("La duración no puede ser negativa."))

    def action_view_materia(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Curso"),
            "res_model": "academia.cursos",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }


class AcademiaMateria(models.Model):
    _name = "academia.materia"
    _description = "Academia Materia"
    _order = "curso_id, sequence, name"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(default=10)

    curso_id = fields.Many2one("academia.cursos", string="Curso", required=True, ondelete="cascade")
    description = fields.Text(string="Descripción")

    planned_class_count = fields.Integer(string="Número de clases", compute="_compute_class_count")
    class_ids = fields.One2many("academia.materia.clase", "materia_id", string="Clases")

    _sql_constraints = [
        (
            "academia_materia_unique_name_per_course",
            "unique(curso_id, name)",
            "La materia ya existe para este curso.",
        )
    ]

    @api.depends("class_ids")
    def _compute_class_count(self):
        for rec in self:
            rec.planned_class_count = len(rec.class_ids)


class AcademiaMateriaClase(models.Model):
    _name = "academia.materia.clase"
    _description = "Academia Materia Clase"
    _order = "materia_id, id"

    materia_id = fields.Many2one("academia.materia", string="Materia", required=True, ondelete="cascade")
    name = fields.Char(string="Título", required=True)


class AcademiaPeriodoLectivo(models.Model):
    _name = "academia.periodo.lectivo"
    _description = "Academia Periodo Lectivo"
    _order = "start_date desc, id desc"

    name = fields.Char(string="Nombre", required=True)
    start_date = fields.Date(string="Fecha de inicio", required=True)
    end_date = fields.Date(string="Fecha de fin", required=True)
    description = fields.Text(string="Descripción")

    _sql_constraints = [
        (
            "academia_periodo_lectivo_name_unique",
            "unique(name)",
            "Ya existe un período lectivo con ese nombre.",
        )
    ]

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("La fecha de fin no puede ser menor a la fecha de inicio."))
