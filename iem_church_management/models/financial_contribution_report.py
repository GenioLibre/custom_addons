import base64
import io

import xlsxwriter
from markupsafe import escape

from odoo import _, api, fields, models


class IemFinancialContributionReportMixin(models.AbstractModel):
    _name = "iem.financial.contribution.report.mixin"
    _description = "IEM Financial Contribution Report Mixin"

    MONTH_HEADERS = [
        (1, _("Enero")),
        (2, _("Febrero")),
        (3, _("Marzo")),
        (4, _("Abril")),
        (5, _("Mayo")),
        (6, _("Junio")),
        (7, _("Julio")),
        (8, _("Agosto")),
        (9, _("Septiembre")),
        (10, _("Octubre")),
        (11, _("Noviembre")),
        (12, _("Diciembre")),
    ]

    @api.model
    def _default_report_year(self):
        return fields.Date.context_today(self).year

    @api.model
    def _report_domain(self, year, contribution_type_ids=None):
        domain = [
            ("state", "=", "confirmed"),
            ("contribution_year", "=", year),
            ("member_id", "!=", False),
        ]
        if contribution_type_ids:
            domain.append(("contribution_type_id", "in", contribution_type_ids))
        return domain

    @api.model
    def _get_report_payload(self, year, contribution_type_ids=None):
        records = self.env["iem.financial.contribution"].search_read(
            self._report_domain(year, contribution_type_ids=contribution_type_ids),
            ["predio_id", "red_id", "member_id", "contribution_month", "amount", "contribution_type_id"],
            order="predio_id, red_id, member_id, contribution_month, id",
        )

        predio_map = {}
        total_by_month = {month: 0.0 for month, _label in self.MONTH_HEADERS}
        member_count = 0

        for rec in records:
            member_value = rec.get("member_id")
            if not member_value:
                continue

            predio_value = rec.get("predio_id") or [0, _("Sin predio")]
            red_value = rec.get("red_id") or [0, _("Sin red")]
            month = int(rec.get("contribution_month") or 0)
            if month not in total_by_month:
                continue

            predio_bucket = predio_map.setdefault(
                predio_value[0],
                {"name": predio_value[1], "reds": {}},
            )
            red_bucket = predio_bucket["reds"].setdefault(
                red_value[0],
                {"name": red_value[1], "members": {}},
            )
            member_bucket = red_bucket["members"].setdefault(
                member_value[0],
                {
                    "name": member_value[1],
                    "months": {month_number: 0.0 for month_number, _label in self.MONTH_HEADERS},
                },
            )
            if not member_bucket.get("_counted"):
                member_bucket["_counted"] = True
                member_count += 1

            amount = rec.get("amount") or 0.0
            member_bucket["months"][month] += amount
            total_by_month[month] += amount

        rows = []
        for predio_data in sorted(predio_map.values(), key=lambda item: (item["name"] or "").lower()):
            red_rows = []
            for red_data in sorted(predio_data["reds"].values(), key=lambda item: (item["name"] or "").lower()):
                member_rows = []
                for member_data in sorted(red_data["members"].values(), key=lambda item: (item["name"] or "").lower()):
                    months = {
                        month: round(member_data["months"].get(month, 0.0), 2)
                        for month, _label in self.MONTH_HEADERS
                    }
                    member_rows.append(
                        {
                            "name": member_data["name"],
                            "months": months,
                            "total": round(sum(months.values()), 2),
                        }
                    )
                red_rows.append({"name": red_data["name"], "members": member_rows})
            rows.append({"name": predio_data["name"], "reds": red_rows})

        total_amount = round(sum(total_by_month.values()), 2)
        type_names = []
        if contribution_type_ids:
            type_names = self.env["iem.financial.contribution.type"].browse(contribution_type_ids).mapped("name")
        return {
            "year": year,
            "rows": rows,
            "months": self.MONTH_HEADERS,
            "member_count": member_count,
            "total_amount": total_amount,
            "totals": {month: round(total_by_month[month], 2) for month, _label in self.MONTH_HEADERS},
            "type_names": type_names,
        }

    @api.model
    def _format_amount(self, amount):
        return f"{amount:,.2f}" if amount else ""

    @api.model
    def _build_report_html(self, payload):
        column_count = len(self.MONTH_HEADERS) + 2
        if not payload["rows"]:
            filter_text = escape(", ".join(payload.get("type_names") or [])) or escape(_("Todos los tipos"))
            return f"""
                <div class="alert alert-info" role="alert">
                    {escape(_('No hay contribuciones confirmadas para el filtro seleccionado.'))}<br/>
                    <strong>{escape(_('Año'))}:</strong> {payload['year']}<br/>
                    <strong>{escape(_('Tipos'))}:</strong> {filter_text}
                </div>
            """

        html_parts = [
            "<div>",
        ]
        filter_text = escape(", ".join(payload.get("type_names") or [])) or escape(_("Todos los tipos"))
        html_parts.append(
            f"<p><strong>{escape(_('Año'))}:</strong> {payload['year']}<br/><strong>{escape(_('Tipos'))}:</strong> {filter_text}<br/><strong>{escape(_('Suma total'))}:</strong> {escape(self._format_amount(payload['total_amount']))}</p>"
        )
        html_parts.append(
            """
            <div class="table-responsive">
                <table class="table table-sm table-bordered o_list_table">
                    <thead>
                        <tr>
                            <th>Miembro</th>
            """
        )
        for _month, label in self.MONTH_HEADERS:
            html_parts.append(f"<th class='text-center'>{escape(label)}</th>")
        html_parts.append("<th class='text-end'>Total</th></tr></thead><tbody>")

        for predio_row in payload["rows"]:
            html_parts.append(
                f"<tr class='table-active'><td colspan='{column_count}'><strong>{escape(_('Predio'))}: {escape(predio_row['name'])}</strong></td></tr>"
            )
            for red_row in predio_row["reds"]:
                html_parts.append(
                    f"<tr class='table-light'><td colspan='{column_count}'><strong>{escape(_('Red'))}: {escape(red_row['name'])}</strong></td></tr>"
                )
                for member_row in red_row["members"]:
                    html_parts.append(f"<tr><td>{escape(member_row['name'])}</td>")
                    for month, _label in self.MONTH_HEADERS:
                        html_parts.append(
                            f"<td class='text-end'>{escape(self._format_amount(member_row['months'].get(month, 0.0)))}</td>"
                        )
                    html_parts.append(f"<td class='text-end'><strong>{escape(self._format_amount(member_row['total']))}</strong></td></tr>")

        html_parts.append("<tr class='table-secondary'><td><strong>Total general</strong></td>")
        for month, _label in self.MONTH_HEADERS:
            html_parts.append(
                f"<td class='text-end'><strong>{escape(self._format_amount(payload['totals'].get(month, 0.0)))}</strong></td>"
            )
        html_parts.append(
            f"<td class='text-end'><strong>{escape(self._format_amount(payload['total_amount']))}</strong></td></tr>"
        )
        html_parts.append("</tbody></table></div></div>")
        return "".join(html_parts)

    @api.model
    def _build_export_filename(self, year, include_amounts=True):
        suffix = "montos" if include_amounts else "checks"
        return f"reporte_contribuciones_{year}_{suffix}.xlsx"

    @api.model
    def _export_payload_to_xlsx(self, payload, include_amounts=True):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet(_("Contribuciones")[:31])

        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9E2F3", "border": 1, "align": "center"})
        group_fmt = workbook.add_format({"bold": True, "bg_color": "#EDEDED", "border": 1})
        text_fmt = workbook.add_format({"border": 1})
        amount_fmt = workbook.add_format({"border": 1, "num_format": "#,##0.00"})
        total_fmt = workbook.add_format({"bold": True, "bg_color": "#FFF2CC", "border": 1, "num_format": "#,##0.00"})
        check_total_fmt = workbook.add_format({"bold": True, "bg_color": "#FFF2CC", "border": 1})

        headers = [_("Miembro")] + [label for _month, label in self.MONTH_HEADERS] + [_("Total")]
        for col, title in enumerate(headers):
            worksheet.write(0, col, title, header_fmt)

        row_idx = 1
        for predio_row in payload["rows"]:
            worksheet.merge_range(row_idx, 0, row_idx, len(headers) - 1, f"{_('Predio')}: {predio_row['name']}", group_fmt)
            row_idx += 1
            for red_row in predio_row["reds"]:
                worksheet.merge_range(row_idx, 0, row_idx, len(headers) - 1, f"{_('Red')}: {red_row['name']}", group_fmt)
                row_idx += 1
                for member_row in red_row["members"]:
                    worksheet.write(row_idx, 0, member_row["name"], text_fmt)
                    month_checks = 0
                    for col_offset, (month, _label) in enumerate(self.MONTH_HEADERS, start=1):
                        amount = member_row["months"].get(month, 0.0)
                        if include_amounts:
                            if amount:
                                worksheet.write_number(row_idx, col_offset, amount, amount_fmt)
                            else:
                                worksheet.write_blank(row_idx, col_offset, "", amount_fmt)
                        else:
                            has_value = bool(amount)
                            worksheet.write(row_idx, col_offset, "X" if has_value else "", text_fmt)
                            month_checks += 1 if has_value else 0
                    if include_amounts:
                        worksheet.write_number(row_idx, len(headers) - 1, member_row["total"], amount_fmt)
                    else:
                        worksheet.write_number(row_idx, len(headers) - 1, month_checks, text_fmt)
                    row_idx += 1

        worksheet.write(row_idx, 0, _("Total general"), check_total_fmt if not include_amounts else total_fmt)
        for col_offset, (month, _label) in enumerate(self.MONTH_HEADERS, start=1):
            if include_amounts:
                worksheet.write_number(row_idx, col_offset, payload["totals"].get(month, 0.0), total_fmt)
            else:
                month_checks = 0
                for predio_row in payload["rows"]:
                    for red_row in predio_row["reds"]:
                        for member_row in red_row["members"]:
                            month_checks += 1 if member_row["months"].get(month, 0.0) else 0
                worksheet.write_number(row_idx, col_offset, month_checks, check_total_fmt)
        if include_amounts:
            worksheet.write_number(row_idx, len(headers) - 1, payload["total_amount"], total_fmt)
        else:
            total_checks = 0
            for predio_row in payload["rows"]:
                for red_row in predio_row["reds"]:
                    for member_row in red_row["members"]:
                        total_checks += sum(1 for month, _label in self.MONTH_HEADERS if member_row["months"].get(month, 0.0))
            worksheet.write_number(row_idx, len(headers) - 1, total_checks, check_total_fmt)

        worksheet.set_column(0, 0, 36)
        worksheet.set_column(1, len(headers) - 1, 14)
        workbook.close()

        xlsx_data = output.getvalue()
        attachment = self.env["ir.attachment"].create(
            {
                "name": self._build_export_filename(payload["year"], include_amounts=include_amounts),
                "type": "binary",
                "datas": base64.b64encode(xlsx_data),
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "res_model": self._name,
                "public": False,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


class IemFinancialContributionReportYearWizard(models.TransientModel):
    _name = "iem.financial.contribution.report.year.wizard"
    _description = "IEM Financial Contribution Report Year Wizard"
    _inherit = "iem.financial.contribution.report.mixin"

    year = fields.Integer(string="Año", required=True, default=lambda self: self._default_report_year())
    contribution_type_ids = fields.Many2many(
        "iem.financial.contribution.type",
        "iem_financial_contribution_report_year_type_rel",
        "wizard_id",
        "type_id",
        string="Tipos de contribución",
    )

    def action_open_report(self):
        self.ensure_one()
        report = self.env["iem.financial.contribution.report.wizard"].create(
            {
                "year": self.year,
                "contribution_type_ids": [(6, 0, self.contribution_type_ids.ids)],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Reporte de contribuciones"),
            "res_model": "iem.financial.contribution.report.wizard",
            "view_mode": "form",
            "res_id": report.id,
            "view_id": self.env.ref("iem_church_management.view_iem_financial_contribution_report_wizard_form").id,
            "target": "current",
        }


class IemFinancialContributionReportWizard(models.TransientModel):
    _name = "iem.financial.contribution.report.wizard"
    _description = "IEM Financial Contribution Report Wizard"
    _inherit = "iem.financial.contribution.report.mixin"

    year = fields.Integer(string="Año", required=True, default=lambda self: self._default_report_year())
    contribution_type_ids = fields.Many2many(
        "iem.financial.contribution.type",
        "iem_financial_contribution_report_type_rel",
        "wizard_id",
        "type_id",
        string="Tipos de contribución",
    )
    report_html = fields.Html(string="Reporte", compute="_compute_report_html", sanitize=False)
    member_count = fields.Integer(string="Miembros con contribuciones", compute="_compute_report_stats")
    total_amount = fields.Monetary(
        string="Monto total",
        currency_field="currency_id",
        compute="_compute_report_stats",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    @api.depends("year", "contribution_type_ids")
    def _compute_report_html(self):
        for rec in self:
            payload = rec._get_report_payload(rec.year, contribution_type_ids=rec.contribution_type_ids.ids)
            rec.report_html = rec._build_report_html(payload)

    @api.depends("year", "contribution_type_ids")
    def _compute_report_stats(self):
        for rec in self:
            payload = rec._get_report_payload(rec.year, contribution_type_ids=rec.contribution_type_ids.ids)
            rec.member_count = payload["member_count"]
            rec.total_amount = payload["total_amount"]

    def action_refresh(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reporte de contribuciones"),
            "res_model": "iem.financial.contribution.report.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "view_id": self.env.ref("iem_church_management.view_iem_financial_contribution_report_wizard_form").id,
            "target": "current",
        }

    def action_open_year_selector(self):
        self.ensure_one()
        wizard = self.env["iem.financial.contribution.report.year.wizard"].create(
            {
                "year": self.year,
                "contribution_type_ids": [(6, 0, self.contribution_type_ids.ids)],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Seleccionar año"),
            "res_model": "iem.financial.contribution.report.year.wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "view_id": self.env.ref("iem_church_management.view_iem_financial_contribution_report_year_wizard_form").id,
            "target": "new",
        }

    def action_open_export_wizard(self):
        self.ensure_one()
        wizard = self.env["iem.financial.contribution.report.export.wizard"].create(
            {
                "year": self.year,
                "contribution_type_ids": [(6, 0, self.contribution_type_ids.ids)],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Exportar reporte"),
            "res_model": "iem.financial.contribution.report.export.wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "view_id": self.env.ref("iem_church_management.view_iem_financial_contribution_report_export_wizard_form").id,
            "target": "new",
        }


class IemFinancialContributionReportExportWizard(models.TransientModel):
    _name = "iem.financial.contribution.report.export.wizard"
    _description = "IEM Financial Contribution Report Export Wizard"
    _inherit = "iem.financial.contribution.report.mixin"

    year = fields.Integer(string="Año", required=True, default=lambda self: self._default_report_year())
    contribution_type_ids = fields.Many2many(
        "iem.financial.contribution.type",
        "iem_financial_contribution_report_export_type_rel",
        "wizard_id",
        "type_id",
        string="Tipos de contribución",
    )
    include_amounts = fields.Boolean(string="Generar excel con montos", default=True)

    def action_export_xlsx(self):
        self.ensure_one()
        payload = self._get_report_payload(self.year, contribution_type_ids=self.contribution_type_ids.ids)
        return self._export_payload_to_xlsx(payload, include_amounts=self.include_amounts)
