# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt
"""
One function per real-world step in the Impart pipeline. Every function
here does the step the same way a human would from the Desk UI - by using
ERPNext's own native "Create" mapped-document functions (make_quotation,
make_sales_order, make_purchase_order, ...) wherever ERPNext provides one -
and then stamps the result with custom_impart_deal so it is visible on the
Impart Deal screen and so the doc_events hooks in deal_sync.py can keep the
deal's ladder and stage in sync automatically.

These functions are the single engine behind both:
  - the demo seed script (impart_ops/setup/demo_data.py), and
  - the "Impart Deal" form's own action buttons (impart_deal.js),
so the demo data is produced by exactly the same code path a real user
would exercise by hand.
"""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, cint, flt, getdate, nowdate


def _advance(deal, action):
	"""Apply a workflow action; never raises (see deal_sync.py for why)."""
	try:
		apply_workflow(deal, action)
	except Exception:
		frappe.log_error(
			title="Impart Deal workflow transition skipped",
			message=f"Deal {deal.name}: could not apply action '{action}' from state "
			f"'{deal.workflow_state}'.\n{frappe.get_traceback()}",
		)


def _deal(deal_name):
	return frappe.get_doc("Impart Deal", deal_name)


def _default_warehouse(company):
	return frappe.db.get_value("Warehouse", {"company": company, "warehouse_name": "Stores"}, "name")


# ---------------------------------------------------------------------
# 1. Birth of the deal: customer asks for a product
# ---------------------------------------------------------------------

@frappe.whitelist()
def new_deal(customer, item_code, qty, description=None, company=None, deal_date=None):
	company = company or frappe.db.get_default("company")

	deal = frappe.new_doc("Impart Deal")
	deal.customer = customer
	deal.item_code = item_code
	deal.qty = flt(qty)
	deal.description = description
	deal.company = company
	deal.deal_date = deal_date or nowdate()
	deal.workflow_state = "New Inquiry"
	# The Deal's own after_insert() creates and links its Opportunity -
	# the same thing happens whether a deal is created here or by hand on
	# the desk's New form, so both paths always end up in the same state.
	deal.insert(ignore_permissions=True)
	deal.reload()
	return deal


# ---------------------------------------------------------------------
# 2. Impart asks the foreign vendor(s) - native Request for Quotation
# ---------------------------------------------------------------------

@frappe.whitelist()
def send_rfq(deal_name, suppliers, message=None):
	from erpnext.crm.doctype.opportunity.opportunity import make_request_for_quotation

	if isinstance(suppliers, str):
		# frappe.call serialises a JS array as a JSON string; a bare name
		# (no brackets) is a single supplier typed directly.
		try:
			parsed = frappe.parse_json(suppliers)
		except Exception:
			parsed = suppliers
		suppliers = parsed if isinstance(parsed, list) else [parsed]

	deal = _deal(deal_name)
	rfq = frappe.get_doc(make_request_for_quotation(deal.opportunity))
	rfq.transaction_date = nowdate()
	rfq.message_for_supplier = message or (
		f"Please share your best price for {deal.qty} x {deal.item_code}."
	)
	rfq.custom_impart_deal = deal.name
	warehouse = _default_warehouse(deal.company)
	for item in rfq.items:
		item.warehouse = warehouse
	for supplier in suppliers:
		rfq.append("suppliers", {"supplier": supplier})
	rfq.insert(ignore_permissions=True)
	rfq.submit()

	deal.request_for_quotation = rfq.name
	deal.save(ignore_permissions=True)
	deal.reload()
	_advance(deal, "Send RFQ")
	return rfq


# ---------------------------------------------------------------------
# 3. Vendor replies with a price in their currency - the "Ask"
# ---------------------------------------------------------------------

@frappe.whitelist()
def record_vendor_quote(deal_name, supplier, rate, currency="USD", exchange_rate=1, valid_till=None):
	deal = _deal(deal_name)

	sq = frappe.new_doc("Supplier Quotation")
	sq.supplier = supplier
	sq.company = deal.company
	sq.currency = currency
	sq.conversion_rate = flt(exchange_rate)
	sq.transaction_date = nowdate()
	sq.valid_till = valid_till
	sq.custom_impart_deal = deal.name
	item_row = {
		"item_code": deal.item_code,
		"qty": deal.qty,
		"rate": flt(rate),
		"warehouse": _default_warehouse(deal.company),
	}
	if deal.request_for_quotation:
		item_row["request_for_quotation"] = deal.request_for_quotation
	sq.append("items", item_row)
	sq.insert(ignore_permissions=True)
	sq.submit()  # doc_events.on_supplier_quotation_submit appends the Ask row
	return sq


# ---------------------------------------------------------------------
# 4. Impart quotes the customer in INR - the "Bid"
# ---------------------------------------------------------------------

@frappe.whitelist()
def send_customer_quotation(deal_name, rate_inr, valid_till=None):
	from erpnext.crm.doctype.opportunity.opportunity import make_quotation

	deal = _deal(deal_name)
	qtn = frappe.get_doc(make_quotation(deal.opportunity))
	qtn.currency = "INR"
	qtn.conversion_rate = 1
	qtn.transaction_date = nowdate()
	qtn.valid_till = valid_till or add_days(nowdate(), 30)
	qtn.custom_impart_deal = deal.name
	for item in qtn.items:
		item.rate = flt(rate_inr)
	qtn.insert(ignore_permissions=True)
	qtn.submit()  # doc_events.on_quotation_submit appends the Bid row
	return qtn


@frappe.whitelist()
def request_revision(deal_name, remarks=None):
	"""Customer asks for a better price - moves the deal into negotiation
	so the next vendor quote / re-quote becomes round 2, 3, ..."""
	deal = _deal(deal_name)
	if remarks:
		deal.remarks = ((deal.remarks or "") + f"\n{nowdate()}: {remarks}").strip()
		deal.save(ignore_permissions=True)
		deal.reload()
	_advance(deal, "Customer Requests Revision")
	return deal


@frappe.whitelist()
def revise_customer_quotation(deal_name, new_rate_inr):
	"""Cancel + amend the existing native Quotation - this *is* the
	revision: Frappe's amendment mechanism creates QTN-...-1, -2, ... and
	each submitted amendment appends one more Bid row to the ladder."""
	deal = _deal(deal_name)
	if not deal.quotation:
		frappe.throw("Deal has no Quotation to revise yet.")

	current = frappe.get_doc("Quotation", deal.quotation)
	if current.docstatus == 1:
		current.cancel()

	amended = frappe.copy_doc(current)
	amended.amended_from = current.name
	amended.docstatus = 0
	amended.transaction_date = nowdate()
	amended.custom_impart_deal = deal.name
	for item in amended.items:
		item.rate = flt(new_rate_inr)
	amended.insert(ignore_permissions=True)
	amended.submit()  # appends the next Bid round automatically
	return amended


@frappe.whitelist()
def customer_rejects(deal_name, reason=None):
	deal = _deal(deal_name)
	if reason:
		deal.remarks = ((deal.remarks or "") + f"\nLost: {reason}").strip()
		deal.save(ignore_permissions=True)
		deal.reload()
	_advance(deal, "Customer Rejects")
	return deal


# ---------------------------------------------------------------------
# 5. Customer places their PO -> native Sales Order
# ---------------------------------------------------------------------

@frappe.whitelist()
def create_sales_order(deal_name, po_no=None, po_date=None, delivery_days=21):
	from erpnext.selling.doctype.quotation.quotation import make_sales_order

	deal = _deal(deal_name)
	so = frappe.get_doc(make_sales_order(deal.quotation))
	so.transaction_date = nowdate()
	so.delivery_date = add_days(nowdate(), cint(delivery_days))
	if po_no:
		so.po_no = po_no
	if po_date:
		so.po_date = po_date
	so.custom_impart_deal = deal.name
	warehouse = _default_warehouse(deal.company)
	for item in so.items:
		item.warehouse = warehouse
	so.insert(ignore_permissions=True)
	so.submit()  # doc_events.on_sales_order_submit links + advances workflow
	return so


# ---------------------------------------------------------------------
# 6. Impart orders from the vendor -> native Purchase Order
# ---------------------------------------------------------------------

@frappe.whitelist()
def create_purchase_order(deal_name, schedule_days=25, incoterm="CIF"):
	from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_purchase_order

	deal = _deal(deal_name)
	po = frappe.get_doc(make_purchase_order(deal.supplier_quotation))
	po.transaction_date = nowdate()
	po.schedule_date = add_days(nowdate(), cint(schedule_days))
	po.incoterm = incoterm
	po.custom_impart_deal = deal.name
	po.insert(ignore_permissions=True)
	po.submit()  # doc_events.on_purchase_order_submit links + advances workflow
	return po


@frappe.whitelist()
def mark_vendor_confirmed(deal_name, confirmation_no=None, confirmation_date=None):
	"""Vendor confirms the order - recorded on the PO's own native fields."""
	deal = _deal(deal_name)
	po = frappe.get_doc("Purchase Order", deal.purchase_order)
	po.db_set("order_confirmation_no", confirmation_no or f"CONF-{po.name}", update_modified=False)
	po.db_set(
		"order_confirmation_date", confirmation_date or nowdate(), update_modified=False
	)
	deal.reload()
	_advance(deal, "Vendor Confirms Order")
	return deal


@frappe.whitelist()
def mark_shipped(deal_name, awb_bl_no, eta):
	"""Vendor dispatches - AWB/BL and ETA are the two fields with no
	native home, so they live as custom fields on the Purchase Order."""
	deal = _deal(deal_name)
	po = frappe.get_doc("Purchase Order", deal.purchase_order)
	po.db_set("custom_awb_bl_no", awb_bl_no, update_modified=False)
	po.db_set("custom_eta", getdate(eta), update_modified=False)
	deal.reload()
	_advance(deal, "Mark Shipped")
	return deal


# ---------------------------------------------------------------------
# 7. Goods arrive at Impart, are checked in -> native Purchase Receipt
# ---------------------------------------------------------------------

@frappe.whitelist()
def create_purchase_receipt(deal_name):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	deal = _deal(deal_name)
	pr = frappe.get_doc(make_purchase_receipt(deal.purchase_order))
	pr.posting_date = nowdate()
	pr.custom_impart_deal = deal.name
	pr.insert(ignore_permissions=True)
	pr.submit()  # doc_events.on_purchase_receipt_submit links + advances workflow
	return pr


@frappe.whitelist()
def create_purchase_invoice(deal_name, bill_no=None, bill_date=None):
	"""The principal's own commercial invoice (data only - no state change)."""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	deal = _deal(deal_name)
	pi = frappe.get_doc(make_purchase_invoice(deal.purchase_order))
	pi.bill_no = bill_no or f"{deal.selected_supplier}-INV-{deal.name}"
	pi.bill_date = bill_date or nowdate()
	pi.set_posting_time = 1
	pi.posting_date = bill_date or nowdate()
	pi.custom_impart_deal = deal.name
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi


# ---------------------------------------------------------------------
# 8. Goods go onward to the customer -> native Delivery Note
# ---------------------------------------------------------------------

@frappe.whitelist()
def create_delivery_note(deal_name):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	deal = _deal(deal_name)
	dn = frappe.get_doc(make_delivery_note(deal.sales_order))
	dn.posting_date = nowdate()
	dn.custom_impart_deal = deal.name
	dn.insert(ignore_permissions=True)
	dn.submit()  # doc_events.on_delivery_note_submit links + advances workflow
	return dn


# ---------------------------------------------------------------------
# 9. Impart bills the customer -> native Sales Invoice
# ---------------------------------------------------------------------

@frappe.whitelist()
def create_sales_invoice(deal_name, credit_days=30, posting_date=None):
	"""posting_date can be backdated (e.g. for demo data) to produce a
	realistic overdue invoice - due_date is always >= posting_date since
	ERPNext itself enforces that, so "overdue" comes from backdating when
	the invoice was raised, not from a negative credit period."""
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

	deal = _deal(deal_name)
	si = frappe.get_doc(make_sales_invoice(deal.delivery_note))
	si.posting_date = posting_date or nowdate()
	si.set_posting_time = 1
	si.due_date = add_days(si.posting_date, cint(credit_days))
	si.custom_impart_deal = deal.name
	si.insert(ignore_permissions=True)
	si.submit()  # doc_events.on_sales_invoice_submit links + advances workflow
	return si


# ---------------------------------------------------------------------
# 10. Money moves - native Payment Entry, both directions
# ---------------------------------------------------------------------

@frappe.whitelist()
def record_customer_payment(deal_name, paid_amount=None, posting_date=None, reference_no=None):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	deal = _deal(deal_name)
	pe = get_payment_entry("Sales Invoice", deal.sales_invoice)
	pe.posting_date = posting_date or nowdate()
	pe.reference_no = reference_no or f"NEFT-{deal.name}"
	pe.reference_date = pe.posting_date
	if paid_amount:
		pe.paid_amount = pe.received_amount = flt(paid_amount)
	pe.custom_impart_deal = deal.name
	pe.insert(ignore_permissions=True)
	pe.submit()  # doc_events.on_payment_entry_submit moves the deal to "Payment Received"
	return pe


@frappe.whitelist()
def record_vendor_payment(deal_name, paid_amount=None, posting_date=None, reference_no=None):
	deal = _deal(deal_name)
	if not deal.purchase_invoice:
		frappe.throw("Deal has no Purchase Invoice to pay yet.")
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry("Purchase Invoice", deal.purchase_invoice)
	pe.posting_date = posting_date or nowdate()
	pe.reference_no = reference_no or f"SWIFT-{deal.name}"
	pe.reference_date = pe.posting_date
	if paid_amount:
		pe.paid_amount = pe.received_amount = flt(paid_amount)
	pe.custom_impart_deal = deal.name
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe
