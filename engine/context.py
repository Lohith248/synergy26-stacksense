"""Derived signals from validated input. Every derived value records the input paths it came from."""
import bisect
import copy
import functools
import re

from . import overeng as ov
from . import integrations as ig
from . import costreal
from . import localfirst as lf
from .kb import AS_OF, TECH

TIER_NAMES = ["tiny", "small", "medium", "large"]
EXP_FACTOR = {"beginner": 1.6, "intermediate": 1.2, "mixed": 1.2, "senior": 0.7}
# Language fit: switching language costs every team real time; seniors ramp faster but never for free.
LANG_FACTOR = {"beginner": 1.6, "intermediate": 1.3, "mixed": 1.3, "senior": 1.0}
DYNAMIC_TYPES = {"web_app", "saas_b2b", "ecommerce", "marketplace", "social", "realtime_collab", "fintech",
                 "healthtech", "data_analytics", "iot", "ai_ml_product", "internal_tool", "gaming", "api_platform"}
LANG_ALIASES = {"js": "javascript", "ts": "typescript", "c#": "csharp", "golang": "go", "py": "python",
                "node": "javascript", "nodejs": "javascript", "node.js": "javascript", "c sharp": "csharp"}

# Deterministic description rules (D7). Each: flag -> regex. They shape supporting services/warnings; ledger, markdown, internal_only and low_end also adjust core scores.
# things a user uploads (a bare "devices upload readings" is not a file upload)
UPLOAD_OBJ = (r"(?:files?|documents?|docs?|pdfs?|photos?|images?|pictures?|videos?|scans?|bills?|receipts?|invoices?|attachments?"
              r"|certificates?|resumes?|cvs?|recordings?|audio|spreadsheets?|csv|forms?)")
DESC_RULES = [
    ("upi", r"\bupi\b"),
    ("recurring", r"\bemi\b|subscription|recurring|per[- ]seat|pay per seat|monthly plan"),
    ("payouts", r"get paid|payout|disburs|pay (?:out|providers|sellers|vendors)|split payment|commission"),
    ("ledger", r"ledger|double[- ]entry"),
    # A12: a rule that must hold across devices (one use per ticket, one booking per slot, no duplicate record); read with offline_support
    # "unique" alone is not a rule ("a unique design"): it must qualify an identifier or be demanded; "one per" and stock that must not go negative count too
    ("unique_rule", r"\bduplicat\w*|\bdupes?\b|\buniqueness\b|\bonly once\b|\bone[- ]time (?:use|only|vouchers?|coupons?|tickets?|entry)"
                    r"|\bunique (?:\w+ ){0,2}(?:tickets?|serials?|numbers?|codes?|ids?|identifiers?|keys?|references?|barcodes?|qr|passes|vouchers?|coupons?|entr(?:y|ies)|records?|bookings?|slots?|seats?|receipts?|usernames?|e-?mails?|invoices?)\b"
                    r"|\b(?:must|should|needs? to|has to|have to) (?:be )?(?:\w+ ){0,2}unique\b|\b(?:ensur\w*|enforc\w*|guarantee\w*|verif\w*|check\w*)\b(?:\W+\w+){0,5}?\W+unique\b"
                    r"|\bone (?:\w+ )?per (?:person|ticket|seat|slot|attendee|member|customer|user|day|device|code)\b"
                    r"|\b(?:stock|inventory|quantit(?:y|ies))\b(?:\W+\w+){0,4}?\W+(?:decrement\w*|deduct\w*|reduc\w*|runs? out|sold out)\b|\b(?:decrement\w*|deduct\w*|reduc\w*|decreas\w*) (?:\w+ ){0,3}(?:stock|inventory|quantit(?:y|ies))\b"
                    r"|\b(?:used|scanned|redeemed|claimed|booked|entered|admitted) (?:twice|more than once|again)\b"
                    r"|\bdouble[- ](?:book\w*|scan\w*|spend\w*|enter\w*|sell\w*|sold)|\bover-?(?:book\w*|sell\w*|sold)\b|\bcheck-?ins?\b"
                    r"|\b(?:validat\w*|scan\w*|redeem\w*|issu\w*) (?:\w+ ){0,2}(?:tickets?|passes|coupons?|vouchers?|admissions?)\b"
                    r"|\b(?:tickets?|passes|coupons?|vouchers?) (?:\w+ ){0,2}(?:validat\w*|scan\w*|redeem\w*|entr(?:y|ies))\b"
                    r"|\bbook(?:ing|ings)\b|\breserv(?:e|es|ed|ation|ations)\b|\bappointments?\b|\bseat (?:selection|maps?|allocation)\b|\bbook(?:ed)? (?:seats?|slots?|rooms?)\b"),
    # A18 (refresh.py): figures that are republished on a schedule (every N minutes, in batches, "latest numbers"); read only for static sites
    ("periodic_refresh", r"\b(?:every|each)\s+(?:\d+|a few|few|couple of|two|three|five|ten|fifteen|thirty)\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
                         r"|\bin batches\b|\bbatch(?:es)? (?:every|roughly|about)\b"
                         # a cadence word next to a refresh verb ("refreshed daily", "rebuilt every night"), or a feed / scrape / API pull; bare "current prices" is not enough
                         r"|\b(?:refresh\w*|updated|republish\w*|rebuil\w*|regenerat\w*|recomput\w*|recalculat\w*|re-?import\w*|synced|scraped|polled|pulled|fetched)\b(?:\W+\w+){0,3}?\W+"
                         r"(?:hourly|daily|nightly|every (?:hour|night|morning|day)|each (?:hour|night|morning|day)|(?:once|twice) (?:a|per) (?:day|hour)|several times (?:a|per) (?:day|hour))\b"
                         r"|\b(?:hourly|daily|nightly) (?:refresh\w*|updates?|imports?|feeds?|snapshots?|batch(?:es)?|scrapes?|rebuilds?|sync\w*|publish\w*)\b"
                         r"|\b(?:live|data|price|results|news|rss|upstream|source) feeds?\b|\bscrap(?:e|es|ed|ing)\b"
                         r"|\b(?:pull|fetch|read|poll)(?:s|ed|ing)? (?:\w+ ){0,3}(?:from|via) (?:an? |the |its |their |our )?(?:\w+ ){0,2}(?:api|feed|webhook)s?\b"
                         r"|\blive (?:results|scores|tallies|standings|counts|data)\b|\bnear[- ]real[- ]?time\b"),
    ("kyc", r"\bkyc\b|know your customer|identity verification"),
    ("chat", r"\bchat|messag"),
    ("collab", r"same board|collaborat|live cursor|multiplayer|co-edit|whiteboard|conflict-free|\bcrdts?\b"
               r"|edit(?:s|ing)? (?:the same|a shared) (?:document|doc|note|canvas|sheet|spreadsheet|diagram|text)"
               r"|(?:shared|collaborative) (?:notes?|canvas|spreadsheets?|text editor)|edit(?:ing)? together|simultaneous(?:ly)? edit"),
    # D13 right-sizing signals, read only for type gaming (engine/rightsize.py): genre vocabulary, no titles or product names
    ("turn_based", r"turn-based|turn based|\basynchronous\b|take (?:a|their) turn|card games?|board games?|\bpuzzles?\b|\btrivia\b|\bquiz"
                   r"|word games?|a move every"),
    ("fast_action", r"\bshooters?\b|\bfps\b|battle royale|\bmoba\b|\bracing\b|fighting game|action game|battle (?:game|arena)"
                    r"|real-?time (?:multiplayer|battles?|combat|pvp|matches)|\bpvp\b|tick[- ]rate|fast-paced"),
    ("markdown", r"markdown|\bmdx?\b"),
    # "GPs" (doctors) is not GPS: lower-case gps needs a location word; upper-case GPS is added in desc_signals.
    # gps = a location is recorded; media = photos or cameras. A photo is not a position (and the reverse).
    ("gps", r"\bgps[- ](?:track\w*|coordinates?|locations?|positions?|fix(?:es)?|pings?|tag\w*|enabled|data|traces?)\b"
            r"|\bgeo-?tag|\blat(?:itude)?\s*(?:/|,|and|&)\s*long(?:itude)?\b|\b(?:gps|geo\w*|map|location)[- ]coordinates?\b"),
    ("media", r"\bphotos?\b|\bphotograph\w*|\bcameras?\b"),
    # words that let a signal's text name lending only when the input does
    ("lending", r"\bloans?\b|\blend(?:ing|er|ers)?\b|\bborrowers?\b"),
    ("emi", r"\bemi\b"),
    ("low_bandwidth", r"\b2g\b|\b3g\b|intermittent|low bandwidth|poor (?:network|connectivity)|no signal|signal is available"),
    ("low_end", r"low-end|low end|2 ?gb ram|1 ?gb ram|budget phones?"),
    ("approvals", r"approv|leave request|workflow"),
    ("internal_only", r"only by employees|internal use|employees only|intranet"),
    ("jobs_dispatch", r"accept jobs|book |booking|dispatch|assign"),
    ("scoring_model", r"scoring model|credit scor|risk model|fraud model"),
    ("notifications", r"notif|alert|remind"),
    # A14 (blind8): also equipment that pushes readings on a schedule (inverters, data loggers); reading FROM a SCADA historian is not device ingestion
    ("iot", r"\bsensors?\b|\biot\b|telemetry|\bdevices? (?:send|report|publish)|smart meters?|trackers? send"
            r"|\binverters?\b|\bdata[- ]?loggers?\b|\bread(?:ing)?s?\s+every\s+\d+(?:\.\d+)?\s*(?:s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)\b|\bpush\w*\s+(?:\w+\s+){0,2}readings?\b"),
    ("digital_goods", r"in-app purchase|in-game|\bcoins\b|\bgems\b|unlock|premium (?:features|content|tier)|loot|battle pass"
                      # E11-3: wording that sells through the app stores (store billing is mandatory for digital goods there)
                      r"|(?:sold|billed|purchased|bought|charged|paid)\s+(?:\w+\s+){0,3}(?:through|via|in|on|with|using)\s+(?:the\s+)?(?:app stores?|apple app store|google play(?: store)?|play store)"
                      r"|\bapp[- ]store (?:billing|subscriptions?|purchases?)|\bstore (?:subscriptions?|billing)|in-app subscriptions?"),
    # A5 (blind8): money taken through the app stores' own billing (a subscription, purchase, plan or pass "through the app stores"),
    # the stores named, also without an in-app goods noun (plain "in-app payments" is not a store route); seat_plan = the price is per seat or per team, which is the only case for Stripe per-seat text
    ("store_billing", r"\b(?:subscri\w*|purchas\w*|pay\w*|billing|billed|buy\w*|bought|sold|charg\w+|plans?|pass(?:es)?|premium|pro)\b(?:\s+(?!(?:published|listed|available|distributed|downloadable|released|installed)\b)[\w'-]+){0,6}?"
                      r"\s+(?:through|via|in|on|with|using|by|from)\s+(?:the\s+|both\s+)?(?:app|play)\s*stores?\b"
                      r"|\b(?:app|play)[- ]?stores?\s+(?:billing|subscriptions?|purchases?|payments?|in-app)|\bstore\s+(?:subscriptions?|billing)"
                      r"|\biaps?\b|\b(?:google )?play (?:store )?billing\b|\bstorekit\b|\bapple in-app"),
    ("seat_plan", r"per[- ]seats?|\bseats?\b|\bteam (?:plans?|subscriptions?|licen[cs]es?)|per[- ](?:user|member|agent|employee)\b"
                  r"|\b(?:organi[sz]ation|workspace|company|enterprise)[- ](?:plans?|subscriptions?|licen[cs]es?)|licen[cs]es? per"),
    # E11-3: facts the description states that no enum field carries (each reads as a service or a named assumption)
    ("sms", r"\bsms\b|\btext[- ]messages? (?:reminders?|alerts?|notifications?|codes?)|\btexts? reminders?|\bwhatsapp (?:reminders?|alerts?|notifications?)"
            # q5 (paraphrase twins): "text messages to customers", "reminders by text": the people-facing wording of SMS (chat between users is not it)
            r"|\btext[- ]messages? (?:to|for) (?:the |our |their |its )?(?:customers?|patients?|clients?|users?|members?|parents?|drivers?|guests?|staff|residents?|tenants?"
            r"|farmers?|operators?|technicians?|subscribers?|them)\b"
            r"|\b(?:remind\w*|notif\w*|alert\w*|confirm\w*|updates?)\b[^.;!?]{0,40}?\b(?:by|via|through|over) text(?:[- ]messages?)?\b"),
    ("otp", r"\botps?\b|one[- ]time (?:pass(?:word|code)s?|codes?)"),
    ("email_out", r"newsletters?|mailing lists?|\be-?mail (?:lists?|campaigns?|receipts?|confirmations?|digests?|reminders?|notifications?)"
                  r"|transactional e-?mails?|\b(?:confirmation|receipt|welcome|reminder|invoice|booking) e-?mails?"
                  r"|\b(?:go|goes|sent|send|sends|delivered|delivery)\s+(?:out\s+)?(?:by|via|through|over)\s+e-?mail"),
    ("uploads", r"\buploads?\b(?:\W+\w+){0,5}?\W+" + UPLOAD_OBJ + r"\b|\b" + UPLOAD_OBJ + r"\b(?:\W+\w+){0,3}?\W+uploaded\b"),
    # A6 (blind8): wording that says videos are uploaded and re-encoded for playback (transcoding, adaptive streaming, HLS, a video platform)
    ("video_vod", r"recorded video|video lectures?|short[- ]video|video (?:upload|sharing|library)|video-sharing|reels?\b|video[- ]on[- ]demand"
                  r"|\btranscod\w*[^.;!?\n]{0,80}\b(?:video|hls|adaptive)\b|\b(?:video|hls|adaptive)\b[^.;!?\n]{0,80}\btranscod\w*|adaptive[- ](?:bitrate )?streaming|\bhls\b|video (?:platform|hosting|streaming service)"
                  r"|\bupload\w*\s+(?:\w+\s+){0,2}videos?\b|\bvideos?\s+(?:is|are|get|gets)\s+uploaded\b"),
    ("video_call", r"video (?:consult|calls?|chat|class|meeting)|live class|teleconsult|tele-consult|telehealth|live stream"
                 # D24-p2: telemedicine and visit/appointment wording for a live video consultation
                 r"|\btele-?(?:medicine|health|therapy|psychiatry)\b|\bvideo[- ](?:visits?|appointments?|consultations?)\b"
                 # recorded "video sessions/interviews" (an editing or import tool) are not a call: only live ones count
                 r"|\blive video (?:sessions?|interviews?)\b"
                 # q5 (paraphrase twins): "live video therapy sessions", "video therapy", "live video lessons"
                 r"|\blive video (?:\w+ )?(?:sessions?|therapy|counsell?ing|coaching|tutoring|lessons?|classes)\b|\bvideo (?:therapy|counsell?ing)\b"
                 r"|\bvirtual (?:visits?|appointments?|consultations?)\b"),
    # A6 (blind8): live media that is not a call (live streaming, karaoke, duets, a named WebRTC need) still needs a media server, not the API;
    # large_downloads = single downloads of gigabytes (signed URLs, range requests and egress cost matter)
    ("live_media", r"\blive[- ]?stream\w*|\bkaraoke\b|\b(?:real-?time|live|online|remote) duets?\b|\bwebrtc\b|\blive (?:audio|video|performances?)\b"
              r"|\bgo(?:ing)? live (?:on (?:stream|camera|air)|to (?:viewers|fans|followers))\b|\bbroadcast\w*\s+(?:live\s+)?(?:video|audio)\b"),
    ("large_downloads", r"\bdownloads?\b[^.;]{0,40}?\b(?:up to|of|over|around|about|~)\s*(?:a few|several|\d+(?:\.\d+)?)\s*(?:gb|gigabytes?|tb|terabytes?)\b"
                        r"|\b(?:a few|several|\d+(?:\.\d+)?)\s*(?:gb|gigabytes?)\s*(?:per|each|a)\s+(?:download|file|mod|asset|dataset|build|game|installer)\b"
                        r"|\bmulti-?gigabyte\b|\bgigabyte-sized\b|\blarge (?:file )?downloads?\b"),
    # CDN gate evidence. public_pages = wording that says pages are open to anyone; media_delivery = video, audio or large files delivered to users
    ("public_pages", r"\bpublic(?:ly)?(?!\s+(?:sector|cloud|key|api|ip|subnet|internet|network|health|transport)\b)(?:[- ]\w+){0,3}[- ](?:pages?|listings?|catalogu?es?|directory|directories|profiles?|websites?|sites?)\b"
                     r"|\b(?:visible|open|available) to (?:the )?(?:public|anyone|everyone)\b|\banyone can (?:browse|view|read|search|see)\b|\banonymous (?:visitors?|users?|browsing)\b"),
    ("media_delivery", r"\brecorded video|\bvideo (?:lectures?|library|libraries|courses?|on demand)\b|\bvideo-on-demand|\bvod\b|\bpodcasts?\b|\bmusic\b|\bsongs?\b|\bmovies?\b|\bfilms?\b|\be-?books?\b"
                       r"|\baudio (?:files?|library|books?|lessons?)|\bstreaming (?:video|audio|media|music|service|platform)\b|\b(?:video|audio|music|media)[- ]?stream\w*"
                       r"|\blarge (?:files?|downloads?|media|assets)\b|\bmedia (?:files?|library|assets)\b|\bdownloadable\b|\b(?:software|installer|firmware) (?:downloads?|images?)\b"
                       r"|\b(?:watch|stream|listen to|download)\w*\s+(?:\w+\s+){0,3}(?:videos?|lectures?|audio|recordings?)\b"),
    ("web3", r"\bnfts?\b|web3|blockchain|cryptocurrenc|wallet connect|smart contract"),
    # A2 (localfirst.py): the text mentions an upload, sync or server step
    ("sync_server", r"\buploads?\b|\bsync(?:s|ed|ing|hroni[sz]\w*)?\b|\bservers?\b|\bback-?ups? (?:to|online)\b"),
    ("scheduler", r"remind(?:er)?s?\b|\bcron\b|nightly|scheduled (?:jobs?|tasks?|emails?)|daily (?:email|digest|report)s?"),
    ("analytics", r"dashboards?|\breports?\b|analysts?|\bbi\b|ad-hoc (?:sql|quer)|data warehouse"),
    # h1 (blind9 A8): wording that the data is a time-ordered stream (readings, metrics, logs, events, ledger rows); with write_heavy and a
    # large volume it adds the time-series storage item (domains.py). write_heavy alone (a social feed, a chat) is not evidence.
    ("time_series", r"time[- ]?series|\btelemetry\b|\bmetrics?\b|\bsensors?\b|\bmeasurements?\b|\bclick-?streams?\b|\bticks?\b(?! per second| a second|/s\b)(?<!\bserver tick)(?<!\bserver ticks)|\bevent (?:logs?|streams?|stor\w+)"
                    r"|\b(?:audit|access|application|server|transaction) (?:logs?|trail)s?\b|\bledgers?\b|\bhistorical (?:prices?|rates?|data)\b|\bquotes? feeds?\b|\blog (?:ingest\w*|aggregat\w*|analy\w*)\b"
                    r"|\blive location\b|\blocation (?:pings?|updates|history|tracks?|tracking)\b|\bgps\b|\btelematics\b"
                    r"|\breadings?\b|\bstats\b|\bobservability\b|\bmonitoring\b|\bperformance data\b|\bover time\b|\btrend\w*\b"
                    r"|\bevery (?:\d+ )?(?:second|minute)s?\b|\bplcs?\b|\bscada\b"),
    # D16 (overeng.py): evidence that payments are a hosted button/link, that the content is editorial, and that the site stores user data
    ("hosted_pay", r"\b(?:donat\w*|payments?|pay|buy|checkout|tip|order)\s+(?:buttons?|links?)\b|\bhosted\s+(?:checkout|payments?|donations?|payment pages?)\b"
                   r"|\bembedded\s+(?:checkout|payments?|donations?)\b|\b(?:paypal|stripe|razorpay|givebutter|ko-?fi|buy ?me ?a ?coffee|gumroad)\s+(?:donat\w*\s+|payment\s+|checkout\s+)?(?:buttons?|links?)\b"),
    ("editorial", r"brochure|landing pages?|marketing (?:site|website|pages?)|portfolio|\bblog\b|documentation|docs site|\bnews\b|magazine|publication"
                  r"|informational|information (?:site|pages?)|service times|opening hours|events? (?:pages?|calendar|listings?)|\bmenu\b|read-only|read[- ]mostly"
                  r"|static (?:site|pages?|content)|press (?:releases?|kit)|case studies|\barticles?\b|\bsermons?\b|\bpublic pages\b"),
    ("user_data", r"\b(?:user|donor|member|customer|visitor|reader|subscriber|student|patient)s?[- ]?accounts?\b|\blog[- ]?in\b|\bsign[- ]?(?:in|up)\b|\bregist(?:er|ered|ration)\b"
                  r"|members?[- ]only|member (?:area|portal)|my account|user profiles?|(?:donor|customer|member|user) (?:history|portal|dashboard|database)"
                  r"|admin (?:panel|dashboard|area)|saved (?:carts?|items|preferences)|shopping cart|\bcart\b|\bshop\b|\bstorefront\b|\binventory\b|booking system|reservations?"
                  r"|comments? sections?|leave comments|post (?:comments|reviews)|\bforum\b|\bdatabase\b|user[- ]generated|submit(?:ted)? (?:forms?|posts|listings)"
                  r"|stores? (?:donor|customer|user|member|visitor|personal)\w*"),
]
DESC_RX = dict(DESC_RULES)
# A2 follow-up (localfirst.py): signals that the data is shared between users/devices or lives on a server that exists or must be built.
# Read only outside sentences that call the step optional or later (optional upload, export, backup), so "optional later upload to a club
# server" stays optional while "syncs records with the team" or "three cashiers share one database on the LAN" does not.
_PEOPLE = (r"(?:team|staff|colleagues?|co-?workers?|everyone|everybody|others?|members?|users?|devices?|laptops?|computers?|machines?|offices?"
           r"|branch\w*|cashiers?|terminals?|workstations?|family|volunteers?|each other)")
SERVER_NEED_RULES = [
    ("server_need", DESC_RX["sync_server"]),
    ("shared_data",
     r"\bshar(?:e|es|ed|ing)\b(?:\W+\w+){0,6}?\W+(?:across|between|among|with (?:the |all |our |their |other |each |every |multiple |several |many )?" + _PEOPLE + r"\b)"
     r"|\bshar(?:e|es|ed|ing) (?:\w+ ){0,3}(?:database|data|inventory|records?|files?|ledger|lists?|budget|calendar|workspace|stock|folder|drive)\b"
     r"|\bshared (?:\w+ )?(?:database|data|inventory|records?|files?|ledger|lists?|budget|calendar|workspace|stock|folder|drive)\b"
     r"|\bsees? (?:the )?(?:others|other \w+|each other)|\b(?:everyone|everybody|all (?:users|staff|members|colleagues|cashiers|devices)|the whole team|colleagues) "
     r"(?:can |will |also )?(?:see|sees|view|views|edit|edits|access|accesses)\b"
     r"|\blan\b|\blocal network\b|\bnetwork (?:drive|share|folder|database)\b|\bsingle source of truth\b|\bcentral(?:i[sz]ed)? (?:database|data ?store|repository|hub|record)\b"
     r"|\b(?:multi|multiple|several|many|various)[- ](?:concurrent |simultaneous )?(?:users?|devices?|terminals?|cashiers?|laptops?|computers?|machines?|workstations?|tills?|registers?|offices?|branches|sites?)\b"
     r"|\b(?:concurrent|simultaneous) (?:users?|access|editing)\b|\breal[- ]?time (?:sync\w*|shar\w*|collab\w*|updates? (?:across|between|for)|multi\w*)|\blive sync\b"),
    ("existing_server",
     r"\b(?:postgres(?:ql)?|mysql|mariadb|sql server|mssql|oracle|mongodb|db2|snowflake|bigquery|redshift|rest(?:ful)? apis?|graphql apis?|back-?ends?)\b"
     r"|\b(?:our|the company'?s?|their|existing|central|corporate|head ?office) (?:\w+ ){0,2}(?:servers?|apis?|erp|crm)\b"
     r"|\bexisting (?:\w+ ){0,2}(?:databases?|systems?|services?)\b"),
]
# a sentence with one of these words describes a later, optional or export-only step, not the core data path
OPTIONAL_STEP_RX = re.compile(r"\boptional(?:ly)?\b|\blater\b|\bafterwards?\b|\beventually\b|\bexport\w*|\bback-?ups?\b|\bnice to have\b|\bin the future\b"
                              r"|\bupload\w* (?:\w+ ){0,3}to (?:the |a )?cloud\b")

# Negation guard shared by every description signal (one helper, not one per signal). A hit counts unless a negation reaches it
# inside its own clause: before it ("no chat", "do not need a ledger", "without KYC") or right after it ("cameras are out of
# scope", "chat: not needed"). Clauses end at punctuation, at "but/however/yet/so/because/since/who/which/that" and at
# "..., and we/now/need ...". A short list ("no in-app chat or messaging", "not adding payments, UPI or cards") shares one cue.
# A negation does not apply when
#   (a) it is a double negation ("cannot ... without KYC", "nothing ships without approval"); "without" negates only when a word
#       comes before it in its sentence ("an app without chat"), so "Without KYC, no account opens" is a requirement,
#   (b) a loss or omission verb sits between the cue and the hit or follows it ("must not lose a ledger entry", "no messages are lost"),
#   (c) the negation is a prohibition or a complaint, not a scope decision: an imperative ("Do not send alerts", "Never assign two
#       jobs"), the rest of the clause says without/unless/until, the negation is about the past ("never used one before") or about
#       today ("Today, staff cannot chat"). Scope verbs ("do not need/plan/build/add ...") and "not needed" stay negations.
# Known limit: a negator more than one word before the hit (or 5 after a scope verb) is not seen, so the signal fires (a missed
# negation adds one supporting service; a false negation would drop a stated requirement). Only a window of _SCAN characters
# around each hit is examined, so cost is linear in the text length.
_SCAN = 120
_CLAUSE_BREAK = re.compile(r"[.!?;:,\n()\[\]]|\s[-\u2013\u2014]+\s"
                           r"|\b(?:but|however|although|though|yet|whereas|while|instead|so|because|since|who|which|that)\b"
                           r"|\band\s+(?:we|they|you|it|i|now|then|also|need|want|require)\b")
# a modal verb ends a relative clause ("users who don't have phones can still chat"): a negation does not reach past it;
# a hyphenated compound ("in-app") is one word
_W = r"(?:\W+(?!(?:can|could|will|would|should|may|might|must|shall)\b)\w+(?:-\w+)*)"
# kind "plain": reaches at most one word ("not chat", "no in-app chat"); "scope": a scope verb reaches further
_STRONG = (
    ("plain", re.compile(r"(?P<cue>\b(?:not|never|neither|nor|cannot)\b(?!\W+(?:only|just|merely|even)\b)|n't\b|\bno need(?: for| of)?\b"
                         r"|\bout of scope\b|\bno longer\b|\bdecided against\b|\brul(?:e|ed) out\b"
                         r"|(?<!can )(?<!may )(?<!could )(?<!might )\bskip(?:ping)?\b)" + _W + r"{0,1}\W*$")),
    ("scope", re.compile(r"(?P<cue>\b(?:not|never)\b|n't\b)\W+(?:plan|want|intend|build|need|use|include|require|support|add|offer"
                         r"|provide|allow|implement)\w*" + _W + r"{0,5}\W*$")),
    ("scope", re.compile(r"(?P<cue>\b(?:will|shall|would) not|\bwon't|\bwouldn't)\W+be\W+(?:any|an?|the)" + _W + r"{0,1}\W*$")),
    ("plain", re.compile(r"(?P<cue>\bnobody\b|\bno one\b|\bnone of\b)" + _W + r"{0,3}\W*$")),
    ("plain", re.compile(r"(?P<cue>\bno\b(?![- ]?code))" + _W + r"{0,2}(?:\W+(?:or|and|nor))?\W*$")),
)
_WEAK = re.compile(r"(?P<cue>\b(?:without|excluding|except)\b)" + _W + r"{0,4}\W*$")
_ANY_NEGATOR = re.compile(r"\b(?:not|never|no|neither|nor|cannot|nobody|nothing|none|no one)\b|n't\b")
_IMPERATIVE = re.compile(r"\W*(?:do\W*)?$")
_LOSS = re.compile(r"\b(?:lose|loses|losing|lost|miss|misses|missed|missing|skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?"
                   r"|delete[sd]?|deleting|drop(?:s|ped|ping)?|leak(?:s|ed|ing|age)?|alter(?:s|ed|ing)?|edit(?:s|ed|ing)?"
                   r"|wait(?:s|ed|ing)?|forget(?:s|ting)?|forgot(?:ten)?|omit(?:s|ted|ting)?)\b")
_LATER_COND = re.compile(r"\b(?:without|unless|until)\b")
_PAST_AFTER = re.compile(r"\W*(?:before|previously|so far|until now|in the past)\b")
_NOW = re.compile(r"\b(?:today|currently|right now|at the moment|at present|as it stands|yet)\b")
_LABEL = re.compile(r"\s*(?::|[-\u2013\u2014]+\s)")
_LIST_NEXT = re.compile(r"\s*(?:or|and|nor)\b")
_LIST_LAST = re.compile(r"\W*(?:or|and|nor)\W*$")
_CONJ_OPEN = re.compile(r"(?:but|yet|while|whereas|although|though|however|instead|and\b.*)$")
_NEG_AFTER = re.compile(r"\W*(?:\w+\W+){0,2}?(?:(?:is|are|was|were|will be|would be|stays?|remains?)\s+)?"
                        r"(?:out of scope|ruled out|excluded|decided against|not a (?:requirement|priority|goal)"
                        r"|(?:not|no longer)\s+(?:needed|required|necessary|in scope|supported|used|planned|wanted|part)"
                        r"|(?:isn't|aren't|wasn't|weren't)\s+(?:needed|required|necessary|in scope|supported|used|planned|wanted))")


@functools.lru_cache(maxsize=16)
def clause_breaks(low):
    """Clause start/end offsets of low; cached because the counterfactual pass re-reads the same description ~100 times."""
    spans = [m.span() for m in _CLAUSE_BREAK.finditer(low)]
    return tuple(b[0] for b in spans), tuple(b[1] for b in spans)


def _cue(pre, opening):
    """The negation cue reaching the end of pre: (match, kind) with kind plain/scope/weak, or (None, None)."""
    found = []
    for kind, rx in _STRONG:
        m = rx.search(pre)
        if not m:
            continue
        before = pre[:m.start("cue")]
        word = m.group("cue")
        # an imperative prohibition ("Do not send alerts", "Never assign two jobs") states a rule, not a scope decision
        if kind == "plain" and _IMPERATIVE.match(before) and (
                word == "never" or (before.strip() and word in ("not", "n't") and re.search(r"\w", pre[m.end("cue"):]))):
            continue
        found.append((m, kind))
    strong = min(found, key=lambda t: (t[0].start(), t[1] != "scope")) if found else None
    weak = _WEAK.search(pre)
    if weak and weak.group("cue") != "excluding":
        # "without"/"except" negate only after a word ("an app without chat"); "Without KYC, no account opens" is a requirement
        if not re.search(r"\w", pre[:weak.start("cue")]) and not _CONJ_OPEN.match(opening):
            weak = None
    if weak and not strong and _ANY_NEGATOR.search(pre, 0, weak.start("cue")):
        weak = None  # double negation
    if strong and not weak:
        return strong
    if weak and not strong:
        return weak, "weak"
    return None, None


def negated_at(low, breaks, start, end):
    """True when low[start:end] sits in a clause that negates it (see the rules above)."""
    starts, ends = breaks
    i = bisect.bisect_right(ends, start)
    j = bisect.bisect_left(starts, end)
    ce = starts[j] if j < len(starts) else len(low)
    post = low[end:min(ce, end + _SCAN)]
    for _ in range(3):
        cs = ends[i - 1] if i else 0
        pre = low[max(cs, start - _SCAN):start]
        opening = low[starts[i - 1]:ends[i - 1]].strip() if i else ""
        cue, kind = _cue(pre, opening)
        # a comma list shares one cue: "not adding payments, UPI or cards"
        if cue or not i or opening != "," or not (_LIST_NEXT.match(post) or _LIST_LAST.match(pre)):
            break
        i -= 1
    if cue:
        neg = not _LOSS.search(pre, cue.end("cue"))
    else:
        kind = "after"
        label = post if post.strip() else low[end:end + _SCAN] if _LABEL.match(low, end) else ""
        neg = bool(_NEG_AFTER.match(label.split(".")[0] if label else post))
    if not neg or _LOSS.search(post) or _PAST_AFTER.match(post):
        return False
    if kind != "weak" and _LATER_COND.search(post):
        return False
    if kind == "plain":  # today's problem is a requirement ("Today, staff cannot chat")
        sp = low[max(0, start - 2 * _SCAN):start]
        sp = sp[max(map(sp.rfind, ".!?;\n")) + 1:]
        sq = low[end:end + 2 * _SCAN]
        m = re.search(r"[.!?;\n]", sq)
        if _NOW.search(sp + " " + (sq[:m.start()] if m else sq)):
            return False
    return True


def live_hit(rx, text, low, breaks, flags=0):
    """rx matches text outside every negated clause (low = lower-cased text of the same length, breaks = clause_breaks(low))."""
    same = len(text) == len(low)
    return any(not (same and negated_at(low, breaks, m.start(), m.end())) for m in re.finditer(rx, text, flags))


# An existing system the input says must not be replaced (entry text or a description sentence naming it).
# STRONG: a negated removal ("cannot be migrated") is a keep even though it contains a removal verb.
# REMOVE: the system is going away ("replace", "migrate off", "must not remain", "retain no", "to be retired", "will not keep").
# KEEP_RX: plain keep wording; in a description it must have the system itself as subject or object (see keep_in_text).
STRONG_KEEP_RX = (r"(?:cannot|can't|can not|won't|will not|must not|may not|should not|is not to) (?:be )?"
                  r"(?:migrat|replac|decommission|retir|remov|switch|mov|chang)\w*")
REMOVE_RX = (r"\breplac(?:e|ed|es|ing|ement)\b|\bmigrat\w* (?:off|away|out|from)\b|\bmov(?:e|ing) (?:off|away from)\b|decommission"
             r"|\bretir(?:e|ed|es|ing)\b|\bsunset|\bphas(?:e|ed|ing) out\b|\bretain no\b|\brewrit|\bend[- ]of[- ]life\b"
             r"|\bmoderni[sz](?:e|ed|es|ing|ation)\b|\bre-?platform\w*"  # q4: the project is the system's replacement
             r"|\b(?:not|never|no longer|don't|won't|cannot|can't) (?:be )?(?:keep|kept|retain|reus|remain|stay|preserv)")
# q4: the description forbids changes to what exists ("without touching the core", "read-only access", "must not modify"): write wording
# elsewhere in the text ("batch jobs writing to Db2") then describes the existing estate, not the new application (planning heuristic)
NO_TOUCH_RX = (r"\bwithout (?:touching|modifying|changing|altering|writing to)\b|\b(?:must|may|can|should|will|do|does)(?: not|n't|not) (?:touch|modify|change|alter|write to)\b"
               r"|\bread[- ]only (?:access|copy|replica|connection|view)\b|\bno writes? (?:to|against|into)\b|\bnever writes? (?:to|into)\b")
KEEP_RX = (r"must (?:stay|remain|be kept|be retained|be reused|be preserved)|\bstays?\b|\bremains?\b|system of record|source of truth"
           r"|\bkeep(?:s|ing)?\b|\bkept\b|\breus(?:e|ed|ing)\b|\bretain\w*|\bpreserv\w*|\bas[- ]is\b|" + STRONG_KEEP_RX)
# words that may sit between a system's name and the keep wording without naming a different thing
_DB_NOUN = r"(?:\s+(?:v?\d[\w.]*|database|db|server|cluster|instance|deployment|tenant|replica set|broker))*"
_DETS = r"(?:(?:the|our|its|their|existing|current|legacy|old|same|this|that)\s+)*"
_AFTER_OBJ = (r"(?=\s*$|\s*[,.;:)(]|\s+(?:for|as|in|and|to|with|on|at|from|unchanged|intact|running|alive|until|because|since|so|but|or"
              r"|while|where|which|that|behind|beside|alongside)\b)")
_KEEP_VERB = r"\b(?:keep(?:s|ing)?|reus(?:e|es|ed|ing)|retain(?:s|ed|ing)?|preserv(?:e|es|ed|ing))\s+"
_KEEP_PRED = (r"\s+(?:must (?:stay|remain|be kept|be retained|be reused|be preserved)|(?:will |must |should )?(?:stays?|remains?)"
              r"|(?:is|are|will be) (?:kept|retained|preserved|reused)|(?:is|remains|stays) (?:the |our )?(?:system of record|source of truth)"
              r"|" + STRONG_KEEP_RX + r")")


def word_rx(pats):
    """Knowledge-base match patterns are regexes matched as whole words, case-insensitive ('teams' never in 'Teamspeak')."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(pats) + r")(?![a-z0-9])", re.I)


def keep_in_entry(low):
    """An existing_systems entry speaks about one system: a removal phrase wins unless the keep is a negated removal."""
    if re.search(STRONG_KEEP_RX, low):
        return True
    return not re.search(REMOVE_RX, low) and bool(re.search(KEEP_RX, low))


def keep_in_text(name_rx, text):
    """A description sentence keeps the system only when, within one clause, the system's own name is the object of a keep
    verb ('keep the Oracle database') or the subject of a keep predicate ('the Oracle database cannot be migrated'). A clause
    that removes it ('replace Oracle', 'migrate off MongoDB') or keeps something else ('reuse our Postgres dashboards') does not."""
    for clause in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", text):
        if not re.search(name_rx, clause):
            continue
        name = r"(?:" + name_rx + r")" + _DB_NOUN
        if re.search(name + r"\s+" + STRONG_KEEP_RX, clause):
            return True
        if re.search(REMOVE_RX, clause):
            continue
        if re.search(_KEEP_VERB + _DETS + name + _AFTER_OBJ, clause) or re.search(name + _KEEP_PRED, clause):
            return True
    return False


def name_rx_plain(pat):
    """Regex for the system's own names in a description (the pattern's match list only, never the vendor's first word)."""
    return r"(?<![a-z0-9])(?:" + "|".join(pat["match"]) + r")(?![a-z0-9])"


def life_rx(life):
    return r"(?<![a-z0-9])(?:" + (life["rx"] if life.get("rx") else re.escape(life["pattern"])) + r")(?![a-z0-9])"


def removal_in_text(name_rx, text):
    """A description clause that names the system and says it is going away ('migrating off a creaking phpBB 3.0 install',
    'the Flash console must be replaced'), without a negated removal."""
    for clause in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", text):
        if re.search(name_rx, clause) and re.search(REMOVE_RX, clause) and not re.search(STRONG_KEEP_RX, clause):
            return True
    return False


# p5 item 8: the new app WRITES to the existing database ('must read and write the existing Oracle database'): that database stays
# the system of record even without keep wording. A clause that removes it, or speaks of a read-only / reporting / replica copy, does not.
WRITE_RX = (r"\bread(?:s|ing)?\s*(?:and|&|/)\s*writ\w*|\bread[- ]write\b|\bwrit(?:e|es|ing)\s+(?:\w+\s+){0,3}?(?:back\s+)?(?:to|into)\b"
            r"|\bupdat(?:e|es|ing)\s+(?:records?|rows?|data)\s+in\b")
_NOT_WRITE_RX = r"read[- ]only|\breport\w*|\breplica\b|\bcopy\b|\bsnapshot\b|\bexport\w*|\bwarehouse\b"
# p5b M1: a clause that moves the data ('migrate data from the Oracle database', 'until we migrate it to PostgreSQL') never reuses it
_MIGRATE_RX = r"\bmigrat\w*\s+(?:\w+\s+){0,3}?(?:to|from|off|onto)\b"
# p5b M1: in a description the database must be the OBJECT of the write wording ('read and write the existing Oracle policy database',
# 'read/write the existing complaints register (old Oracle 11g DB)'); 'reads ... from Oracle and writes orders to Kafka' does not write Oracle
_WRITE_VERB = (r"(?:\bread(?:s|ing)?\s*(?:and|&|/)\s*writ\w*(?:\s+(?:to|into|from|in))?|\bread[- ]write(?:\s+access)?(?:\s+(?:to|on|into))?"
               r"|\bwrit(?:e|es|ing)\s+(?:[\w-]+\s+){0,2}?(?:back\s+)?(?:to|into)"
               r"|\bupdat(?:e|es|ing)\s+(?:records?|rows?|data)\s+in)")


ANON_READERS_RX = (r"\b(?:readers?|visitors?|viewers?|listeners?|the public|audience|citizens?)\s+(?:do not|don't|never|will not|won't|need not|needn't|does not|doesn't)"
                   r"\s+(?:need to\s+|have to\s+)?(?:log ?in|sign ?in|sign up|register|create accounts?|have accounts?|need (?:an? )?accounts?)\b"
                   r"|\banonymous (?:readers?|visitors?|viewers?|listeners?|browsing)\b|\bno (?:reader|visitor|public) (?:accounts?|logins?|sign-?ins?)\b")
_STAFF = (r"(?:editors?|staff|admins?|administrators?|journalists?|authors?|moderators?|employees?|newsroom|curators?|producers?|officers?"
          r"|reporters?|contributors?)")
STAFF_LOGIN_RX = r"\b" + _STAFF + r"\b[^.;]{0,40}?\b(?:log ?in|logs ?in|sign ?in|signs ?in|logins?)\b"
STAFF_COUNT_RX = r"(?<![\d/,.])(\d{1,3}(?:,\d{3})+|\d{1,5})(?![\d/,])\s+(?:\w+\s+)?(" + _STAFF + r")\b"
STAFF_LOGIN_DEFAULT = 100  # planning heuristic: sign-in users when only staff log in and the description gives no staff count


def tier_for(users):
    """Scale tier for a user count alone (the same user thresholds as build's tier; no peak or request-rate evidence)."""
    return 0 if users <= 5000 else 1 if users <= 50000 else 2 if users <= 500000 else 3


def staff_login_count(desc):
    """The staff count (stated, else STAFF_LOGIN_DEFAULT) when the description says readers stay anonymous and staff log in; else None."""
    if not (re.search(ANON_READERS_RX, desc) and re.search(STAFF_LOGIN_RX, desc)) or customer_login(desc):
        return None
    # p5b S5: '1,200 employees' is 1200; '24/7 newsroom' is not a count; '40 reporters and 5 editors' is 45
    found = {(int(m.group(1).replace(",", "")), m.group(2)) for m in re.finditer(STAFF_COUNT_RX, desc)}
    return sum(n for n, _ in found) if found else STAFF_LOGIN_DEFAULT


# p5b M2: customers / users / members who sign in ('customers must sign in to check out') are not anonymous readers
_CUSTOMERS = r"(?:customers?|users?|members?|buyers?|shoppers?|subscribers?|clients?|patients?|students?|guests?|players?|tenants?)"
CUSTOMER_LOGIN_RX = (r"(?<!staff )(?<!admin )(?<!internal )(?<!back-office )\b" + _CUSTOMERS + r"\b([^.;]{0,30}?)\b(?:log ?in|logs ?in|sign ?in|signs ?in|sign up|signs up|register|create accounts?"
                     r"|have accounts?|logins?)\b")
_NEG = r"\b(?:not|never|no|without)\b|n't\b"


def customer_login(desc):
    """A clause where customers or users (not staff) sign in, without a negation between them and the sign-in verb."""
    return any(not re.search(_NEG, m.group(1)) and not re.search(r"\b" + _STAFF + r"\b", m.group(1))
               for m in re.finditer(CUSTOMER_LOGIN_RX, desc))


def login_users(ctx):
    """Users who sign in, read at use time (a sized-down cost pass changes ctx['users'])."""
    n = ctx.get("staff_login_n")
    return min(ctx["users"], n) if n else ctx["users"]


def staff_login_only(ctx):
    return login_users(ctx) < ctx["users"]


def write_in_text(name_rx, text, entry=False):
    """A clause that names the database and says the app reads and writes / writes to it. An existing_systems entry speaks about
    one system, so any write wording counts there; in a description the database must be the object of the write wording."""
    obj = _WRITE_VERB + r"\s+" + _DETS + r"(?:[\w-]+\s+){0,3}?\(?" + _DETS + r"(?:" + name_rx + r")"
    for clause in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", text):
        if (re.search(name_rx, clause) and re.search(WRITE_RX if entry else obj, clause) and not re.search(REMOVE_RX, clause)
                and not re.search(_NOT_WRITE_RX, clause) and not re.search(_MIGRATE_RX, clause)):
            return True
    return False


def moved_in_text(name_rx, sentences):
    """p5b M1: some sentence says the database is replaced or migrated ('will be replaced by PostgreSQL next year')."""
    return any(removal_in_text(name_rx, s) or any(re.search(name_rx, c) and re.search(_MIGRATE_RX, c)
                                                   for c in re.split(r"[,;:]\s*|\s+(?:but|while|whereas)\s+", s)) for s in sentences)


# Server-side language named by an existing system (frameworks and app servers included; front-end frameworks are not).
# Node needs a version or an app noun ('Kubernetes node pool' is not Node.js).
EXISTING_LANG = {"java": r"\bjava\b|\btomcat\b|\bspring\b|\bjboss\b|\bwildfly\b|\bweblogic\b|\bwebsphere\b",
                 "python": r"\bpython\b|\bdjango\b|\bflask\b", "csharp": r"\.net\b|\bc#|\basp\.net\b",
                 "php": r"\bphp\b|\blaravel\b|\bsymfony\b", "ruby": r"\bruby\b|\brails\b", "go": r"\bgolang\b|\bgo \d",
                 "javascript": r"\bnode\.?js\b|\bnode\s*v?\d|\bnode (?:api|app|application|service|backend|server)s?\b|\bexpress\.?js\b"}
# 'Flask-shaped': a hyphenated modifier names a look, not the application; '-based'/'-powered' still name the stack
_COMPOUND = re.compile(r"-(?!(?:based|powered|backed|built|driven)\b)[a-z]")


def existing_langs(raws):
    """Languages of applications that keep running: an entry being decommissioned or rewritten does not count, and
    neither does a word used as a modifier."""
    out = set()
    for r in raws:
        low = r.lower()
        if re.search(REMOVE_RX, low) and not re.search(STRONG_KEEP_RX, low):
            continue
        for lang, rx in EXISTING_LANG.items():
            if any(not _COMPOUND.match(low, m.end()) for m in re.finditer(rx, low)):
                out.add(lang)
    return out


_CLOUD_WORDS = re.compile(r"\b(?:cloud|saas|managed|aws|azure|gcp|google|amazon|atlas|hosted by)\b")


def fallback_pattern(raw, low):
    """An existing system the knowledge base does not know by name, read by keyword (first matching category in knowledge-base
    order) into a stand-in pattern that the by-name handling (reused database / broker / identity provider, integration
    component) treats like a recognised one; None when no keyword names a kind of system."""
    for fb in TECH["existing_fallback"]:
        m = word_rx(fb["match"]).search(low)
        if not m:
            continue
        head = re.split(r"\s*[(,;]|\s+[-–—]\s", raw.strip(), maxsplit=1)[0].strip().rstrip(" .:") or fb["label"]
        name = head[:60].rstrip()
        pat = {"match": [re.escape(m.group(0))], "kind": fb["kind"], "name": name, "how": fb["how"], "src": fb["src"],
               "synthetic": True, "category": fb["category"], "label": fb["label"], "handled": fb["handled"],
               "keyword": m.group(0)}
        if fb["kind"] == "database":
            pat.update(engine="other", product=name)
        elif fb["kind"] == "identity":
            pat.update(reuse=True, provider="neutral", deployment="self_hosted")
        return pat
    return None


_SIGNIN_WORDS = re.compile(r"\b(?:oauth2?|openid|oidc|sso|log-?in|sign[- ]?in|social|auth\w*)\b")
_GAME_WORDS = re.compile(r"\b(?:games?|gaming|gamers?|steamworks|steam deck|achievements?|esports?|multiplayer)\b")


def social_login_counts(req, pat, raw):
    """A social-login entry (Discord, Steam, LinkedIn) is a sign-in provider only when requirements.auth is social and the entry is
    the bare provider name or says sign-in; Steam also needs a game context (type gaming, or game words in the description or entry).
    Otherwise it is read as some other system of that vendor: not a provider, so it falls through to the unrecognised-system warning."""
    low = raw.lower()
    if req["requirements.auth"] != "social":
        return False
    if not (_SIGNIN_WORDS.search(low) or len(low.split()) <= 2):
        return False
    if pat["name"] == "Steam":
        return req["project.type"] == "gaming" or bool(_GAME_WORDS.search(low) or _GAME_WORDS.search((req["project.description"] or "").lower()))
    return True


# D12: data_residency 'other' -> jurisdiction. Ids, display names and keywords from ../research/R15-regions-other.md.
# Whole-word, case-insensitive; acronyms in ACRONYMS match upper-case only (as written) so "mas", "sama" or "nia" in prose
# never pick a country. Lookbehinds keep "New Mexico", "North Korea", "New England" and "New South Wales" out.
COUNTRIES = {
    "australia": ("Australia", r"australian?|aussie|sydney|melbourne|canberra|brisbane|perth"),
    "singapore": ("Singapore", r"singaporean?|pdpa-sg"),
    "japan": ("Japan", r"japan(?:ese)?|tokyo|osaka"),
    "south_korea": ("South Korea", r"(?<!north )korean?|seoul|busan|k-isms"),
    "indonesia": ("Indonesia", r"indonesian?|jakarta|pdp law"),
    "united_kingdom": ("the United Kingdom", r"u\.k\.|united kingdom|british(?! columbia)|britain|(?<!new )england|scotland|(?<!new south )wales|london|uk gdpr"),
    "canada": ("Canada", r"canad(?:a|ian)|toronto|montr[eé]al|quebec|ottawa|vancouver|pipeda|law 25"),
    "brazil": ("Brazil", r"brazil(?:ian)?|brasil|s[aã]o paulo|rio|lgpd|bacen"),
    "uae": ("the UAE", r"united arab emirates|emirat(?:i|es)|dubai|abu dhabi"),
    "saudi_arabia": ("Saudi Arabia", r"saudi(?: arabia)?|riyadh|jeddah|dammam|vision 2030"),
    "qatar": ("Qatar", r"qatar[i]?|doha"),
    "israel": ("Israel", r"israeli?|tel aviv|jerusalem|haifa"),
    "south_africa": ("South Africa", r"south african?|johannesburg|cape town|pretoria|popia"),
    "switzerland": ("Switzerland", r"switzerland|swiss(?! army)|zurich|geneva|bern|ndsg|fadp"),
    "mexico": ("Mexico", r"(?<!new )mexic(?:o|an)|cdmx|quer[eé]taro|monterrey|lfpdppp"),
}
ACRONYMS = {"australia": "IRAP|APRA", "singapore": "MAS", "japan": "APPI|FISC", "south_korea": "PIPA",
            "indonesia": "OJK", "united_kingdom": "UK|NHS", "uae": "UAE|DIFC|ADGM|TDRA",
            "saudi_arabia": "KSA|NCA|SAMA", "qatar": "QCB|NIA", "south_africa": "SARB", "switzerland": "FINMA"}
# Regional words that name several jurisdictions (R15 "ambiguous" column): never pinned, only reported as plausible.
AMBIGUOUS = [
    (r"gulf|gcc", "i", ["uae", "saudi_arabia", "qatar"]),
    (r"middle east|mena", "i", ["uae", "saudi_arabia", "qatar", "israel"]),
    (r"MEA", "", ["uae", "saudi_arabia", "qatar", "israel", "south_africa"]),
    (r"apac|asia[- ]pacific|oceania|anz", "i", ["australia", "singapore", "japan", "south_korea", "indonesia"]),
    (r"south ?east asia|asean", "i", ["singapore", "indonesia"]),
    (r"SEA", "", ["singapore", "indonesia"]),
    (r"asia", "i", ["singapore", "japan", "south_korea", "indonesia"]),
    (r"(?<!east )(?<!west )(?<!north )(?<!central )(?<!eastern )(?<!western )(?<!northern )(?:sub-saharan )?africa", "i", ["south_africa"]),  # p5: East/West/North Africa never suggests South Africa
    (r"latam|latin america|south america", "i", ["brazil", "mexico"]),
    (r"north america", "i", ["canada", "mexico"]),
    (r"europe", "i", ["united_kingdom", "switzerland"]),
    (r"arabia", "i", ["saudi_arabia"]),
    (r"SA", "", ["saudi_arabia", "south_africa"]),
]


def detect_country(text):
    """project.description -> (country id or None, matched word, plausible ids). Exactly one jurisdiction named -> that
    one; several or only regional words -> None with the plausible list (D12)."""
    text = text or ""
    hits = {}
    for cid, (_, rx) in COUNTRIES.items():
        m = re.search(r"(?<!\w)(?:" + rx + r")(?!\w)", text, re.I)
        if not m and cid in ACRONYMS:
            m = re.search(r"(?<!\w)(?:" + ACRONYMS[cid] + r")(?!\w)", text)
        if m:
            hits[cid] = m.group(0)
    if len(hits) == 1:
        cid = next(iter(hits))
        return cid, hits[cid], []
    plaus = list(hits)
    for rx, flags, ids in AMBIGUOUS:
        if not hits and re.search(r"(?<!\w)(?:" + rx + r")(?!\w)", text, re.I if flags else 0):
            plaus += [i for i in ids if i not in plaus]
    return None, None, plaus


# F13: continent words in the description (whole words; country names do not count as a continent)
CONTINENTS = [("north_america", r"\bnorth america(?:n)?\b"), ("south_america", r"\b(?:south|latin) america(?:n)?\b|\blatam\b"),
              ("europe", r"\beurope(?:an)?\b"), ("asia", r"\basia(?:n)?\b|\bapac\b|\basia[- ]pacific\b"),
              ("africa", r"\bafrica(?:n)?\b"), ("oceania", r"\boceania\b"), ("middle_east", r"\bmiddle east\b")]
# "the Americas" names both American continents
_AMERICAS = r"\bamericas\b"
# a continent counts only in a sentence about who uses the product ("teams in Europe and Asia", not "Asian art styles")
_AUDIENCE = (r"\b(?:users?|customers?|clients?|traffic|teams?|visitors?|buyers?|players?|audiences?|subscribers?"
             r"|partners?|merchants?|sellers?|shoppers?|members?|consumers?|students?|patients?|tenants?|people"
             r"|used by|sell(?:s|ing)?|sold|serv(?:e|es|ed|ing))\b")


def continents_in(text):
    """F13: continents named in project.description sentences that also name the product's users or market."""
    found = set()
    for clause in re.split(r"(?<=[.!?;])\s+|\n", text or ""):
        if not re.search(_AUDIENCE, clause, re.I):
            continue
        found |= {k for k, rx in CONTINENTS if re.search(rx, clause, re.I)}
        if re.search(_AMERICAS, clause, re.I):
            found |= {"north_america", "south_america"}
    return [k for k, _ in CONTINENTS if k in found]


# D12a: a sentence states a data-residency requirement when it has a data noun and a residency verb phrase.
RES_DATA = r"\b(?:data|records?|backups?|pii|databases?|information|files?|documents?)\b"
RES_VERB = (r"\b(?:must|shall|should|has to|have to|needs? to|required to|is to|are to|to|will|may only|can only)\s+(?:only\s+)?"
            r"(?:stay|remain|reside|be (?:stored|hosted|located|localised|localized|processed)"
            r"|be (?:kept|held)(?=(?:\s+\w+){0,5}?\s+(?:in|within|inside|outside|locally|on[- ]?prem\w*|on[- ]site)\b)"  # i2: a bare 'be kept' means retain, not a place
            r"|not (?:leave|be (?:stored|hosted|kept) outside))\b"
            r"|\bnever leaves?\b|\b(?:stored|hosted|kept|held|localised|localized|resident)\s+(?:only\s+)?(?:in|within)\b")


# a residency verb preceded by a negation in its sentence ("does not need to stay", "need not be stored") or a sentence that
# allows any location states no requirement
RES_NEGATED = r"\bnot\b|n't\b|\bno need\b|\bnever (?:need|has|have)\b"
RES_ANYWHERE = r"\bany (?:region|country|location|jurisdiction)\b|\banywhere\b"
# data_residency enum values the knowledge base covers directly (a country inside them, e.g. Germany -> eu)
RES_ENUM = ("india", "eu", "us")  # patterns: EXISTING_LOCATIONS below
_RES_PLACE = r"\b(?:in|within|inside)\s+(?:the\s+)?((?-i:[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?))"


def _residency_stated(sent):
    """A sentence states residency when a data noun and an un-negated residency verb appear and it allows no 'anywhere'."""
    if not re.search(RES_DATA, sent, re.I) or re.search(RES_ANYWHERE, sent, re.I):
        return False
    return any(not re.search(RES_NEGATED, sent[:m.start()], re.I) for m in re.finditer(RES_VERB, sent, re.I))


def residency_from_description(text):
    """D12a: project.description -> {'country', 'sentence', 'hints', 'ambiguous', 'conflict'}. A country is pinned only
    when residency sentences (data noun + residency verb) name exactly one country between them; regional words or
    two countries keep it unresolved ('ambiguous' / 'conflict' list the candidates). Place names elsewhere are 'hints'.
    Cached per text (counterfactual reruns rebuild the context ~125 times); callers get a copy they may change."""
    return copy.deepcopy(_residency_from_description(text or ""))


@functools.lru_cache(maxsize=8)
def _residency_from_description(text):
    found, ambiguous, enum, unsupported, stated = [], [], [], [], []
    for sent in re.split(r"(?<=[.!?;])\s+|\n", text):
        if not _residency_stated(sent):
            continue
        stated.append(sent.strip())
        cid, _, plaus = detect_country(sent)
        if cid:
            found.append((cid, sent.strip()))
        elif plaus:
            ambiguous += [p for p in plaus if p not in ambiguous]
        else:  # D12a: an enum-covered place (India, Germany -> eu, the US) or a country the knowledge base does not cover
            hits = [loc for rx, loc in EXISTING_LOCATIONS if loc in RES_ENUM and re.search(r"(?<![a-z0-9])(?:" + rx + r")(?![a-z0-9])", sent, re.I)]
            if re.search(r"(?<![A-Za-z])US(?![A-Za-z])", sent) and "us" not in hits:
                hits.append("us")
            if hits:
                enum += [(h, sent.strip()) for h in hits if h not in [e[0] for e in enum]]
            else:
                m = re.search(_RES_PLACE, sent)
                if m and m.group(1) not in unsupported:
                    unsupported.append(m.group(1))
    countries = list(dict.fromkeys(c for c, _ in found))
    cid, _, plaus = detect_country(text)
    hints = [cid] if cid else plaus
    out = {"country": None, "sentence": None, "hints": hints, "ambiguous": ambiguous, "conflict": [],
           "enum": enum, "unsupported": unsupported, "stated": stated}
    if len(countries) == 1 and not ambiguous:
        out["country"], out["sentence"] = countries[0], found[0][1]
    elif len(countries) > 1:
        out["conflict"] = countries
    elif countries:  # one country sentence plus a regional / multi-country one
        out["ambiguous"] = countries + [p for p in ambiguous if p not in countries]
    return out


# Where an existing system says it runs: provider region codes/names and cities. London/Zurich regions are named first so
# 'eu-west-2' is the UK, not the EU. Only an exact single location counts; several or none -> None (unverified).
EXISTING_LOCATIONS = [
    (r"eu-west-2|europe-west2|uk ?south|uk ?west", "united_kingdom"),
    (r"eu-central-2|europe-west6|switzerland ?(?:north|west)", "switzerland"),
    (r"ap-south-[12]|asia-south[12]|(?:central|south|west|jio) ?india(?: \w+)?|india|indian|mumbai|pune|hyderabad|chennai|delhi"
     r"|bengaluru|bangalore|noida|gurugram|gurgaon|kolkata", "india"),
    (r"eu-[a-z]+-\d|europe-[a-z]+\d+|(?:west|north) ?europe|germany ?(?:west ?central|north)|france ?(?:central|south)"
     r"|sweden ?central|italy ?north|poland ?central|spain ?central|eu|europe|european union|frankfurt|dublin|ireland|paris"
     r"|amsterdam|netherlands|germany|france|stockholm|milan|madrid|warsaw|belgium|finland|italy|spain|sweden|poland", "eu"),
    (r"us-(?:east|west|central|north|south)[a-z]*-?\d|(?:east|west|central|north ?central|south ?central|west ?central) ?us ?\d?"
     r"|usa|u\.s\.a?\.?|united states|virginia|ohio|oregon|california|iowa|texas|arizona|illinois", "us"),
]


def existing_location(raw):
    """existing_systems entry -> 'india' / 'eu' / 'us' / a D12 country id, or None when no single location is stated."""
    hits = {loc for rx, loc in EXISTING_LOCATIONS if re.search(r"(?<![a-z0-9])(?:" + rx + r")(?![a-z0-9])", raw, re.I)}
    if "united_kingdom" in hits or "switzerland" in hits:
        hits.discard("eu")
    cid, _, _ = detect_country(raw)
    if cid and not hits & {"united_kingdom", "switzerland"}:
        hits.add(cid)
    return next(iter(hits)) if len(hits) == 1 else None


def lifecycle_text(low):
    """Normalise common product spellings so 'Node.js 18', 'node-18', 'ASP.NET Core 8', 'PostgreSQL14', 'Angular 1.x'
    meet the lifecycle patterns ('node 18', '.net 8', 'postgresql 14', 'angularjs'); a digit may not follow a pattern."""
    low = re.sub(r"node\s*\.?\s*js", "node", low)
    low = re.sub(r"\.net core", ".net", low)
    low = re.sub(r"angular\s*(?:\.?js\b|1(?:\.|x\b|\b))", "angularjs ", low)
    low = re.sub(r"\bmongo(?:\s*db)?\b", "mongodb", low)
    low = re.sub(r"\bcentos\s+linux\b", "centos", low)
    low = re.sub(r"\bruby\s+on\s+rails\b", "rails", low)
    low = re.sub(r"\boracle\s+database\b", "oracle", low)
    low = re.sub(r"\b(?:vb|visual\s+basic)[\s\-_]*6(?:\.0)?(?![\d.]*\d)", "visual basic 6", low)
    low = re.sub(r"\bwin(?:dows)?[\s\-_]*server[\s\-_]*(?=\d)", "windows server ", low)
    low = re.sub(r"\b(?:vmware\s+)?(?:vsphere|esxi?)[\s\-_]*(?:server\s*)?v?(?=\d)", "vsphere ", low)  # h1: vSphere / ESXi 7 -> "vsphere 7"
    # A3 (blind8): legacy runtimes and products often named with a vendor prefix or a 1.x style version
    low = re.sub(r"\b(?:java(?:\s*se)?|jdk|jre|j2se)[\s\-_]*(?:1\.)?(?=[67](?!\d))", "java ", low)
    low = re.sub(r"\bstruts[\s\-_]*v?(?=1(?!\d))", "struts ", low)
    low = re.sub(r"\b(?:(?:adobe|macromedia)\s+)?flash(?:\s+player)?(?=[\s\-]+(?:player|plugin|app\b|apps\b|application|client|front-?end|ui\b|console|movie|based|admin|portal|widget|site|website|game|content|applet)|\s*$|\s*[,/;)(])", "adobe flash", low)
    low = re.sub(r"\boracle\s+forms(?:\s+(?:and|&)\s+reports)?[\s\-_]*v?(?=\d)", "oracle forms ", low)
    low = re.sub(r"\bphp[\s\-_]*bb[\s\-_]*v?(?=\d)", "phpbb ", low)
    low = re.sub(r"\bshare[\s\-_]*point(?:\s+server)?[\s\-_]*(?=(?:20|19)\d\d\b)", "sharepoint ", low)
    low = re.sub(r"\b(?:eclipse\s+)?mosquitto[\s\-_]*v?(?=\d)", "mosquitto ", low)
    low = re.sub(r"\bcold[\s\-]?fusion(?:\s+(?:server|cfml))?[\s\-_]*v?(?=\d|mx\b)", "coldfusion ", low)
    low = re.sub(r"\bclassic[\s\-]*asp\b|\basp[\s\-]*classic\b|\basp\s*3(?:\.0)?\b", "asp classic", low)
    low = re.sub(r"\b(?:ms\s+)?(?:microsoft\s+)?\.?net[\s\-]*framework[\s\-_]*v?(?=\d)", ".net framework ", low)
    low = re.sub(r"\b(?:apache\s+)?tomcat[\s\-_]*v?(?=\d)", "tomcat ", low)
    low = re.sub(r"\binternet explorer[\s\-_]*v?(?=\d)|\bie[\s\-_]*v?(?=\d{1,2}\b)", "internet explorer ", low)
    return re.sub(r"\b(node|python|postgresql|postgres|\.net|vue|mysql|angular|php|django|laravel|mongodb|centos|rails|ruby|oracle|elasticsearch|ubuntu)[\s\-_]*v?(?=\d)",
                  r"\1 ", low)


def lifecycle_hits(norm):
    """Every knowledge-base lifecycle entry the (normalised) text names, one per product name, in knowledge-base order. An entry
    matches its literal pattern as a whole token, or its optional "rx" regular expression; a digit may not follow a literal pattern."""
    out = []
    for lc, rx in _life_compiled():
        if rx.search(norm) and all(o["name"] != lc["name"] for o in out):
            out.append(lc)
    # one row per release: a point release ("android 12.1") and its major line ("android 12") from the same source keep the point release
    pats = [o.get("pattern", "") for o in out]
    return [o for o in out if not any(p != o.get("pattern", "") and p.startswith(o.get("pattern", "") + ".") and q.get("src") == o.get("src")
                                      for p, q in zip(pats, out))]


_LIFE_RX = []


def _life_compiled():
    """The lifecycle rows with their match expressions, compiled once (the table holds over a thousand rows; re's own cache
    holds 512, so per-call compilation would thrash it)."""
    if len(_LIFE_RX) != len(TECH["lifecycle"]):
        _LIFE_RX[:] = []
        for lc in TECH["lifecycle"]:
            if lc.get("rx"):
                rx = r"(?<![a-z0-9])(?:" + lc["rx"] + r")"
            else:
                rx = (r"(?<![a-z0-9])" if lc["pattern"][0].isalnum() else "") + re.escape(lc["pattern"]) + r"(?!\d)"
            _LIFE_RX.append((lc, re.compile(rx)))
    return _LIFE_RX


# A3 (blind8): a "Server" edition or a versioned release of a Microsoft collaboration product ('SharePoint Server 2013',
# 'Exchange 2010 on-prem') is self-hosted software; the Microsoft 365 / Graph / Entra profile does not describe it
_MS_SELF_HOSTED = re.compile(r"(?<![a-z0-9])(?:sharepoint|exchange|skype for business|lync)\s+(?:server(?![a-z0-9])|(?:19|20)\d\d\b)"
                             r"|(?<![a-z0-9])(?:sharepoint|exchange)\b[^,;()]*\bon[- ]?prem", re.I)


# h1 (blind9 A1), planning heuristic: the lowest release line of a few well-known product families that the knowledge base holds
# lifecycle rows for (kb "version_floors"). An existing_systems entry that names an older version of one of them and matches no
# lifecycle row is flagged END_OF_LIFE_SUSPECTED ("older version of a known product") with soft wording: the date is not stated.
# a number followed by a count noun is a quantity, not a version ("Postgres 2 replicas", "vSphere 3 hosts"); (?!\d) ends the version
OLD_VERSION_TAIL = r"(?!\d)"
COUNT_NOUN_RX = re.compile(r"\s*(?:x\s*)?(?:\w+[- ])?(?:replicas?|nodes?|shards?|servers?|hosts?|instances?|vms?|boxes|machines?"
                           r"|copies|sites?|regions?|zones?|dbs?|databases?)\b")


def old_version_hit(norm):
    """The version-floor family an entry names below its oldest known line, or None. Returns {family, version, oldest, successor}."""
    for fl in TECH.get("version_floors", []):
        for m in re.finditer(r"(?<![a-z0-9])" + fl["rx"] + OLD_VERSION_TAIL, norm):
            ver = tuple(int(g) for g in m.groups() if g)
            if len(ver) == 1 and COUNT_NOUN_RX.match(norm, m.end()):
                continue  # a bare whole number before a count noun is a quantity, not a release ("Postgres 2 replicas"); a dotted version always is one
            if ver + (0,) * (2 - len(ver)) < tuple(fl["floor"]):
                return {"family": fl["family"], "version": ".".join(g for g in m.groups() if g), "oldest": fl["oldest"], "successor": fl.get("successor")}
    return None


def life_what(life):
    """Why an existing system's lifecycle entry is a warning: sentence tail for 'X <what> (<product>)'. Entries marked soft
    carry dates the knowledge base did not re-check against the vendor page (source status official-unverified), so the text
    says so and prints no day-level date."""
    kind = life.get("kind")
    if life.get("soft"):
        if kind == "older_line":
            return (f"belongs to an older release line than the current {life.get('line', 'one')}; the knowledge base does not confirm "
                    "whether it still receives security fixes")
        if kind == "legacy":
            return ("is a legacy technology without new development; its support depends on the platform it runs on, "
                    "which the knowledge base does not confirm in detail")
        if life.get("approx"):
            return f"is past its vendor's end of support (around {life['approx']}; the knowledge base has not re-checked the exact date)"
        if life.get("detail"):
            return f"is past its vendor's end of support ({life['detail']}; the knowledge base has not re-checked the exact dates)"
        return ("is older than any release its vendor still lists as supported; the exact end-of-support date is not confirmed "
                "in the knowledge base")
    return {"unmaintained": f"is no longer maintained (repository archived {life['eol']})",
            "unsupported": f"is no longer supported by its vendor as of {life['eol']}",
            "closed": f"is closed to new customers (since {life['eol']})", "deprecated": f"was deprecated on {life['eol']}"}.get(
        kind, f"reached end of support on {life['eol']}")


def life_short(life):
    """Short predicate for text that follows a lifecycle warning ('It is past end of support')."""
    if life.get("soft") and life.get("kind") == "older_line":
        return "is on an older release line"
    if life.get("soft") and life.get("kind") == "legacy":
        return "is a legacy technology"
    return "is past end of support"


# A3 (blind8), planning heuristic: an existing_systems entry with no lifecycle data whose text carries an old-release marker
# (a product edition year of 2015 or earlier written right after a product word, an Oracle 8i-11g style tag, a 1.x line, or a
# long-retired product name) is flagged END_OF_LIFE_SUSPECTED instead of being silently assumed supported. A bare year is no
# trigger: a contract or upgrade date ("2014 contract", "upgraded 2015") says nothing about the product's release.
EOL_TOKEN_RX = re.compile(
    r"(?<![a-z0-9])(?:\d{1,2}[ig]|v?1\.x|(?:adobe |macromedia )?flash(?= (?:player|plugin|apps?|application|client|front-?end|ui|console|movie|based|admin|portal|widget|site|website|game|content|applet)\b)|(?:adobe|macromedia) flash|silverlight|activex|java applets?|foxpro|powerbuilder|lotus notes|clipper|netware"
    r"|windows (?:xp|vista|nt)|win(?:dows)? ?(?:95|98|me|2000)|asp classic|classic asp)(?![a-z0-9])", re.I)


EOL_YEAR_RX = re.compile(r"(?<![\w.])(19[89]\d|200\d|201[0-5])(?![\w.])")
# the word before an edition year must be a product name (capitalised as written) or a product noun, never a date or verb word
_EOL_PRODUCT_NOUN = {"suite", "server", "edition", "release", "version", "platform", "studio", "system", "engine", "database", "office", "v"}
_EOL_NOT_PRODUCT = {"since", "from", "in", "of", "to", "until", "by", "upgraded", "migrated", "installed", "deployed", "launched", "built", "signed",
                    "renewed", "bought", "released", "updated", "patched", "dated", "circa", "around", "about", "before", "after", "during", "as",
                    "at", "on", "year", "fy", "contract", "data", "established", "founded", "started", "purchased", "acquired", "implemented",
                    "licensed", "licenced", "created", "written", "last", "late", "early", "mid", "end", "and", "or", "the", "a", "an", "est"}


def eol_token(raw):
    """The old-release marker in an existing_systems entry (see EOL_TOKEN_RX and EOL_YEAR_RX), or None."""
    m = EOL_TOKEN_RX.search(raw)
    if m:
        return m.group(0)
    for y in EOL_YEAR_RX.finditer(raw):
        prev = re.search(r"([A-Za-z][\w+#-]*)\s+$", raw[:y.start()])
        if prev:
            w = prev.group(1)
            if w.lower() not in _EOL_NOT_PRODUCT and (w[0].isupper() or w.lower() in _EOL_PRODUCT_NOUN):
                return y.group(0)
    return None


# F1 (round 11): the team's own server language named in project.description ("Rails shop", "the team writes Elixir",
# "our Django team"). Language or framework word -> language id. Whole words only; a match marks a primary language.
# Common English words count only in their language spelling: "Go"/"Golang" (never "go"), "Rust" (never "rust"), Express
# only as Express.js or "Express framework".
PRIMARY_WORDS = {"ruby": r"ruby(?: on rails)?|rails", "elixir": r"elixir|phoenix", "python": r"python|django|fastapi|flask",
                 "java": r"java|spring(?: boot)?", "kotlin": r"kotlin(?: multiplatform)?|jetpack compose", "csharp": r"c#|\.net|asp\.net(?: core)?|dotnet|blazor",
                 "php": r"php|laravel|symfony", "go": r"golang|(?-i:Go|GO)", "rust": r"(?-i:Rust)",
                 "javascript": r"node(?:\.?js)?|javascript|express(?:\.?js| framework)|react[- ]native|next\.?js|sveltekit|nuxt",
                 "typescript": r"typescript|nestjs|angular(?!js)", "dart": r"dart|flutter", "swift": r"(?-i:Swift(?:UI)?)"}
# A4 (blind8): a framework the description names as the team's own (same clause rules as the languages above) -> the knowledge-base
# candidates it stands for; select.py gives them a bonus beside the language credit (FRAMEWORK_FIT_SHARE there).
TEAM_FRAMEWORKS = [(r"flutter", ["flutter"]), (r"react[- ]native", ["react-native-expo"]), (r"swiftui", ["swiftui"]),
                   (r"jetpack compose", ["kotlin-compose"]), (r"kotlin multiplatform", ["kmp-compose"]),
                   (r"phoenix", ["elixir-phoenix"]), (r"laravel", ["php-laravel"]), (r"django", ["python-django"]),
                   (r"fastapi", ["python-fastapi"]), (r"ruby on rails|rails", ["ruby-rails"]), (r"spring(?: boot)?", ["java-spring"]),
                   (r"nestjs", ["node-nestjs"]), (r"express(?:\.?js| framework)", ["node-express"]),
                   (r"asp\.net(?: core)?", ["dotnet-aspnet"]), (r"next\.?js", ["nextjs"]), (r"sveltekit", ["sveltekit"]),
                   (r"nuxt", ["nuxt"]), (r"angular(?!js)", ["angular"]), (r"blazor", ["blazor"])]
_PRIMARY_RX = {lang: re.compile(r"(?<![\w.#])(?:" + w + r")(?![\w#])", re.I) for lang, w in PRIMARY_WORDS.items()}
_TEAM_NOUN = re.compile(r"\s+(?:shop|team|house|developers|engineers|devs|programmers)\b", re.I)
_TEAM_VERB = re.compile(r"(?:team|we|developers|engineers|devs|programmers)\s+(?:mostly |mainly |only |already |all )?(?:writes?|codes?|works?|builds?"
                        r"|knows?|uses?|is fluent|are fluent)(?:\s+(?:in|with))?\s+(?:mostly |mainly |only )?", re.I)
# a clause that negates, contrasts, looks back or plans hiring does not state the team's current language
_NOT_OWN = re.compile(r"\bnot\b|n't\b|\bnever\b|\bno longer\b|\bunlike\b|\bprevious(?:ly)?\b|\bformer(?:ly)?\b|\bleft\b"
                      r"|\bused to\b|\bhir(?:e|es|ed|ing)\b|\brecruit\w*|\bavoid\w*|\bmov(?:e|ed|ing) away\b|\bmigrat\w* away\b"
                      r"|\binstead of\b|\brather than\b", re.I)
_LIST_SEP = re.compile(r"\s*(?:,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+|&\s*|/\s*)", re.I)
# Round 16: experience phrasing. A team subject (we/team/developers/engineers...) earlier in the clause, then "have built
# [and maintained] <X> apps", "have been writing <X>", "years of <X>" or "experience(d) in/with <X>". After "have built" each
# listed language/framework must be followed by a product noun or the clause end ("We have run Spring sales" is not Java).
_EXP_SUBJ = re.compile(r"\b(?:we|i|team|developers|engineers|devs|programmers|founders)\b", re.I)
_EXP_VERB = r"(?:built|maintained|shipped|run|written|developed|delivered|operated)"
_EXP_BUILT = re.compile(r"(?:\bhave|\bhas|'ve)\s+(?:all\s+|both\s+|long\s+)?" + _EXP_VERB + r"(?:(?:\s*,\s*|\s+and\s+)" + _EXP_VERB
                        + r")*\s+(?:(?:with|in|on)\s+)?", re.I)
_EXP_OTHER = re.compile(r"(?:\bhave|\bhas|'ve)\s+been\s+(?:writing|coding|using|building|shipping|running|maintaining|working)(?:\s+(?:with|in|on))?\s+"
                        r"|\byears of\s+(?:(?:professional|production|hands-on|commercial)\s+)?(?:experience\s+(?:in|with)\s+)?"
                        r"|\b(?:experienced|experience|expertise|skilled|proficient)\s+(?:in|with)\s+", re.I)
_EXP_NOUN = re.compile(r"\s+(?:apps?|applications?|services?|sites?|websites?|backends?|apis?|projects?|systems?|platforms?|products?"
                       r"|code(?:bases?)?|monoliths?|microservices?|stacks?|servers?)\b", re.I)
_EXP_END = re.compile(r"\s+(?:for|since|professionally|in production)\b|\s*(?:[.,;:)]|$)", re.I)
# A4: "solid Elixir/Phoenix experience", "strong Django background": the list is followed by an experience noun and a team subject
# comes earlier in the clause, with no word that says the experience is missing or thin
_EXP_TRAIL = re.compile(r"\s+(?:experience|expertise|background|skills?|know-how)\b", re.I)
_EXP_THIN = re.compile(r"\b(?:no|little|limited|zero|lacks?|lacking|without|some|basic|beginner|minimal)\b", re.I)
# present-tense possession must come before the skill ("has solid X experience", "with strong X background", "already ..."); a wish,
# hire, learning goal, plan or a past remark in the same clause means the skill is not the team's today
_EXP_POSS = re.compile(r"\b(?:have|has|having|with|solid|strong|deep|good|extensive|proven|already)\b|'ve\b", re.I)
_EXP_NOT_NOW = re.compile(r"\b(?:need\w*|want\w*|wish\w*|hope\w*|look(?:ing)? for|seek\w*|hir(?:e|es|ed|ing)|gain\w*|learn\w*|acquir\w*|soon|"
                          r"years ago|ago|used to|previous(?:ly)?|former(?:ly)?|once|consider\w*|plans? to|planned to|planning to|would like|"
                          r"no experience|lack\w*|lacking)\b", re.I)
# a city or place name is not the framework: "Phoenix" counts only beside Elixir or as "Phoenix framework / LiveView / app"
_PHOENIX_NAME = re.compile(r"\bphoenix\b(?!\s+(?:framework|live\s?view|apps?)\b)", re.I)


def _lang_at(clause, pos):
    """(language id, end, matched word) of a language word starting exactly at pos, or None; hyphen compounds ('go-live') do not count."""
    for lang, rx in _PRIMARY_RX.items():
        m = rx.match(clause, pos)
        if m and not _COMPOUND.match(clause.lower(), m.end()):
            return lang, m.end(), m.group(0).lower()
    return None


def _team_hits(text):
    """(language ids, matched words) the description names as the team's own, only in a clause without negation, contrast,
    past or hiring words."""
    out, words = set(), set()
    for clause in re.split(r"(?<=[.!?;])\s+|\n|\s+but\s+|,\s+(?=(?:and |so |while |whereas )?(?:we|our|the|they|their|it|its|this|i)\b)",
                           text or "", flags=re.I):
        if _NOT_OWN.search(clause):
            continue
        # "Phoenix shop / team" and "<X> experience" read Phoenix as the framework only beside Elixir or as "Phoenix framework/LiveView/app"
        mclause = clause if re.search(r"\belixir\b", clause, re.I) else _PHOENIX_NAME.sub(lambda m: "_" * len(m.group(0)), clause)
        for lang, rx in _PRIMARY_RX.items():
            for m in rx.finditer(mclause):
                if not _COMPOUND.match(mclause.lower(), m.end()) and _TEAM_NOUN.match(mclause, m.end()):
                    out.add(lang)
                    words.add((lang, m.group(0).lower()))
        for v in _TEAM_VERB.finditer(clause):
            _walk_langs(clause, v.end(), out, False, words)
        for rx, need_noun in ((_EXP_BUILT, True), (_EXP_OTHER, False)):
            for v in rx.finditer(clause):
                if _EXP_SUBJ.search(clause[:v.start()]):
                    _walk_langs(clause, v.end(), out, need_noun, words)
        for rx in _PRIMARY_RX.values():  # A4: "<list> experience"
            for m in rx.finditer(mclause):
                before = mclause[:m.start()]
                if (_EXP_SUBJ.search(before) and _EXP_POSS.search(before) and not _EXP_THIN.search(before)
                        and not _EXP_NOT_NOW.search(mclause)):
                    found, wset = set(), set()
                    end = _walk_langs(mclause, m.start(), found, False, wset)
                    if _EXP_TRAIL.match(mclause, end):
                        out |= found
                        words |= wset
    return out, words


def primary_langs(text):
    """Languages project.description names as the team's own (sorted ids): '<lang> shop/team/developers' or 'the team
    writes <lang>[, <lang> and <lang>]' or experience phrasing ('our developers have built Laravel apps for years', 'years
    of Django', 'solid Elixir/Phoenix experience'), only in a clause without negation, contrast, past or hiring words."""
    return sorted(_team_hits(text)[0])


@functools.lru_cache(maxsize=8)
def team_frameworks(text, langs=None):
    """Knowledge-base candidate ids of the frameworks project.description names as the team's own (see TEAM_FRAMEWORKS). With
    langs (team.languages ids) a framework counts only if its language is listed: the description never adds a language."""
    words = _team_hits(text)[1]
    return tuple(sorted({cid for lang, w in words if langs is None or lang in langs
                         for rx, cids in TEAM_FRAMEWORKS if re.fullmatch(rx, w) for cid in cids}))


def _walk_langs(clause, pos, out, need_noun, words=None):
    """Add each language in a list starting at pos ('Python, Go and Rust'; 'Laravel apps and Django services'). With
    need_noun every item must be followed by a product noun or the clause end. Returns the end of the list."""
    end = pos
    while True:
        hit = _lang_at(clause, pos)
        if not hit:
            return end
        end = hit[1]
        noun = _EXP_NOUN.match(clause, end)
        if need_noun and not noun and not _EXP_END.match(clause, end):
            return end
        out.add(hit[0])
        if words is not None:
            words.add((hit[0], hit[2]))
        end = noun.end() if noun else end
        sep = _LIST_SEP.match(clause, end)
        if not sep:
            return end
        pos = sep.end()


NO_VIDEO_RX = r"\b(?:no|without|not)\s+(?:any\s+)?video\b(?![- ](?:recordings?|recorded|storage|files?|uploads?|archives?))|\bvideo[- ]free\b"
TEXT_ONLY_RX = r"\btext[- ]only\b"  # rules video out only when the description names no video at all ("reminders are text only")
# q5: "newsletter signup link", "mailing-list sign-up form", "link to our newsletter", "subscribe box for the newsletter" (planning heuristic)
_NL = r"(?:newsletters?|mailing[- ]lists?)"
_NL_UI = r"(?:links?|forms?|box(?:es)?|widgets?|buttons?|embeds?|pop-?ups?|pages?|fields?)"
NEWSLETTER_SIGNUP_RX = (r"\b" + _NL + r"\s+(?:sign[- ]?ups?|subscri\w+|opt[- ]?ins?)(?:\s+" + _NL_UI + r")?\b"
                        r"|\b(?:sign[- ]?up|subscri\w+|opt[- ]?in|join)\s+(?:" + _NL_UI + r"\s+)?(?:to|for)\s+(?:the |our |a |my |their )?" + _NL + r"\b"
                        r"|\b" + _NL_UI + r"\s+to\s+(?:the |our |a |my |their )?" + _NL + r"\b")


@functools.lru_cache(maxsize=8)
def desc_signals(desc):
    """Description flags (lower-cased text) and primary languages (original case: 'Go' vs 'go'), computed once per
    description: counterfactual reruns rebuild the context ~125 times with the same (up to 20,000-character) text."""
    low = desc.lower().replace("\u2019", "'")
    breaks = clause_breaks(low)
    flags = {flag: live_hit(rx, low, low, breaks) for flag, rx in DESC_RULES}
    flags["gps"] = flags["gps"] or live_hit(r"\bGPS\b", desc, low, breaks)
    # a description that rules video out ("no video", "without video", "text only") gets no video-call service from a telehealth word
    if flags["video_call"] and (re.search(NO_VIDEO_RX, low) or (re.search(TEXT_ONLY_RX, low) and "video" not in low)):
        flags["video_call"] = False
    # q5: a newsletter (or mailing-list) sign-up link, form or box points at a newsletter service; it is not this application sending mail.
    # With those mentions blanked out, email_out must still fire on sending wording of its own to stay set.
    if flags["email_out"] and re.search(NEWSLETTER_SIGNUP_RX, low):
        rest = re.sub(NEWSLETTER_SIGNUP_RX, lambda m: " " * len(m.group()), low)
        flags["email_out"] = live_hit(DESC_RX["email_out"], rest, rest, clause_breaks(rest))
    firm = re.sub(r"[^.!?;\n]+", lambda m: " " * len(m.group()) if OPTIONAL_STEP_RX.search(m.group()) else m.group(), low)
    fb = clause_breaks(firm)
    flags.update({flag: live_hit(rx, firm, firm, fb) for flag, rx in SERVER_NEED_RULES})
    return flags, tuple(primary_langs(desc))


def num(x):
    """Plain number for prose: never an exponent; thousands separators from 10,000 (as the cost lines)."""
    if float(x).is_integer():
        n = int(x)
        return f"{n:,}" if abs(n) >= 10000 else str(n)
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def usd(x):
    """Dollar amount for prose: thousands separators from 1,000 so one sentence never mixes '$33,297' and '$5933'."""
    return num(x) if not float(x).is_integer() else f"{int(x):,}"


def lang_norm(langs):
    return sorted({LANG_ALIASES.get(x, x) for x in langs})


PEAK_RATE_RX = re.compile(r"\b(?:req(?:uest)?s?|txns?|calls?|ops)\s*/\s*s(?:ec(?:ond)?)?\b|\bper\s+(?:second|sec)\b|\b(?:tps|rps|qps)\b|\b(?:requests?|transactions?|calls?|messages?|events?)\s*(?:/\s*s\b|a second\b)", re.I)


def build(req):
    c = {"req": req}
    plats = req["project.platforms"]
    c["platforms"] = plats
    c["web"] = "web" in plats
    c["mobile"] = [p for p in ("android", "ios") if p in plats]
    c["desktop"] = "desktop" in plats
    c["api_only"] = plats == ["api_only"] or (set(plats) == {"api_only"})
    users = max(req["scale.users_12_months"], req["scale.users_at_launch"])
    peak = req["scale.peak_concurrent_users"]
    c["peak_derived"], c["peak_fraction"], c["peak_why"] = peak is None, None, ""
    if peak is None:  # E8e: users x a documented fraction, never above users
        peak, c["peak_fraction"], c["peak_why"] = costreal.derived_peak(users, req, req["project.type"])
        if users != req["scale.users_12_months"]:
            c["peak_why"] = c["peak_why"].replace("of users_12_months", f"of the {users:,} users used for sizing")
    # h1 (blind9 A6): an explicit peak above the total user count is capped at the users for sizing (planning heuristic). An API-shaped
    # project (api_platform, or api_only among the platforms) counts its customers' end users or requests, not its own accounts, so it
    # is never capped; if its description gives the peak as a rate ("5,000 transactions per second") the warning is dropped too.
    api_shaped = req["project.type"] == "api_platform" or "api_only" in plats
    c["peak_is_rate"] = api_shaped and bool(PEAK_RATE_RX.search(req["project.description"] or ""))
    c["peak_capped_from"] = None
    if peak > users and not api_shaped:  # sized like an absent peak: users x the documented fraction, never all users at once
        c["peak_capped_from"] = peak
        peak, c["peak_cap_fraction"], c["peak_cap_why"] = costreal.derived_peak(users, req, req["project.type"])
        if users != req["scale.users_12_months"]:  # the basis is the larger of launch and 12-month users: say so instead of naming users_12_months
            c["peak_cap_why"] = c["peak_cap_why"].replace("of users_12_months", f"of the {users:,} users used for sizing")
    c["users"], c["peak"] = users, peak
    if users <= 5000 and peak <= 200:
        tier = 0
    elif users <= 50000 and peak <= 2000:
        tier = 1
    elif users <= 500000 and peak <= 20000:
        tier = 2
    else:
        tier = 3
    rps = req["scale.peak_rps"]
    c["rps_tier"] = None
    if rps is not None:  # an explicit request rate is better evidence than people counts
        c["rps_tier"] = 0 if rps <= 20 else 1 if rps <= 200 else 2 if rps <= 2000 else 3
        tier = max(tier, c["rps_tier"])
    c["tier"] = tier
    c["data_gb"] = req["scale.data_volume_gb_12_months"] if req["scale.data_volume_gb_12_months"] is not None else 5
    # planning heuristic: file or media storage is requested but the stated volume is 0 GB (contradictory): size and price for at least 1 GB and say so
    c["data_gb_floored"] = bool(req["requirements.file_media_storage"] and req["scale.data_volume_gb_12_months"] == 0)
    if c["data_gb_floored"]:
        c["data_gb"] = 1
    c["langs"] = lang_norm(req["team.languages"])
    c["hiring"] = [x for x in lang_norm(req["team.hiring_languages"]) if x not in c["langs"]]
    c["geo"] = req["scale.geo_spread"]
    # F13: continents the description says users are on; geo_spread 'global' or two or more -> users span continents
    c["continents"] = continents_in(req["project.description"])
    c["multi_continent"] = c["geo"] == "global" or len(c["continents"]) >= 2
    c["lock"] = req["infrastructure.lock_in_tolerance"]
    c["exp"] = req["team.experience"]
    c["xf"] = EXP_FACTOR[c["exp"]]
    c["lf"] = LANG_FACTOR[c["exp"]]
    c["devops"] = req["team.has_devops"]
    c["size"] = req["team.size"]
    c["weeks"] = req["timeline.mvp_weeks"]
    c["budget"] = req["budget.monthly_infra_usd"]
    c["cloud"] = req["infrastructure.cloud_preference"]
    c["deploy"] = req["infrastructure.deployment_model"]
    comp = req["compliance"]
    c["compliance"] = comp
    res = req["infrastructure.data_residency"]
    c["residency_from_rbi"] = False
    if res == "none" and "rbi_localisation" in comp:
        res = "india"
        c["residency_from_rbi"] = True
    c["residency"] = res
    # users are in India when data must stay there or Indian data-protection/payment rules apply (DPDP covers data of
    # people in India even without a residency requirement); drives Indian SMS and payment providers
    c["india_users"] = res == "india" or "dpdp" in comp or "rbi_localisation" in comp
    c["res_key"] = res if res in ("india", "eu", "us") else None
    # D12a: 'other' resolved from the extra field, else from one explicit residency sentence in the description
    c["country"] = c["country_path"] = c["country_sentence"] = None
    c["country_res"] = {"country": None, "sentence": None, "hints": [], "ambiguous": [], "conflict": []}
    if res == "other":
        r = c["country_res"] = residency_from_description(req["project.description"])
        rc = req.get("infrastructure.residency_country")
        stated = r["conflict"] or ([r["country"]] if r["country"] else [])
        if rc and any(x != rc for x in stated):
            r["conflict"] = [rc] + [x for x in stated if x != rc]
            r["conflict_field"] = True
        elif rc:
            c["country"], c["country_path"] = rc, "infrastructure.residency_country"
        elif r["country"]:
            c["country"], c["country_path"], c["country_sentence"] = r["country"], "project.description", r["sentence"]
    # Round 16: data_residency 'none' (or absent) while a D12a residency sentence in project.description states a
    # requirement. The stricter reading wins when the sentences name one supported jurisdiction (an enum-covered place such
    # as Germany -> eu, or one D12 country); a regional word ("Europe"), several places or an unsupported country keep
    # the field, and recommend.py only warns.
    c["res_stated"] = None
    if res == "none":
        r = residency_from_description(req["project.description"])
        if r["stated"]:
            vals = list(dict.fromkeys(v for v, _ in r["enum"]))
            pin, sent = None, r["stated"][0]
            if r["country"] and not vals and not r["unsupported"]:
                pin, sent = r["country"], r["sentence"]
                c["country"], c["country_path"], c["country_sentence"] = pin, "project.description", sent
            elif len(vals) == 1 and not (r["country"] or r["conflict"] or r["ambiguous"] or r["unsupported"]):
                pin, sent = vals[0], r["enum"][0][1]
                res = c["residency"] = c["res_key"] = pin
                c["india_users"] = c["india_users"] or pin == "india"
            c["res_stated"] = {"sentence": sent, "pin": pin, "ambiguous": r["ambiguous"] or r["conflict"],
                               "enum": vals, "unsupported": r["unsupported"]}
    if c["country"]:
        c["residency"] = c["res_key"] = c["country"]
    c["res_label"] = COUNTRIES[c["country"]][0] if c["country"] else (c["residency"] or "").upper()
    # a named jurisdiction (india/eu/us or a resolved 'other'); rbi-derived India stays separate as before
    c["res_named"] = res in ("india", "eu", "us") or bool(c["country"])
    c["res_paths"] = ["infrastructure.data_residency"] + ([c["country_path"]] if c["country"] else [])
    if c["residency_from_rbi"]:  # M1: data_residency is "none"; the region is pinned by the compliance entry, so that is the input to cite
        c["res_paths"][0] = "compliance"
    if c["res_stated"] and c["res_stated"]["pin"] and not c["country"]:
        c["res_paths"].append("project.description")
    if c["res_stated"] and c["res_stated"]["pin"] and req["infrastructure.data_residency"] == "none":  # n1: the sentence, not the neutral field, pinned the region
        c["res_paths"] = [x for x in c["res_paths"] if x != "infrastructure.data_residency"]
    c["self_host_only"] = c["deploy"] in ("on_premise", "air_gapped")
    c["no_internet"] = c["deploy"] == "air_gapped"
    c["prio"] = {k: req[f"priorities.{k}"] for k in ("cost", "time_to_market", "scalability", "performance",
                                                       "maintainability", "security")}
    flags, prim = desc_signals(req["project.description"] or "")
    desc = (req["project.description"] or "").lower()
    # p5 item 5: readers are anonymous and only staff sign in: sign-in is sized for the staff, not the audience
    c["staff_login_n"] = None if req["project.type"] in ("ecommerce", "marketplace") else staff_login_count(desc)
    # the description only promotes a language team.languages already lists; it never adds one
    c["desc"], c["primary_langs"] = dict(flags), [x for x in prim if x in c["langs"]]
    # A1: a web3 word that only a stakeholder asks for ("the CTO wants blockchain receipts") or a hype word frames is not a requirement
    # (only where the decline also fires: a large project keeps what its stakeholders asked for)
    if c["desc"]["web3"] and c["tier"] <= ov.THRESHOLDS["decline_max_tier"] and ov.web3_only_requested(req["project.description"], req["project.type"]):
        c["desc"]["web3"] = False
    c["team_frameworks"] = list(team_frameworks(req["project.description"] or "", tuple(c["langs"])))  # A4
    ex = []
    sentences = re.split(r"(?<=[.!?;])\s+|\n", desc)
    for raw in req["infrastructure.existing_systems"]:
        low = f" {raw.lower()} "
        hit = next((pat for pat in TECH["existing_patterns"] if word_rx(pat["match"]).search(low)), None)
        if hit and hit["kind"] == "collaboration" and _MS_SELF_HOSTED.search(low):
            hit = None  # self-hosted release: never the Microsoft 365 / Graph profile
        hit = hit or fallback_pattern(raw, low)
        if hit and hit["kind"] == "social_login" and not social_login_counts(req, hit, raw):
            hit = fallback_pattern(raw, low)
        norm = lifecycle_text(low)
        lifes = lifecycle_hits(norm)
        life = lifes[0] if lifes else None
        if life and life.get("discontinued") and life["eol"] <= AS_OF:
            hit = None  # h1: a retired service cannot be integrated with, whatever product family its name resembles ("MongoDB Atlas Device Sync")
        old_ver = None if life else old_version_hit(norm)
        # "must stay": in the entry itself, or in a description sentence that names the same system (its patterns, or the
        # product's first word: 'Keep the Oracle database' names 'Oracle 19c')
        name_rx = None
        if hit:
            name_rx = r"(?<![a-z0-9])(?:" + "|".join(hit["match"] + ([re.escape(hit["product"].split()[0].lower())] if hit.get("product") and not hit.get("synthetic") else [])) + r")(?![a-z0-9])"
        keep = "infrastructure.existing_systems" if keep_in_entry(low) else "project.description" if hit and any(
            keep_in_text(name_rx, s) for s in sentences) else None
        if (not keep and hit and hit["kind"] == "database" and not moved_in_text(name_rx, sentences) and not re.search(NO_TOUCH_RX, desc.lower())
                and (write_in_text(name_rx, low, entry=True) or any(write_in_text(name_rx, s) for s in sentences))):
            keep, keep_write = ("infrastructure.existing_systems" if write_in_text(name_rx, low, entry=True) else "project.description"), True
        else:
            keep_write = False
        # a tenant described only as workforce/staff identity is not a customer login directory
        workforce = bool(re.search(r"\b(?:workforce|employees?|staff)\b", low)) and not re.search(
            r"\b(?:customers?|consumers?|ciam|b2c|external|partners?|public)\b", low)
        onprem = "on-prem" in low or "on prem" in low or "onprem" in low or "on-premises" in low
        if hit and hit.get("synthetic"):  # read by keyword: a mainframe, or a system that must stay and is not said to be a cloud service, is estate to bridge to
            onprem = onprem or "mainframe" in low or bool(keep and not _CLOUD_WORDS.search(low))
        # A7: an entry the knowledge base does not know by name is integrated by what the description does with it
        adapter = None if hit or life else ig.infer(raw, req["project.description"])
        # A3: the input says the system is going away (entry text, or a description clause that names it): its integration is a
        # one-off read, then retirement
        retire = False
        if not keep and (hit or life):
            if re.search(REMOVE_RX, low) and not re.search(STRONG_KEEP_RX, low):
                retire = True
            else:
                names = ([name_rx_plain(hit)] if hit else []) + ([life_rx(life)] if life else [])
                retire = any(removal_in_text(n, lifecycle_text(s)) for n in names for s in sentences)
        ex.append({"raw": raw, "pattern": hit, "life": life, "life_more": lifes[1:], "old_ver": old_ver, "keep": keep, "keep_write": keep_write, "onprem": onprem, "workforce": workforce,
                   "retire": retire, "adapter": adapter})
    # list-order invariance: knowledge-base pattern order (identity, databases, brokers, ...), then keyword categories
    # (knowledge-base order), then name; unrecognised last
    order = {id(p): i for i, p in enumerate(TECH["existing_patterns"])}
    cats = {fb["category"]: len(order) + i for i, fb in enumerate(TECH["existing_fallback"])}
    ex.sort(key=lambda e: (order[id(e["pattern"])] if e["pattern"] and id(e["pattern"]) in order
                           else cats[e["pattern"]["category"]] if e["pattern"] else len(order) + len(cats), e["raw"]))
    c["existing"] = ex
    c["existing_langs"] = existing_langs(req["infrastructure.existing_systems"])

    def of_kind(kind):  # every recognised system of a kind, the ones the input says must stay first (then list order above)
        return sorted((e for e in ex if e["pattern"] and e["pattern"]["kind"] == kind), key=lambda e: not e["keep"])
    dbs = of_kind("database")
    c["existing_db"] = dbs[0] if dbs else None
    # a database the input says must stay (system of record) is reused as THE database, not integrated beside a new one
    c["kept_db"] = c["existing_db"] if c["existing_db"] and c["existing_db"]["keep"] else None
    c["other_kept_dbs"] = [e for e in dbs[1:] if e["keep"]]
    queues, idps = of_kind("queue"), of_kind("identity")
    c["existing_queue"] = queues[0] if queues else None
    c["queue_transport"] = bool(queues and re.search(ig.QUEUE_VIA_RX, desc))  # A7: the description reaches another system through the broker
    c["existing_idp"] = idps[0] if idps else None
    c["unused_existing"] = {"identity provider": idps[1:], "message broker": queues[1:]}
    c["idp_customer_login"] = bool(c["existing_idp"] and c["existing_idp"]["pattern"].get("customer_login")
                                   and not c["existing_idp"]["workforce"])
    # A16: social sign-in providers the input names (existing_systems, in list order); the auth text lists them before the defaults
    c["social_named"] = [e["pattern"]["name"] for e in ex if e["pattern"] and e["pattern"]["kind"] == "social_login"]
    c["ms_idp"] = bool(c["existing_idp"] and c["existing_idp"]["pattern"].get("vendor") == "microsoft")
    c["existing_m365"] = next((e for e in ex if e["pattern"] and e["pattern"]["kind"] == "collaboration"), None)
    r = req
    typ = r["project.type"]
    c["type"] = typ
    # D16: payments that are a hosted button/link, or editorial content under a generic type, do not need a backend
    c["static_rule"] = ov.static_override(c)
    # q5: media the site owner publishes (audio, images, video, downloads on a content site with no sign-in) is static content behind the
    # CDN, not a reason for a backend; media that visitors upload still is (ov.published_media reads the fields and the description)
    c["published_media"] = ov.published_media(c)
    dynamic_need = (r["requirements.auth"] != "none" or (r["requirements.payments"] and c["static_rule"] != "hosted_payments")
                    or r["requirements.realtime"]
                    or (r["requirements.file_media_storage"] and not c["published_media"]) or r["requirements.multi_tenant"]
                    or r["requirements.ml_features"] != "none"  # offline alone: a static site precaches (services.py)
                    or c["api_only"] or bool(c["mobile"]))
    # A2: a desktop-only app with no server need is local-first (embedded database on the device), never a static site
    dynamic_need = dynamic_need or lf.needs_server(c)  # a desktop app that shares data or talks to a server is not local-first (and not a static site)
    c["local_first"] = lf.applies(c, dynamic_need)
    c["needs_backend"] = dynamic_need or (typ in DYNAMIC_TYPES and not c["static_rule"] and not c["local_first"])
    c["needs_db"] = c["needs_backend"]
    c["static_search"] = (not c["needs_backend"]) and r["requirements.full_text_search"]
    return c
