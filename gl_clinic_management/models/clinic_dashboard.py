# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class ClinicDashboard(models.Model):
    _name = "gl.clinic.dashboard"
    _description = "Panel de historias clínicas"

    name = fields.Char(string="Nombre", default="Panel")
    patient_count = fields.Integer(string="Total de pacientes", compute="_compute_stats")
    history_count = fields.Integer(string="Total de historias clínicas", compute="_compute_stats")
    today_history_count = fields.Integer(string="Historias registradas hoy", compute="_compute_stats")
    last_attention_date = fields.Datetime(string="Última atención registrada", compute="_compute_stats")
    patient_ids = fields.Many2many(
        "gl.clinic.patient",
        string="Pacientes",
        compute="_compute_patients",
    )

    def _get_company_domain(self):
        return [("company_id", "in", self.env.companies.ids)]

    @api.depends_context("allowed_company_ids")
    def _compute_stats(self):
        Patient = self.env["gl.clinic.patient"]
        History = self.env["gl.clinic.medical.history"]
        today_start = fields.Datetime.to_datetime(fields.Date.context_today(self))
        today_end = fields.Datetime.add(today_start, days=1)
        company_domain = self._get_company_domain()
        for dashboard in self:
            dashboard.patient_count = Patient.search_count(company_domain)
            dashboard.history_count = History.search_count(company_domain)
            dashboard.today_history_count = History.search_count(
                company_domain
                + [
                    ("attention_date", ">=", today_start),
                    ("attention_date", "<", today_end),
                ]
            )
            last_history = History.search(company_domain, order="attention_date desc", limit=1)
            dashboard.last_attention_date = last_history.attention_date

    @api.depends_context("allowed_company_ids")
    def _compute_patients(self):
        patients = self.env["gl.clinic.patient"].search(
            self._get_company_domain(),
            order="registration_date desc, id desc",
            limit=80,
        )
        for dashboard in self:
            dashboard.patient_ids = patients

    def action_open_patients(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Pacientes"),
            "res_model": "gl.clinic.patient",
            "view_mode": "list,form",
        }

    def action_open_histories(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Historias clínicas"),
            "res_model": "gl.clinic.medical.history",
            "view_mode": "list,form,calendar",
        }

    def action_new_patient(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Nuevo paciente"),
            "res_model": "gl.clinic.patient",
            "view_mode": "form",
            "target": "current",
        }

    def action_new_history(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Nueva historia clínica"),
            "res_model": "gl.clinic.medical.history",
            "view_mode": "form",
            "target": "current",
        }
