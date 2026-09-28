# Impart Ops — Build Status

Last updated: 28 September 2026

This document is the honest record of what has been built, what has actually
been verified working, and what has not been tested yet. It exists so the
next person picking this up (including a future session of Claude) does not
have to re-discover any of this the hard way.

The running demo lives on `impart.local:8002` on the project VM
(`192.168.64.6`), inside the `frappe-bench` that also hosts other sites. This
repository is a copy of the `impart_ops` custom app from that bench.

---

## 1. What this is

A Frappe/ERPNext app for Impart, an import/export trading business. One
custom doctype, **Impart Deal**, is the single screen that maps a domestic
customer's request through to a foreign vendor's fulfillment of it. Every
other step of the pipeline — the RFQ, the vendor's quotation, the customer's
quotation, the sales order, the purchase order, receipt, delivery, invoicing,
payment — is a **native ERPNext document**, not something custom-built. See
the published spec/walkthrough doc for the full field-by-field mapping and a
button-by-button guide:
<https://claude.ai/artifact/Pp2nSwvuFdJSARu4n9Y4mJ>

## 2. Architecture, in one paragraph

`Impart Deal` (custom) holds the customer, item, pricing calculator, current
pipeline stage (driven by a real Frappe Workflow with 14 states and 16
transitions), and link fields to every native document produced for it.
`Impart Deal Entry` (custom, a child table) is the bid/ask negotiation
ladder — one row per round, Ask (vendor price) or Bid (customer price),
linked back to the native document that produced it. `doc_events` hooks in
`deal_sync.py` keep the deal's links and stage in sync automatically whenever
a linked native document is submitted or cancelled. `deal_actions.py` is the
single engine — one function per real pipeline step — used identically by
the form's own buttons (`impart_deal.js`) and by the demo seed script
(`setup/demo_data.py`), so a button click and a seeded deal go through
exactly the same code.

Two small custom fields exist on Purchase Order (`custom_awb_bl_no`,
`custom_eta`) — the only two pieces of data in the whole pipeline with no
native ERPNext home. Everything else (Incoterm, weight, PO number, invoice
numbers, due dates, aging) comes straight from native fields.

## 3. What has been built

- Custom doctypes: `Impart Deal`, `Impart Deal Entry` (child table).
- `custom_impart_deal` link field added to 11 native doctypes (Opportunity,
  Request for Quotation, Supplier Quotation, Quotation, Sales Order,
  Purchase Order, Purchase Receipt, Purchase Invoice, Delivery Note, Sales
  Invoice, Payment Entry).
- `custom_awb_bl_no` / `custom_eta` on Purchase Order.
- A 14-state, 16-transition Frappe Workflow on Impart Deal, with a
  `condition` on every transition that requires the real backing document
  to already exist — see §6.2, this was a real bug fix, not a first-draft
  design.
- `impart_deal.js` — guided "Pipeline Action" buttons on the Deal form, one
  per real business step, each calling the matching `deal_actions.py`
  function.
- `deal_actions.py` — the engine: `new_deal`, `send_rfq`,
  `record_vendor_quote`, `send_customer_quotation`, `request_revision`,
  `revise_customer_quotation`, `customer_rejects`, `create_sales_order`,
  `create_purchase_order`, `mark_vendor_confirmed`, `mark_shipped`,
  `create_purchase_receipt`, `create_purchase_invoice`,
  `create_delivery_note`, `create_sales_invoice`, `record_customer_payment`,
  `record_vendor_payment`.
- `deal_sync.py` — `doc_events` hooks that keep the deal's stage and links
  current whenever a linked native document is submitted/cancelled.
  Defensive by design: every hook checks `custom_impart_deal` is set before
  doing anything, and never raises, so a bug here can never block an
  unrelated business document from being submitted.
- `Impart Deal Tracker` — a script report reproducing the client's original
  23-column Excel sheet, live from the linked native documents, with
  working **Customer** and **Stage** filter boxes.
- The **Impart** workspace — the single landing screen, restricted to
  System Manager and the `Impart User` role.
- `setup/install.py` — idempotent one-time site setup: the `Impart User`
  role, all custom fields, the workflow, the multi-currency accounting
  setting needed for foreign-currency vendor invoices, the two minimal
  permission grants the Supplier Portal needs (see §6.3), the workspace.
- `setup/demo_data.py` — seeds 2 foreign vendors (one USD, one EUR — each
  with a real, portal-only Supplier Portal login), 5 domestic customers, 5
  items, and 6 deals covering every pipeline stage.
- A real, working **Supplier Portal** integration: a vendor logs in at
  `/rfq` with their own account (Website User, `Supplier` role only, no
  desk access) and submits their own price through native ERPNext, no
  custom code on that side at all.

## 4. What has been tested and verified — specifically

Not "should work" — these were actually run, through the real code paths a
person uses, and re-verified after every fix below.

- **The full happy path**, button by button, in an actual browser: create a
  deal → send RFQ → record vendor quote → set the pricing calculator → send
  customer quotation → customer approves → sales order → purchase order →
  vendor confirmed → shipped → received → vendor invoice → delivery note →
  sales invoice → customer payment → vendor payment. Reaches **Payment
  Received** correctly.
- **Multi-round negotiation**: 2 and 3-round negotiate-then-revise cycles,
  each round correctly appending to the ladder with the right round number
  and Superseded/Sent status, ending in either approval or rejection.
- **Customer rejection** → Lost / Cancelled, with the reason recorded.
- **The vendor's own Supplier Portal submission**, end to end: logged in as
  the real vendor account, submitted a price through the native `/rfq`
  page, confirmed it created a draft Supplier Quotation auto-tagged to the
  right deal (via a `before_insert` hook tracing the RFQ link — the portal's
  own code has no idea Impart Deal exists), then submitted it as Impart
  staff and confirmed the ladder and stage updated.
- **A genuinely logged-out visitor** gets refused (403, "Not Permitted") on
  both the desk and the portal — access control is enforced, not just
  hidden by the UI.
- **One vendor cannot open another vendor's own Purchase Order** by
  guessing the URL — confirmed with a real cross-account test, refused with
  403.
- **The Impart Deal Tracker report** — column values checked against the
  underlying native documents by hand, including correct Aging calculation
  on a deliberately overdue, unpaid invoice.
- **The multi-vendor RFQ flow** — sending one RFQ to several vendors at
  once, and the follow-up "Record Vendor Quote" step correctly restricting
  its vendor field to only those actually asked.

## 5. Known simplifications (deliberate, agreed with the client)

- GST is a flat configurable rate on the pricing calculator, not a full
  CGST/SGST/IGST split.
- FX rates are entered manually per deal, not fetched live.
- Only Impart staff have desk access; there is no customer-facing portal
  yet (the vendor Supplier Portal is built; the analogous Customer Portal
  is not, though ERPNext ships one and it could be enabled the same way).
- No payment reminder / dunning emails are configured (ERPNext's native
  Dunning doctype covers this and needs no new development, just
  configuration, once the reminder rules are confirmed).
- Demo data is invented (Kotian's real historical workbook was never
  provided).
- Reusing this app for Polemarch is architecturally supported (nothing is
  hard-coded to the word "Impart" in code) but has never actually been
  installed or exercised on a second site.

## 6. Bugs found and fixed while testing through the real UI

Worth recording precisely, because all three were invisible to script-based
testing and only surfaced once the actual desk UI was clicked through by
hand — the lesson driving the "what still needs testing" list below.

1. **Company field default.** `"default": "company:default"` in the
   doctype JSON is not valid Frappe syntax; it made every deal created from
   the desk's own New form fail immediately. Fixed by removing the bad
   default and setting it via client script (`onload`) instead, matching
   how native ERPNext forms handle it.
2. **A native workflow button could fake a stage with no real document.**
   Frappe automatically offers a plain status-change action for every valid
   workflow transition, in addition to this app's own guided buttons, and
   the two can have near-identical labels. Clicking the bare one just
   flips the Stage field with nothing behind it. Fixed with a `condition`
   on every transition that requires the real linked document to already
   exist, enforced server-side (not just hidden from the menu) — confirmed
   by direct API test that a bare transition attempt is now refused.
3. **A deal created directly on the desk had no automatic link to its own
   Opportunity.** `new_deal()` created both together, but a deal made by
   hand on the New form only ever got the Impart Deal row, so its first
   "Send RFQ" button crashed. Fixed by moving Opportunity creation into the
   doctype's own `after_insert()`, so it happens no matter how the deal was
   created.

A process lesson from the same session, also worth recording: after every
code change, the site's web workers must be restarted
(`sudo supervisorctl restart frappe-bench-web: frappe-bench-workers:`) for
the new code to actually take effect — a plain file sync is not enough,
and skipping this step produced confusing "it's still broken" reports
even after a real fix had already landed on disk.

## 7. What has NOT been tested yet — read this before wider rollout

- **No automated test suite.** Everything above was verified with one-off
  scripts (`setup/pipeline_smoke_test.py` is the closest thing to a
  regression test, and it should be extended, not thrown away) and manual
  browser clicks. There is no `pytest`/CI suite that runs these scenarios
  automatically on every change.
- **Concurrency / multi-user usage.** Every test so far ran as a single
  Administrator session. Two Impart staff editing the same deal at once,
  or a staff member editing while a vendor submits via the portal at the
  same time, has not been tried.
- **Permission edges.** Only the "Impart User can do everything, everyone
  else can't see it, a vendor can only see their own records" cases were
  tested. A user with e.g. Sales User or Purchase User but not Impart User
  has not been checked for accidental partial visibility into Impart Deal
  or its linked documents.
- **Cancelling and amending native documents other than Quotation.** The
  Quotation cancel+amend cycle (the negotiation mechanism) is well tested.
  Cancelling or amending a Sales Order, Purchase Order, Purchase Receipt,
  Delivery Note, or Sales Invoice after the fact, and what that does to the
  deal's stage and links, has not been exercised.
- **Partial payments.** Only full payment (`record_customer_payment` /
  `record_vendor_payment` with no amount, meaning "pay in full") has been
  tested. A partial amount, and what the deal looks like sitting in a
  partially-paid state, has not been checked.
- **Volume / performance.** The tracker report and the deal list have only
  ever had a handful of deals in them (under 10). Behaviour with hundreds
  or thousands of deals, and the report's query performance at that scale,
  is unknown.
- **Edge-case inputs.** Zero or negative quantity, zero exchange rate,
  vendor rate of zero, an item with no `weight_per_unit` set (breaks the
  Wt Kg column), a customer or supplier with no address — none of these
  have been deliberately tried.
- **Browser coverage.** All UI testing was done in one browser (Chromium,
  via the Claude Code built-in browser tool). Safari/Firefox, and mobile
  browsers, have not been checked.
- **The Polemarch reuse story** is a design claim, not a tested one — the
  app has only ever been installed on this one site for Impart.
- **Backup / restore and production deployment** (proper domain, HTTPS,
  a real email/SMS setup for notifications, production-grade MariaDB
  tuning) — this is still a bench running on a dev VM, not hardened for
  real production traffic.
- **India Compliance / real GST filing** — the flat-rate GST on the
  calculator has not been checked against India Compliance app output or
  real filing requirements, since that app is not installed on this site.

## 8. How to test the negotiation revision and the ladder table, step by step

This is the mechanism the client specifically asked for — a revision is not
a new document type, it is just one more row appended to the same child
table. Here is exactly how to exercise it and see it working.

### 8.1 Get a deal to the point where a revision makes sense

1. Open **Impart Deal → New**. Fill Customer, Item, Qty, Location, Save.
   Stage shows **New Inquiry**.
2. **Pipeline Action → Send RFQ to Vendor**. Pick one vendor (e.g. Trident
   Global Computers Inc). Submit. Stage moves to **RFQ Sent to Vendor**.
3. **Pipeline Action → Record Vendor Quote (Ask)**. The vendor is already
   filled in. Enter a currency, rate, and exchange rate — e.g. USD, 420,
   87.5. Submit. Stage moves to **Vendor Quote Received**.
4. Scroll to **Bid / Ask Ladder (Negotiation Log)**. There is now exactly
   **one row**: Round 1, Side = **Ask**, the vendor's name, the currency
   and rate you entered, Status = **Sent**, and a **Reference** column
   linking straight to the Supplier Quotation document that produced it.
   This is the ladder working for the very first time on this deal.
5. Fill in the **Pricing Calculator** section (FX Buffer %, Customs Duty %,
   Freight, Margin %), Save.
6. **Pipeline Action → Send Customer Quotation (Bid)**. Confirm. Stage
   moves to **Customer Quotation Sent**.
7. Look at the ladder again. There are now **two rows**: Round 1 Ask (the
   vendor's price, unchanged) and Round 1 Bid (the customer's price you
   just sent), also Status = Sent, also linked to its own document — the
   native Quotation this time.

### 8.2 Run an actual revision — this is the part to watch closely

8. **Pipeline Action → Customer Requests Revision**. Type a reason (e.g.
   "customer wants a better price"). Stage moves to **In Negotiation**. The
   ladder is unchanged by this click — it's a pure status move, nothing is
   appended yet, because nothing new has actually happened.
9. **Pipeline Action → Record Vendor Quote (Ask)** again. Enter a *lower*
   rate this time (e.g. 400 instead of 420), same currency, exchange rate.
   Submit.
10. Open the ladder. There are now **three rows**. The important thing to
    check: **Round 1 Ask is still there, untouched**, but its Status has
    changed to **Superseded**. A brand new row, **Round 2, Side = Ask**,
    holds the new lower price with Status = **Sent**, linked to a
    **second, separate Supplier Quotation document** (a fresh document,
    not an edit of the first one — open both from the ladder's Reference
    links and confirm they are two distinct Supplier Quotation records).
11. Update the pricing calculator with the new numbers, Save.
12. **Pipeline Action → Revise Customer Quotation**. Confirm the new price.
    This is the actual "revision" mechanic: behind the scenes it cancels
    the original Quotation and amends it — open the **Quotation** link
    from Round 1's Bid row and you'll see it is now **Cancelled**, with an
    **Amended From** trail pointing to it from a new Quotation document
    whose name ends in **-1**.
13. Open the ladder again. **Round 1 Bid is now Superseded**, and a new
    **Round 2 Bid** row holds the revised price, Status **Sent**, linked
    to that amended Quotation (the `-1` one).

### 8.3 Do it again, to see the pattern repeat

14. Repeat steps 8–13 once more (Customer Requests Revision → Record
    Vendor Quote at an even lower price → update calculator → Revise
    Customer Quotation). The ladder should now hold **six rows total**:
    Ask rounds 1, 2, 3 (rounds 1 and 2 Superseded, round 3 Sent) and Bid
    rounds 1, 2, 3 (same pattern). The Quotation's amendment trail should
    now be three documents deep (original, `-1`, `-2`).

### 8.4 What "correct" looks like when you're done

- The ladder's **Round** column always counts up separately per side (Ask
  1, 2, 3... and Bid 1, 2, 3...), never skipping or resetting.
- Every row except the very latest on each side reads **Superseded**.
- Every row's **Reference** link opens a real, distinct native document —
  clicking through the Ask rows should open two or three separate Supplier
  Quotation records; clicking through the Bid rows should open one
  Quotation and its amendments (same document lineage, different names).
- Nothing is ever deleted. The whole point of the ladder is that the full
  negotiation history stays visible and auditable, including the prices
  that were superseded.
- Finish it off with **Customer Approves → Create Sales Order** (or
  **Customer Rejects**) to confirm the deal moves on normally from
  whichever round you stopped at — the negotiation loop doesn't need to
  run a fixed number of times before the rest of the pipeline works.

## 9. How to run it

```
# re-seed the demo (safe to re-run: clears and rebuilds the 6 demo deals)
bench --site impart.local execute impart_ops.setup.demo_data.run

# run the pipeline smoke test (full happy path + negotiation + rejection)
bench --site impart.local execute impart_ops.setup.pipeline_smoke_test.run

# re-apply site setup (role, custom fields, workflow, workspace) after a
# fresh install or if any of that needs repairing
bench --site impart.local execute impart_ops.setup.install.after_install
```

## 10. File map

```
impart_ops/
  hooks.py                          doc_events wiring
  impart_ops/
    deal_actions.py                 the engine - one fn per pipeline step
    deal_sync.py                    doc_events handlers, keep deal in sync
    doctype/
      impart_deal/                  the parent doctype + controller + JS
      impart_deal_entry/            the bid/ask ladder child table
    report/impart_deal_tracker/     the 23-column tracker report
    workspace/impart/               the landing screen
  setup/
    install.py                      one-time site setup (idempotent)
    demo_data.py                    seeds the 6 demo deals
    pipeline_smoke_test.py          scripted regression check
```
