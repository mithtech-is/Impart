app_name = "impart_ops"
app_title = "Impart Ops"
app_publisher = "Impart"
app_description = "Impart order, quotation and logistics tracking"
app_email = "support@impart.local"
app_license = "mit"

# Installation
# ------------
after_install = "impart_ops.setup.install.after_install"

# Document Events
# ---------------
# Every stage of the customer <-> Impart <-> vendor pipeline is a native
# ERPNext document. These hooks keep the custom "Impart Deal" record (the
# single-screen view) automatically in sync with those native documents:
# every submit of a Supplier Quotation (an "Ask" from the vendor) or a
# Quotation (a "Bid" to the customer) - including every amendment, which is
# how a negotiation revision is represented - appends one row to the deal's
# bid/ask ladder, and every submit of a downstream document (Sales Order,
# Purchase Order, Purchase Receipt, Purchase Invoice, Delivery Note, Sales
# Invoice) links itself back onto the deal and advances its stage.
doc_events = {
	"Supplier Quotation": {
		"before_insert": "impart_ops.impart_ops.deal_sync.set_deal_on_supplier_quotation",
		"on_submit": "impart_ops.impart_ops.deal_sync.on_supplier_quotation_submit",
		"on_cancel": "impart_ops.impart_ops.deal_sync.on_supplier_quotation_cancel",
	},
	"Quotation": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_quotation_submit",
		"on_cancel": "impart_ops.impart_ops.deal_sync.on_quotation_cancel",
	},
	"Sales Order": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_sales_order_submit",
	},
	"Purchase Order": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_purchase_order_submit",
	},
	"Purchase Receipt": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_purchase_receipt_submit",
	},
	"Purchase Invoice": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_purchase_invoice_submit",
	},
	"Delivery Note": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_delivery_note_submit",
	},
	"Sales Invoice": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_sales_invoice_submit",
	},
	"Payment Entry": {
		"on_submit": "impart_ops.impart_ops.deal_sync.on_payment_entry_submit",
	},
}
