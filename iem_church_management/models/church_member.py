import random
import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ChurchMember(models.Model):
    _name = "church.member"
    _description = "Church Member"
    _inherits = {"res.partner": "partner_id"}

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
        string="Contacto",
    )

    is_member = fields.Boolean(
        string="Es Miembro de la Iglesia",
        related="partner_id.is_member",
        store=True,
        readonly=False,
    )
    first_name = fields.Char(
        string="Nombre",
        compute="_compute_name_parts",
        inverse="_inverse_name_parts",
        store=True,
    )
    last_name = fields.Char(
        string="Apellido",
        compute="_compute_name_parts",
        inverse="_inverse_name_parts",
        store=True,
    )
    member_code = fields.Char(string="Codigo de miembro", readonly=True, copy=False)
    member_status = fields.Selection(
        [
            ("active", "Activo"),
            ("inactive", "Inactivo"),
            ("suspended", "Suspendido"),
        ],
        string="Estado del miembro",
        default="active",
    )
    membership_date = fields.Date(string="Fecha de ingreso")
    predio_id = fields.Many2one("iem.church.predio", string="Predio")
    red_id = fields.Many2one("iem.church.red", string="Red")
    discipulado_id = fields.Many2one("iem.church.discipulado", string="Discipulado")
    celula_id = fields.Many2one("iem.church.celula", string="Celula")
    current_position = fields.Selection(
        [
            ("pastor_gobierno", "Pastor de Gobierno"),
            ("pastor", "Pastor"),
            ("obrero", "Obrero"),
            ("discipulador", "Discipulador"),
            ("lider_celula", "Lider de celula"),
            ("lider_entrenamiento", "Lider en entrenamiento"),
            ("miembro", "Miembro"),
            ("participante", "Participante"),
            ("visitante", "Visitante"),
        ],
        string="Cargo actual",
    )

    baptism_date = fields.Date(string="Fecha de bautismo")
    spiritual_encounter_date = fields.Date(string="Fecha encuentro con Dios")

    marital_status = fields.Selection(
        [
            ("single", "Soltero(a)"),
            ("married", "Casado(a)"),
            ("divorced", "Divorciado(a)"),
            ("widowed", "Viudo(a)"),
            ("separated", "Separado(a)"),
            ("union", "Union libre"),
        ],
        string="Estado civil",
    )
    spouse_id = fields.Many2one("res.partner", string="Conyuge")
    child_ids = fields.Many2many(
        "res.partner",
        "church_member_child_rel",
        "member_id",
        "partner_id",
        string="Hijos",
    )

    last_update_date = fields.Datetime(
        related="write_date",
        string="Fecha ultima actualizacion",
        readonly=True,
    )
    registered_by_id = fields.Many2one(
        "res.users",
        related="create_uid",
        string="Usuario que registro",
        readonly=True,
    )

    has_portal_user = fields.Boolean(
        string="Tiene usuario portal",
        compute="_compute_has_portal_user",
    )
    has_user = fields.Boolean(
        string="Tiene usuario",
        compute="_compute_has_portal_user",
    )

    @api.depends("partner_id.user_ids")
    def _compute_has_portal_user(self):
        for member in self:
            users = member.partner_id.user_ids
            member.has_portal_user = any(user.share for user in users)
            member.has_user = bool(users)

    def _get_access_group_ids(self):
        self.ensure_one()
        group_user = self.env.ref("base.group_user")
        position_group_map = {
            "pastor_gobierno": "iem_church_management.group_iem_pastor_gobierno",
            "pastor": "iem_church_management.group_iem_pastor",
            "discipulador": "iem_church_management.group_iem_discipulador",
        }
        group_ids = [group_user.id]
        group_xmlid = position_group_map.get(self.current_position)
        if group_xmlid:
            group_ids.append(self.env.ref(group_xmlid).id)
        return group_ids

    @api.depends("name")
    def _compute_name_parts(self):
        for member in self:
            name = (member.name or "").strip()
            if name and "," in name:
                last, first = [part.strip() for part in name.split(",", 1)]
                member.first_name = first
                member.last_name = last
            else:
                member.first_name = name
                member.last_name = ""

    @api.constrains("first_name", "last_name")
    def _check_required_name_parts(self):
        for member in self:
            if not (member.first_name or "").strip() or not (member.last_name or "").strip():
                raise ValidationError(_("Nombre y Apellido son obligatorios."))

    def _check_scope_for_user(self, vals=None):
        user = self.env.user
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return
        partner = user.partner_id
        target_predio = vals.get("predio_id") if vals else self.predio_id.id
        target_red = vals.get("red_id") if vals else self.red_id.id
        target_discipulado = vals.get("discipulado_id") if vals else self.discipulado_id.id

        if user.has_group("iem_church_management.group_iem_pastor_gobierno"):
            if partner.predio_id and target_predio and partner.predio_id.id != target_predio:
                raise UserError(_("No tienes permiso para agregar registros fuera de tu ambito (Predio, Red, Discipulado)."))
        elif user.has_group("iem_church_management.group_iem_pastor"):
            if (
                (partner.predio_id and target_predio and partner.predio_id.id != target_predio)
                or (partner.red_id and target_red and partner.red_id.id != target_red)
            ):
                raise UserError(_("No tienes permiso para agregar registros fuera de tu ambito (Predio, Red, Discipulado)."))
        elif user.has_group("iem_church_management.group_iem_discipulador"):
            if (
                (partner.predio_id and target_predio and partner.predio_id.id != target_predio)
                or (partner.red_id and target_red and partner.red_id.id != target_red)
                or (partner.discipulado_id and target_discipulado and partner.discipulado_id.id != target_discipulado)
            ):
                raise UserError(_("No tienes permiso para agregar registros fuera de tu ambito (Predio, Red, Discipulado)."))

    @api.onchange("predio_id")
    def _onchange_predio_id_reset_structure(self):
        for member in self:
            if member.red_id and member.red_id.predio_id != member.predio_id:
                member.red_id = False
            if member.red_id:
                continue
            member.discipulado_id = False
            member.celula_id = False

    @api.onchange("red_id")
    def _onchange_red_id_reset_structure(self):
        for member in self:
            if member.discipulado_id and member.discipulado_id.red_id != member.red_id:
                member.discipulado_id = False
            if member.celula_id and member.discipulado_id and member.celula_id.discipulado_id != member.discipulado_id:
                member.celula_id = False
            if not member.discipulado_id:
                member.celula_id = False

    @api.onchange("discipulado_id")
    def _onchange_discipulado_id_reset_structure(self):
        for member in self:
            if member.celula_id and member.celula_id.discipulado_id != member.discipulado_id:
                member.celula_id = False

    def _inverse_name_parts(self):
        for member in self:
            first = (member.first_name or "").strip()
            last = (member.last_name or "").strip()
            if first and last:
                member.name = f"{last}, {first}"
            elif first:
                member.name = first
            elif last:
                member.name = last
            else:
                member.name = ""

    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env["res.partner"]
        partner_fields = Partner._fields
        for vals in vals_list:
            self._check_scope_for_user(vals)
            identification_type_id = vals.get("l10n_latam_identification_type_id")
            identification_type = self.env["l10n_latam.identification.type"].browse(
                identification_type_id
            )
            vat = (vals.get("vat") or "").strip()
            if identification_type and vat:
                existing_partner = self.env["res.partner"].search(
                    [
                        ("l10n_latam_identification_type_id", "=", identification_type_id),
                        ("vat", "=", vat),
                    ],
                    limit=1,
                )
                if existing_partner:
                    raise ValidationError(
                        _("El documento ya esta registrado en el contacto: %s.")
                        % existing_partner.display_name
                    )
            if not vals.get("partner_id"):
                partner_vals = {k: v for k, v in vals.items() if k in partner_fields}
                if not partner_vals.get("name"):
                    partner_vals["name"] = self._build_partner_name(
                        vals.get("first_name"),
                        vals.get("last_name"),
                    )
                partner = Partner.create(partner_vals)
                vals["partner_id"] = partner.id
            else:
                partner_vals = {k: v for k, v in vals.items() if k in partner_fields}
                if partner_vals:
                    Partner.browse(vals["partner_id"]).write(partner_vals)
            if not vals.get("member_code"):
                vals["member_code"] = self._generate_member_code(
                    vals.get("first_name") or partner_vals.get("name"),
                    vals.get("last_name"),
                )
        return super().create(vals_list)

    def write(self, vals):
        if {"predio_id", "red_id", "discipulado_id"} & set(vals.keys()):
            for member in self:
                merged = {
                    "predio_id": vals.get("predio_id", member.predio_id.id),
                    "red_id": vals.get("red_id", member.red_id.id),
                    "discipulado_id": vals.get("discipulado_id", member.discipulado_id.id),
                }
                member._check_scope_for_user(merged)
        if "vat" in vals or "l10n_latam_identification_type_id" in vals:
            for member in self:
                identification_type_id = vals.get(
                    "l10n_latam_identification_type_id",
                    member.l10n_latam_identification_type_id.id,
                )
                vat = (vals.get("vat") or member.vat or "").strip()
                if identification_type_id and vat:
                    existing_partner = self.env["res.partner"].search(
                        [
                            ("l10n_latam_identification_type_id", "=", identification_type_id),
                            ("vat", "=", vat),
                            ("id", "!=", member.partner_id.id),
                        ],
                        limit=1,
                    )
                    if existing_partner:
                        raise ValidationError(
                            _(
                                "El documento ya esta registrado en el contacto: %s."
                            )
                            % existing_partner.display_name
                        )
        res = super().write(vals)
        partner_sync_fields = {"predio_id", "red_id", "discipulado_id", "celula_id", "membership_date"}
        if partner_sync_fields & set(vals.keys()):
            for member in self:
                partner_vals = {k: vals[k] for k in partner_sync_fields if k in vals}
                if partner_vals:
                    member.partner_id.write(partner_vals)
        if {"first_name", "last_name", "name"} & set(vals.keys()):
            for member in self:
                if member._needs_member_code_refresh():
                    member.member_code = member._generate_member_code(
                        member.first_name or member.name,
                        member.last_name,
                    )
        return res

    @api.constrains("predio_id", "red_id", "discipulado_id", "celula_id")
    def _check_membership_chain(self):
        for member in self:
            if member.red_id and member.predio_id and member.red_id.predio_id != member.predio_id:
                raise ValidationError(_("La Red no pertenece al Predio seleccionado."))
            if (
                member.discipulado_id
                and member.red_id
                and member.discipulado_id.red_id != member.red_id
            ):
                raise ValidationError(_("El Discipulado no pertenece a la Red seleccionada."))
            if (
                member.celula_id
                and member.discipulado_id
                and member.celula_id.discipulado_id != member.discipulado_id
            ):
                raise ValidationError(_("La Celula no pertenece al Discipulado seleccionado."))

    @api.model
    def _generate_member_code(self, first_name, last_name):
        def _letters(value, count):
            if not value:
                return "X" * count
            letters = "".join(ch for ch in value.upper() if ch.isalpha())
            letters = letters.ljust(count, "X")
            return letters[:count]

        prefix = f"{_letters(first_name, 2)}{_letters(last_name, 2)}"
        for _ in range(100):
            number = random.randint(1000, 9999)
            code = f"{prefix}{number}"
            if not self.search_count([("member_code", "=", code)]):
                return code
        return f"{prefix}{random.randint(100000, 999999)}"

    @api.model
    def _build_partner_name(self, first_name, last_name):
        first = (first_name or "").strip()
        last = (last_name or "").strip()
        if first and last:
            return f"{first}, {last}"
        return first or last or ""

    def _needs_member_code_refresh(self):
        if not self.member_code:
            return True
        prefix = self.member_code[:4]
        return "X" in prefix

    @api.model
    def _is_dni_type(self, identification_type):
        if not identification_type:
            return False
        # Odoo 18 (l10n_latam_base) no tiene campo `code`
        code = (getattr(identification_type, "code", "") or "").strip().upper()
        l10n_pe_vat_code = (getattr(identification_type, "l10n_pe_vat_code", "") or "").strip().upper()
        name = (identification_type.name or "").strip().upper()
        return code == "DNI" or l10n_pe_vat_code == "1" or "DNI" in name

    @api.onchange("vat")
    def _onchange_vat_fetch_dni(self):
        for member in self:
            dni = (member.vat or "").strip()
            if not member.l10n_latam_identification_type_id or not dni:
                continue

            existing_partner = self.env["res.partner"].search(
                [
                    (
                        "l10n_latam_identification_type_id",
                        "=",
                        member.l10n_latam_identification_type_id.id,
                    ),
                    ("vat", "=", dni),
                    ("id", "!=", member.partner_id.id),
                ],
                limit=1,
            )
            if existing_partner:
                return {
                    "warning": {
                        "title": _("Documento"),
                        "message": _(
                            "El documento ya esta registrado en el contacto: %s."
                        )
                        % existing_partner.display_name,
                    }
                }

            if not self._is_dni_type(member.l10n_latam_identification_type_id):
                return {
                    "warning": {
                        "title": _("DNI"),
                        "message": _("Seleccione tipo de documento DNI."),
                    }
                }

            if not dni.isdigit() or len(dni) != 8:
                return {
                    "warning": {
                        "title": _("DNI"),
                        "message": _("Ingrese un DNI valido de 8 digitos."),
                    }
                }

            token = self.env["ir.config_parameter"].sudo().get_param("iem.dni_api_token")
            if not token:
                return {
                    "warning": {
                        "title": _("DNI"),
                        "message": _("Falta configurar el token de la API de DNI."),
                    }
                }

            try:
                response = requests.post(
                    "https://api.json.pe/api/dni",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"dni": dni},
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                return {
                    "warning": {
                        "title": _("DNI"),
                        "message": _("Error consultando la API de DNI: %s") % exc,
                    }
                }

            data = payload.get("data") or {}
            nombres = (data.get("nombres") or "").strip()
            ap_pat = (data.get("apellido_paterno") or "").strip()
            ap_mat = (data.get("apellido_materno") or "").strip()
            if not (nombres or ap_pat or ap_mat):
                return {
                    "warning": {
                        "title": _("DNI"),
                        "message": _("No se encontraron datos para el DNI ingresado."),
                    }
                }

            last_name = " ".join(part for part in [ap_pat, ap_mat] if part).strip()
            if nombres:
                member.first_name = nombres.title()
            if last_name:
                member.last_name = last_name.title()

    def action_fetch_dni(self):
        self.ensure_one()
        dni = (self.vat or "").strip()
        if not self._is_dni_type(self.l10n_latam_identification_type_id):
            return self._notify(_("DNI"), _("Seleccione tipo de documento DNI."), "warning")
        if not dni.isdigit() or len(dni) != 8:
            return self._notify(_("DNI"), _("Ingrese un DNI valido de 8 digitos."), "warning")

        existing_partner = self.env["res.partner"].search(
            [
                (
                    "l10n_latam_identification_type_id",
                    "=",
                    self.l10n_latam_identification_type_id.id,
                ),
                ("vat", "=", dni),
                ("id", "!=", self.partner_id.id),
            ],
            limit=1,
        )
        if existing_partner:
            return self._notify(
                _("DNI"),
                _("El DNI ya esta registrado en el contacto: %s.") % existing_partner.display_name,
                "warning",
            )

        token = self.env["ir.config_parameter"].sudo().get_param("iem.dni_api_token")
        if not token:
            return self._notify(_("DNI"), _("Falta configurar el token de la API de DNI."), "warning")

        try:
            response = requests.post(
                "https://api.json.pe/api/dni",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"dni": dni},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return self._notify(
                _("DNI"),
                _("Error consultando la API de DNI: %s") % exc,
                "danger",
            )

        data = payload.get("data") or {}
        nombres = (data.get("nombres") or "").strip()
        ap_pat = (data.get("apellido_paterno") or "").strip()
        ap_mat = (data.get("apellido_materno") or "").strip()
        if not (nombres or ap_pat or ap_mat):
            return self._notify(
                _("DNI"),
                _("No se encontraron datos para el DNI ingresado."),
                "warning",
            )

        last_name = " ".join(part for part in [ap_pat, ap_mat] if part).strip()
        vals = {}
        if nombres:
            vals["first_name"] = nombres.title()
        if last_name:
            vals["last_name"] = last_name.title()
        if vals:
            self.write(vals)
            return self._notify(
                _("DNI"),
                _("Datos actualizados correctamente."),
                "success",
                sticky=False,
            )
        return True

    def action_grant_access(self):
        self.ensure_one()
        email = (self.email or "").strip().lower()
        if not email:
            raise UserError(_("El contacto debe tener un correo para crear el usuario."))
        group_ids = self._get_access_group_ids()

        existing_user = self.partner_id.user_ids[:1]
        if existing_user:
            existing_user.sudo().write({"groups_id": [(6, 0, group_ids)]})
            return existing_user._action_show()

        existing_user = self.env["res.users"].sudo().search([("login", "=", email)], limit=1)
        if existing_user:
            raise UserError(_("Ya existe un usuario con el correo: %s.") % email)

        user = self.env["res.users"].sudo().create(
            {
                "name": self.name,
                "login": email,
                "partner_id": self.partner_id.id,
                "groups_id": [(6, 0, group_ids)],
                "company_id": self.env.company.id,
                "company_ids": [(6, 0, [self.env.company.id])],
                "share": False,
            }
        )
        user.action_reset_password()
        return user._action_show()

    def action_sync_access(self):
        self.ensure_one()
        users = self.partner_id.user_ids
        if not users:
            return self.action_grant_access()
        group_ids = self._get_access_group_ids()
        users.sudo().write({"groups_id": [(6, 0, group_ids)]})
        return users[0]._action_show()

    def action_revoke_access(self):
        self.ensure_one()
        users = self.partner_id.user_ids
        if not users:
            return True
        users.sudo().unlink()
        return True

    def unlink(self):
        partners = self.mapped("partner_id")
        res = super(ChurchMember, self.with_context(skip_church_member_partner_cleanup=True)).unlink()
        if not self.env.context.get("skip_church_member_partner_cleanup") and partners:
            partners.with_context(skip_church_member_partner_cleanup=True).unlink()
        return res

    def _notify(self, title, message, notif_type, sticky=False):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "sticky": sticky,
                "type": notif_type,
            },
        }
