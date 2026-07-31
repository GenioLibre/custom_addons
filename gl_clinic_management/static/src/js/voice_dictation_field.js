/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillUnmount, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class VoiceDictationField extends Component {
    static template = "gl_clinic_management.VoiceDictationField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.textareaRef = useRef("textarea");
        this.state = useState({ listening: false });
        this.recognition = null;
        onWillUnmount(() => this.stopDictation());
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get isSupported() {
        return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
    }

    async onInput(ev) {
        await this.props.record.update({ [this.props.name]: ev.target.value });
    }

    async toggleDictation() {
        if (this.state.listening) {
            this.stopDictation();
            return;
        }
        if (!this.isSupported) {
            this.notification.add(
                _t("Este navegador no admite reconocimiento de voz."),
                { type: "warning" }
            );
            return;
        }
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.recognition = new SpeechRecognition();
        this.recognition.lang = "es-PE";
        this.recognition.continuous = true;
        this.recognition.interimResults = false;
        this.recognition.onstart = () => {
            this.state.listening = true;
        };
        this.recognition.onresult = async (event) => {
            let text = "";
            for (let index = event.resultIndex; index < event.results.length; index++) {
                text += event.results[index][0].transcript;
            }
            const current = this.value.trim();
            const next = current ? `${current} ${text.trim()}` : text.trim();
            await this.props.record.update({ [this.props.name]: next });
        };
        this.recognition.onerror = (event) => {
            const message = event.error === "not-allowed"
                ? _t("Permiso de micrófono denegado.")
                : _t("No se pudo usar el micrófono.");
            this.notification.add(message, { type: "danger" });
            this.stopDictation();
        };
        this.recognition.onend = () => {
            this.state.listening = false;
        };
        try {
            this.recognition.start();
        } catch {
            this.notification.add(_t("El dictado ya está activo."), { type: "info" });
        }
    }

    stopDictation() {
        if (this.recognition) {
            this.recognition.onend = null;
            this.recognition.stop();
            this.recognition = null;
        }
        this.state.listening = false;
    }
}

export const voiceDictationField = {
    component: VoiceDictationField,
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({
        placeholder: attrs.placeholder,
    }),
};

registry.category("fields").add("gl_voice_dictation_text", voiceDictationField);
