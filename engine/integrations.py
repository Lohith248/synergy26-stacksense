"""A7: an existing system the knowledge base does not know by name is integrated by what the description says is done with it.

Instead of "assumed to sit outside this design", an unrecognised entry (no knowledge-base pattern, no lifecycle row) is read by verb
and noun, from the entry text first and then from the description clauses that name it:

  protocol   MQ, MLLP/HL7 v2, SOAP/WSDL, OPC UA, MQTT, SMPP, LoRaWAN  -> an adapter that names the protocol
  webhook    webhook / push / feed                                      -> inbound receiver: signature, idempotency key, queue
  file       CSV / XML / Excel / named export formats / import / export -> import/export job with validation and idempotent re-run
  accounting accounting / ERP / Tally / SAP / billing / payroll         -> export adapter with reconciliation
  device     rig control / serial / USB / PLC / barcode                 -> local device-control adapter
  retire     replace / retire / decommission                            -> no component; the entry is going away
  api        must call / reads / queries / via / sync                   -> adapter that owns the contract (protocol not stated)

Only kinds of interface and protocol names are listed (plus three accounting-package keywords used as nouns for 'accounting system'); no
scenario, project or vendor behaviour appears. The result says what is assumed, states no vendor facts, and costs nothing (library code). None is returned when neither the entry nor a description clause gives a reason.
"""
import re

# words in an entry that do not identify it (a clause is "about" the entry only when it shares a word outside this set)
GENERIC = frozenset("""the and for with from into via over under system systems server servers service services console app apps application
applications tool tools platform portal data file files import export imports exports exported imported feed feeds database record records
legacy old existing current new main core admin user users member members customer customers staff report reports log logs sheet sheets
document documents version production test dev network gateway interface module software program""".split())

# protocol -> (name, what the adapter does). Interface design only: no vendor behaviour is asserted.
PROTOCOLS = (
    ("mllp", r"\bmllp\b|\bhl7 ?v?2\b", "HL7 v2 over MLLP",
     "an MLLP listener or client behind an interface layer that maps segments to the application's own model, with ACK/NACK handling and a log of every message"),
    ("soap", r"\bsoap\b|\bwsdl\b", "SOAP",
     "a SOAP client generated from the service's WSDL, behind one interface so the generated types do not spread through the code"),
    ("opcua", r"\bopc[- ]?ua\b", "OPC UA",
     "a read-only OPC UA client that subscribes to (or polls) the named nodes, stores each reading with its source timestamp and quality code, "
     "reconnects with back-off, and trusts the gateway's certificate explicitly"),
    ("mqtt", r"\bmqtt\b", "MQTT",
     "an MQTT subscriber with one topic filter per device class, a persistent session, at-least-once delivery handled idempotently, and reconnect with back-off"),
    ("smpp", r"\bsmpp\b", "SMPP",
     "an SMPP client bound to the SMS gateway (rate-limited to its window), with delivery receipts stored per message"),
    ("lorawan", r"\blorawan\b|\blora network\b", "LoRaWAN network server",
     "a consumer of the network server's uplink events through its integration interface (the exact interface, MQTT or HTTP, is to be confirmed "
     "with its operators), storing each uplink with its device id and frame counter so repeats are ignored"),
    ("mq", r"\bmq\b|\bamqp\b|\bmessage queue\b", "MQ messaging",
     "an MQ client with a request queue and a reply queue (or one inbound queue), persistent messages, correlation ids, an idempotent consumer and a dead-letter queue"),
)
WEBHOOK_RX = r"\bwebhooks?\b|\bpush(?:ed|es|ing)?\b|\bfeeds?\b|\bcallbacks?\b"
FILE_FORMATS = r"\bcsv\b|\btsv\b|\bxml\b|\bxlsx?\b|\bexcel\b|\bspreadsheets?\b|\bsheets?\b|\bflat files?\b|\bfixed[- ]width\b|\badif\b|\bcabrillo\b|\bjson files?\b"
FILE_RX = FILE_FORMATS + r"|\bfiles?\b|\bimports?\b|\bimported\b|\bexports?\b|\bexported\b"
ACCOUNTING_RX = r"\baccounting\b|\baccounts\b|\berp\b|\btally\b|\bsap\b|\bquickbooks\b|\bbilling\b|\bpayroll\b|\binvoic\w+|\bgeneral ledger\b"
DEVICE_RX = r"\brig control\b|\bcat control\b|\bserial\b|\busb\b|\bplc\b|\bbarcode\b|\bscanners?\b|\bprinters?\b|\bcard readers?\b|\bhardware\b"
RETIRE_RX = r"\breplac(?:e|ed|es|ing|ement)\b|\bretir(?:e|ed|es|ing)\b|\bdecommission\w*|\bphas(?:e|ed|ing) out\b|\bsunset\w*|\bmigrat\w* (?:off|away)\b"
VERB_RX = (r"\b(?:calls?|calling|invokes?|reads?|reading|fetch\w*|quer(?:y|ies|ied)|pull\w*|talks? to|connect\w*|integrat\w*|sync\w*|via|"
           r"through|feeds?|feeding|receives?|sends?|posts? to|writes? to|looks? up)\b")
# "X exported as/from/by ..." names a file the system produces, which the application reads: an import
IMPORT_RX = r"\bimport\w*|\bread\w*|\bload\w*|\bingest\w*|\breceiv\w*|\bexported (?:as|from|by)\b|\blives? in\b|\bcomes? from\b"
EXPORT_RX = r"\bexport(?:s|ed)?\b(?!\s+(?:as|from|by)\b)|\bwrit\w*|\bsubmi\w*|\bsend\w*|\bprint\w*"
# the description reaches another system through a message broker ("read member records from the mainframe via MQ")
QUEUE_VIA_RX = r"\b(?:via|over|through|using)\s+(?:the\s+)?(?:\w+\s+)?(?:mq|message queues?|message brokers?)\b"
FORMAT_NAMES = {"csv": "CSV", "tsv": "TSV", "xml": "XML", "xls": "Excel", "xlsx": "Excel", "excel": "Excel", "spreadsheet": "spreadsheet",
                "spreadsheets": "spreadsheet", "sheet": "spreadsheet", "sheets": "spreadsheet", "flat file": "flat-file", "flat files": "flat-file",
                "fixed-width": "fixed-width", "fixed width": "fixed-width", "adif": "ADIF", "cabrillo": "Cabrillo", "json file": "JSON", "json files": "JSON"}


def _tokens(raw):
    """Words that identify the entry: not generic, 4+ letters, or an upper-case acronym of 2+ letters as written."""
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", raw):
        lw = w.lower()
        if lw in GENERIC or len(lw) < 3:
            continue
        if len(lw) >= 4 or w.isupper():
            out.add(lw)
    return out


def _balanced(cl):
    """A clause cut inside a parenthesis gets its closing bracket back, so a quoted clause reads whole."""
    return cl + ")" * max(0, cl.count("(") - cl.count(")"))


def _clauses(raw, desc):
    """The description clauses (split at sentence ends and commas) that share an identifying word with the entry."""
    toks = _tokens(raw)
    if not toks:
        return []
    out = []
    for sent in re.split(r"(?<=[.!?;])\s+|\n", desc or ""):
        for cl in re.split(r",(?!\d)\s*|[;:]\s*|\s+[-–—]\s+", sent):
            words = set(re.findall(r"[a-z0-9]+", cl.lower()))
            if words & toks:
                out.append(_balanced(cl.strip()))
    return out


def cite(ad):
    """How a warning or assumption refers to the evidence of an inferred integration."""
    return f"the description ('{ad['evidence']}')" if ad["from_desc"] else "the entry text"


def infer(raw, desc):
    """{'kind', 'title', 'how', 'evidence', 'protocol'} for an unrecognised existing system, or None when nothing says what is done with it."""
    own = raw.lower()
    cls = _clauses(raw, desc)
    both = own + " | " + " | ".join(c.lower() for c in cls)
    name = re.sub(r"\s+", " ", raw).strip()[:60]

    def evidence_for(rx):  # the description clause that carries the deciding word; the entry text itself when no clause does
        c = next((c for c in cls if re.search(rx, c.lower())), None)
        return (c[:130] if c else name), bool(c)

    def ref():  # text for a clause quoted from the description (nothing when the entry text alone decided)
        return f" ('{evidence}')" if from_desc else ""

    for _key, rx, pname, text in PROTOCOLS:
        if re.search(rx, both):
            evidence, from_desc = evidence_for(rx)
            return {"kind": "api", "protocol": pname, "evidence": evidence, "from_desc": from_desc,
                    "title": f"{pname} adapter for {name}",
                    "how": (f"{'The description' if from_desc else 'The entry'} names {pname}{ref()}. The application reaches it through {text}. Timeouts, retries and error mapping live in "
                            "that one adapter, with a stub for tests, so the rest of the application never depends on the wire format. Endpoint, credentials and "
                            "message contract are not given in the input: confirm them with the system's owners.")}
    if re.search(RETIRE_RX, own):  # the entry itself says it is going away ("... (to be replaced)")
        return {"kind": "retire", "protocol": None, "evidence": name, "from_desc": False, "title": "", "how": ""}
    if re.search(WEBHOOK_RX, both):
        evidence, from_desc = evidence_for(WEBHOOK_RX)
        return {"kind": "webhook", "protocol": None, "evidence": evidence, "from_desc": from_desc,
                "title": f"Inbound webhook / feed receiver for {name}",
                "how": (f"Events arrive from the external source{ref()}. A public HTTPS endpoint verifies the sender's signature or shared secret, stores each event "
                        "under its id so a repeated delivery is ignored (idempotency key), acknowledges at once and hands the work to a queue worker (a database-backed "
                        "job table is enough at this scale; use the existing broker if there is one); failed events go to a dead-letter list and can be replayed. "
                        "The provider's signing scheme and delivery guarantees are not in the knowledge base: confirm them with the provider.")}
    if re.search(FILE_FORMATS, both) or (re.search(FILE_RX, both) and not re.search(ACCOUNTING_RX, both)):  # a named format beats the accounting noun
        evidence, from_desc = evidence_for(FILE_RX)
        fmts = sorted({FORMAT_NAMES.get(m.group(0).strip(), m.group(0).strip()) for m in re.finditer(FILE_FORMATS, both)} - {"spreadsheet"}
                      or {"spreadsheet"})
        imp, exp = bool(re.search(IMPORT_RX, both)), bool(re.search(EXPORT_RX, both))
        way = "Import and export" if imp and exp else "Export" if exp and not imp else "Import"
        fm = f" ({'/'.join(fmts)})" if fmts else ""
        return {"kind": "file", "protocol": None, "evidence": evidence, "from_desc": from_desc,
                "title": f"File {way.lower()} job{fm} for {name}",
                "how": (f"{way} runs as a scheduled or on-demand job (a script or the backend, whichever the stack has) for {name}{ref()}: it validates the schema and "
                        "encoding on read, writes a reject report for bad rows, uses a stable key per row so re-running the same file never duplicates records, and keeps "
                        "the original file for audit. The exact columns or record layout are not given in the input: confirm them with the file's owner.")}
    if re.search(ACCOUNTING_RX, both):
        evidence, from_desc = evidence_for(ACCOUNTING_RX)
        return {"kind": "accounting", "protocol": None, "evidence": evidence, "from_desc": from_desc,
                "title": f"Accounting / billing adapter for {name}",
                "how": (f"The application hands its financial records to the accounting or billing system{ref()} through one adapter that writes the target's "
                        "import format (a file or an API, as its owners confirm) in idempotent batches, and a reconciliation report compares totals on both sides. "
                        "The application never writes into that system's own tables; the interface is not stated in the input, so the format is an assumption to confirm.")}
    if re.search(DEVICE_RX, both):
        evidence, from_desc = evidence_for(DEVICE_RX)
        return {"kind": "device", "protocol": None, "evidence": evidence, "from_desc": from_desc,
                "title": f"Local device-control adapter for {name}",
                "how": (f"Equipment control{ref()} runs on the operator's machine next to the application (serial, USB or local network to the equipment), never in "
                        "a cloud service; the application talks to a small local interface so the equipment can be mocked in tests and a failure does not stop data entry.")}
    toks = _tokens(raw)
    # a replace verb counts only in the same part of the clause as the system's own name ("migrating off X and keeping Y" retires X only)
    gone = next((p.strip() for c in cls for p in re.split(r"\b(?:and|but)\b", c.lower())
                 if re.search(RETIRE_RX, p) and set(re.findall(r"[a-z0-9]+", p)) & toks), None)
    if gone:
        return {"kind": "retire", "protocol": None, "evidence": gone[:130], "from_desc": True, "title": "", "how": ""}
    if any(re.search(VERB_RX, c.lower()) for c in cls):
        evidence, from_desc = evidence_for(VERB_RX)
        return {"kind": "api", "protocol": None, "evidence": evidence, "from_desc": from_desc,
                "title": f"Integration adapter for {name}",
                "how": (f"The description says what the application does with it{ref()}. One adapter owns the contract, timeouts, retries with back-off and error "
                        "mapping, with a stub for tests, so the rest of the application never depends on the other system's interface. The protocol is not stated in the "
                        "input (REST, SOAP, files or a queue): confirm it, and the credentials and rate limits, with the system's owners.")}
    return None
