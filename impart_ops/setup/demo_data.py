# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt
"""
Seeds a complete, realistic demo: 2 foreign vendors (one billing in USD,
one in EUR - each with a real Supplier Portal login, portal-only, no desk
access), 5 domestic customers, 5 computer-hardware items, and 6 Impart
Deals that between them walk through every stage of the pipeline:

  Deal 1  Nimbus Retail Chain   - fully closed & paid end to end
  Deal 2  Zenith Manufacturing  - negotiated over 3 rounds, delivered &
                                   invoiced, payment still outstanding
                                   (overdue, so Aging > 0)
  Deal 3  BlueOrbit Logistics   - PO placed, vendor invoiced, shipped,
                                   still in transit (ETA in the future)
  Deal 4  Skyline Hospitals     - mid-negotiation, no Sales Order yet
  Deal 5  Coral Reef Exports    - quoted, then lost
  Deal 6  Solstice Textiles     - left at "RFQ Sent to Vendor" so the
                                   vendor's own Supplier Portal login can
                                   be demoed live (vendor logs in, sees
                                   the RFQ, submits a price himself)

Run with:
    bench --site impart.local execute impart_ops.setup.demo_data.run
Safe to re-run: run() clears any deals/masters it created before (by a
name prefix) and rebuilds from scratch.
"""

import frappe
from frappe.utils import add_days, nowdate

from impart_ops.impart_ops import deal_actions as A

COMPANY = "Impart Trading Pvt Ltd"

ITEMS = [
	{"item_code": "Desktop Computer - Business Class", "weight": 8},
	{"item_code": "Laptop - Business Ultrabook", "weight": 2},
	{"item_code": "Server Rack Unit - 2U", "weight": 25},
	{"item_code": "Network Switch - 24 Port Managed", "weight": 4},
	{"item_code": "UPS Backup Unit - 2KVA", "weight": 15},
]

SUPPLIERS = [
	{
		"name": "Trident Global Computers Inc",
		"country": "United States",
		"currency": "USD",
		"portal_email": "sales@tridentglobal.example",
		"portal_name": "Mark Whitfield",
	},
	{
		"name": "EuroTech Systems GmbH",
		"country": "Germany",
		"currency": "EUR",
		"portal_email": "vertrieb@eurotech-systems.example",
		"portal_name": "Lukas Bergmann",
	},
]

PORTAL_PASSWORD = "Vendor@2026"

CUSTOMERS = [
	{"name": "Nimbus Retail Chain Pvt Ltd", "city": "Mumbai", "state": "Maharashtra"},
	{"name": "Zenith Manufacturing Ltd", "city": "Pune", "state": "Maharashtra"},
	{"name": "BlueOrbit Logistics Pvt Ltd", "city": "Bengaluru", "state": "Karnataka"},
	{"name": "Skyline Hospitals Pvt Ltd", "city": "New Delhi", "state": "Delhi"},
	{"name": "Coral Reef Exports Pvt Ltd", "city": "Chennai", "state": "Tamil Nadu"},
	{"name": "Solstice Textiles Pvt Ltd", "city": "Ahmedabad", "state": "Gujarat"},
]


def run():
	frappe.flags.in_test = frappe.flags.in_test or False
	setup_items()
	setup_suppliers()
	setup_customers()
	frappe.db.commit()

	results = {}
	for fn in (deal_1, deal_2, deal_3, deal_4, deal_5, deal_6):
		try:
			deal = fn()
			frappe.db.commit()
			results[fn.__name__] = f"OK -> {deal.name} [{deal.workflow_state}]"
		except Exception:
			frappe.db.rollback()
			results[fn.__name__] = f"FAILED\n{frappe.get_traceback()}"

	for k, v in results.items():
		print(f"\n=== {k} ===\n{v}")
	return results


# ---------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------

def _warehouse():
	return frappe.db.get_value("Warehouse", {"company": COMPANY, "warehouse_name": "Stores"}, "name")


def setup_items():
	warehouse = _warehouse()
	for spec in ITEMS:
		if frappe.db.exists("Item", spec["item_code"]):
			continue
		item = frappe.new_doc("Item")
		item.item_code = spec["item_code"]
		item.item_name = spec["item_code"]
		item.item_group = "Products"
		item.stock_uom = "Nos"
		item.is_stock_item = 1
		item.weight_per_unit = spec["weight"]
		item.weight_uom = "Kg"
		item.append("item_defaults", {
			"company": COMPANY,
			"default_warehouse": warehouse,
		})
		item.insert(ignore_permissions=True)


def setup_suppliers():
	for spec in SUPPLIERS:
		if not frappe.db.exists("Supplier", spec["name"]):
			sup = frappe.new_doc("Supplier")
			sup.supplier_name = spec["name"]
			sup.supplier_group = "Distributor"
			sup.supplier_type = "Company"
			sup.country = spec["country"]
			sup.default_currency = spec["currency"]
			sup.insert(ignore_permissions=True)

		_create_portal_login(
			doctype="Supplier",
			party=spec["name"],
			email=spec["portal_email"],
			full_name=spec["portal_name"],
			role="Supplier",
		)


def setup_customers():
	for spec in CUSTOMERS:
		if frappe.db.exists("Customer", spec["name"]):
			continue
		cust = frappe.new_doc("Customer")
		cust.customer_name = spec["name"]
		cust.customer_group = "Commercial"
		cust.customer_type = "Company"
		cust.territory = "India"
		cust.insert(ignore_permissions=True)

		address = frappe.new_doc("Address")
		address.address_title = spec["name"]
		address.address_type = "Billing"
		address.address_line1 = "Industrial Estate"
		address.city = spec["city"]
		address.state = spec["state"]
		address.country = "India"
		address.append("links", {"link_doctype": "Customer", "link_name": spec["name"]})
		address.insert(ignore_permissions=True)


def _create_portal_login(doctype, party, email, full_name, role):
	"""Portal-only login: Website User + the party's role, no desk access.
	Impart's own staff use System User accounts with the Impart User role
	instead - the two are kept completely separate on purpose."""
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = full_name
		user.user_type = "Website User"
		user.send_welcome_email = 0
		user.append("roles", {"role": role})
		user.new_password = PORTAL_PASSWORD
		user.flags.ignore_password_policy = True
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.new_password = PORTAL_PASSWORD
		user.flags.ignore_password_policy = True
		user.save(ignore_permissions=True)

	party_doc = frappe.get_doc(doctype, party)
	if email not in [d.user for d in party_doc.get("portal_users", [])]:
		party_doc.append("portal_users", {"user": email})
		party_doc.save(ignore_permissions=True)

	if not frappe.db.exists("Contact", {"email_id": email}):
		contact = frappe.new_doc("Contact")
		contact.first_name = full_name
		contact.append("email_ids", {"email_id": email, "is_primary": 1})
		contact.append("links", {"link_doctype": doctype, "link_name": party})
		contact.insert(ignore_permissions=True)


def _find_deal(customer):
	name = frappe.db.get_value(
		"Impart Deal", {"customer": customer}, "name", order_by="creation desc"
	)
	return frappe.get_doc("Impart Deal", name) if name else None


def _price(deal_name, fx_buffer, duty, freight, margin, gst=18):
	deal = frappe.get_doc("Impart Deal", deal_name)
	deal.fx_buffer_pct = fx_buffer
	deal.customs_duty_pct = duty
	deal.freight_inr = freight
	deal.margin_pct = margin
	deal.gst_pct = gst
	deal.save(ignore_permissions=True)
	deal.reload()
	return deal.final_rate_inr


# ---------------------------------------------------------------------
# Deal 1 - Nimbus Retail Chain: fully closed & paid
# ---------------------------------------------------------------------

def deal_1():
	customer = "Nimbus Retail Chain Pvt Ltd"
	deal = A.new_deal(
		customer=customer, item_code="Desktop Computer - Business Class", qty=50,
		description="50x Business-class desktop computers for new store rollout.",
		company=COMPANY,
	)
	deal.location = "Mumbai, Maharashtra"
	deal.save(ignore_permissions=True)

	A.send_rfq(deal.name, ["Trident Global Computers Inc"])
	A.record_vendor_quote(deal.name, "Trident Global Computers Inc", rate=420, currency="USD", exchange_rate=87.5)
	rate = _price(deal.name, fx_buffer=2, duty=18, freight=45000, margin=15)
	A.send_customer_quotation(deal.name, rate_inr=rate)

	A.create_sales_order(deal.name, po_no="NIM/PO/2026/041", po_date=nowdate())
	A.create_purchase_order(deal.name, incoterm="FOB")
	A.mark_vendor_confirmed(deal.name, confirmation_no="TGC-CONF-3301")
	A.mark_shipped(deal.name, awb_bl_no="AWB-176-30442918", eta=add_days(nowdate(), -2))
	A.create_purchase_receipt(deal.name)
	A.create_purchase_invoice(deal.name, bill_no="TGC/INV/2026/1187")
	A.create_delivery_note(deal.name)
	A.create_sales_invoice(deal.name, credit_days=15)
	A.record_customer_payment(deal.name)
	A.record_vendor_payment(deal.name)
	return _find_deal(customer)


# ---------------------------------------------------------------------
# Deal 2 - Zenith Manufacturing: 3-round negotiation, delivered, UNPAID
# ---------------------------------------------------------------------

def deal_2():
	customer = "Zenith Manufacturing Ltd"
	deal = A.new_deal(
		customer=customer, item_code="Server Rack Unit - 2U", qty=10,
		description="10x 2U rack servers for new data room.",
		company=COMPANY,
	)
	deal.location = "Pune, Maharashtra"
	deal.save(ignore_permissions=True)

	A.send_rfq(deal.name, ["EuroTech Systems GmbH"])

	# Round 1 - opening prices
	A.record_vendor_quote(deal.name, "EuroTech Systems GmbH", rate=2450, currency="EUR", exchange_rate=94.8)
	rate1 = _price(deal.name, fx_buffer=3, duty=15, freight=60000, margin=18)
	A.send_customer_quotation(deal.name, rate_inr=rate1)

	# Round 2 - customer negotiates, Impart goes back to vendor
	A.request_revision(deal.name, remarks="Customer asked for a better price (round 2).")
	A.record_vendor_quote(deal.name, "EuroTech Systems GmbH", rate=2300, currency="EUR", exchange_rate=94.8)
	rate2 = _price(deal.name, fx_buffer=3, duty=15, freight=55000, margin=15)
	A.revise_customer_quotation(deal.name, new_rate_inr=rate2)

	# Round 3 - final agreed price
	A.request_revision(deal.name, remarks="Customer countered again (round 3, final).")
	A.record_vendor_quote(deal.name, "EuroTech Systems GmbH", rate=2225, currency="EUR", exchange_rate=94.8)
	rate3 = _price(deal.name, fx_buffer=3, duty=15, freight=55000, margin=13)
	A.revise_customer_quotation(deal.name, new_rate_inr=rate3)

	A.create_sales_order(deal.name, po_no="ZML/CAP/2026/0087", po_date=nowdate())
	A.create_purchase_order(deal.name, incoterm="CIF")
	A.mark_vendor_confirmed(deal.name, confirmation_no="ETS-CONF-9915")
	A.mark_shipped(deal.name, awb_bl_no="MAEU-BL-88214477", eta=add_days(nowdate(), -5))
	A.create_purchase_receipt(deal.name)
	A.create_purchase_invoice(deal.name, bill_no="ETS/RE/2026/554")
	A.create_delivery_note(deal.name)
	# Backdated so the invoice is genuinely overdue today, without ever
	# setting a due_date before its own posting_date (ERPNext enforces that).
	A.create_sales_invoice(deal.name, posting_date=add_days(nowdate(), -20), credit_days=8)
	return _find_deal(customer)


# ---------------------------------------------------------------------
# Deal 3 - BlueOrbit Logistics: shipped, still in transit
# ---------------------------------------------------------------------

def deal_3():
	customer = "BlueOrbit Logistics Pvt Ltd"
	deal = A.new_deal(
		customer=customer, item_code="UPS Backup Unit - 2KVA", qty=30,
		description="30x 2KVA UPS units for warehouse automation racks.",
		company=COMPANY,
	)
	deal.location = "Bengaluru, Karnataka"
	deal.save(ignore_permissions=True)

	A.send_rfq(deal.name, ["Trident Global Computers Inc"])
	A.record_vendor_quote(deal.name, "Trident Global Computers Inc", rate=165, currency="USD", exchange_rate=87.8)
	rate = _price(deal.name, fx_buffer=2.5, duty=12, freight=30000, margin=16)
	A.send_customer_quotation(deal.name, rate_inr=rate)

	A.create_sales_order(deal.name, po_no="BOL/PO/2026/0219", po_date=nowdate())
	A.create_purchase_order(deal.name, incoterm="FOB")
	A.mark_vendor_confirmed(deal.name, confirmation_no="TGC-CONF-3355")
	A.mark_shipped(deal.name, awb_bl_no="AWB-176-30559102", eta=add_days(nowdate(), 7))
	A.create_purchase_invoice(deal.name, bill_no="TGC/INV/2026/1210")
	# Deliberately no Purchase Receipt yet - goods are still in transit.
	return _find_deal(customer)


# ---------------------------------------------------------------------
# Deal 4 - Skyline Hospitals: mid-negotiation, no Sales Order yet
# ---------------------------------------------------------------------

def deal_4():
	customer = "Skyline Hospitals Pvt Ltd"
	deal = A.new_deal(
		customer=customer, item_code="Laptop - Business Ultrabook", qty=100,
		description="100x ultrabooks for hospital administration rollout.",
		company=COMPANY,
	)
	deal.location = "New Delhi, Delhi"
	deal.save(ignore_permissions=True)

	A.send_rfq(deal.name, ["EuroTech Systems GmbH"])
	A.record_vendor_quote(deal.name, "EuroTech Systems GmbH", rate=780, currency="EUR", exchange_rate=94.8)
	rate1 = _price(deal.name, fx_buffer=3, duty=15, freight=40000, margin=17)
	A.send_customer_quotation(deal.name, rate_inr=rate1)

	A.request_revision(deal.name, remarks="Customer wants a volume discount for 100 units.")
	A.record_vendor_quote(deal.name, "EuroTech Systems GmbH", rate=745, currency="EUR", exchange_rate=94.8)
	rate2 = _price(deal.name, fx_buffer=3, duty=15, freight=38000, margin=14)
	A.revise_customer_quotation(deal.name, new_rate_inr=rate2)
	# Still with the customer for a decision - nothing further yet.
	return _find_deal(customer)


# ---------------------------------------------------------------------
# Deal 5 - Coral Reef Exports: quoted, then lost
# ---------------------------------------------------------------------

def deal_5():
	customer = "Coral Reef Exports Pvt Ltd"
	deal = A.new_deal(
		customer=customer, item_code="Network Switch - 24 Port Managed", qty=20,
		description="20x managed switches for new export packing unit.",
		company=COMPANY,
	)
	deal.location = "Chennai, Tamil Nadu"
	deal.save(ignore_permissions=True)

	A.send_rfq(deal.name, ["Trident Global Computers Inc"])
	A.record_vendor_quote(deal.name, "Trident Global Computers Inc", rate=210, currency="USD", exchange_rate=87.5)
	rate = _price(deal.name, fx_buffer=2, duty=18, freight=20000, margin=20)
	A.send_customer_quotation(deal.name, rate_inr=rate)
	A.customer_rejects(deal.name, reason="Customer found a cheaper local alternative.")
	return _find_deal(customer)


# ---------------------------------------------------------------------
# Deal 6 - Solstice Textiles: left open for a LIVE vendor-portal demo
# ---------------------------------------------------------------------

def deal_6():
	customer = "Solstice Textiles Pvt Ltd"
	deal = A.new_deal(
		customer=customer, item_code="Desktop Computer - Business Class", qty=15,
		description="15x desktop computers for new admin block (LIVE DEMO: "
		"log in as the vendor's portal user to submit this quote yourself).",
		company=COMPANY,
	)
	deal.location = "Ahmedabad, Gujarat"
	deal.save(ignore_permissions=True)

	A.send_rfq(
		deal.name, ["EuroTech Systems GmbH"],
		message="Please quote your best price for 15 business-class desktop computers.",
	)
	# Deliberately left here: open the vendor's Supplier Portal
	# (/rfq, login vertrieb@eurotech-systems.example) to submit the price live.
	return _find_deal(customer)
