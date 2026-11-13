"""Offline conflicts (A12): what a disconnected device can and cannot guarantee.

Two limits of any offline client are stated as warnings, and the sync policy follows the data:
  OFFLINE_UNIQUENESS: a rule that must hold across devices (one use per ticket, one booking per slot, no duplicate record) cannot be
                      checked while a device is disconnected, because it cannot see what the other devices accepted.
  OFFLINE_PAYMENTS:   a card or UPI payment needs the provider's live answer, so it cannot be completed offline.
For ledger-, booking- and ticket-like data the offline sync policy is an append-only command log, not last-writer-wins per field.
Text only: nothing here ranks a technology or changes a core choice.
"""

def offline_server(c):
    """Offline sync with a server as the shared system of record (not a single-device local-first app, not a static site)."""
    return bool(c["req"]["requirements.offline_support"] and c["needs_backend"] and not c["local_first"])


def append_only(c):
    """Data whose entries must never be overwritten or silently merged: ledger entries, bookings, tickets, payments (planning heuristic: description signals and requirements.payments)."""
    return bool(c["desc"]["ledger"] or c["desc"]["unique_rule"] or c["req"]["requirements.payments"])


def policy_bit(c):
    """The sentence in the offline-sync component that states the conflict policy."""
    if append_only(c):
        return ("the policy is an append-only command log: a device sends what happened (an entry, a scan, a booking request) and the server "
                "appends it in order and accepts or rejects it against the current state, never overwriting a field, so no entry is silently "
                "lost and a rejected one comes back with a reason")
    return "server applies last-writer-wins per field with an edit log"


def uniqueness_warning(c, quote):
    """(code, severity, message, fields) or None. quote(): the description sentence that names the cross-device rule."""
    if not (offline_server(c) and c["desc"]["unique_rule"]):
        return None
    return ("OFFLINE_UNIQUENESS", "warning",
            f"offline_support is on and the description names a rule that must hold across devices (\"{quote()}\"). While a device is "
            "disconnected it cannot see what the other devices accepted, so uniqueness cannot be guaranteed offline. Design for it: the server "
            "stays the single authority and enforces the rule with a unique constraint when records sync; each device holds a local allow-list "
            "or deny-list downloaded before it goes offline; entries accepted offline are marked provisional until reconciled; a double entry "
            "found at sync goes to a manual resolution queue. Decide how many double entries the business can tolerate while partitioned.",
            ["requirements.offline_support", "project.description"])


def payments_warning(c):
    if not (offline_server(c) and c["req"]["requirements.payments"]):
        return None
    return ("OFFLINE_PAYMENTS", "warning",
            "requirements.payments and offline_support are both on: a card, UPI or app-store payment needs the provider's live authorisation, so it cannot be "
            "completed while the device is offline. Queue the order or renewal as 'payment pending' (a pay-later link or collection on reconnect), "
            "never mark it paid before the provider confirms, and never keep card data on the device. Store-and-forward payment modes, where a "
            "provider offers them, move the risk of declined payments to you: read the provider's terms before relying on them.",
            ["requirements.payments", "requirements.offline_support"])



SNIPPET_CONTEXT = 45  # planning heuristic: characters of the description kept on each side of the words that set a signal


def snippet(desc, rx):
    """The words of the description that set a signal, with a little context, cut at word boundaries (for warning text)."""
    import re
    text = " ".join((desc or "").split())
    m = re.search(rx, text, re.I)
    if not m:
        return "project.description"
    a, b = max(0, m.start() - SNIPPET_CONTEXT), min(len(text), m.end() + SNIPPET_CONTEXT)
    if a > 0:
        a = text.find(" ", a) + 1 or m.start()
        a = min(a, m.start())
    if b < len(text):
        b = text.rfind(" ", m.end(), b)
        b = b if b > m.end() else m.end()
    return ("..." if a > 0 else "") + text[a:b].strip(" ,;.") + ("..." if b < len(text) else "")
