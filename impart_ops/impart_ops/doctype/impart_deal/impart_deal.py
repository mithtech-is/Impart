# Copyright (c) 2026, Impart and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class ImpartDeal(Document):
	def validate(self):
		self.calculate_pricing()
		self.renumber_ladder()

	def after_insert(self):
		# A deal must always have its own Opportunity - the native record of
		# the customer's incoming request - the moment it is first saved, no
		# matter how it was created: by hand on the desk's New form, or via
		# impart_ops.deal_actions.new_deal(). Creating it here, once, in the
		# controller itself (rather than only inside new_deal()) means every
		# deal gets one automatically and the "Send RFQ to Vendor" button
		# always has something real to map from.
		if self.opportunity:
			return
		opp = frappe.new_doc("Opportunity")
		opp.opportunity_from = "Customer"
		opp.party_name = self.customer
		opp.company = self.company
		opp.transaction_date = self.deal_date
		opp.custom_impart_deal = self.name
		opp.append("items", {
			"item_code": self.item_code,
			"qty": self.qty,
			"uom": frappe.db.get_value("Item", self.item_code, "stock_uom"),
			# nominal placeholder - the real price is negotiated later and
			# lives on this deal's own pricing calculator, not here.
			"rate": 1,
		})
		opp.insert(ignore_permissions=True)
		self.db_set("opportunity", opp.name, update_modified=False)

	def calculate_pricing(self):
		"""
		Pricing sequence (all inputs are entered manually by the Impart
		user for every deal, since they change per order):

		1. Vendor Amount (INR) = Vendor Rate x Qty x Exchange Rate
		2. Landed Cost/unit  = (Vendor Rate x Exchange Rate) x (1 + FX Buffer %)
		                        + Freight/unit + Customs Duty % on that subtotal
		3. Final Rate/unit   = Landed Cost/unit x (1 + Margin %)
		4. Final Quotation Value (incl. GST) = Final Rate x Qty x (1 + GST %)
		"""
		qty = flt(self.qty) or 0
		vendor_rate = flt(self.vendor_rate)
		exchange_rate = flt(self.exchange_rate) or 1

		self.vendor_amount_inr = vendor_rate * qty * exchange_rate

		base_inr_per_unit = vendor_rate * exchange_rate
		buffered = base_inr_per_unit * (1 + flt(self.fx_buffer_pct) / 100)
		freight_per_unit = (flt(self.freight_inr) / qty) if qty else flt(self.freight_inr)
		with_freight = buffered + freight_per_unit
		with_duty = with_freight * (1 + flt(self.customs_duty_pct) / 100)
		self.landed_cost_inr = with_duty

		final_rate = with_duty * (1 + flt(self.margin_pct) / 100)
		self.final_rate_inr = final_rate

		self.final_quotation_value_inr = final_rate * qty * (1 + flt(self.gst_pct) / 100)

	def renumber_ladder(self):
		"""Keep round numbers sequential per side (Ask / Bid) so the
		depth view always reads 1, 2, 3... on each side even if rows
		were added out of order."""
		counters = {"Ask": 0, "Bid": 0}
		for row in sorted(self.ladder, key=lambda r: (r.idx or 0)):
			counters[row.side] = counters.get(row.side, 0) + 1
			row.round = counters[row.side]
