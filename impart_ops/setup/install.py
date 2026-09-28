# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt
"""
Runs once when impart_ops is installed on a site. Everything here is
idempotent (safe to re-run via `bench execute impart_ops.setup.install.after_install`)
so it can be used both for the first install and to repair/upgrade later.

What this sets up, in order:
  1. The "Impart User" role (the only role, besides System Manager, that
     can see the Impart Deal screen).
  2. custom_impart_deal - one Link field added to every native document
     in the pipeline (Opportunity, RFQ, Supplier Quotation, Quotation,
     Sales Order, Purchase Order, Purchase Receipt, Purchase Invoice,
     Delivery Note, Sales Invoice, Payment Entry) so each native document
     always knows which deal it belongs to.
  3. Two small custom fields on Purchase Order for AWB/BL and ETA - the
     only two pieces of data in the whole pipeline with no native home.
  4. The Impart Deal Workflow: 14 states and 16 transitions covering the
     full inquiry -> negotiation -> order -> shipment -> invoice -> payment
     lifecycle, including the negotiation loop back to the vendor.
"""

import frappe


CUSTOM_FIELDS = {
	"Opportunity": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "opportunity_owner",
			"no_copy": 1,
		}
	],
	"Request for Quotation": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "message_for_supplier",
			"no_copy": 1,
		}
	],
	"Supplier Quotation": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "supplier",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Quotation": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "party_name",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Sales Order": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "customer",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Purchase Order": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "supplier",
			"no_copy": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_awb_bl_no",
			"label": "AWB / BL No",
			"fieldtype": "Data",
			"insert_after": "shipping_address",
			"no_copy": 1,
		},
		{
			"fieldname": "custom_eta",
			"label": "ETA",
			"fieldtype": "Date",
			"insert_after": "custom_awb_bl_no",
			"no_copy": 1,
		},
	],
	"Purchase Receipt": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "supplier",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Purchase Invoice": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "supplier",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Delivery Note": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "customer",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Sales Invoice": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "customer",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
	"Payment Entry": [
		{
			"fieldname": "custom_impart_deal",
			"label": "Impart Deal",
			"fieldtype": "Link",
			"options": "Impart Deal",
			"insert_after": "party",
			"no_copy": 1,
			"in_standard_filter": 1,
		}
	],
}

# (state name, doc_status)
WORKFLOW_STATES = [
	("New Inquiry", 0),
	("RFQ Sent to Vendor", 0),
	("Vendor Quote Received", 0),
	("Customer Quotation Sent", 0),
	("In Negotiation", 0),
	("Customer Approved", 0),
	("Order Placed with Vendor", 0),
	("Vendor Order Confirmed", 0),
	("Shipped / In Transit", 0),
	("Received at Impart", 0),
	("Delivered to Customer", 0),
	("Invoiced", 0),
	# Impart Deal is a plain tracking record (like Opportunity or Issue),
	# not a submittable legal document - the real submit/cancel lifecycle
	# already belongs to the native Quotation/Sales Order/Sales Invoice
	# documents it links to. So every state here, including the two
	# "final" ones, stays doc_status 0; "closed" is just a status value.
	# (A submittable Impart Deal would also make Frappe block every later
	# save once the ladder's audit trail points at a cancelled/amended
	# Quotation - which is the whole point of the ladder.)
	("Payment Received", 0),
	("Lost / Cancelled", 0),
]

# (from_state, action, to_state, condition)
#
# The condition is the real fix for a serious problem: Frappe automatically
# offers a plain status-change button for every transition valid from the
# current state, in ADDITION to this app's own guided buttons (impart_deal.js)
# - and the two can look identical to a user ("Send RFQ" vs "Send RFQ to
# Vendor"). Without a condition, clicking the bare native button just flips
# the Stage label with no real document behind it - exactly what happened
# once already. The condition makes Frappe refuse to even offer a transition
# until the matching native document genuinely exists, both in the button
# list AND server-side if somehow called directly - so a bare click can no
# longer produce a fake stage with nothing behind it. Every one of this
# app's own action functions (deal_actions.py) already sets that document's
# link field on the deal BEFORE advancing the stage, so none of them are
# ever blocked by their own condition.
WORKFLOW_TRANSITIONS = [
	("New Inquiry", "Send RFQ", "RFQ Sent to Vendor",
		'doc.get("request_for_quotation")'),
	("RFQ Sent to Vendor", "Record Vendor Quote", "Vendor Quote Received",
		'doc.get("supplier_quotation")'),
	("Vendor Quote Received", "Send Customer Quotation", "Customer Quotation Sent",
		'doc.get("quotation")'),
	("Customer Quotation Sent", "Customer Requests Revision", "In Negotiation", None),
	("In Negotiation", "Record Vendor Quote", "Vendor Quote Received",
		'doc.get("supplier_quotation")'),
	("Customer Quotation Sent", "Customer Approves", "Customer Approved",
		'doc.get("sales_order")'),
	("In Negotiation", "Customer Approves", "Customer Approved",
		'doc.get("sales_order")'),
	("Customer Quotation Sent", "Customer Rejects", "Lost / Cancelled", None),
	("In Negotiation", "Customer Rejects", "Lost / Cancelled", None),
	("Customer Approved", "Place Vendor Order", "Order Placed with Vendor",
		'doc.get("purchase_order")'),
	("Order Placed with Vendor", "Vendor Confirms Order", "Vendor Order Confirmed",
		'doc.get("purchase_order") and frappe.db.get_value("Purchase Order", doc.get("purchase_order"), "order_confirmation_no")'),
	("Vendor Order Confirmed", "Mark Shipped", "Shipped / In Transit",
		'doc.get("purchase_order") and frappe.db.get_value("Purchase Order", doc.get("purchase_order"), "custom_awb_bl_no")'),
	("Shipped / In Transit", "Mark Received", "Received at Impart",
		'doc.get("purchase_receipt")'),
	("Received at Impart", "Deliver to Customer", "Delivered to Customer",
		'doc.get("delivery_note")'),
	("Delivered to Customer", "Raise Invoice", "Invoiced",
		'doc.get("sales_invoice")'),
	("Invoiced", "Confirm Payment Received", "Payment Received",
		'doc.get("sales_invoice")'),
]

ROLE = "Impart User"


def after_install():
	create_role()
	create_custom_fields()
	create_workflow()
	configure_accounts_settings()
	grant_supplier_portal_permissions()
	create_workspace()
	frappe.db.commit()


WORKSPACE_SHORTCUTS = [
	# (label, type, link_to)
	("Impart Deal", "DocType", "Impart Deal"),
	("Impart Deal Tracker", "Report", "Impart Deal Tracker"),
	("Customer", "DocType", "Customer"),
	("Supplier", "DocType", "Supplier"),
	("Opportunity", "DocType", "Opportunity"),
	("Request for Quotation", "DocType", "Request for Quotation"),
	("Supplier Quotation", "DocType", "Supplier Quotation"),
	("Quotation", "DocType", "Quotation"),
	("Sales Order", "DocType", "Sales Order"),
	("Purchase Order", "DocType", "Purchase Order"),
	("Sales Invoice", "DocType", "Sales Invoice"),
	("Purchase Invoice", "DocType", "Purchase Invoice"),
	("Accounts Receivable", "Report", "Accounts Receivable"),
]


def create_workspace():
	"""The single landing screen Impart's team opens every morning: the
	Deal list and tracker report up top, every native document type in
	the pipeline one click away below. Visible only to System Manager and
	Impart User - the same restriction as the Impart Deal doctype itself."""
	import json

	name = "Impart"
	if frappe.db.exists("Workspace", name):
		ws = frappe.get_doc("Workspace", name)
		ws.shortcuts = []
	else:
		ws = frappe.new_doc("Workspace")
		ws.name = name
		ws.title = name
		ws.label = name
		ws.module = "Impart Ops"
		ws.public = 1
		ws.is_hidden = 0
		ws.icon = "non-standard-navigation"

	content = [
		{"id": "impart-header", "type": "header",
			"data": {"text": '<span class="h4"><b>Impart – Order &amp; Quotation Pipeline</b></span>', "col": 12}},
	]
	for label, _type, _link in WORKSPACE_SHORTCUTS:
		content.append({
			"id": f"impart-sc-{label.replace(' ', '-')}",
			"type": "shortcut",
			"data": {"shortcut_name": label, "col": 3},
		})

	ws.content = json.dumps(content)
	for label, stype, link in WORKSPACE_SHORTCUTS:
		ws.append("shortcuts", {"label": label, "type": stype, "link_to": link})
	ws.roles = []
	for role in ("System Manager", "Impart User"):
		ws.append("roles", {"role": role})

	if ws.is_new():
		ws.insert(ignore_permissions=True)
	else:
		ws.save(ignore_permissions=True)


def grant_supplier_portal_permissions():
	"""The native Supplier Portal (/rfq) lets a vendor submit their own
	price via erpnext's create_supplier_quotation, which runs entirely as
	the LOGGED-IN VENDOR (a Website User), not as Administrator. That one
	native function, while building the Supplier Quotation, needs to:
	  - read the Item master (get_item_details), and
	  - resolve the company's payable Account to know its currency
	    (get_party_account) - only a "select" lookup, not a ledger read.
	Core ERPNext ships without either for the Supplier role, so without
	this grant every vendor's own price submission fails with a
	permission error - a one-time, minimal, read-only site setting
	required for the portal flow to work at all."""
	_add_custom_docperm("Item", "Supplier", read=1)
	_add_custom_docperm("Account", "Supplier", select=1)


def _add_custom_docperm(doctype, role, **perm_flags):
	if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role}):
		return
	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": doctype,
		"parenttype": "DocType",
		"parentfield": "permissions",
		"role": role,
		**perm_flags,
	}).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)


def configure_accounts_settings():
	"""Impart bills foreign principals in USD/EUR/etc. against one INR
	Creditors ledger per company - this is the standard native setting
	for exactly that (import/export multi-currency payables)."""
	frappe.db.set_single_value(
		"Accounts Settings", "allow_multi_currency_invoices_against_single_party_account", 1
	)


def create_role():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": ROLE,
			"desk_access": 1,
		}).insert(ignore_permissions=True)

	# The demo runs as Administrator; make sure that account also carries
	# the Impart User role so the workflow's allow_edit rules never block it.
	if frappe.db.exists("User", "Administrator"):
		user = frappe.get_doc("User", "Administrator")
		if ROLE not in [r.role for r in user.roles]:
			user.append("roles", {"role": ROLE})
			user.save(ignore_permissions=True)


def create_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields as _ccf

	_ccf(CUSTOM_FIELDS, ignore_validate=True, update=True)


def create_workflow():
	for state, _ in WORKFLOW_STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
				ignore_permissions=True
			)

	actions = sorted({action for _, action, _, _ in WORKFLOW_TRANSITIONS})
	for action in actions:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)

	workflow_name = "Impart Deal Workflow"
	if frappe.db.exists("Workflow", workflow_name):
		wf = frappe.get_doc("Workflow", workflow_name)
		wf.states = []
		wf.transitions = []
	else:
		wf = frappe.new_doc("Workflow")
		wf.workflow_name = workflow_name
		wf.document_type = "Impart Deal"
		wf.is_active = 1
		wf.send_email_alert = 0
		wf.workflow_state_field = "workflow_state"

	for state, doc_status in WORKFLOW_STATES:
		wf.append("states", {
			"state": state,
			"doc_status": str(doc_status),
			"allow_edit": ROLE,
		})

	for from_state, action, to_state, condition in WORKFLOW_TRANSITIONS:
		wf.append("transitions", {
			"state": from_state,
			"action": action,
			"next_state": to_state,
			"allowed": ROLE,
			"condition": condition,
		})

	if wf.is_new():
		wf.insert(ignore_permissions=True)
	else:
		wf.save(ignore_permissions=True)
