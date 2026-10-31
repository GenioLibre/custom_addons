import { download } from "@web/core/network/download";
import { patch } from "@web/core/utils/patch";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";

patch(PivotRenderer.prototype, {
    async onWeeklyAttendanceExportClicked() {
        await download({
            url: "/iem_church_management/weekly_attendance/export_xlsx",
            data: {
                domain: JSON.stringify(this.model.searchParams.domain || []),
                context: JSON.stringify(this.model.searchParams.context || {}),
            },
        });
    },
});
