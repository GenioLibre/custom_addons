/** @odoo-module **/

import { Component, useState, onWillStart, useRef, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class ChatroomView extends Component {
    static template = "whatsapp.chatroom.owl";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            chatrooms: [],
            selected: null,
            messages: [],
            showEmojiPicker: false,
            attachedFile: null,
            fileName: "",
            filePreview: null,
            fileType: null,
            partnerData: null,
            partnerOrders: [],
            loadingPartner: false,
            loadingAiReply: false,
            activeTab: 'reply',
            suggestedMessages: [],
            selectedMessage: null
        });
        this.STATE_LABELS = {
            draft: "Borrador",
            sent: "Enviado",
            sale: "Confirmado",
            done: "Hecho",
            cancel: "Cancelado",
        };

        // Referencias
        this.inputRef = useRef("inputMessage");
        this.customMessageInput = useRef("customMessageInput");
        this.clientSimulationInput = useRef("clientSimulationInput");
        this.fileInputRef = useRef("file-input");
        this.messageScrollRef = useRef("messageScroll");

        // Binding de métodos
        this.toggleEmojiPicker = this.toggleEmojiPicker.bind(this);
        this.insertEmoji = this.insertEmoji.bind(this);

        onWillStart(async () => {
            console.log("[DEBUG] Iniciando carga inicial de datos...");

            try {
                const rooms = await this.orm.call('whatsapp.chatroom', 'search_read', [[['state', '=', 'open']]]);
                this.state.chatrooms = rooms;

                if (rooms.length > 0) {
                    this.state.selected = rooms[0];
                    this.state.messages = await this._loadMessages(rooms[0]);

                    if (rooms[0].partner_id) {
                        await this._loadPartnerInfo(rooms[0].partner_id[0]);
                    }
                }

                this.state.suggestedMessages = await this.orm.searchRead(
                    'mensajes.automaticos',
                    [['activo', '=', true]],
                    ['name', 'contenido'],
                    { order: 'prioridad asc' }
                );

            } catch (error) {
                console.error("[ERROR] Error en carga inicial:", error);
            }
        });

        onPatched(() => {
            this._scrollMessagesToBottom();
        });
    }

    _scrollMessagesToBottom() {
        const el = this.messageScrollRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    // Cargar datos del partner y sus documentos de venta
    async _loadPartnerInfo(partnerId) {
        this.state.loadingPartner = true;
        try {
            const partnerData = await this.orm.read(
                'res.partner',
                [partnerId],
                ['name', 'email', 'phone', 'image_1920', 'mobile', 'street', 'city']
            );
            this.state.partnerData = partnerData[0];

            const orders = await this.orm.searchRead(
                'sale.order',
                [['partner_id', '=', partnerId]],
                ['id', 'name', 'state', 'date_order', 'currency_id', 'amount_total'],
                { order: 'date_order desc', limit: 10 }
            );
            this.state.partnerOrders = orders;
        } catch (error) {
            console.error("[ERROR] Error al obtener info del partner:", error);
            this.state.partnerData = null;
            this.state.partnerOrders = [];
        } finally {
            this.state.loadingPartner = false;
        }
    }

    // Manejo de selección de chatroom
    async selectChatroom(chat) {
        this.state.selected = chat;
        this.state.messages = await this._loadMessages(chat);

        if (chat.partner_id) {
            await this._loadPartnerInfo(chat.partner_id[0]);
        } else {
            this.state.partnerData = null;
            this.state.partnerOrders = [];
        }
    }

    async _loadMessages(chat) {
        const messages = await this.orm.call(
            'whatsapp.chatmessage',
            'search_read',
            [[['chatroom_id', '=', chat.id]]]
        );
        return messages;
    }

    async _refreshCurrentChatroom() {
        if (!this.state.selected) {
            return;
        }
        this.state.messages = await this._loadMessages(this.state.selected);

        const updatedChatrooms = await this.orm.call(
            'whatsapp.chatroom',
            'search_read',
            [[['state', '=', 'open']]]
        );
        this.state.chatrooms = updatedChatrooms;
        this.state.selected = updatedChatrooms.find(chat => chat.id === this.state.selected.id) || this.state.selected;
    }

    async _createOutgoingMessage(message, sender = 'user') {
        if (!this.state.selected) {
            this.notification.add("Selecciona un chat antes de enviar un mensaje.", {
                type: "warning",
            });
            return false;
        }

        const cleanMessage = (message || "").trim();
        if (!cleanMessage) {
            this.notification.add("Escribe un mensaje antes de enviar.", {
                type: "warning",
            });
            return false;
        }

        try {
            await this.orm.call(
                'whatsapp.chatroom',
                'create_outgoing_message',
                [[this.state.selected.id], cleanMessage, sender, 'text']
            );
            await this._refreshCurrentChatroom();
            return true;
        } catch (error) {
            console.error("[ERROR] Error al guardar el mensaje:", error);
            this.notification.add("No se pudo registrar el mensaje en el chat.", {
                type: "danger",
            });
            return false;
        }
    }

    // Respuestas sugeridas
    handleSelectMessage(ev) {
        const messageId = parseInt(ev.target.value);
        this.state.selectedMessage = this.state.suggestedMessages.find(msg => msg.id === messageId) || null;
    }

    async sendSuggestedMessage() {
        if (!this.state.selected) {
            this.notification.add("Selecciona un chat antes de enviar una respuesta.", {
                type: "warning",
            });
            return;
        }
        if (!this.state.selectedMessage) {
            this.notification.add("Por favor selecciona un mensaje.", {
                type: "warning",
            });
            return;
        }

        try {
            const sent = await this._createOutgoingMessage(this.state.selectedMessage.contenido, 'bot');
            if (sent) {
                this.notification.add("Respuesta registrada en el chat.", {
                    type: "success",
                });
            }
        } catch (error) {
            console.error("[ERROR] Error al guardar la respuesta sugerida:", error);
            this.notification.add("No se pudo registrar la respuesta en el chat.", {
                type: "danger",
            });
        }
    }

    async sendCustomMessage() {
        const message = this.customMessageInput.el.value.trim();
        if (message) {
            const sent = await this._createOutgoingMessage(message, 'bot');
            if (sent) {
                this.customMessageInput.el.value = "";
                this.notification.add("Mensaje sugerido registrado en el chat.", {
                    type: "success",
                });
            }
        } else {
            this.notification.add("Por favor escribe un mensaje.", {
                type: "warning",
            });
        }
    }

    async generateAiReply() {
        if (!this.state.selected) {
            this.notification.add("Selecciona un chat antes de generar una respuesta.", {
                type: "warning",
            });
            return;
        }

        this.state.loadingAiReply = true;
        try {
            const reply = await this.orm.call(
                'whatsapp.chatroom',
                'generate_ai_reply',
                [[this.state.selected.id]]
            );
            if (this.customMessageInput.el) {
                this.customMessageInput.el.value = reply;
            }
            this.notification.add("Respuesta generada con Ollama.", {
                type: "success",
            });
        } catch (error) {
            console.error("[ERROR] Error al generar la respuesta IA:", error);
            this.notification.add(error.message || "No se pudo generar la respuesta con IA.", {
                type: "danger",
            });
        } finally {
            this.state.loadingAiReply = false;
        }
    }

    async simulateClientMessage() {
        const message = this.clientSimulationInput.el ? this.clientSimulationInput.el.value.trim() : "";
        if (message) {
            const sent = await this._createOutgoingMessage(message, 'client');
            if (sent) {
                this.clientSimulationInput.el.value = "";
                this.notification.add("Mensaje de cliente simulado en el chat.", {
                    type: "success",
                });
            }
        } else {
            this.notification.add("Escribe el mensaje del cliente para simularlo.", {
                type: "warning",
            });
        }
    }

    async sendMainMessage() {
        const message = this.inputRef.el ? this.inputRef.el.value.trim() : "";
        if (message) {
            const sent = await this._createOutgoingMessage(message, 'user');
            if (sent) {
                this.inputRef.el.value = "";
                this.state.showEmojiPicker = false;
                this.notification.add("Mensaje enviado al chat.", {
                    type: "success",
                });
            }
        } else {
            this.notification.add("Por favor escribe un mensaje.", {
                type: "warning",
            });
        }
    }

    async onMainFormSubmit(ev) {
        if (ev) {
            ev.preventDefault();
        }
        await this.sendMainMessage();
    }

    // Adjuntar archivos
    openFilePicker() {
        this.fileInputRef.el.click();
    }

    handleFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) return;

        const isImage = file.type.match('image.*');
        const isPDF = file.type === 'application/pdf';
        const isExcel = file.type.match('application/vnd.ms-excel') ||
                        file.type.match('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');

        if (!isImage && !isPDF && !isExcel) {
            this.displayFileError("Solo se permiten imágenes (JPG, PNG), PDFs y archivos Excel");
            return;
        }

        this.state.attachedFile = file;
        this.state.fileName = file.name;
        this.state.fileType = isImage ? 'image' : (isPDF ? 'pdf' : 'excel');

        if (isImage) {
            const reader = new FileReader();
            reader.onload = (e) => {
                this.state.filePreview = e.target.result;
            };
            reader.readAsDataURL(file);
        } else {
            this.state.filePreview = this.getFileIcon(this.state.fileType);
        }
    }

    getFileIcon(fileType) {
        const icons = {
            pdf: '/web/static/src/img/pdf_icon.png',
            excel: '/web/static/src/img/excel_icon.png'
        };
        return icons[fileType] || '/web/static/src/img/file_icon.png';
    }

    displayFileError(message) {
        console.error(message);
        this.fileInputRef.el.value = "";
    }

    removeAttachment() {
        this.state.attachedFile = null;
        this.state.fileName = "";
        this.state.filePreview = null;
        this.fileInputRef.el.value = "";
    }

    // Emojis
    insertEmoji(emoji) {
        const input = this.inputRef.el;
        if (!input) return;
        const start = input.selectionStart || 0;
        const end = input.selectionEnd || 0;
        input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
        input.selectionStart = input.selectionEnd = start + emoji.length;
    }

    toggleEmojiPicker() {
        this.state.showEmojiPicker = !this.state.showEmojiPicker;
        if (this.state.showEmojiPicker) {
            document.addEventListener('click', this.closeEmojiPickerOnClickOutside);
        } else {
            this.removeClickListener();
        }
    }

    closeEmojiPickerOnClickOutside = (event) => {
        const emojiPicker = document.getElementById('emoji-picker');
        if (emojiPicker && !emojiPicker.contains(event.target)) {
            this.state.showEmojiPicker = false;
            this.removeClickListener();
        }
    }

    removeClickListener() {
        document.removeEventListener('click', this.closeEmojiPickerOnClickOutside);
    }

    __destroy() {
        this.removeClickListener();
        super.__destroy();
    }
}

registry.category("actions").add("whatsapp.chatroom.owl", ChatroomView);
