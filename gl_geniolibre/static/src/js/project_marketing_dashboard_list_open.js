/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.orm = useService("orm");
    },

    async onCellClicked(record, column, ev) {
        if (
            record?.resModel === "project.marketing.dashboard" &&
            !this.props.archInfo.noOpen &&
            !ev.target.special_click &&
            !ev.target.closest("button, a, input, .o_list_record_selector")
        ) {
            const action = await this.orm.call(
                "project.marketing.dashboard",
                "action_open_marketing_form",
                [[record.resId]]
            );
            return this.actionService.doAction(action);
        }
        return super.onCellClicked(...arguments);
    },
});
