/** @odoo-module **/

import { Component, useState, onWillStart, useRef, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

const CHATROOM_PAGE_SIZE = 30;
const MESSAGE_PAGE_SIZE = 40;

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
            partnerSummary: null,
            loadingPartner: false,
            loadingAiReply: false,
            loadingChatrooms: false,
            loadingMessages: false,
            loadingOlderMessages: false,
            hasMoreChatrooms: true,
            hasMoreMessages: true,
            chatroomOffset: 0,
            messageOffset: 0,
            activeTab: "reply",
            suggestedMessages: [],
            selectedMessage: null,
        });
        this.STATE_LABELS = {
            draft: "Borrador",
            sent: "Enviado",
            sale: "Confirmado",
            done: "Hecho",
            cancel: "Cancelado",
        };

        this.inputRef = useRef("inputMessage");
        this.customMessageInput = useRef("customMessageInput");
        this.clientSimulationInput = useRef("clientSimulationInput");
        this.fileInputRef = useRef("file-input");
        this.messageScrollRef = useRef("messageScroll");
        this.chatListScrollRef = useRef("chatListScroll");

        this.shouldScrollMessagesToBottom = false;

        this.toggleEmojiPicker = this.toggleEmojiPicker.bind(this);
        this.insertEmoji = this.insertEmoji.bind(this);
        this.onChatListScroll = this.onChatListScroll.bind(this);
        this.onMessageScroll = this.onMessageScroll.bind(this);

        onWillStart(async () => {
            try {
                await Promise.all([
                    this._loadChatrooms({ reset: true }),
                    this._loadSuggestedMessages(),
                ]);

                if (this.state.chatrooms.length > 0) {
                    await this.selectChatroom(this.state.chatrooms[0]);
                }
            } catch (error) {
                console.error("[ERROR] Error en carga inicial:", error);
            }
        });

        onPatched(() => {
            if (this.shouldScrollMessagesToBottom) {
                this._scrollMessagesToBottom();
                this.shouldScrollMessagesToBottom = false;
            }
        });
    }

    async _loadSuggestedMessages() {
        this.state.suggestedMessages = await this.orm.searchRead(
            "mensajes.automaticos",
            [["activo", "=", true]],
            ["name", "contenido"],
            { order: "prioridad asc" }
        );
    }

    async _loadChatrooms({ reset = false, preserveSelectedId = null } = {}) {
        if (this.state.loadingChatrooms) {
            return;
        }
        if (!reset && !this.state.hasMoreChatrooms) {
            return;
        }

        this.state.loadingChatrooms = true;
        try {
            const offset = reset ? 0 : this.state.chatroomOffset;
            const rooms = await this.orm.searchRead(
                "whatsapp.chatroom",
                [["state", "=", "open"]],
                ["name", "phone_number", "last_message", "last_message_time", "partner_id", "state"],
                {
                    order: "last_message_time desc, id desc",
                    limit: CHATROOM_PAGE_SIZE,
                    offset,
                }
            );

            const roomMap = new Map();
            const sourceRooms = reset ? rooms : [...this.state.chatrooms, ...rooms];
            for (const room of sourceRooms) {
                roomMap.set(room.id, room);
            }

            this.state.chatrooms = Array.from(roomMap.values());
            this.state.chatroomOffset = offset + rooms.length;
            this.state.hasMoreChatrooms = rooms.length === CHATROOM_PAGE_SIZE;

            if (preserveSelectedId) {
                this.state.selected = this.state.chatrooms.find((chat) => chat.id === preserveSelectedId) || this.state.selected;
            }
        } finally {
            this.state.loadingChatrooms = false;
        }
    }

    _scrollMessagesToBottom() {
        const el = this.messageScrollRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    async _loadPartnerInfo(partnerId) {
        this.state.loadingPartner = true;
        try {
            const partnerData = await this.orm.read(
                "res.partner",
                [partnerId],
                ["name", "email", "phone", "image_1920", "mobile", "street", "city"]
            );
            this.state.partnerData = partnerData[0] || null;

            const [orders, orderCount] = await Promise.all([
                this.orm.searchRead(
                    "sale.order",
                    [["partner_id", "=", partnerId]],
                    ["id", "name", "state", "date_order", "currency_id", "amount_total"],
                    { order: "date_order desc", limit: 10 }
                ),
                this.orm.searchCount("sale.order", [["partner_id", "=", partnerId]]),
            ]);

            this.state.partnerOrders = orders;
            this.state.partnerSummary = this._buildPartnerSummary(orders, orderCount);
        } catch (error) {
            console.error("[ERROR] Error al obtener info del partner:", error);
            this.state.partnerData = null;
            this.state.partnerOrders = [];
            this.state.partnerSummary = null;
        } finally {
            this.state.loadingPartner = false;
        }
    }

    _buildPartnerSummary(orders, orderCount) {
        const latestOrder = orders[0] || null;
        const recentTotal = orders.reduce((acc, order) => acc + (order.amount_total || 0), 0);
        return {
            orderCount,
            recentTotal,
            latestOrder,
            isExistingCustomer: orderCount > 0,
        };
    }

    _resetPartnerInfo() {
        this.state.partnerData = null;
        this.state.partnerOrders = [];
        this.state.partnerSummary = null;
    }

    async selectChatroom(chat) {
        this.state.selected = chat;
        await this._loadMessages(chat, { reset: true });

        if (chat.partner_id) {
            await this._loadPartnerInfo(chat.partner_id[0]);
        } else {
            this._resetPartnerInfo();
        }
    }

    async _loadMessages(chat, { reset = false } = {}) {
        if (!chat) {
            return;
        }
        if (this.state.loadingMessages || this.state.loadingOlderMessages) {
            return;
        }
        if (!reset && !this.state.hasMoreMessages) {
            return;
        }

        const scrollEl = this.messageScrollRef.el;
        const previousScrollHeight = scrollEl ? scrollEl.scrollHeight : 0;
        const previousScrollTop = scrollEl ? scrollEl.scrollTop : 0;

        if (reset) {
            this.state.loadingMessages = true;
        } else {
            this.state.loadingOlderMessages = true;
        }

        try {
            const offset = reset ? 0 : this.state.messageOffset;
            const fetchedMessages = await this.orm.searchRead(
                "whatsapp.chatmessage",
                [["chatroom_id", "=", chat.id]],
                ["sender", "message", "timestamp", "message_type"],
                {
                    order: "timestamp desc, id desc",
                    limit: MESSAGE_PAGE_SIZE,
                    offset,
                }
            );
            const orderedMessages = [...fetchedMessages].reverse();

            if (reset) {
                this.state.messages = orderedMessages;
                this.state.messageOffset = fetchedMessages.length;
                this.state.hasMoreMessages = fetchedMessages.length === MESSAGE_PAGE_SIZE;
                this.shouldScrollMessagesToBottom = true;
            } else {
                const existingIds = new Set(this.state.messages.map((msg) => msg.id));
                const prependedMessages = orderedMessages.filter((msg) => !existingIds.has(msg.id));
                this.state.messages = [...prependedMessages, ...this.state.messages];
                this.state.messageOffset += fetchedMessages.length;
                this.state.hasMoreMessages = fetchedMessages.length === MESSAGE_PAGE_SIZE;

                requestAnimationFrame(() => {
                    const currentScrollEl = this.messageScrollRef.el;
                    if (currentScrollEl) {
                        currentScrollEl.scrollTop = currentScrollEl.scrollHeight - previousScrollHeight + previousScrollTop;
                    }
                });
            }
        } finally {
            this.state.loadingMessages = false;
            this.state.loadingOlderMessages = false;
        }
    }

    async _refreshCurrentChatroom() {
        if (!this.state.selected) {
            return;
        }
        await Promise.all([
            this._loadMessages(this.state.selected, { reset: true }),
            this._loadChatrooms({ reset: true, preserveSelectedId: this.state.selected.id }),
        ]);

        if (this.state.selected?.partner_id) {
            await this._loadPartnerInfo(this.state.selected.partner_id[0]);
        }
    }

    async _createOutgoingMessage(message, sender = "user") {
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
                "whatsapp.chatroom",
                "create_outgoing_message",
                [[this.state.selected.id], cleanMessage, sender, "text"]
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

    handleSelectMessage(ev) {
        const messageId = parseInt(ev.target.value);
        this.state.selectedMessage = this.state.suggestedMessages.find((msg) => msg.id === messageId) || null;
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

        const sent = await this._createOutgoingMessage(this.state.selectedMessage.contenido, "bot");
        if (sent) {
            this.notification.add("Respuesta registrada en el chat.", {
                type: "success",
            });
        }
    }

    async sendCustomMessage() {
        const message = this.customMessageInput.el.value.trim();
        if (message) {
            const sent = await this._createOutgoingMessage(message, "bot");
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
                "whatsapp.chatroom",
                "generate_ai_reply",
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
            if (!this.state.selected) {
                this.notification.add("Selecciona un chat antes de simular un mensaje.", {
                    type: "warning",
                });
                return;
            }
            try {
                await this.orm.call(
                    "whatsapp.chatroom",
                    "simulate_client_message",
                    [[this.state.selected.id], message]
                );
                this.clientSimulationInput.el.value = "";
                await this._refreshCurrentChatroom();
                this.notification.add("Mensaje de cliente simulado en el chat.", {
                    type: "success",
                });
            } catch (error) {
                console.error("[ERROR] Error al simular el mensaje del cliente:", error);
                this.notification.add("No se pudo simular el mensaje del cliente.", {
                    type: "danger",
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
            const sent = await this._createOutgoingMessage(message, "user");
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

    onChatListScroll(ev) {
        const el = ev.target;
        if (this.state.loadingChatrooms || !this.state.hasMoreChatrooms) {
            return;
        }
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
            this._loadChatrooms();
        }
    }

    onMessageScroll(ev) {
        const el = ev.target;
        if (this.state.loadingOlderMessages || !this.state.hasMoreMessages || !this.state.selected) {
            return;
        }
        if (el.scrollTop <= 80) {
            this._loadMessages(this.state.selected, { reset: false });
        }
    }

    formatDate(dateValue) {
        return dateValue ? new Date(dateValue).toLocaleDateString() : "";
    }

    formatDateTime(dateValue) {
        return dateValue ? new Date(dateValue).toLocaleString() : "";
    }

    formatAmount(amount, currencyField) {
        const currencyName = Array.isArray(currencyField) ? currencyField[1] : "";
        return `${(amount || 0).toFixed(2)}${currencyName ? ` ${currencyName}` : ""}`;
    }

    getCustomerStatusLabel() {
        if (!this.state.selected) {
            return "";
        }
        if (!this.state.partnerData) {
            return "Cliente nuevo";
        }
        return this.state.partnerSummary?.isExistingCustomer ? "Cliente existente" : "Contacto sin ventas";
    }

    getCustomerStatusClass() {
        if (!this.state.partnerData) {
            return "status-new";
        }
        return this.state.partnerSummary?.isExistingCustomer ? "status-existing" : "status-contact";
    }

    openFilePicker() {
        this.fileInputRef.el.click();
    }

    handleFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) {
            return;
        }

        const isImage = file.type.match("image.*");
        const isPDF = file.type === "application/pdf";
        const isExcel = file.type.match("application/vnd.ms-excel")
            || file.type.match("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

        if (!isImage && !isPDF && !isExcel) {
            this.displayFileError("Solo se permiten imágenes (JPG, PNG), PDFs y archivos Excel");
            return;
        }

        this.state.attachedFile = file;
        this.state.fileName = file.name;
        this.state.fileType = isImage ? "image" : (isPDF ? "pdf" : "excel");

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
            pdf: "/web/static/src/img/pdf_icon.png",
            excel: "/web/static/src/img/excel_icon.png",
        };
        return icons[fileType] || "/web/static/src/img/file_icon.png";
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

    insertEmoji(emoji) {
        const input = this.inputRef.el;
        if (!input) {
            return;
        }
        const start = input.selectionStart || 0;
        const end = input.selectionEnd || 0;
        input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
        input.selectionStart = input.selectionEnd = start + emoji.length;
    }

    toggleEmojiPicker() {
        this.state.showEmojiPicker = !this.state.showEmojiPicker;
        if (this.state.showEmojiPicker) {
            document.addEventListener("click", this.closeEmojiPickerOnClickOutside);
        } else {
            this.removeClickListener();
        }
    }

    closeEmojiPickerOnClickOutside = (event) => {
        const emojiPicker = document.getElementById("emoji-picker");
        if (emojiPicker && !emojiPicker.contains(event.target)) {
            this.state.showEmojiPicker = false;
            this.removeClickListener();
        }
    }

    removeClickListener() {
        document.removeEventListener("click", this.closeEmojiPickerOnClickOutside);
    }

    __destroy() {
        this.removeClickListener();
        super.__destroy();
    }
}

registry.category("actions").add("whatsapp.chatroom.owl", ChatroomView);
