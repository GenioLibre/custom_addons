from odoo import _, models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _notify_security_setting_update(self, subject, content, mail_values=None, **kwargs):
        """Send security update emails with a custom layout without Odoo branding footer."""
        mail_create_values = []
        for user in self:
            body_html = self.env["ir.qweb"]._render(
                "mail.account_security_setting_update",
                user._notify_security_setting_update_prepare_values(content, **kwargs),
                minimal_qcontext=True,
            )

            body_html = self.env["mail.render.mixin"]._render_encapsulate(
                "iem_church_management.mail_notification_light_no_brand",
                body_html,
                add_context={
                    "message": self.env["mail.message"].sudo().new(dict(body=body_html, record_name=user.name)),
                    "model_description": _("Account"),
                    "company": user.company_id,
                },
            )

            vals = {
                "auto_delete": True,
                "body_html": body_html,
                "author_id": self.env.user.partner_id.id,
                "email_from": (
                    user.company_id.partner_id.email_formatted
                    or self.env.user.email_formatted
                    or self.env.ref("base.user_root").email_formatted
                ),
                "email_to": kwargs.get("force_email") or user.email_formatted,
                "subject": subject,
            }

            if mail_values:
                vals.update(mail_values)

            mail_create_values.append(vals)

        self.env["mail.mail"].sudo().create(mail_create_values)
