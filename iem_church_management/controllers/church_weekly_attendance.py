import json

from odoo import http
from odoo.http import content_disposition, request


class IemChurchWeeklyAttendanceController(http.Controller):
    @http.route("/iem_church_management/weekly_attendance/export_xlsx", type="http", auth="user", methods=["POST"])
    def export_xlsx(self, domain="[]", context="{}", **kwargs):
        content = request.env["iem.church.weekly.attendance"].export_filtered_xlsx(
            domain=json.loads(domain),
            context=json.loads(context),
        )
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition("reporte_celulas.xlsx")),
            ],
        )
