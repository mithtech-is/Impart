# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt
"""
Keeps the custom "Impart Deal" record (the single screen the Impart team
lives in) automatically in sync with the native ERPNext documents that do
the real work: Supplier Quotation, Quotation, Sales Order, Purchase Order,
Purchase Receipt, Purchase Invoice, Delivery Note and Sales Invoice.

Every function here is defensive on purpose: these hooks are attached to
core ERPNext doctypes, so a bug here must never block a real business
document (a Sales Order, an Invoice, ...) from being submitted. Every
function starts by checking custom_impart_deal is set, and every workflow
transition is wrapped so an unexpected state never raises.
"""

import frappe
from frappe.utils import flt, nowdate


def _get_deal(doc):
	deal_name = doc.get("custom_impart_deal")
	if not deal_name:
		return None
	if not frappe.db.exists("Impart Deal", deal_name):
		return None
	return frappe.get_doc("Impart Deal", deal_name)


def _advance(deal, action):
	"""Apply a workflow action if it is valid from the deal's current
	state. Never raises - a mismatched state just means the operator
	will drive that transition by hand from the Deal screen instead."""
	from frappe.model.workflow import apply_workflow

	try:
		apply_workflow(deal, action)
	except Exception:
		frappe.log_error(
			title="Impart Deal workflow transition skipped",
			message=f"Deal {deal.name}: could not apply action '{action}' from state "
			f"'{deal.workflow_state}'.\n{frappe.get_traceback()}",
		)


def _next_round(deal, side):
	return len([r for r in deal.ladder if r.side == side]) + 1


def _append_ladder_row(deal, *, side, party_type, party, currency, rate, exchange_rate,
	qty, status, reference_doctype, reference_name, remarks=None):
	deal.append("ladder", {
		"round": _next_round(deal, side),
		"posting_date": nowdate(),
		"side": side,
		"party_type": party_type,
		"party": party,
		"currency": currency,
		"rate": rate,
		"exchange_rate": exchange_rate,
		"qty": qty,
		"amount_inr": flt(rate) * flt(qty) * flt(exchange_rate or 1),
		"status": status,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"remarks": remarks,
	})
	deal.save(ignore_permissions=True)


def _mark_superseded(reference_doctype, reference_name):
	rows = frappe.get_all(
		"Impart Deal Entry",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=["name", "parent"],
	)
	for row in rows:
		frappe.db.set_value("Impart Deal Entry", row.name, "status", "Superseded")


# ---------------------------------------------------------------------
# Supplier Quotation (the vendor's Ask, in foreign currency)
# ---------------------------------------------------------------------

def set_deal_on_supplier_quotation(doc, method=None):
	"""When a vendor submits their price through the native Supplier
	Portal (/rfq), ERPNext builds a fresh Supplier Quotation from a plain
	dict, so custom_impart_deal is not carried over automatically. Every
	item row it creates *does* keep a link back to the source Request for
	Quotation (that's native, core ERPNext behaviour) - so trace through
	that to find the deal and tag the document before it is even saved."""
	if doc.get("custom_impart_deal"):
		return
	for item in doc.items:
		rfq = item.get("request_for_quotation")
		if not rfq:
			continue
		deal_name = frappe.db.get_value("Request for Quotation", rfq, "custom_impart_deal")
		if deal_name:
			doc.custom_impart_deal = deal_name
			return


def on_supplier_quotation_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return

	qty = sum(flt(i.qty) for i in doc.items) or flt(deal.qty)
	rate = flt(doc.items[0].rate) if doc.items else 0

	deal.supplier_quotation = doc.name
	if not deal.selected_supplier:
		deal.selected_supplier = doc.supplier
	deal.vendor_currency = doc.currency
	deal.vendor_rate = rate
	deal.exchange_rate = flt(doc.conversion_rate) or deal.exchange_rate or 1
	deal.save(ignore_permissions=True)

	_append_ladder_row(
		deal, side="Ask", party_type="Supplier", party=doc.supplier,
		currency=doc.currency, rate=rate, exchange_rate=doc.conversion_rate,
		qty=qty, status="Sent",
		reference_doctype="Supplier Quotation", reference_name=doc.name,
	)

	deal.reload()
	if deal.workflow_state in ("RFQ Sent to Vendor", "In Negotiation"):
		_advance(deal, "Record Vendor Quote")


def on_supplier_quotation_cancel(doc, method=None):
	_mark_superseded("Supplier Quotation", doc.name)


# ---------------------------------------------------------------------
# Quotation (Impart's Bid to the domestic customer, in INR)
# ---------------------------------------------------------------------

def on_quotation_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return

	qty = sum(flt(i.qty) for i in doc.items) or flt(deal.qty)
	rate = flt(doc.items[0].rate) if doc.items else 0

	deal.quotation = doc.name
	deal.save(ignore_permissions=True)

	_append_ladder_row(
		deal, side="Bid", party_type="Customer", party=doc.party_name,
		currency=doc.currency, rate=rate, exchange_rate=1,
		qty=qty, status="Sent",
		reference_doctype="Quotation", reference_name=doc.name,
	)

	deal.reload()
	if deal.workflow_state == "Vendor Quote Received":
		_advance(deal, "Send Customer Quotation")


def on_quotation_cancel(doc, method=None):
	_mark_superseded("Quotation", doc.name)


# ---------------------------------------------------------------------
# Sales Order = customer accepted the (final) quotation and placed a PO
# ---------------------------------------------------------------------

def on_sales_order_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.sales_order = doc.name
	deal.save(ignore_permissions=True)
	deal.reload()
	if deal.workflow_state in ("Customer Quotation Sent", "In Negotiation"):
		_advance(deal, "Customer Approves")


# ---------------------------------------------------------------------
# Purchase Order = Impart places the order on the foreign principal
# ---------------------------------------------------------------------

def on_purchase_order_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.purchase_order = doc.name
	deal.save(ignore_permissions=True)
	deal.reload()
	if deal.workflow_state == "Customer Approved":
		_advance(deal, "Place Vendor Order")


# ---------------------------------------------------------------------
# Purchase Receipt = goods physically received & checked at Impart
# ---------------------------------------------------------------------

def on_purchase_receipt_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.purchase_receipt = doc.name
	deal.save(ignore_permissions=True)
	deal.reload()
	if deal.workflow_state == "Shipped / In Transit":
		_advance(deal, "Mark Received")


# ---------------------------------------------------------------------
# Purchase Invoice = the principal's commercial invoice (data only)
# ---------------------------------------------------------------------

def on_purchase_invoice_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.purchase_invoice = doc.name
	deal.save(ignore_permissions=True)


# ---------------------------------------------------------------------
# Delivery Note = goods dispatched onward to the domestic customer
# ---------------------------------------------------------------------

def on_delivery_note_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.delivery_note = doc.name
	deal.save(ignore_permissions=True)
	deal.reload()
	if deal.workflow_state == "Received at Impart":
		_advance(deal, "Deliver to Customer")


# ---------------------------------------------------------------------
# Sales Invoice = Impart bills the domestic customer in INR
# ---------------------------------------------------------------------

def on_sales_invoice_submit(doc, method=None):
	deal = _get_deal(doc)
	if not deal:
		return
	deal.sales_invoice = doc.name
	deal.save(ignore_permissions=True)
	deal.reload()
	if deal.workflow_state == "Delivered to Customer":
		_advance(deal, "Raise Invoice")


# ---------------------------------------------------------------------
# Payment Entry = the customer pays Impart (deal closes) or Impart pays
# the vendor (informational only, no deal-state transition)
# ---------------------------------------------------------------------

def on_payment_entry_submit(doc, method=None):
	if doc.party_type != "Customer":
		return
	deal = _get_deal(doc)
	if not deal:
		# fall back: find the deal via the Sales Invoice this payment references
		for ref in doc.references:
			if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
				dn = frappe.db.get_value(
					"Impart Deal", {"sales_invoice": ref.reference_name}, "name"
				)
				if dn:
					deal = frappe.get_doc("Impart Deal", dn)
					break
	if not deal:
		return
	deal.reload()
	if deal.workflow_state == "Invoiced":
		_advance(deal, "Confirm Payment Received")
