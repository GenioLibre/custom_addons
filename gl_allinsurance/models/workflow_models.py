from odoo import api, fields, models


WORKFLOW_TYPE_SELECTION = [
    ("homeowners", "Homeowners"),
    ("contents", "Contents"),
    ("condo", "Condo"),
    ("health", "Health"),
    ("auto", "Auto"),
]

TEAM_SOURCE_SELECTION = [
    ("website", "Website"),
    ("phil", "Phil"),
]

YES_NO_SELECTION = [
    ("yes", "Yes"),
    ("no", "No"),
]

PROCEEDING_SELECTION = [
    ("yes", "Yes"),
    ("no", "No"),
    ("pending", "Pending"),
]

PROCESSING_STATUS_SELECTION = [
    ("draft", "Draft"),
    ("in_progress", "In Progress"),
    ("waiting", "Waiting"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
]

PENDING_STATUS_SELECTION = [
    ("pending", "Pending"),
    ("follow_up", "Follow Up"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
]

LETTER_TYPE_SELECTION = [
    ("quote", "Quote"),
    ("follow_up", "Follow Up"),
    ("closing", "Closing"),
    ("remodel", "Remodel"),
    ("general", "General"),
]


class GlWorkflow(models.Model):
    _name = "gl.workflow"
    _description = "Work Flow"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "quote_date desc, id desc"
    _rec_name = "quote_number"

    quote_number = fields.Char(string="Quote #", required=True, tracking=True, index=True)
    quote_date = fields.Date(string="Quote Date", tracking=True)
    partner_id = fields.Many2one("res.partner", string="Client Information", required=True, tracking=True)
    workflow_type = fields.Selection(WORKFLOW_TYPE_SELECTION, string="Type", required=True, tracking=True)
    quote_request_date = fields.Date(string="Quote Request Date", tracking=True)
    premium_quote = fields.Char(string="Premium / Quote", tracking=True)
    quote_sent = fields.Selection(YES_NO_SELECTION, string="Quote Sent", tracking=True)
    closing_remodel = fields.Char(string="Closing / Remodel", tracking=True)
    team_source = fields.Selection(TEAM_SOURCE_SELECTION, string="Team Source", tracking=True)
    client_proceeding = fields.Selection(PROCEEDING_SELECTION, string="Client Proceeding?", tracking=True)
    letter_template_id = fields.Many2one("gl.email.template", string="Letter # / Type", tracking=True)
    date_sent = fields.Date(string="Date Sent", tracking=True)
    send_yes_no = fields.Selection(YES_NO_SELECTION, string="Send Yes or No", tracking=True)
    added_to_home_processing = fields.Boolean(string="Added to Home Processing", tracking=True)
    processing_status = fields.Selection(
        PROCESSING_STATUS_SELECTION,
        string="Processing Status",
        default="draft",
        tracking=True,
    )
    processor_id = fields.Many2one(
        "res.users",
        string="Processor",
        domain="[('share', '=', False)]",
        tracking=True,
    )
    pending_ids = fields.One2many("gl.workflow.pending", "workflow_id", string="Pendientes")
    history_line_ids = fields.One2many("gl.workflow.history", "workflow_id", string="Notes / History")

    _sql_constraints = [
        ("gl_workflow_quote_number_unique", "unique(quote_number)", "Quote # must be unique."),
    ]


class GlWorkflowPending(models.Model):
    _name = "gl.workflow.pending"
    _description = "Pendientes"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_received desc, id desc"

    workflow_id = fields.Many2one("gl.workflow", string="Work Flow", required=True, ondelete="cascade", tracking=True)
    date_received = fields.Date(string="Date Received", required=True, default=fields.Date.context_today, tracking=True)
    quote_number = fields.Char(string="Quote #", related="workflow_id.quote_number", store=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Client Information",
        related="workflow_id.partner_id",
        store=True,
        readonly=True,
    )
    letter_template_id = fields.Many2one(
        "gl.email.template",
        string="Letter #",
        related="workflow_id.letter_template_id",
        store=True,
        readonly=True,
    )
    processor_id = fields.Many2one(
        "res.users",
        string="Processor",
        domain="[('share', '=', False)]",
        tracking=True,
    )
    status = fields.Selection(PENDING_STATUS_SELECTION, string="Status", default="pending", tracking=True)
    follow_up_date = fields.Date(string="Follow-Up Date", tracking=True)
    notes = fields.Text(string="Notes", tracking=True)


class GlEmailTemplate(models.Model):
    _name = "gl.email.template"
    _description = "Email Templates"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "letter_number asc, id desc"
    _rec_name = "letter_number"

    letter_number = fields.Char(string="Letter #", required=True, tracking=True, index=True)
    name = fields.Char(string="Template Name", required=True, tracking=True)
    letter_type = fields.Selection(LETTER_TYPE_SELECTION, string="Letter Type Options", required=True, tracking=True)
    insurance_type = fields.Selection(WORKFLOW_TYPE_SELECTION, string="Insurance Type", required=True, tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "gl_email_template_ir_attachments_rel",
        "template_id",
        "attachment_id",
        string="Attachments",
    )
    subject = fields.Char(string="Subject", tracking=True)
    body_html = fields.Html(string="Body")
    active = fields.Boolean(default=True)
    workflow_ids = fields.One2many("gl.workflow", "letter_template_id", string="Work Flows")

    _sql_constraints = [
        ("gl_email_template_letter_number_unique", "unique(letter_number)", "Letter # must be unique."),
    ]


class GlWorkflowHistory(models.Model):
    _name = "gl.workflow.history"
    _description = "Workflow History"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "history_date desc, id desc"
    _rec_name = "title"

    title = fields.Char(string="Title")
    workflow_id = fields.Many2one("gl.workflow", string="Work Flow", required=True, ondelete="cascade")
    history_date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", string="User", default=lambda self: self.env.user, required=True)
    note = fields.Text(string="Note")

    @api.model
    def create(self, vals):
        if not vals.get("title") and vals.get("workflow_id"):
            workflow = self.env["gl.workflow"].browse(vals["workflow_id"])
            vals["title"] = f"History - {workflow.quote_number}"
        return super().create(vals)
