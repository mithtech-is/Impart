# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt
"""
Impart Deal Tracker - reproduces the 23-column Excel sheet Impart's team
already works from (Customer -> PO -> Principal Order -> Logistics ->
Invoice -> Aging), one row per deal, pulled live from the native ERPNext
documents linked on each Impart Deal. Nothing here is cached: every value
is read straight from the current Sales Order / Purchase Order / Purchase
Invoice / Sales Invoice, so the report is always exactly what those native
documents currently say.
"""

import frappe
from frappe.utils import date_diff, flt, nowdate


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters or {})
	return columns, data


def get_columns():
	return [
		{"label": "Deal", "fieldname": "deal", "fieldtype": "Link", "options": "Impart Deal", "width": 110},
		{"label": "Stage", "fieldname": "stage", "fieldtype": "Data", "width": 150},
		{"label": "Customer", "fieldname": "customer", "fieldtype": "Data", "width": 140},
		{"label": "Location", "fieldname": "location", "fieldtype": "Data", "width": 100},
		{"label": "PO No", "fieldname": "po_no", "fieldtype": "Data", "width": 110},
		{"label": "PO Date", "fieldname": "po_date", "fieldtype": "Date", "width": 95},
		{"label": "PO Value", "fieldname": "po_value", "fieldtype": "Currency", "options": "INR", "width": 120},
		{"label": "Description", "fieldname": "description", "fieldtype": "Data", "width": 160},
		{"label": "Order To", "fieldname": "order_to", "fieldtype": "Link", "options": "Supplier", "width": 120},
		{"label": "Inco", "fieldname": "inco", "fieldtype": "Data", "width": 70},
		{"label": "Impart Order", "fieldname": "impart_order", "fieldtype": "Link", "options": "Purchase Order", "width": 110},
		{"label": "Odr Date", "fieldname": "odr_date", "fieldtype": "Date", "width": 95},
		{"label": "Order Val", "fieldname": "order_val", "fieldtype": "Float", "width": 100},
		{"label": "Odr Cur", "fieldname": "odr_cur", "fieldtype": "Data", "width": 70},
		{"label": "Invoice", "fieldname": "invoice", "fieldtype": "Data", "width": 110},
		{"label": "In Valu", "fieldname": "in_valu", "fieldtype": "Float", "width": 100},
		{"label": "AWB/BL", "fieldname": "awb_bl", "fieldtype": "Data", "width": 110},
		{"label": "Wt KG", "fieldname": "wt_kg", "fieldtype": "Float", "width": 80},
		{"label": "ETA", "fieldname": "eta", "fieldtype": "Date", "width": 95},
		{"label": "Impart Invoice", "fieldname": "impart_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 120},
		{"label": "Invoice Date", "fieldname": "invoice_date", "fieldtype": "Date", "width": 95},
		{"label": "Invoice Val", "fieldname": "invoice_val", "fieldtype": "Currency", "options": "INR", "width": 120},
		{"label": "True/False", "fieldname": "true_false", "fieldtype": "Data", "width": 80},
		{"label": "Due of PA", "fieldname": "due_of_pa", "fieldtype": "Date", "width": 95},
		{"label": "Aging", "fieldname": "aging", "fieldtype": "Int", "width": 70},
	]


def get_data(filters):
	conditions, values = [], {}
	if filters.get("customer"):
		conditions.append("d.customer = %(customer)s")
		values["customer"] = filters["customer"]
	if filters.get("workflow_state"):
		conditions.append("d.workflow_state = %(workflow_state)s")
		values["workflow_state"] = filters["workflow_state"]
	where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

	deals = frappe.db.sql(
		f"""
		SELECT d.name, d.customer_name, d.location, d.description, d.workflow_state,
		       d.sales_order, d.selected_supplier, d.purchase_order, d.purchase_invoice,
		       d.sales_invoice
		FROM `tabImpart Deal` d
		{where}
		ORDER BY d.modified DESC
		""",
		values,
		as_dict=True,
	)

	rows = []
	for d in deals:
		so = frappe.db.get_value(
			"Sales Order", d.sales_order, ["po_no", "po_date", "base_grand_total"], as_dict=True
		) if d.sales_order else {}
		po = frappe.db.get_value(
			"Purchase Order",
			d.purchase_order,
			["supplier", "incoterm", "transaction_date", "grand_total", "currency",
				"custom_awb_bl_no", "custom_eta", "total_net_weight"],
			as_dict=True,
		) if d.purchase_order else {}
		pi = frappe.db.get_value(
			"Purchase Invoice", d.purchase_invoice, ["bill_no", "grand_total"], as_dict=True
		) if d.purchase_invoice else {}
		si = frappe.db.get_value(
			"Sales Invoice",
			d.sales_invoice,
			["posting_date", "grand_total", "status", "due_date", "outstanding_amount"],
			as_dict=True,
		) if d.sales_invoice else {}

		aging = 0
		true_false = ""
		if si:
			true_false = "TRUE" if si.status == "Paid" else "FALSE"
			if si.status != "Paid" and si.due_date:
				aging = max(date_diff(nowdate(), si.due_date), 0)

		rows.append({
			"deal": d.name,
			"stage": d.workflow_state,
			"customer": d.customer_name,
			"location": d.location,
			"po_no": (so or {}).get("po_no"),
			"po_date": (so or {}).get("po_date"),
			"po_value": (so or {}).get("base_grand_total"),
			"description": d.description,
			"order_to": (po or {}).get("supplier") or d.selected_supplier,
			"inco": (po or {}).get("incoterm"),
			"impart_order": d.purchase_order,
			"odr_date": (po or {}).get("transaction_date"),
			"order_val": (po or {}).get("grand_total"),
			"odr_cur": (po or {}).get("currency"),
			"invoice": (pi or {}).get("bill_no"),
			"in_valu": (pi or {}).get("grand_total"),
			"awb_bl": (po or {}).get("custom_awb_bl_no"),
			"wt_kg": (po or {}).get("total_net_weight"),
			"eta": (po or {}).get("custom_eta"),
			"impart_invoice": d.sales_invoice,
			"invoice_date": (si or {}).get("posting_date"),
			"invoice_val": (si or {}).get("grand_total"),
			"true_false": true_false,
			"due_of_pa": (si or {}).get("due_date"),
			"aging": aging,
		})

	return rows
