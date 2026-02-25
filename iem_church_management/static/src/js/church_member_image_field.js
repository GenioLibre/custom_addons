import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ImageField } from "@web/views/fields/image/image_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FileUploader } from "@web/views/fields/file_handler";

export class ChurchMemberFileUploader extends FileUploader {
    static props = {
        ...FileUploader.props,
        capture: { type: String, optional: true },
    };
    static template = "iem_church_management.FileUploaderCapture";
}

export class ChurchMemberImageField extends ImageField {
    static template = "iem_church_management.ChurchMemberImageField";
    static components = {
        FileUploader: ChurchMemberFileUploader,
    };

    async onFileUploaded(info) {
        if (info.type && info.type.startsWith("image/")) {
            const maxSize = 1024;
            const img = new Image();
            img.src = `data:${info.type};base64,${info.data}`;
            await new Promise((resolve) => img.addEventListener("load", resolve));
            const scale = Math.min(1, maxSize / Math.max(img.width, img.height));
            if (scale < 1) {
                const canvas = document.createElement("canvas");
                canvas.width = Math.round(img.width * scale);
                canvas.height = Math.round(img.height * scale);
                const ctx = canvas.getContext("2d");
                ctx.imageSmoothingEnabled = true;
                ctx.imageSmoothingQuality = "high";
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                const mimeType = info.type === "image/png" ? "image/png" : "image/jpeg";
                const quality = mimeType === "image/jpeg" ? 0.85 : 1.0;
                const dataUrl = canvas.toDataURL(mimeType, quality);
                info.data = dataUrl.split(",")[1];
                info.type = mimeType;
                if (mimeType === "image/jpeg" && !/\.jpe?g$/i.test(info.name)) {
                    info.name = info.name.replace(/\.[^/.]+$/, ".jpg");
                }
            }
        }
        await super.onFileUploaded(info);
    }
}

export const churchMemberImageField = {
    ...registry.category("fields").get("image"),
    component: ChurchMemberImageField,
};

registry.category("fields").add("church_member_image", churchMemberImageField);

patch(ListRenderer.prototype, {
    processAllColumn(allColumns, list) {
        const columns = super.processAllColumn(allColumns, list);
        if (!list || list.resModel !== "iem.church.member.list.line") {
            return columns;
        }
        const context = list.context || {};
        const parentRecord = list._parent;
        const parentValues = {
            ...(parentRecord?.data || {}),
            ...(parentRecord?._changes || {}),
        };
        const labelMap = {
            extra_boolean: context.list_boolean_label || parentValues.boolean_extra_label,
            extra_amount: context.list_amount_label || parentValues.amount_extra_label,
            extra_text: context.list_text_label || parentValues.text_extra_label,
        };
        return columns.map((column) => {
            const customLabel = column?.name ? labelMap[column.name] : false;
            if (customLabel) {
                return {
                    ...column,
                    label: customLabel,
                };
            }
            return column;
        });
    },
});
