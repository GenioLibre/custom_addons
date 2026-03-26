# -*- coding: utf-8 -*-

from odoo import models, fields, api


class TikTokPublishConfirmWizard(models.TransientModel):
    _name = "gl.tiktok.publish.confirm.wizard"
    _description = "Confirmacion de publicacion TikTok"

    action_type = fields.Selection(
        [
            ("publish", "Publicar"),
            ("schedule", "Programar"),
        ],
        string="Accion",
        required=True,
        default="publish",
        readonly=True,
    )
    task_id = fields.Many2one("project.task", string="Tarea", required=True, readonly=True)
    partner_id = fields.Many2one("res.partner", related="task_id.partner_id", string="Creador", readonly=True)
    fecha_publicacion = fields.Datetime(related="task_id.fecha_publicacion", string="Fecha de publicacion", readonly=True)
    tiktok_title = fields.Char(related="task_id.tiktok_title", string="Titulo TikTok", readonly=True)
    tiktok_caption_preview = fields.Text(string="Caption TikTok", readonly=True, compute="_compute_tiktok_caption_preview")
    tiktok_nickname = fields.Char(related="task_id.tiktok_nickname", string="TikTok Nickname", readonly=True)
    tiktok_creator_username = fields.Char(related="task_id.tiktok_creator_username", string="TikTok Username", readonly=True)
    tiktok_can_publish = fields.Boolean(related="task_id.tiktok_can_publish", string="Puede publicar", readonly=True)
    tiktok_can_publish_reason = fields.Char(related="task_id.tiktok_can_publish_reason", string="Motivo estado TikTok", readonly=True)
    tiktok_privacy_level = fields.Selection(related="task_id.tiktok_privacy_level", string="Privacidad", readonly=True)
    tiktok_privacy_level_label = fields.Char(string="Privacidad", readonly=True, compute="_compute_tiktok_privacy_level_label")
    tiktok_allow_comments = fields.Boolean(related="task_id.tiktok_allow_comments", string="Permitir comentarios", readonly=True)
    tiktok_allow_duet = fields.Boolean(related="task_id.tiktok_allow_duet", string="Permitir duet", readonly=True)
    tiktok_allow_stitch = fields.Boolean(related="task_id.tiktok_allow_stitch", string="Permitir stitch", readonly=True)
    tiktok_is_aigc = fields.Boolean(related="task_id.tiktok_is_aigc", string="Contenido generado con IA", readonly=True)
    tiktok_is_commercial = fields.Boolean(related="task_id.tiktok_is_commercial", string="Es contenido comercial", readonly=True)
    tiktok_commercial_your_brand = fields.Boolean(related="task_id.tiktok_commercial_your_brand", string="Your Brand", readonly=True)
    tiktok_commercial_branded = fields.Boolean(related="task_id.tiktok_commercial_branded", string="Branded Content", readonly=True)
    tiktok_commercial_label_preview = fields.Char(
        related="task_id.tiktok_commercial_label_preview",
        string="Etiqueta comercial",
        readonly=True,
    )
    tiktok_privacy_note = fields.Text(related="task_id.tiktok_privacy_note", string="Nota Privacidad", readonly=True)
    tiktok_declaration_text = fields.Text(
        related="task_id.tiktok_declaration_text",
        string="Declaracion legal TikTok",
        readonly=True,
    )
    tiktok_legal_text = fields.Text(related="task_id.tiktok_legal_text", string="Texto Legal", readonly=True)
    tiktok_creator_status_info = fields.Text(
        related="task_id.tiktok_creator_status_info",
        string="Estado del creador",
        readonly=True,
    )

    @api.depends("task_id")
    def _compute_tiktok_caption_preview(self):
        for wizard in self:
            wizard.tiktok_caption_preview = wizard.task_id._prepare_text() if wizard.task_id else False

    @api.depends("task_id", "task_id.tiktok_privacy_level")
    def _compute_tiktok_privacy_level_label(self):
        privacy_selection = dict(self.env["project.task"]._fields["tiktok_privacy_level"].selection)
        for wizard in self:
            value = wizard.task_id.tiktok_privacy_level if wizard.task_id else False
            wizard.tiktok_privacy_level_label = privacy_selection.get(value, False)

    def action_confirm(self):
        self.ensure_one()
        if self.action_type == "schedule":
            return self.task_id.with_context(skip_tiktok_confirmation=True).programar_post()
        return self.task_id.with_context(skip_tiktok_confirmation=True).publicar_post()
