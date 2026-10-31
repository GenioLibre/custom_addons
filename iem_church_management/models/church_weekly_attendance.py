import io
from collections import defaultdict
from datetime import date, timedelta

import xlsxwriter

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
    total_members = fields.Integer(string="Miembros", compute="_compute_attendance_totals", store=True)
    total_attended_celula = fields.Integer(string="Asistencia a célula", compute="_compute_attendance_totals", store=True)
    total_attended_culto = fields.Integer(string="Asistencia al culto", compute="_compute_attendance_totals", store=True)
    total_attended_discipulado = fields.Integer(string="Asistencia al discipulado", compute="_compute_attendance_totals", store=True)
    total_tithed = fields.Integer(string="Diezmistas", compute="_compute_attendance_totals", store=True)

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

    @api.depends(
        "line_ids",
        "line_ids.attended_celula",
        "line_ids.attended_culto",
        "line_ids.attended_discipulado",
        "line_ids.tithed",
    )
    def _compute_attendance_totals(self):
        for rec in self:
            rec.total_members = len(rec.line_ids)
            rec.total_attended_celula = len(rec.line_ids.filtered("attended_celula"))
            rec.total_attended_culto = len(rec.line_ids.filtered("attended_culto"))
            rec.total_attended_discipulado = len(rec.line_ids.filtered("attended_discipulado"))
            rec.total_tithed = len(rec.line_ids.filtered("tithed"))

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

    @api.model
    def export_filtered_xlsx(self, domain=None, context=None):
        attendances = self.with_context(**(context or {})).search(
            domain or [], order="celula_id, week_start, id"
        )
        if not attendances:
            raise ValidationError(_("No hay registros para exportar con los filtros seleccionados."))

        weeks = sorted(
            {(rec.week_start, rec.week_end, rec.week_year, rec.week_number) for rec in attendances},
            key=lambda value: (value[0], value[3]),
        )
        by_cell = defaultdict(list)
        for rec in attendances:
            by_cell[rec.celula_id].append(rec)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("RED REDIMIDOS")
        worksheet.freeze_panes(7, 2)
        worksheet.hide_gridlines(2)
        title = workbook.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"})
        subtitle = workbook.add_format({"bold": True, "font_size": 12, "align": "center", "valign": "vcenter"})
        info = workbook.add_format({"bold": True, "font_size": 11, "align": "left", "valign": "vcenter"})
        cell_title = workbook.add_format({"bold": True, "bg_color": "#D9EAD3", "border": 1, "align": "left", "valign": "vcenter"})
        week_header = workbook.add_format({"bold": True, "bg_color": "#D9E2F3", "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        header = workbook.add_format({"bold": True, "bg_color": "#D9E2F3", "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        text = workbook.add_format({"border": 1, "valign": "vcenter"})
        center = workbook.add_format({"border": 1, "align": "center", "valign": "vcenter"})
        green = workbook.add_format({"border": 1, "align": "center", "bg_color": "#B6D7A8"})
        yellow = workbook.add_format({"border": 1, "align": "center", "bg_color": "#FFE599"})
        red = workbook.add_format({"border": 1, "align": "center", "bg_color": "#EA9999"})

        last_col = 1 + len(weeks) * 5
        worksheet.set_column(0, 0, 6)
        worksheet.set_column(1, 1, 34)
        worksheet.set_column(2, last_col, 13)
        row = 0
        worksheet.merge_range(row, 0, row, last_col, "RED REDIMIDOS", title)
        row += 1
        worksheet.merge_range(row, 0, row, last_col, "INFORME DE CELULA", subtitle)
        row += 1
        worksheet.merge_range(row, 0, row, last_col, f"MES: {self._export_period_label(weeks)}", info)
        row += 2

        for cell, cell_attendances in by_cell.items():
            worksheet.merge_range(row, 0, row, 1, f"CELULA {cell.name}", cell_title)
            for week_index, week in enumerate(weeks):
                start_col = 2 + week_index * 5
                worksheet.merge_range(row, start_col, row, start_col + 4, self._export_week_label(week), week_header)
            row += 1
            worksheet.merge_range(row, 0, row, last_col, f"LIDER: {cell.lider_id.name or ''}", info)
            row += 1
            worksheet.write(row, 0, "N°", header)
            worksheet.write(row, 1, "NOMBRE", header)
            attendance_by_week = {
                (rec.week_start, rec.week_end, rec.week_year, rec.week_number): rec
                for rec in cell_attendances
            }
            for week_index, week in enumerate(weeks):
                start_col = 2 + week_index * 5
                worksheet.merge_range(row, start_col, row, start_col + 2, "ASISTENCIA", header)
                worksheet.write(row, start_col + 3, "DIEZMO", header)
                worksheet.write(row, start_col + 4, "ESTADO 🟢 🟡 🔴", header)
            row += 1

            members = {}
            for attendance in cell_attendances:
                for line in attendance.line_ids:
                    members[line.member_id.id] = line.member_id
            ordered_members = sorted(
                members.values(),
                key=lambda member: (member.last_name or "", member.first_name or "", member.id),
            )
            for number, member in enumerate(ordered_members, 1):
                worksheet.write(row, 0, number, center)
                worksheet.write(row, 1, member.name, text)
                for week_index, week in enumerate(weeks):
                    start_col = 2 + week_index * 5
                    attendance = attendance_by_week.get(week)
                    line = attendance.line_ids.filtered(lambda item: item.member_id == member)[:1] if attendance else False
                    if line:
                        values = [line.attended_culto, line.attended_celula, line.attended_discipulado, line.tithed]
                        for offset, value in enumerate(values):
                            worksheet.write(row, start_col + offset, "✅" if value else "❌", center)
                        status_format = green if all(values) else yellow if any(values[:3]) else red
                        status = "🟢" if all(values) else "🟡" if any(values[:3]) else "🔴"
                        worksheet.write(row, start_col + 4, status, status_format)
                    else:
                        for offset in range(5):
                            worksheet.write_blank(row, start_col + offset, None, center)
                row += 1
            row += 3

        workbook.close()
        output.seek(0)
        return output.getvalue()

    @api.model
    def _export_period_label(self, weeks):
        months = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 9: "Setiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
        labels = {(fields.Date.to_date(week[0]).month, fields.Date.to_date(week[0]).year) for week in weeks}
        return ", ".join(f"{months[month]} {year}" for month, year in sorted(labels))

    @api.model
    def _export_week_label(self, week):
        start = fields.Date.to_date(week[0])
        end = fields.Date.to_date(week[1])
        return _("SEMANA %(week)s - %(start)s AL %(end)s") % {"week": rec_week_number(week[3]), "start": start.strftime("%d/%m/%Y"), "end": end.strftime("%d/%m/%Y")}

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
