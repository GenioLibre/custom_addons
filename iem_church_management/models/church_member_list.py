from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IemChurchMemberList(models.Model):
    _name = "iem.church.member.list"
    _description = "IEM Member List"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Título", required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    creation_date = fields.Datetime(string="Fecha de creación", related="create_date", readonly=True)

    gender = fields.Selection(
        [("male", "Masculino"), ("female", "Femenino")],
        string="Sexo",
        tracking=True,
    )
    member_status = fields.Selection(
        [
            ("active", "Activo"),
            ("inactive", "Inactivo"),
            ("suspended", "Suspendido"),
        ],
        string="Estado del miembro",
        tracking=True,
    )
    position_filter_ids = fields.Many2many(
        "iem.church.member.position.option",
        "iem_church_member_list_position_rel",
        "list_id",
        "position_id",
        string="Cargos",
        tracking=True,
    )
    predio_id = fields.Many2one("iem.church.predio", string="Predio", tracking=True)
    red_id = fields.Many2one("iem.church.red", string="Red", tracking=True)
    discipulado_id = fields.Many2one("iem.church.discipulado", string="Discipulado", tracking=True)
    celula_id = fields.Many2one("iem.church.celula", string="Célula", tracking=True)
    age_from = fields.Integer(string="Edad mínima", tracking=True)
    age_to = fields.Integer(string="Edad máxima", default=99, tracking=True)

    filter_summary = fields.Text(string="Filtro original", readonly=True, tracking=True)

    show_boolean_extra = fields.Boolean(string="Usar campo Sí/No", default=True, tracking=True)
    boolean_extra_label = fields.Char(string="Título Sí/No", tracking=True)
    show_amount_extra = fields.Boolean(string="Usar campo Monto", default=True, tracking=True)
    amount_extra_label = fields.Char(string="Título Monto", tracking=True)
    show_text_extra = fields.Boolean(string="Usar campo Texto", default=True, tracking=True)
    text_extra_label = fields.Char(string="Título Texto", tracking=True)

    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        default=lambda self: self.env.company.currency_id,
        required=True,
        tracking=True,
    )

    member_line_ids = fields.One2many(
        "iem.church.member.list.line",
        "list_id",
        string="Miembros",
    )
    member_count = fields.Integer(compute="_compute_member_counts", string="Total miembros")
    filter_member_count = fields.Integer(compute="_compute_member_counts", string="Por filtro")
    manual_member_count = fields.Integer(compute="_compute_member_counts", string="Manuales")

    @api.model
    def fields_view_get(self, view_id=None, view_type="form", toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type != "form" or not result.get("arch"):
            return result

        params = self.env.context.get("params") or {}
        record_id = (
            params.get("id")
            or self.env.context.get("active_id")
            or self.env.context.get("id")
        )
        if not record_id:
            return result

        record = self.browse(record_id).exists()
        if not record:
            return result

        arch = etree.XML(result["arch"])
        label_map = {
            "extra_boolean": record.boolean_extra_label,
            "extra_amount": record.amount_extra_label,
            "extra_text": record.text_extra_label,
        }
        for field_name, label in label_map.items():
            if not label:
                continue
            for node in arch.xpath(f"//field[@name='member_line_ids']//field[@name='{field_name}']"):
                node.set("string", label)
        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    @api.depends("member_line_ids.source")
    def _compute_member_counts(self):
        for rec in self:
            rec.member_count = len(rec.member_line_ids)
            rec.filter_member_count = len(rec.member_line_ids.filtered(lambda line: line.source == "filter"))
            rec.manual_member_count = len(rec.member_line_ids.filtered(lambda line: line.source == "manual"))

    @api.constrains("age_from", "age_to")
    def _check_age_bounds(self):
        for rec in self:
            if rec.age_from and rec.age_from < 0:
                raise ValidationError(_("La edad mínima no puede ser negativa."))
            if rec.age_to and rec.age_to < 0:
                raise ValidationError(_("La edad máxima no puede ser negativa."))
            if rec.age_from and rec.age_to and rec.age_from > rec.age_to:
                raise ValidationError(_("La edad mínima no puede ser mayor a la edad máxima."))

    @api.onchange("predio_id")
    def _onchange_predio_id_reset_structure(self):
        for rec in self:
            if rec.red_id and rec.red_id.predio_id != rec.predio_id:
                rec.red_id = False
            if not rec.red_id:
                rec.discipulado_id = False
                rec.celula_id = False

    @api.onchange("red_id")
    def _onchange_red_id_reset_structure(self):
        for rec in self:
            if rec.discipulado_id and rec.discipulado_id.red_id != rec.red_id:
                rec.discipulado_id = False
            if rec.celula_id and rec.discipulado_id and rec.celula_id.discipulado_id != rec.discipulado_id:
                rec.celula_id = False
            if not rec.discipulado_id:
                rec.celula_id = False

    @api.onchange("discipulado_id")
    def _onchange_discipulado_id_reset_structure(self):
        for rec in self:
            if rec.celula_id and rec.celula_id.discipulado_id != rec.discipulado_id:
                rec.celula_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._apply_scope_defaults(vals)
            self._check_scope_for_user(vals)
        records = super().create(vals_list)
        for rec in records:
            rec.with_context(allow_filter_write=True).write({"filter_summary": rec._build_filter_summary()})
            rec.message_post(body=_("Lista creada."))
        return records

    def write(self, vals):
        if self.env.context.get("allow_filter_write"):
            return super().write(vals)
        if self._is_limited_discipulador() and ("name" in vals or vals.get("active") is False):
            foreign_lists = self.filtered(lambda rec: rec.create_uid != self.env.user)
            if foreign_lists:
                raise UserError(
                    _(
                        "No tienes permiso para renombrar o borrar listas creadas por otros usuarios."
                    )
                )
        return super().write(vals)

    def unlink(self):
        if self._is_limited_discipulador():
            foreign_lists = self.filtered(lambda rec: rec.create_uid != self.env.user)
            if foreign_lists:
                raise UserError(
                    _("No tienes permiso para borrar listas creadas por otros usuarios.")
                )
        return super().unlink()

    def _is_limited_discipulador(self):
        user = self.env.user
        return (
            user.has_group("iem_church_management.group_iem_discipulador")
            and not user.has_group("iem_church_management.group_iem_pastor")
            and not user.has_group("iem_church_management.group_iem_pastor_gobierno")
            and not user.has_group("iem_church_management.group_iem_admin")
            and not user.has_group("base.group_system")
        )

    def _apply_scope_defaults(self, vals):
        user = self.env.user
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return
        partner = user.partner_id
        if user.has_group("iem_church_management.group_iem_pastor_gobierno") and partner.predio_id:
            vals.setdefault("predio_id", partner.predio_id.id)
        if user.has_group("iem_church_management.group_iem_pastor"):
            if partner.predio_id:
                vals.setdefault("predio_id", partner.predio_id.id)
            if partner.red_id:
                vals.setdefault("red_id", partner.red_id.id)
        if user.has_group("iem_church_management.group_iem_discipulador"):
            if partner.predio_id:
                vals.setdefault("predio_id", partner.predio_id.id)
            if partner.red_id:
                vals.setdefault("red_id", partner.red_id.id)
            if partner.discipulado_id:
                vals.setdefault("discipulado_id", partner.discipulado_id.id)

    def _check_scope_for_user(self, vals):
        if self.env.context.get("skip_scope_check"):
            return
        user = self.env.user
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return

        partner = user.partner_id
        target_predio = vals.get("predio_id")
        target_red = vals.get("red_id")
        target_discipulado = vals.get("discipulado_id")
        message = _("No tienes permiso para crear listas fuera de tu ámbito (Predio, Red, Discipulado).")

        if user.has_group("iem_church_management.group_iem_pastor_gobierno"):
            if not target_predio:
                raise UserError(message)
            if partner.predio_id and target_predio != partner.predio_id.id:
                raise UserError(message)
        elif user.has_group("iem_church_management.group_iem_pastor"):
            if not target_predio or not target_red:
                raise UserError(message)
            if (
                (partner.predio_id and target_predio != partner.predio_id.id)
                or (partner.red_id and target_red != partner.red_id.id)
            ):
                raise UserError(message)
        elif user.has_group("iem_church_management.group_iem_discipulador"):
            if not target_predio or not target_red or not target_discipulado:
                raise UserError(message)
            if (
                (partner.predio_id and target_predio != partner.predio_id.id)
                or (partner.red_id and target_red != partner.red_id.id)
                or (partner.discipulado_id and target_discipulado != partner.discipulado_id.id)
            ):
                raise UserError(message)

    def _member_domain_from_filter(self):
        self.ensure_one()
        domain = [("is_member", "=", True)]
        if self.gender:
            domain.append(("gender", "=", self.gender))
        if self.member_status:
            domain.append(("member_status", "=", self.member_status))
        if self.position_filter_ids:
            domain.append(("current_position", "in", self.position_filter_ids.mapped("code")))
        if self.predio_id:
            domain.append(("predio_id", "=", self.predio_id.id))
        if self.red_id:
            domain.append(("red_id", "=", self.red_id.id))
        if self.discipulado_id:
            domain.append(("discipulado_id", "=", self.discipulado_id.id))
        if self.celula_id:
            domain.append(("celula_id", "=", self.celula_id.id))

        today = fields.Date.context_today(self)
        if self.age_from:
            max_birthdate = today - relativedelta(years=self.age_from)
            domain.append(("birth_date", "<=", max_birthdate))
        if self.age_to:
            min_birthdate = today - relativedelta(years=self.age_to + 1) + relativedelta(days=1)
            if self.age_from:
                domain.append(("birth_date", ">=", min_birthdate))
            else:
                # With only max age set, keep members without birth date in result.
                domain.extend(["|", ("birth_date", "=", False), ("birth_date", ">=", min_birthdate)])
        if self.age_from:
            domain.append(("birth_date", "!=", False))

        return domain

    def _build_filter_summary(self):
        self.ensure_one()
        parts = []
        if self.gender:
            parts.append(_("Sexo: %s") % dict(self._fields["gender"].selection).get(self.gender))
        if self.member_status:
            parts.append(
                _("Estado: %s")
                % dict(self._fields["member_status"].selection).get(self.member_status)
            )
        if self.position_filter_ids:
            parts.append(_("Cargos: %s") % ", ".join(self.position_filter_ids.mapped("name")))
        if self.predio_id:
            parts.append(_("Predio: %s") % self.predio_id.display_name)
        if self.red_id:
            parts.append(_("Red: %s") % self.red_id.display_name)
        if self.discipulado_id:
            parts.append(_("Discipulado: %s") % self.discipulado_id.display_name)
        if self.celula_id:
            parts.append(_("Célula: %s") % self.celula_id.display_name)
        if self.age_from:
            parts.append(_("Edad mínima: %s") % self.age_from)
        if self.age_to:
            parts.append(_("Edad máxima: %s") % self.age_to)
        return " | ".join(parts) if parts else _("Sin filtros")

    def action_add_members_from_filter(self):
        for rec in self:
            rec.with_context(allow_filter_write=True).write({"filter_summary": rec._build_filter_summary()})
            added_count = rec._populate_members_from_filter()
            rec.message_post(
                body=_("Filtro aplicado. Miembros agregados a la lista: %s") % added_count
            )
        return True

    def action_clear_member_lines(self):
        for rec in self:
            removed_count = len(rec.member_line_ids)
            if removed_count:
                rec.member_line_ids.unlink()
            rec.message_post(body=_("Lista limpiada. Miembros removidos: %s") % removed_count)
        return True

    def _populate_members_from_filter(self):
        self.ensure_one()
        Line = self.env["iem.church.member.list.line"]
        members = self.env["church.member"].search(self._member_domain_from_filter())
        if not members:
            return 0
        existing_member_ids = set(self.member_line_ids.mapped("member_id").ids)
        line_vals = [
            {
                "list_id": self.id,
                "member_id": member.id,
                "source": "filter",
            }
            for member in members
            if member.id not in existing_member_ids
        ]
        if line_vals:
            Line.create(line_vals)
        return len(line_vals)


class IemChurchMemberListLine(models.Model):
    _name = "iem.church.member.list.line"
    _description = "IEM Member List Line"
    _order = "id"

    _sql_constraints = [
        (
            "iem_member_list_member_unique",
            "unique(list_id, member_id)",
            "El miembro ya existe en esta lista.",
        ),
    ]

    list_id = fields.Many2one(
        "iem.church.member.list",
        string="Lista",
        required=True,
        ondelete="cascade",
        index=True,
    )
    member_id = fields.Many2one(
        "church.member",
        string="Miembro",
        required=True,
        ondelete="restrict",
        index=True,
    )
    source = fields.Selection(
        [("filter", "Filtro"), ("manual", "Manual")],
        string="Origen",
        required=True,
        default="manual",
        readonly=True,
    )

    extra_boolean = fields.Boolean()
    extra_amount = fields.Monetary( currency_field="currency_id")
    extra_text = fields.Char()
    currency_id = fields.Many2one(related="list_id.currency_id", store=True, readonly=True)

    predio_id = fields.Many2one(related="member_id.predio_id", store=True, readonly=True)
    red_id = fields.Many2one(related="member_id.red_id", store=True, readonly=True)
    discipulado_id = fields.Many2one(related="member_id.discipulado_id", store=True, readonly=True)
    celula_id = fields.Many2one(related="member_id.celula_id", store=True, readonly=True)

    @api.model
    def fields_view_get(self, view_id=None, view_type="form", toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        label_map = {
            "extra_boolean": self.env.context.get("list_boolean_label"),
            "extra_amount": self.env.context.get("list_amount_label"),
            "extra_text": self.env.context.get("list_text_label"),
        }
        if not any(label_map.values()) or not result.get("arch"):
            return result

        arch = etree.XML(result["arch"])
        for field_name, label in label_map.items():
            if not label:
                continue
            for node in arch.xpath(f"//field[@name='{field_name}']"):
                node.set("string", label)
        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.source == "manual":
                rec.list_id.message_post(body=_("Miembro agregado manualmente: %s") % rec.member_id.display_name)
        return records

    def write(self, vals):
        res = super().write(vals)
        tracked_fields = {"extra_boolean", "extra_amount", "extra_text"}
        if tracked_fields & set(vals.keys()):
            for rec in self:
                changes = []
                if "extra_boolean" in vals:
                    label = rec.list_id.boolean_extra_label or _("Sí/No")
                    changes.append(_("%s: %s") % (label, _("Sí") if rec.extra_boolean else _("No")))
                if "extra_amount" in vals:
                    label = rec.list_id.amount_extra_label or _("Monto")
                    changes.append(_("%s: %s") % (label, rec.extra_amount))
                if "extra_text" in vals:
                    label = rec.list_id.text_extra_label or _("Texto")
                    changes.append(_("%s: %s") % (label, rec.extra_text or "-"))
                if changes:
                    rec.list_id.message_post(
                        body=_("Actualización de %s -> %s")
                        % (rec.member_id.display_name, " | ".join(changes))
                    )
        return res

    def unlink(self):
        logs_by_list = {}
        for rec in self:
            if rec.list_id and rec.member_id:
                logs_by_list.setdefault(rec.list_id, []).append(
                    _("Miembro removido de la lista: %s") % rec.member_id.display_name
                )
        res = super().unlink()
        for list_rec, bodies in logs_by_list.items():
            for body in bodies:
                list_rec.message_post(body=body)
        return res
