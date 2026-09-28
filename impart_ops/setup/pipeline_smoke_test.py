import frappe
from impart_ops.impart_ops import deal_actions as A


def _new(customer, item, qty=5, supplier="Trident Global Computers Inc"):
	deal = frappe.new_doc("Impart Deal")
	deal.customer = customer
	deal.item_code = item
	deal.qty = qty
	deal.company = frappe.db.get_default("company")
	deal.insert(ignore_permissions=True)
	frappe.db.commit()
	return frappe.get_doc("Impart Deal", deal.name)


def _cleanup(d):
	for dt, fname in [
		("Payment Entry", None), ("Sales Invoice", d.sales_invoice), ("Delivery Note", d.delivery_note),
		("Purchase Receipt", d.purchase_receipt), ("Purchase Invoice", d.purchase_invoice),
		("Purchase Order", d.purchase_order), ("Sales Order", d.sales_order), ("Quotation", d.quotation),
		("Supplier Quotation", d.supplier_quotation), ("Request for Quotation", d.request_for_quotation),
		("Opportunity", d.opportunity),
	]:
		if fname:
			try:
				doc = frappe.get_doc(dt, fname)
				if doc.docstatus == 1:
					doc.cancel()
				frappe.delete_doc(dt, fname, force=True, ignore_permissions=True)
			except Exception as e:
				print("cleanup skip", dt, fname, e)
	frappe.delete_doc("Impart Deal", d.name, force=True, ignore_permissions=True)
	frappe.db.commit()


def scenario_full_happy_path():
	print("\n=== SCENARIO: full happy path, single price, paid in full ===")
	d = _new("Nimbus Retail Chain Pvt Ltd", "Desktop Computer - Business Class")
	try:
		A.send_rfq(d.name, ["Trident Global Computers Inc"]); frappe.db.commit()
		A.record_vendor_quote(d.name, "Trident Global Computers Inc", rate=400, currency="USD", exchange_rate=87.5); frappe.db.commit()
		d.reload(); d.fx_buffer_pct=2; d.customs_duty_pct=18; d.freight_inr=20000; d.margin_pct=15; d.save(ignore_permissions=True); frappe.db.commit()
		d.reload()
		A.send_customer_quotation(d.name, rate_inr=d.final_rate_inr); frappe.db.commit()
		A.create_sales_order(d.name, po_no="TEST/PO/001"); frappe.db.commit()
		A.create_purchase_order(d.name); frappe.db.commit()
		A.mark_vendor_confirmed(d.name, confirmation_no="C1"); frappe.db.commit()
		A.mark_shipped(d.name, awb_bl_no="AWB1", eta=frappe.utils.add_days(frappe.utils.nowdate(), 5)); frappe.db.commit()
		A.create_purchase_receipt(d.name); frappe.db.commit()
		A.create_purchase_invoice(d.name, bill_no="VINV1"); frappe.db.commit()
		A.create_delivery_note(d.name); frappe.db.commit()
		A.create_sales_invoice(d.name); frappe.db.commit()
		A.record_customer_payment(d.name); frappe.db.commit()
		A.record_vendor_payment(d.name); frappe.db.commit()
		d.reload()
		print("RESULT:", d.name, d.workflow_state, "(expect Payment Received)")
		assert d.workflow_state == "Payment Received"
		print("PASS")
	except Exception:
		frappe.db.rollback()
		print("FAIL\n", frappe.get_traceback())
	finally:
		_cleanup(d)


def scenario_negotiation_then_reject():
	print("\n=== SCENARIO: 2-round negotiation, then customer rejects ===")
	d = _new("Zenith Manufacturing Ltd", "Server Rack Unit - 2U")
	try:
		A.send_rfq(d.name, ["EuroTech Systems GmbH"]); frappe.db.commit()
		A.record_vendor_quote(d.name, "EuroTech Systems GmbH", rate=2450, currency="EUR", exchange_rate=94.8); frappe.db.commit()
		d.reload(); d.fx_buffer_pct=3; d.customs_duty_pct=15; d.freight_inr=60000; d.margin_pct=18; d.save(ignore_permissions=True); frappe.db.commit()
		d.reload()
		A.send_customer_quotation(d.name, rate_inr=d.final_rate_inr); frappe.db.commit()
		d.reload(); print(" after round 1 quote:", d.workflow_state)

		A.request_revision(d.name, remarks="wants a better price"); frappe.db.commit()
		d.reload(); print(" after request_revision:", d.workflow_state)
		A.record_vendor_quote(d.name, "EuroTech Systems GmbH", rate=2300, currency="EUR", exchange_rate=94.8); frappe.db.commit()
		d.reload(); print(" after 2nd vendor quote:", d.workflow_state)
		A.revise_customer_quotation(d.name, new_rate_inr=d.final_rate_inr); frappe.db.commit()
		d.reload(); print(" after revise (round 2):", d.workflow_state, "| ladder rows:", len(d.ladder))

		A.customer_rejects(d.name, reason="found cheaper local alternative"); frappe.db.commit()
		d.reload()
		print("RESULT:", d.name, d.workflow_state, "(expect Lost / Cancelled)")
		assert d.workflow_state == "Lost / Cancelled"
		assert len(d.ladder) == 4, f"expected 4 ladder rows (2 asks + 2 bids), got {len(d.ladder)}"
		print("PASS")
	except Exception:
		frappe.db.rollback()
		print("FAIL\n", frappe.get_traceback())
	finally:
		_cleanup(d)


def run():
	scenario_full_happy_path()
	scenario_negotiation_then_reject()
