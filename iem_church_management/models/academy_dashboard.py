from odoo import fields, models, _


class IemAcademyDashboard(models.Model):
    _name = "iem.academy.dashboard"
    _description = "IEM Academy Dashboard"

    name = fields.Char(string="Nombre", required=True)
    demo_enrollment_count = fields.Integer(string="Inscripciones del mes", default=128, readonly=True)
    demo_attendance_rate = fields.Float(string="Asistencia promedio", default=87.5, readonly=True)
    demo_pending_payments = fields.Integer(string="Mensualidades pendientes", default=34, readonly=True)
    demo_teachers_count = fields.Integer(string="Maestros activos", default=16, readonly=True)

    def _coming_soon_action(self, title):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": _("Este módulo se habilitará en la siguiente fase."),
                "type": "info",
                "sticky": False,
            },
        }

    def action_open_enrollment(self):
        self.ensure_one()
        return self.env.ref("iem_church_management.academia_action_inscripcion").read()[0]

    def action_open_courses(self):
        self.ensure_one()
        return self.env.ref("iem_church_management.academia_action_cursos").read()[0]

    def action_open_attendance(self):
        self.ensure_one()
        return self.env.ref("iem_church_management.academia_action_asistencia").read()[0]

    def action_open_monthly_fees(self):
        return self._coming_soon_action(_("Mensualidades"))

    def action_open_teacher_schedule(self):
        return self._coming_soon_action(_("Escala de maestros"))

    def action_reports_dropdown_placeholder(self):
        return True

    def action_report_attendance_placeholder(self):
        return True
