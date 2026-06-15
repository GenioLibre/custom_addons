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
    visibility = fields.Selection(
        [("public", "Pública"), ("private", "Privada")],
        string="Visibilidad",
        default="private",
        required=True,
        tracking=True,
    )
    website_registration_enabled = fields.Boolean(
        string="Habilitado para Registro Online",
        default=False,
        tracking=True,
    )
    creator_access_level = fields.Integer(
        string="Nivel del creador",
        compute="_compute_creator_access_level",
        store=True,
        readonly=True,
    )
    creator_scope_role = fields.Selection(
        [
            ("admin", "Administrador"),
            ("pastor_gobierno", "Pastor de Gobierno"),
            ("pastor", "Pastor / Obrero"),
            ("discipulador", "Discipulador"),
            ("other", "Otro"),
        ],
        string="Rol del creador",
        compute="_compute_creator_scope_role",
        store=True,
        readonly=True,
    )
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
    scope_predio_id = fields.Many2one(
        "iem.church.predio",
        string="Predio",
        readonly=True,
        copy=False,
        tracking=True,
    )
    scope_red_id = fields.Many2one(
        "iem.church.red",
        string="Red",
        readonly=True,
        copy=False,
        tracking=True,
    )
    scope_discipulado_id = fields.Many2one(
        "iem.church.discipulado",
        string="Discipulado",
        readonly=True,
        copy=False,
        tracking=True,
    )
    predio_id = fields.Many2one("iem.church.predio", string="Predio", tracking=True)
    red_id = fields.Many2one("iem.church.red", string="Red", tracking=True)
    discipulado_id = fields.Many2one("iem.church.discipulado", string="Discipulado", tracking=True)
    celula_id = fields.Many2one("iem.church.celula", string="Célula", tracking=True)
    age_from = fields.Integer(string="Edad mínima", tracking=True)
    age_to = fields.Integer(string="Edad máxima", default=99, tracking=True)

    filter_summary = fields.Text(string="Filtro original", readonly=True, tracking=True)
    details = fields.Text(string="Detalles", tracking=True)

    show_boolean_extra = fields.Boolean(string="Usar campo Sí/No", default=True, tracking=True)
    boolean_extra_label = fields.Char(string="Título Sí/No", tracking=True)
    show_amount_extra = fields.Boolean(string="Usar campo Monto", default=True, tracking=True)
    amount_extra_label = fields.Char(string="Título Monto", tracking=True)
    show_text_extra = fields.Boolean(string="Usar campo Texto", default=True, tracking=True)
    text_extra_label = fields.Char(string="Título Texto", tracking=True)
    show_image_extra = fields.Boolean(string="Usar campo Imagen", default=True, tracking=True)
    image_extra_label = fields.Char(string="Título Imagen", tracking=True)
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
    member_line_search = fields.Char(string="Buscar en miembros")
    member_count = fields.Integer(compute="_compute_member_counts", string="Total miembros")
    filter_member_count = fields.Integer(compute="_compute_member_counts", string="Por filtro")
    manual_member_count = fields.Integer(compute="_compute_member_counts", string="Manuales")
    can_edit_predio = fields.Boolean(compute="_compute_scope_edit_flags")
    can_edit_red = fields.Boolean(compute="_compute_scope_edit_flags")
    can_edit_discipulado = fields.Boolean(compute="_compute_scope_edit_flags")

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
        member_line_field = result.get("fields", {}).get("member_line_ids", {})
        member_line_views = member_line_field.get("views", {})
        label_map = {
            "extra_boolean": record.boolean_extra_label,
            "extra_amount": record.amount_extra_label,
            "extra_text": record.text_extra_label,
            "extra_image": record.image_extra_label,
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

    @api.depends("create_uid", "create_uid.groups_id")
    def _compute_creator_access_level(self):
        for rec in self:
            rec.creator_access_level = rec._access_level_for_user(rec.create_uid)

    @api.depends("create_uid", "create_uid.groups_id")
    def _compute_creator_scope_role(self):
        for rec in self:
            rec.creator_scope_role = rec._scope_role_for_user(rec.create_uid)

    def _compute_scope_edit_flags(self):
        role = self._scope_role_for_user(self.env.user)
        can_edit_predio = role == "admin"
        can_edit_red = role in {"admin", "pastor_gobierno"}
        can_edit_discipulado = role in {"admin", "pastor_gobierno", "pastor"}
        for rec in self:
            rec.can_edit_predio = can_edit_predio
            rec.can_edit_red = can_edit_red
            rec.can_edit_discipulado = can_edit_discipulado

    @api.model
    def _access_level_for_user(self, user):
        if not user:
            return 0
        if user.has_group("base.group_system") or user.has_group("iem_church_management.group_iem_admin"):
            return 4
        if user.has_group("iem_church_management.group_iem_pastor_gobierno"):
            return 3
        if user.has_group("iem_church_management.group_iem_pastor"):
            return 2
        if user.has_group("iem_church_management.group_iem_discipulador"):
            return 1
        return 0

    @api.model
    def _scope_role_for_user(self, user):
        if not user:
            return "other"
        if user.has_group("base.group_system") or user.has_group("iem_church_management.group_iem_admin"):
            return "admin"
        if user.has_group("iem_church_management.group_iem_pastor_gobierno"):
            return "pastor_gobierno"
        if user.has_group("iem_church_management.group_iem_pastor"):
            return "pastor"
        if user.has_group("iem_church_management.group_iem_discipulador"):
            return "discipulador"
        return "other"

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
            if not self._can_manage_visibility():
                vals["visibility"] = "private"
            self._apply_scope_defaults(vals)
            self._check_scope_field_edit_permissions(vals)
            self._apply_scope_snapshot(vals)
            self._check_scope_for_user(vals)
        records = super().create(vals_list)
        for rec in records:
            rec.with_context(allow_filter_write=True).write({"filter_summary": rec._build_filter_summary()})
            rec.message_post(body=_("Lista creada."))
        return records

    def write(self, vals):
        if self.env.context.get("allow_filter_write"):
            return super().write(vals)
        if "visibility" in vals:
            if not self._can_manage_visibility():
                vals["visibility"] = "private"
        scope_fields = {"predio_id", "red_id", "discipulado_id"}
        if scope_fields & set(vals.keys()):
            for rec in self:
                rec._check_scope_field_edit_permissions(vals)
                merged_vals = {
                    "predio_id": vals.get("predio_id", rec.predio_id.id),
                    "red_id": vals.get("red_id", rec.red_id.id),
                    "discipulado_id": vals.get("discipulado_id", rec.discipulado_id.id),
                }
                rec._check_scope_for_user(merged_vals)
        return super().write(vals)

    def unlink(self):
        if self._is_limited_discipulador():
            raise UserError(_("Los discipuladores no pueden eliminar listas."))
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

    def _can_manage_visibility(self):
        user = self.env.user
        return (
            user.has_group("iem_church_management.group_iem_pastor_gobierno")
            or user.has_group("iem_church_management.group_iem_pastor")
            or user.has_group("iem_church_management.group_iem_discipulador")
            or user.has_group("iem_church_management.group_iem_admin")
            or user.has_group("base.group_system")
        )

    def _apply_scope_defaults(self, vals):
        user = self.env.user
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return
        partner = user.partner_id
        if user.has_group("iem_church_management.group_iem_pastor_gobierno") and partner.predio_id:
            if not vals.get("predio_id"):
                vals["predio_id"] = partner.predio_id.id
        if user.has_group("iem_church_management.group_iem_pastor"):
            if partner.predio_id:
                if not vals.get("predio_id"):
                    vals["predio_id"] = partner.predio_id.id
            if partner.red_id:
                if not vals.get("red_id"):
                    vals["red_id"] = partner.red_id.id
        if user.has_group("iem_church_management.group_iem_discipulador"):
            if partner.predio_id:
                if not vals.get("predio_id"):
                    vals["predio_id"] = partner.predio_id.id
            if partner.red_id:
                if not vals.get("red_id"):
                    vals["red_id"] = partner.red_id.id
            if partner.discipulado_id:
                if not vals.get("discipulado_id"):
                    vals["discipulado_id"] = partner.discipulado_id.id

    def _apply_scope_snapshot(self, vals):
        user = self.env.user
        partner = user.partner_id
        role = self._scope_role_for_user(user)

        if role == "admin":
            return

        if role == "pastor_gobierno":
            vals["scope_predio_id"] = vals.get("predio_id") or partner.predio_id.id or False
            return

        if role == "pastor":
            vals["scope_predio_id"] = vals.get("predio_id") or partner.predio_id.id or False
            vals["scope_red_id"] = vals.get("red_id") or partner.red_id.id or False
            return

        if role == "discipulador":
            vals["scope_predio_id"] = vals.get("predio_id") or partner.predio_id.id or False
            vals["scope_red_id"] = vals.get("red_id") or partner.red_id.id or False
            vals["scope_discipulado_id"] = (
                vals.get("discipulado_id") or partner.discipulado_id.id or False
            )

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
            if target_predio and partner.predio_id and target_predio != partner.predio_id.id:
                raise UserError(message)
        elif user.has_group("iem_church_management.group_iem_pastor"):
            if (
                (target_predio and partner.predio_id and target_predio != partner.predio_id.id)
                or (target_red and partner.red_id and target_red != partner.red_id.id)
            ):
                raise UserError(message)
        elif user.has_group("iem_church_management.group_iem_discipulador"):
            if (
                (target_predio and partner.predio_id and target_predio != partner.predio_id.id)
                or (target_red and partner.red_id and target_red != partner.red_id.id)
                or (
                    target_discipulado
                    and partner.discipulado_id
                    and target_discipulado != partner.discipulado_id.id
                )
            ):
                raise UserError(message)

    def _check_scope_field_edit_permissions(self, vals):
        role = self._scope_role_for_user(self.env.user)
        if role == "admin":
            return

        locked_fields_by_role = {
            "pastor_gobierno": {"predio_id"},
            "pastor": {"predio_id", "red_id"},
            "discipulador": {"predio_id", "red_id", "discipulado_id"},
        }
        locked_fields = locked_fields_by_role.get(role, set())
        if not locked_fields:
            return

        partner = self.env.user.partner_id
        allowed_values = {
            "predio_id": partner.predio_id.id or False,
            "red_id": partner.red_id.id or False,
            "discipulado_id": partner.discipulado_id.id or False,
        }

        for field_name in locked_fields:
            if field_name not in vals:
                continue
            new_value = vals.get(field_name) or False
            if self:
                current_values = set(self.mapped(field_name).ids)
                if new_value in current_values and len(current_values) == 1:
                    continue
            if new_value != allowed_values[field_name]:
                raise UserError(_("No tienes permiso para modificar este campo en la lista."))

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

    def action_export_member_list_xlsx(self):
        self.ensure_one()
        members = self.member_line_ids.mapped("member_id")
        today = fields.Date.context_today(self)
        safe_name = (self.name or "lista").strip().replace(" ", "_")
        filename = f"{safe_name}_{fields.Date.to_string(today)}.xlsx"
        boolean_title = self.boolean_extra_label or _("Sí/No")
        amount_title = self.amount_extra_label or _("Monto")
        text_title = self.text_extra_label or _("Texto")
        extra_headers = [boolean_title, amount_title, text_title]
        values_by_member = {}
        for line in self.member_line_ids:
            values_by_member[line.member_id.id] = [
                _("Sí") if line.extra_boolean else _("No"),
                line.extra_amount or 0.0,
                line.extra_text or "",
            ]
        return self.env["church.member"]._export_basic_list_xlsx(
            members,
            filename=filename,
            extra_headers=extra_headers,
            extra_values_by_member=values_by_member,
        )

    def action_print_member_registration_forms(self):
        self.ensure_one()
        members = self.member_line_ids.mapped("member_id")
        if not members:
            raise UserError(_("La lista no tiene miembros para imprimir."))
        return self.env.ref("iem_church_management.action_report_church_member_registration").report_action(members)

    def _member_domain_by_scope(self):
        self.ensure_one()
        domain = [("is_member", "=", True)]
        if self.predio_id:
            domain.append(("predio_id", "=", self.predio_id.id))
        if self.red_id:
            domain.append(("red_id", "=", self.red_id.id))
        if self.discipulado_id:
            domain.append(("discipulado_id", "=", self.discipulado_id.id))
        return domain

    def _website_member_domain(self):
        self.ensure_one()
        return self._member_domain_by_scope()

    def _website_has_extra_step(self):
        self.ensure_one()
        return bool(
            self.show_boolean_extra
            or self.show_amount_extra
            or self.show_text_extra
            or self.show_image_extra
        )


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

    extra_boolean = fields.Boolean(string="Si/No")
    extra_amount = fields.Monetary(string="Monto", currency_field="currency_id")
    extra_text = fields.Char(string="Notas")
    extra_image = fields.Binary(string="Imagen", attachment=True)
    currency_id = fields.Many2one(related="list_id.currency_id", store=True, readonly=True)

    member_name = fields.Char(related="member_id.name", store=True, readonly=True)
    member_document = fields.Char(related="member_id.vat", store=True, readonly=True)
    member_code = fields.Char(related="member_id.member_code", store=True, readonly=True)
    predio_id = fields.Many2one(related="member_id.predio_id", store=True, readonly=True)
    red_id = fields.Many2one(related="member_id.red_id", store=True, readonly=True)
    discipulado_id = fields.Many2one(related="member_id.discipulado_id", store=True, readonly=True)
    celula_id = fields.Many2one(related="member_id.celula_id", store=True, readonly=True)

    @api.onchange("list_id")
    def _onchange_list_id_member_domain(self):
        if not self.list_id:
            return {"domain": {"member_id": [("is_member", "=", True)]}}
        return {"domain": {"member_id": self.list_id._member_domain_by_scope()}}

    @api.model
    def fields_view_get(self, view_id=None, view_type="form", toolbar=False, submenu=False):
        result = super().fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        params = self.env.context.get("params") or {}
        record_id = (
            params.get("id")
            or self.env.context.get("active_id")
            or self.env.context.get("id")
        )
        line = self.browse(record_id).exists() if record_id else self.env["iem.church.member.list.line"]
        label_map = {
            "extra_boolean": self.env.context.get("list_boolean_label") or (line.list_id.boolean_extra_label if line else False),
            "extra_amount": self.env.context.get("list_amount_label") or (line.list_id.amount_extra_label if line else False),
            "extra_text": self.env.context.get("list_text_label") or (line.list_id.text_extra_label if line else False),
            "extra_image": self.env.context.get("list_image_label") or (line.list_id.image_extra_label if line else False),
        }
        if not any(label_map.values()) or not result.get("arch"):
            return result

        arch = etree.XML(result["arch"])
        for field_name, label in label_map.items():
            if not label:
                continue
            if result.get("fields", {}).get(field_name):
                result["fields"][field_name]["string"] = label
            for node in arch.xpath(f"//field[@name='{field_name}']"):
                node.set("string", label)
        result["arch"] = etree.tostring(arch, encoding="unicode")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        self._check_member_scope_for_vals_list(vals_list)
        records = super().create(vals_list)
        for rec in records:
            if rec.source == "manual":
                rec.list_id.message_post(body=_("Miembro agregado manualmente: %s") % rec.member_id.display_name)
        return records

    def write(self, vals):
        self._check_member_scope_for_write(vals)
        res = super().write(vals)
        tracked_fields = {"extra_boolean", "extra_amount", "extra_text", "extra_image"}
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
                if "extra_image" in vals:
                    label = rec.list_id.image_extra_label or _("Imagen")
                    changes.append(_("%s: %s") % (label, _("Cargada") if rec.extra_image else _("Eliminada")))
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


    @api.model
    def _check_member_scope_for_vals_list(self, vals_list):
        for vals in vals_list:
            list_id = vals.get("list_id")
            member_id = vals.get("member_id")
            if not list_id or not member_id:
                continue
            list_rec = self.env["iem.church.member.list"].browse(list_id).exists()
            member = self.env["church.member"].browse(member_id).exists()
            self._check_member_scope(member, list_rec)

    def _check_member_scope_for_write(self, vals):
        for rec in self:
            list_rec = (
                self.env["iem.church.member.list"].browse(vals["list_id"]).exists()
                if vals.get("list_id")
                else rec.list_id
            )
            member = (
                self.env["church.member"].browse(vals["member_id"]).exists()
                if vals.get("member_id")
                else rec.member_id
            )
            self._check_member_scope(member, list_rec)

    @api.model
    def _check_member_scope(self, member, list_rec):
        if not member or not list_rec:
            return

        user = self.env.user
        partner = user.partner_id
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return

        if user.has_group("iem_church_management.group_iem_discipulador"):
            if partner.discipulado_id and member.discipulado_id != partner.discipulado_id:
                raise UserError(
                    _("Como discipulador solo puedes agregar o modificar miembros de tu discipulado.")
                )
            return

        if user.has_group("iem_church_management.group_iem_pastor"):
            if partner.red_id and member.red_id != partner.red_id:
                raise UserError(
                    _("Como obrero o pastor solo puedes agregar o modificar miembros de tu red.")
                )
            return
