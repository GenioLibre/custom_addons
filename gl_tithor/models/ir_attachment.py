from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def check(self, mode, values=None):
        if self.env.user._is_internal():
            return True
        return super().check(mode, values=values)
