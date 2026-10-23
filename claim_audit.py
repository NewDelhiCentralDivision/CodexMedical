"""Deterministic checks between extracted bills, the claim form, and rate review."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib


def money(value):
    """Reject uncertain amounts instead of treating unreadable digits as zero."""
    try:
        amount = Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, AttributeError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fingerprint(files):
    digest = hashlib.sha256()
    for file in files:
        raw = file.getvalue()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def merge_extractions(chunks):
    """Merge numbered page batches without copying referral or report rows."""
    combined = {"line_items": [], "bill_totals": []}
    seen_rows = set()
    seen_bills = set()
    issues = []
    def order_number(value):
        digits = str(value or "").strip()
        return int(digits) if digits.isdigit() else 0
    for chunk in chunks:
        for key, value in chunk.items():
            if key not in ("line_items", "bill_totals") and value not in (None, ""):
                # The claimant and declared total must come from the actual form.
                if key in ("claimant_name", "employee_id", "total_claimed_amount", "diagnosis", "diagnosis_source"):
                    if chunk.get("claim_form_page") and not combined.get(key):
                        combined[key] = value
                elif not combined.get(key):
                    combined[key] = value
        if chunk.get("claim_form_page") and not combined.get("claim_form_page"):
            combined["claim_form_page"] = chunk["claim_form_page"]
        for item in chunk.get("line_items") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("source_document_type") or "").lower().strip()
            if kind not in ("bill", "receipt", "pharmacy invoice"):
                continue
            amount = money(item.get("claimed_amount"))
            if amount is None or not str(item.get("description") or "").strip():
                issues.append("A billed row had an unreadable amount or description and needs manual entry.")
                continue
            invoice = str(item.get("invoice_number") or "").strip().upper()
            line_no = str(item.get("line_number") or "").strip()
            if invoice and line_no:
                identity = (invoice, line_no)
                if identity in seen_rows:
                    continue  # the same numbered line appeared on a repeated scan
                seen_rows.add(identity)
            clean = dict(item)
            clean["claimed_amount"] = float(amount)
            clean["invoice_number"] = invoice
            clean["line_number"] = line_no
            combined["line_items"].append(clean)
        for bill in chunk.get("bill_totals") or []:
            if not isinstance(bill, dict):
                continue
            invoice = str(bill.get("invoice_number") or "").strip().upper()
            total = money(bill.get("printed_total"))
            if not invoice or total is None:
                continue
            if invoice in seen_bills:
                continue  # a multi-page receipt often repeats its total
            seen_bills.add(invoice)
            combined["bill_totals"].append({**bill, "invoice_number": invoice, "printed_total": float(total)})
    combined["line_items"].sort(key=lambda row: (
        order_number(row.get("source_page")), str(row.get("invoice_number") or ""),
        order_number(row.get("line_number")),
    ))
    combined["audit_issues"] = issues
    return combined


def reconcile(extracted):
    """Compare printed form and invoice totals; never invent a balancing row."""
    issues = list(extracted.get("audit_issues") or [])
    claimed = money(extracted.get("total_claimed_amount"))
    bills = extracted.get("bill_totals") or []
    invoice_total = sum((money(b.get("printed_total")) or Decimal(0) for b in bills), Decimal(0))
    if claimed is not None and not bills:
        issues.append("No readable bill or receipt totals were found to reconcile with the claim form.")
    if claimed is not None and bills and abs(claimed - invoice_total) > Decimal("1.00"):
        issues.append(f"Claim form total ₹{claimed:,.2f} differs from unique bill totals ₹{invoice_total:,.2f}.")
    by_invoice = {}
    for row in extracted.get("line_items") or []:
        invoice = row.get("invoice_number")
        if invoice:
            by_invoice[invoice] = by_invoice.get(invoice, Decimal(0)) + (money(row.get("claimed_amount")) or Decimal(0))
    for bill in bills:
        invoice = bill["invoice_number"]
        if invoice not in by_invoice:
            issues.append(f"Invoice {invoice} has a printed total but no extracted bill rows.")
            continue
        if invoice in by_invoice and abs(by_invoice[invoice] - (money(bill["printed_total"]) or Decimal(0))) > Decimal("1.00"):
            issues.append(f"Invoice {invoice}: extracted lines ₹{by_invoice[invoice]:,.2f} differ from printed total ₹{money(bill['printed_total']):,.2f}.")
    if claimed is None:
        issues.append("No readable total was found on the applicant claim form.")
    return {"form_total": claimed, "invoice_total": invoice_total if bills else None, "issues": issues}
