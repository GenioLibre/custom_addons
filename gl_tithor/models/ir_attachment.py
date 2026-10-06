from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def check(self, mode, values=None):
        if not self.env.user._is_public():
            return True
        return super().check(mode, values=values)
