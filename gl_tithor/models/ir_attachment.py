from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def _confection_attachment_ids(self):
        self.env.cr.execute(
            "SELECT attachment_id FROM gl_confection_design_attachment_rel "
            "UNION SELECT attachment_id FROM gl_confection_printing_attachment_rel"
        )
        return {row[0] for row in self.env.cr.fetchall()}

    @api.model
    def check(self, mode, values=None):
        allowed_groups = (
            "gl_tithor.group_confection_user",
            "gl_tithor.group_confection_admin",
        )
        if self.env.user.has_group(allowed_groups[0]) or self.env.user.has_group(allowed_groups[1]):
            allowed_ids = self._confection_attachment_ids()
            allowed = self.filtered(lambda attachment: attachment.id in allowed_ids)
            remaining = self - allowed
            if not remaining:
                return True
            return super(IrAttachment, remaining).check(mode, values=values)
        return super().check(mode, values=values)
