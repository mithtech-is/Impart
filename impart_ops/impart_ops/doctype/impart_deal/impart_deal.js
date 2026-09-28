// Copyright (c) 2026, Impart and contributors
// For license information, please see license.txt

// Every button here does one real pipeline step: it creates (or amends)
// the right native ERPNext document, in the same way impart_ops.setup.demo_data
// does it - so clicking a button is exactly the same code path as the seed
// data, just with your own numbers. After a native document is created you
// will land on ITS screen (so you can look it over, print it, email it);
// come back to this Impart Deal to see the ladder and the stage update,
// or just click the browser Back button.

frappe.ui.form.on("Impart Deal", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_default("company"));
		}
	},
	refresh(frm) {
		if (frm.is_new()) return;
		add_pipeline_buttons(frm);
	},
});

function add_pipeline_buttons(frm) {
	const state = frm.doc.workflow_state;
	const GROUP = __("Pipeline Action");

	// 1. New Inquiry -> send the requirement to one or more foreign vendors.
	// Asking several known vendors at once is normal sourcing practice -
	// whichever one(s) actually reply get picked up later, by name, in
	// Record Vendor Quote.
	if (state === "New Inquiry") {
		frm.add_custom_button(__("Send RFQ to Vendor"), () => {
			frappe.prompt(
				[
					{
						fieldname: "suppliers",
						fieldtype: "MultiSelectList",
						label: __("Vendor(s) to ask"),
						reqd: 1,
						get_data: function (txt) {
							return frappe.db.get_link_options("Supplier", txt);
						},
					},
					{
						fieldname: "message",
						fieldtype: "Small Text",
						label: __("Message to vendor (optional)"),
					},
				],
				(v) => call(frm, "send_rfq", { suppliers: v.suppliers, message: v.message }, true),
				__("Send Request for Quotation")
			);
		}, GROUP);
	}

	// 2. Waiting on a vendor price (first ask, or another negotiation round)
	if (["RFQ Sent to Vendor", "In Negotiation"].includes(state)) {
		frm.add_custom_button(__("Record Vendor Quote (Ask)"), () => {
			// The RFQ already says which vendor(s) this deal asked - don't
			// make the user retype that. Look it up, then either pre-fill
			// it (one vendor asked) or restrict the dropdown to just them
			// (more than one asked).
			frappe.db.get_doc("Request for Quotation", frm.doc.request_for_quotation).then((rfq) => {
				const asked = (rfq.suppliers || []).map((r) => r.supplier);
				const single = asked.length === 1 ? asked[0] : frm.doc.selected_supplier;

				frappe.prompt(
					[
						{
							fieldname: "supplier",
							fieldtype: "Link",
							options: "Supplier",
							label: __("Vendor"),
							default: single,
							reqd: 1,
							read_only: asked.length === 1 ? 1 : 0,
							get_query: () =>
								asked.length
									? { filters: { name: ["in", asked] } }
									: {},
						},
						{
							fieldname: "currency",
							fieldtype: "Link",
							options: "Currency",
							label: __("Currency"),
							default: frm.doc.vendor_currency || "USD",
							reqd: 1,
						},
						{
							fieldname: "rate",
							fieldtype: "Currency",
							label: __("Vendor rate per unit"),
							reqd: 1,
						},
						{
							fieldname: "exchange_rate",
							fieldtype: "Float",
							label: __("Exchange rate to INR"),
							default: frm.doc.exchange_rate || 1,
							reqd: 1,
						},
					],
					(v) => call(frm, "record_vendor_quote", v, true),
					__("Record the Vendor's Price")
				);
			});
		}, GROUP);
		frm.add_custom_button(
			__("...or: vendor submits it themselves via the Supplier Portal"),
			() => frappe.msgprint({
				title: __("Vendor Portal"),
				message: __(
					"The vendor can log in at <b>/rfq</b> with their own portal account and " +
					"submit their price directly - no login sharing needed. It lands here as a " +
					"draft Supplier Quotation, already linked to this deal. Open it from the " +
					"Connections tab below and click <b>Submit</b> to bring it into the ladder."
				),
			}),
			GROUP
		);
	}

	// 3. Vendor's price is in - quote the customer in INR
	if (state === "Vendor Quote Received") {
		frm.add_custom_button(__("Send Customer Quotation (Bid)"), () => {
			if (!frm.doc.final_rate_inr) {
				frappe.msgprint(__(
					"Set the FX Buffer / Customs Duty / Freight / Margin / GST fields above and " +
					"save first, so the Final Quoted Rate is computed."
				));
				return;
			}
			frappe.confirm(
				__("Send the customer a quotation at {0} per unit (INR)?", [
					format_currency(frm.doc.final_rate_inr, "INR"),
				]),
				() => call(frm, "send_customer_quotation", { rate_inr: frm.doc.final_rate_inr }, true)
			);
		}, GROUP);
	}

	// 4. Customer has a quotation in hand - approve, negotiate, or reject
	if (["Customer Quotation Sent", "In Negotiation"].includes(state)) {
		frm.add_custom_button(__("Customer Requests Revision"), () => {
			frappe.prompt(
				[{ fieldname: "remarks", fieldtype: "Small Text", label: __("What did the customer ask for?") }],
				(v) => call(frm, "request_revision", v, false),
				__("Move to Negotiation")
			);
		}, GROUP);

		frm.add_custom_button(__("Revise Customer Quotation"), () => {
			if (!frm.doc.final_rate_inr) {
				frappe.msgprint(__("Update the pricing calculator fields and save first."));
				return;
			}
			frappe.confirm(
				__("Amend the Quotation to {0} per unit (INR)?", [format_currency(frm.doc.final_rate_inr, "INR")]),
				() => call(frm, "revise_customer_quotation", { new_rate_inr: frm.doc.final_rate_inr }, true)
			);
		}, GROUP);

		frm.add_custom_button(__("Customer Approves → Create Sales Order"), () => {
			frappe.prompt(
				[
					{ fieldname: "po_no", fieldtype: "Data", label: __("Customer's PO Number") },
					{ fieldname: "po_date", fieldtype: "Date", label: __("Customer's PO Date"), default: frappe.datetime.get_today() },
				],
				(v) => call(frm, "create_sales_order", v, true),
				__("Create Sales Order")
			);
		}, GROUP);

		frm.add_custom_button(__("Customer Rejects"), () => {
			frappe.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason") }],
				(v) => call(frm, "customer_rejects", v, false),
				__("Mark this Deal Lost")
			);
		}, GROUP);
	}

	// 5. Customer approved - place the order on the vendor
	if (state === "Customer Approved") {
		frm.add_custom_button(__("Create Purchase Order (to Vendor)"), () => {
			frappe.prompt(
				[
					{
						fieldname: "incoterm",
						fieldtype: "Link",
						options: "Incoterm",
						label: __("Incoterm"),
						default: "CIF",
					},
					{ fieldname: "schedule_days", fieldtype: "Int", label: __("Expected in (days)"), default: 25 },
				],
				(v) => call(frm, "create_purchase_order", v, true),
				__("Order from Vendor")
			);
		}, GROUP);
	}

	// 6. Order placed - vendor confirms it
	if (state === "Order Placed with Vendor") {
		frm.add_custom_button(__("Mark Vendor Confirmed"), () => {
			frappe.prompt(
				[{ fieldname: "confirmation_no", fieldtype: "Data", label: __("Vendor's Confirmation No.") }],
				(v) => call(frm, "mark_vendor_confirmed", v, false),
				__("Vendor Order Confirmation")
			);
		}, GROUP);
	}

	// 7. Vendor confirmed - they dispatch
	if (state === "Vendor Order Confirmed") {
		frm.add_custom_button(__("Mark Shipped"), () => {
			frappe.prompt(
				[
					{ fieldname: "awb_bl_no", fieldtype: "Data", label: __("AWB / BL No"), reqd: 1 },
					{ fieldname: "eta", fieldtype: "Date", label: __("ETA"), reqd: 1 },
				],
				(v) => call(frm, "mark_shipped", v, false),
				__("Shipment Details")
			);
		}, GROUP);
	}

	// 8. In transit - goods arrive & are checked in
	if (state === "Shipped / In Transit") {
		frm.add_custom_button(__("Create Purchase Receipt (Goods Received)"), () => {
			frappe.confirm(__("Confirm the goods have arrived and been checked?"), () =>
				call(frm, "create_purchase_receipt", {}, true)
			);
		}, GROUP);
	}

	// 9. Received - send onward to the customer
	if (state === "Received at Impart") {
		frm.add_custom_button(__("Create Delivery Note (Dispatch to Customer)"), () => {
			call(frm, "create_delivery_note", {}, true);
		}, GROUP);
	}

	// 10. Delivered - bill the customer
	if (state === "Delivered to Customer") {
		frm.add_custom_button(__("Create Sales Invoice (Bill Customer)"), () => {
			frappe.prompt(
				[{ fieldname: "credit_days", fieldtype: "Int", label: __("Credit period (days)"), default: 30 }],
				(v) => call(frm, "create_sales_invoice", v, true),
				__("Raise Invoice")
			);
		}, GROUP);
	}

	// 11. Invoiced - collect payment
	if (state === "Invoiced") {
		frm.add_custom_button(__("Record Customer Payment"), () => {
			frappe.prompt(
				[
					{ fieldname: "paid_amount", fieldtype: "Currency", label: __("Amount received (blank = full outstanding)") },
					{ fieldname: "posting_date", fieldtype: "Date", label: __("Date"), default: frappe.datetime.get_today() },
				],
				(v) => call(frm, "record_customer_payment", v, false),
				__("Customer Payment")
			);
		}, GROUP);
	}

	// Always available once the vendor's own invoice exists, independent
	// of the main customer-side pipeline stage above.
	if (frm.doc.purchase_order && !frm.doc.purchase_invoice) {
		frm.add_custom_button(__("Record Vendor's Invoice"), () => {
			frappe.prompt(
				[
					{ fieldname: "bill_no", fieldtype: "Data", label: __("Vendor's Invoice No.") },
					{ fieldname: "bill_date", fieldtype: "Date", label: __("Vendor's Invoice Date"), default: frappe.datetime.get_today() },
				],
				(v) => call(frm, "create_purchase_invoice", v, true),
				__("Principal's Commercial Invoice")
			);
		}, GROUP);
	}
	if (frm.doc.purchase_invoice) {
		frm.add_custom_button(__("Record Vendor Payment"), () => {
			frappe.prompt(
				[
					{ fieldname: "paid_amount", fieldtype: "Currency", label: __("Amount paid (blank = full outstanding)") },
					{ fieldname: "posting_date", fieldtype: "Date", label: __("Date"), default: frappe.datetime.get_today() },
				],
				(v) => call(frm, "record_vendor_payment", v, false),
				__("Pay the Vendor")
			);
		}, GROUP);
	}
}

function call(frm, method, args, open_result) {
	frappe.call({
		method: `impart_ops.impart_ops.deal_actions.${method}`,
		args: Object.assign({ deal_name: frm.doc.name }, args),
		freeze: true,
		freeze_message: __("Working..."),
		callback: (r) => {
			frm.reload_doc();
			if (open_result && r.message && r.message.doctype && r.message.name) {
				frappe.show_alert({ message: __("Created {0}", [r.message.name]), indicator: "green" });
				frappe.set_route("Form", r.message.doctype, r.message.name);
			}
		},
	});
}
