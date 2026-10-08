from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _check_access(self, operation):
        return None

    @api.model
    def check(self, mode, values=None):
        return True
