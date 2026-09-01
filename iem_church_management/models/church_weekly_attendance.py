from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class IemChurchWeeklyAttendance(models.Model):
    _name = "iem.church.weekly.attendance"
    _description = "IEM Asistencia Semanal"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "week_start desc, celula_id"

    name = fields.Char(string="Referencia", compute="_compute_name", store=True)
    celula_id = fields.Many2one("iem.church.celula", string="Célula", required=True, ondelete="restrict", tracking=True)
    week_year = fields.Integer(string="Año", required=True, tracking=True)
    week_number = fields.Integer(string="Semana", required=True, tracking=True)
    week_start = fields.Date(string="Inicio de semana", required=True, tracking=True)
    week_end = fields.Date(string="Fin de semana", required=True, tracking=True)
    predio_id = fields.Many2one(
        "iem.church.predio",
        string="Predio",
        related="celula_id.discipulado_id.red_id.predio_id",
        store=True,
        readonly=True,
    )
    red_id = fields.Many2one(
        "iem.church.red",
        string="Red",
        related="celula_id.discipulado_id.red_id",
        store=True,
        readonly=True,
    )
    discipulado_id = fields.Many2one(
        "iem.church.discipulado",
        string="Discipulado",
        related="celula_id.discipulado_id",
        store=True,
        readonly=True,
    )
    line_ids = fields.One2many("iem.church.weekly.attendance.line", "attendance_id", string="Miembros")

    _sql_constraints = [
        (
            "iem_weekly_attendance_unique_celula_week",
            "unique(celula_id, week_year, week_number)",
            "Ya existe un registro de asistencia para esta célula y semana.",
        ),
    ]

    @api.depends("celula_id", "week_year", "week_number", "week_start", "week_end")
    def _compute_name(self):
        for rec in self:
            if rec.celula_id and rec.week_year and rec.week_number and rec.week_start and rec.week_end:
                rec.name = "%s - %s" % (rec.celula_id.display_name, rec._format_week_label())
            else:
                rec.name = _("Asistencia semanal")

    def _format_week_label(self):
        self.ensure_one()
        return _("Semana %(week)s / Año %(year)s / del %(start)s al %(end)s") % {
            "week": rec_week_number(self.week_number),
            "year": self.week_year,
            "start": self._format_short_date(self.week_start),
            "end": self._format_short_date(self.week_end),
        }

    def _format_short_date(self, value):
        date_value = fields.Date.to_date(value)
        month_names = {
            1: _("Ene"),
            2: _("Feb"),
            3: _("Mar"),
            4: _("Abr"),
            5: _("May"),
            6: _("Jun"),
            7: _("Jul"),
            8: _("Ago"),
            9: _("Sep"),
            10: _("Oct"),
            11: _("Nov"),
            12: _("Dic"),
        }
        return "%02d %s" % (date_value.day, month_names[date_value.month])

    @api.constrains("week_number", "week_year", "week_start", "week_end")
    def _check_week_values(self):
        for rec in self:
            if rec.week_number < 1 or rec.week_number > 53:
                raise ValidationError(_("La semana debe estar entre 1 y 53."))
            if rec.week_year < 1900:
                raise ValidationError(_("El año no es válido."))
            if rec.week_start and rec.week_end and rec.week_end < rec.week_start:
                raise ValidationError(_("La fecha final no puede ser menor que la fecha inicial."))

    @api.model
    def week_values_from_iso(self, week_key):
        year_text, week_text = (week_key or "").split("-W", 1)
        year = int(year_text)
        week = int(week_text)
        week_start = date.fromisocalendar(year, week, 1)
        week_end = week_start + timedelta(days=6)
        return {
            "week_year": year,
            "week_number": week,
            "week_start": week_start,
            "week_end": week_end,
        }

    @api.model
    def format_week_label_from_values(self, vals):
        rec = self.new(vals)
        return rec._format_week_label()

    def ensure_member_lines(self):
        member_model = self.env["church.member"].sudo()
        for rec in self:
            members = member_model.search(
                [
                    ("celula_id", "=", rec.celula_id.id),
                    ("member_status", "=", "active"),
                ],
                order="last_name asc, first_name asc, id asc",
            )
            existing_member_ids = set(rec.line_ids.mapped("member_id").ids)
            commands = [
                (
                    0,
                    0,
                    {
                        "member_id": member.id,
                    },
                )
                for member in members
                if member.id not in existing_member_ids
            ]
            if commands:
                rec.write({"line_ids": commands})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.ensure_member_lines()
        return records


def rec_week_number(week_number):
    return str(week_number).zfill(2)


class IemChurchWeeklyAttendanceLine(models.Model):
    _name = "iem.church.weekly.attendance.line"
    _description = "IEM Asistencia Semanal Línea"
    _order = "member_name, id"

    attendance_id = fields.Many2one(
        "iem.church.weekly.attendance",
        string="Asistencia",
        required=True,
        ondelete="cascade",
    )
    member_id = fields.Many2one("church.member", string="Miembro", required=True, ondelete="restrict")
    member_name = fields.Char(string="Nombre", related="member_id.name", store=True, readonly=True)
    celula_id = fields.Many2one("iem.church.celula", string="Célula", related="attendance_id.celula_id", store=True, readonly=True)
    attended_celula = fields.Boolean(string="Asistió a célula")
    attended_discipulado = fields.Boolean(string="Asistió a discipulado")
    attended_culto = fields.Boolean(string="Asistió al culto")
    tithed = fields.Boolean(string="Diezmó")

    _sql_constraints = [
        (
            "iem_weekly_attendance_line_unique_member",
            "unique(attendance_id, member_id)",
            "El miembro ya está registrado en esta asistencia semanal.",
        ),
    ]
