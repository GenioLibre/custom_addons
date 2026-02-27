from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AcademiaInscripcion(models.Model):
    _name = "academia.inscripcion"
    _description = "Academia Inscripción"
    _order = "start_date desc, id desc"

    STAGE_SELECTION = [
        ("inscripcion", "Inscripción"),
        ("en_curso", "En curso"),
        ("finalizado", "Finalizado"),
    ]

    name = fields.Char(string="Nombre", required=True)
    curso_id = fields.Many2one("academia.cursos", string="Curso", required=True, ondelete="restrict")
    periodo_lectivo_id = fields.Many2one("academia.periodo.lectivo", string="Período lectivo", ondelete="restrict")

    start_date = fields.Date(string="Fecha de inicio", required=True, default=fields.Date.context_today)
    stage = fields.Selection(STAGE_SELECTION, string="Etapa", required=True, default="inscripcion")

    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    amount = fields.Monetary(string="Monto", currency_field="currency_id", required=True)
    capacity = fields.Integer(string="Cupos")

    line_ids = fields.One2many("academia.inscripcion.member", "inscripcion_id", string="Inscritos")
    member_ids = fields.Many2many(
        "church.member",
        string="Inscritos (compatibilidad)",
        compute="_compute_member_ids",
        inverse="_inverse_member_ids",
    )
    enrolled_count = fields.Integer(string="Inscritos", compute="_compute_enrolled_count")

    @api.depends("line_ids")
    def _compute_enrolled_count(self):
        for rec in self:
            rec.enrolled_count = len(rec.line_ids)

    @api.depends("line_ids.member_id")
    def _compute_member_ids(self):
        for rec in self:
            rec.member_ids = rec.line_ids.mapped("member_id")

    def _inverse_member_ids(self):
        for rec in self:
            current_members = rec.line_ids.mapped("member_id")
            target_members = rec.member_ids

            to_add = target_members - current_members
            to_remove = current_members - target_members

            for member in to_add:
                self.env["academia.inscripcion.member"].create(
                    {
                        "inscripcion_id": rec.id,
                        "member_id": member.id,
                    }
                )

            lines_to_remove = rec.line_ids.filtered(lambda line: line.member_id in to_remove)
            if lines_to_remove:
                lines_to_remove.unlink()

    @api.constrains("amount", "capacity")
    def _check_non_negative_values(self):
        for rec in self:
            if rec.amount and rec.amount < 0:
                raise ValidationError(_("El monto no puede ser negativo."))
            if rec.capacity and rec.capacity < 0:
                raise ValidationError(_("Los cupos no pueden ser negativos."))

    def action_close_enrollment(self):
        for rec in self:
            rec.stage = "en_curso"
        return True

    def action_back_to_enrollment(self):
        for rec in self:
            rec.stage = "inscripcion"
        return True


class AcademiaInscripcionMember(models.Model):
    _name = "academia.inscripcion.member"
    _description = "Academia Inscripción Miembro"
    _order = "id desc"

    SITUATION_SELECTION = [
        ("regular", "Regular"),
        ("inasistencia", "Inasistencia"),
        ("removido", "Removido"),
    ]
    STUDENT_TYPE_SELECTION = [
        ("presencial", "Presencial"),
        ("virtual", "Virtual"),
    ]

    inscripcion_id = fields.Many2one("academia.inscripcion", string="Inscripción", required=True, ondelete="cascade")
    member_id = fields.Many2one("church.member", string="Miembro", required=True, ondelete="restrict")
    predio_id = fields.Many2one("iem.church.predio", string="Predio", related="member_id.predio_id", store=True, readonly=True)
    red_id = fields.Many2one("iem.church.red", string="Red", related="member_id.red_id", store=True, readonly=True)
    discipulado_id = fields.Many2one(
        "iem.church.discipulado", string="Discipulado", related="member_id.discipulado_id", store=True, readonly=True
    )
    situation = fields.Selection(SITUATION_SELECTION, string="Situación", default="regular", required=True)
    student_type = fields.Selection(STUDENT_TYPE_SELECTION, string="Tipo de estudiante", default="presencial", required=True)

    _sql_constraints = [
        (
            "academia_inscripcion_member_unique",
            "unique(inscripcion_id, member_id)",
            "El miembro ya está inscrito en esta inscripción.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            inscripcion_id = vals.get("inscripcion_id")
            if not inscripcion_id:
                continue
            inscripcion = self.env["academia.inscripcion"].browse(inscripcion_id)
            if inscripcion.stage != "inscripcion":
                raise ValidationError(_("No se pueden agregar estudiantes cuando la inscripción está en curso o finalizada."))
        return super().create(vals_list)
