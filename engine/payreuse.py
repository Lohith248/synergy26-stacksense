"""q2: a payment provider the organisation already has (merchant account, contract or integration) is reused by the payments layer.

Read from infrastructure.existing_systems (an entry that names the provider and is not being retired) or from a description sentence
that states ownership of it ("our existing Adyen merchant account", "we already have a PayU account"). A sentence that compares
providers, names one as a competitor's, or moves away from it never counts (must-not-fire wording, planning heuristic)."""
import re

# (regex over lower-case text, display name, provider key). General list of payment providers; KB facts exist only for some (KNOWN).
PROVIDERS = (
    (r"adyen", "Adyen", "adyen"), (r"(?<!magnetic )(?<!magnetic-)(?<!mag )stripe", "Stripe", "stripe"), (r"razorpay", "Razorpay", "razorpay"), (r"payu", "PayU", "payu"),
    (r"paytm", "Paytm", "paytm"), (r"cashfree", "Cashfree", "cashfree"), (r"ccavenue", "CCAvenue", "ccavenue"),
    (r"billdesk", "BillDesk", "billdesk"), (r"paypal", "PayPal", "paypal"), (r"braintree", "Braintree", "braintree"),
    (r"mollie", "Mollie", "mollie"), (r"checkout\.com", "Checkout.com", "checkoutcom"), (r"worldpay", "Worldpay", "worldpay"),
    (r"square(?= (?:payments|pos|point of sale|account|merchant|checkout|terminal|online|invoices)\b)", "Square", "square"), (r"mercado ?pago", "Mercado Pago", "mercadopago"), (r"paystack", "Paystack", "paystack"),
    (r"flutterwave", "Flutterwave", "flutterwave"),
)
# providers whose fees/regions the knowledge base has verified pages for (others get an honest "not in the knowledge base")
KNOWN = {"stripe", "razorpay"}

_B = r"(?<![a-z0-9])"
_E = r"(?![a-z0-9])"
# ownership wording around the provider name in one sentence (planning heuristic)
OWN_RX = (r"\b(?:our|the|an?)\s+(?:existing|current)\s+(?:\w+\s+){{0,2}}?{p}{e}",
          r"\balready\s+(?:have|has|had|use|uses|using|run|runs|on|with|process\w*)\s+(?:\w+\s+){{0,3}}?{p}{e}",
          r"\b(?:our|existing|current)\s+(?:\w+\s+){{0,2}}?(?:merchant account|account|contract|integration|setup)\s+(?:with|at|on)\s+{p}{e}",
          r"\bour\s+{p}\s+(?:merchant\s+)?(?:account|contract|integration|setup)\b",
          r"\b(?:keep|continue)\w*\s+(?:using\s+)?(?:our\s+)?{p}{e}")
# a sentence with one of these never establishes ownership (comparison, competitor, moving away, negation)
VETO_RX = (r"\bcompar\w*|\bcompetitors?\b|\bversus\b|\bvs\.?\s|\binstead of\b|\bevaluat\w*|\bconsider\w*|\bshortlist\w*"
           r"|\b(?:migrat|mov|switch|transition)\w*\s+(?:\w+\s+){0,2}?(?:away\s+)?(?:from|off)\b|\breplac\w*|\bleav\w*|\bleft\b|\bquit\w*|\bdrop\w*|\bretir\w*|\bphas\w* out"
           r"|\bcancel\w*|\bclos(?:e|ed|ing)\b|\bterminat\w*|\bformer\w*|\bprevious\w*|\bused to\b|\buntil\b|\bexpir\w*"
           r"|\bno longer\b|\bnot\b|\bnever\b|\bdon'?t\b|\bdoesn'?t\b|\bwithout\b")


def _prov_rx(p):
    return _B + p + _E


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?;])\s+|\n", text or "") if s.strip()]


def existing_psp(ctx):
    """(key, display name, quote, input path) of the payment provider the organisation already has, else None."""
    desc = ctx["req"]["project.description"] or ""
    sents = _sentences(desc)
    for p, name, key in PROVIDERS:
        rx = _prov_rx(p)
        # the product itself takes donations when a sentence that does not name this provider says so
        donations = any(re.search(r"\bdonat\w*|\bcharit\w*|\bfundrais\w*", s.lower()) and not re.search(rx, s.lower()) for s in sents)
        # q8: someone else's account ("their Stripe account") or one kept for donations only, in a product that takes other payments
        veto = VETO_RX + r"|\btheir\s+(?:own\s+|existing\s+|current\s+)*" + p + ("" if donations else r"|\bdonat\w*")
        named = [s for s in sents if re.search(rx, s.lower())]
        if any(re.search(veto, s.lower()) for s in named):
            continue
        for e in ctx.get("existing", []):
            if re.search(rx, e["raw"].lower()) and not e.get("retire") and not re.search(veto, e["raw"].lower()):
                return key, name, e["raw"].strip(), "infrastructure.existing_systems"
        for s in named:
            low = s.lower()
            if any(re.search(o.format(p=p, e=_E), low) for o in OWN_RX):
                return key, name, s.strip().rstrip("."), "project.description"
    return None


# q2: the description plans to keep card data itself (full card numbers, CVV, magnetic-stripe data). A storage verb and a card-data
# noun within a few words, in a sentence without a negation (planning heuristic wording signal).
_CARD = (r"(?:full |raw |complete |plain(?:-text)? )?(?:credit |debit |payment )?card ?(?:numbers?|details|data)\b|\bpans?\b|\bprimary account numbers?\b"
         r"|\bcvv2?s?\b|\bcvcs?\b|\bcard (?:verification|security) (?:codes?|values?)\b|\bmagnetic[- ]?stripe\b|\btrack (?:1 |2 )?data\b")
_STORE = r"\b(?:stor\w*|keep\w*|kept|sav\w*|retain\w*|persist\w*|hold\w*|log\w*|record\w*)\b"
CARD_STORE_RX = (r"(?i:" + _STORE + r"(?:\W+\w+){0,6}?\W+(?:" + _CARD + r")|(?:" + _CARD + r")(?:\W+\w+){0,4}?\W+(?:will be |are |is |get |gets )?"
                 + _STORE + r")")
_CARD_NEG = r"(?i:\b(?:not|never|no(?!-)|don'?t|won'?t|without|avoid\w*|instead of|tokeni[sz]\w*)\b)"


def card_storage(desc):
    """The description sentence that plans to store card data (PAN, CVV, stripe data), else None."""
    for s in _sentences(desc):
        if re.search(CARD_STORE_RX, s) and not re.search(_CARD_NEG, s):
            return s.strip().rstrip(".")
    return None

