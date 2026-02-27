from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IemFinancialContributionType(models.Model):
    _name = "iem.financial.contribution.type"
    _description = "IEM Financial Contribution Type"
    _order = "sequence, name"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "iem_financial_contribution_type_name_uniq",
            "unique(name)",
            "El tipo de contribución ya existe.",
        ),
    ]


class IemFinancialPaymentMethod(models.Model):
    _name = "iem.financial.payment.method"
    _description = "IEM Financial Payment Method"
    _order = "sequence, name"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "iem_financial_payment_method_name_uniq",
            "unique(name)",
            "El método de pago ya existe.",
        ),
    ]


class IemFinancialContribution(models.Model):
    _name = "iem.financial.contribution"
    _description = "IEM Financial Contribution"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "registration_date desc, id desc"

    MONTH_SELECTION = [
        ("1", "Enero"),
        ("2", "Febrero"),
        ("3", "Marzo"),
        ("4", "Abril"),
        ("5", "Mayo"),
        ("6", "Junio"),
        ("7", "Julio"),
        ("8", "Agosto"),
        ("9", "Septiembre"),
        ("10", "Octubre"),
        ("11", "Noviembre"),
        ("12", "Diciembre"),
    ]

    name = fields.Char(string="Referencia", copy=False, readonly=True, default=lambda self: _("Nuevo"))
    member_id = fields.Many2one("church.member", string="Miembro")

    predio_id = fields.Many2one("iem.church.predio", string="Predio", index=True)
    red_id = fields.Many2one("iem.church.red", string="Red", index=True)
    discipulado_id = fields.Many2one("iem.church.discipulado", string="Discipulado", index=True)

    registration_date = fields.Date(
        string="Fecha de registro",
        default=fields.Date.context_today,
        tracking=True,
    )
    contribution_type_id = fields.Many2one(
        "iem.financial.contribution.type",
        string="Tipo de contribución",
        ondelete="restrict",
    )
    contribution_month = fields.Selection(MONTH_SELECTION, string="Mes de contribución", tracking=True)
    contribution_year = fields.Integer(string="Año de contribución", tracking=True)

    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount = fields.Monetary(string="Monto", currency_field="currency_id", required=True, tracking=True)

    state = fields.Selection(
        [("draft", "Borrador"), ("confirmed", "Confirmado"), ("cancelled", "Anulado")],
        string="Estado",
        default="draft",
        tracking=True,
    )
    payment_method_id = fields.Many2one(
        "iem.financial.payment.method",
        string="Método de pago",
        ondelete="restrict",
    )
    reference = fields.Char(string="Nro. operación / voucher")
    note = fields.Text(string="Observación")

    @api.onchange("member_id")
    def _onchange_member_id_scope(self):
        for rec in self:
            rec._copy_scope_from_member()

    @api.onchange("registration_date")
    def _onchange_registration_date(self):
        for rec in self:
            rec._set_period_from_registration_date(force=True)

    def _copy_scope_from_member(self):
        for rec in self:
            if rec.member_id:
                rec.predio_id = rec.member_id.predio_id
                rec.red_id = rec.member_id.red_id
                rec.discipulado_id = rec.member_id.discipulado_id

    def _set_period_from_registration_date(self, force=False):
        for rec in self:
            if not rec.registration_date:
                continue
            if force or not rec.contribution_month:
                rec.contribution_month = str(rec.registration_date.month)
            if force or not rec.contribution_year:
                rec.contribution_year = rec.registration_date.year

    def _scope_error_message(self):
        return _("No tienes permiso para registrar contribuciones fuera de tu ámbito (Predio, Red, Discipulado).")

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

    def _check_scope_for_user(self, vals=None):
        if self.env.context.get("skip_scope_check"):
            return

        user = self.env.user
        if user.has_group("iem_church_management.group_iem_admin") or user.has_group("base.group_system"):
            return

        partner = user.partner_id
        if vals is None:
            target_predio = self.predio_id.id
            target_red = self.red_id.id
            target_discipulado = self.discipulado_id.id
        else:
            target_predio = vals.get("predio_id")
            target_red = vals.get("red_id")
            target_discipulado = vals.get("discipulado_id")

        message = self._scope_error_message()

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("member_id"):
                member = self.env["church.member"].browse(vals["member_id"])
                vals.setdefault("predio_id", member.predio_id.id)
                vals.setdefault("red_id", member.red_id.id)
                vals.setdefault("discipulado_id", member.discipulado_id.id)

            vals.setdefault("registration_date", fields.Date.context_today(self))
            if vals.get("registration_date"):
                reg_date = fields.Date.to_date(vals["registration_date"])
                vals.setdefault("contribution_month", str(reg_date.month))
                vals.setdefault("contribution_year", reg_date.year)

            self._apply_scope_defaults(vals)
            self._check_scope_for_user(vals)

            if not vals.get("name") or vals.get("name") == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iem.financial.contribution") or _("Nuevo")

        return super().create(vals_list)

    def write(self, vals):
        if vals.get("member_id"):
            member = self.env["church.member"].browse(vals["member_id"])
            vals.setdefault("predio_id", member.predio_id.id)
            vals.setdefault("red_id", member.red_id.id)
            vals.setdefault("discipulado_id", member.discipulado_id.id)

        if vals.get("registration_date"):
            reg_date = fields.Date.to_date(vals["registration_date"])
            vals.setdefault("contribution_month", str(reg_date.month))
            vals.setdefault("contribution_year", reg_date.year)

        if {"predio_id", "red_id", "discipulado_id"} & set(vals.keys()):
            for rec in self:
                merged = {
                    "predio_id": vals.get("predio_id", rec.predio_id.id),
                    "red_id": vals.get("red_id", rec.red_id.id),
                    "discipulado_id": vals.get("discipulado_id", rec.discipulado_id.id),
                }
                rec._check_scope_for_user(merged)

        return super().write(vals)

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_set_draft(self):
        self.write({"state": "draft"})
