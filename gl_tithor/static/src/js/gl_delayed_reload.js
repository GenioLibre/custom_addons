/** @odoo-module **/

import { registry } from "@web/core/registry";

function delayedReloadAction(env, action) {
    const params = action.params || {};
    env.services.notification.add(params.message || "Importación completada.", {
        title: params.title || "Importación completada",
        type: params.type || "success",
    });

    return new Promise((resolve) => {
        window.setTimeout(() => {
            window.location.reload();
            resolve();
        }, params.delay || 3000);
    });
}

registry.category("actions").add("gl_tithor_delayed_reload", delayedReloadAction);
