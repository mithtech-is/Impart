## Impart Ops

A Frappe/ERPNext app for Impart's import/export order and quotation
pipeline: the `Impart Deal` doctype, its bid/ask negotiation ladder, and
the native-document wiring that keeps it in sync with Opportunity, Request
for Quotation, Supplier Quotation, Quotation, Sales Order, Purchase Order,
Purchase Receipt, Purchase Invoice, Delivery Note, Sales Invoice, and
Payment Entry across the ERPNext buy/sell pipeline. Only two doctypes here
are custom — everything else is native ERPNext, used as-is.

- **[STATUS.md](STATUS.md)** — what has been built, what has actually been
  tested and verified, what has not been tested yet, and a step-by-step
  guide to testing the negotiation ladder yourself. Read this first.
- **[Spec and walkthrough doc](https://claude.ai/artifact/Pp2nSwvuFdJSARu4n9Y4mJ)**
  — the full architecture explanation, field-by-field mapping to the
  client's original Excel columns, and a button-by-button demo guide.

#### License
mit
