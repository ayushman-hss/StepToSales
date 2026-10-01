"""Turn a shopkeeper's sentence into a question the shop's data can answer.

Rule-based on purpose: nothing leaves the server, it costs nothing, and every
answer can be traced to a rule. It understands plain English and the common
Hinglish a shopkeeper types ("aaj kitna becha", "kal ki sale"), with or
without punctuation and in any order.

A ``Query`` is what, when, which hours and which products:

    "what sold most yesterday evening"  -> TOP, yesterday, 16:00-20:00
    "how many maggi today"              -> PRODUCT (instant masala noodles), today
    "how can I improve sales"           -> ADVICE
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# ---- what is being asked ---------------------------------------------------

SUMMARY = "summary"
SALES = "sales"
BILLS = "bills"
VISITORS = "visitors"
CONVERSION = "conversion"
AVG_BILL = "avg_bill"
PROFIT = "profit"
TOP = "top"
BOTTOM = "bottom"
PRODUCT = "product"
PRICE = "price"
PEAK_HOUR = "peak_hour"
QUIET_HOUR = "quiet_hour"
BEST_DAY = "best_day"
STATUS = "status"
ADVICE = "advice"
BUNDLES = "bundles"
STOCK = "stock"
GREETING = "greeting"
THANKS = "thanks"
HELP = "help"
HOURLY_ON = "hourly_on"
HOURLY_OFF = "hourly_off"
STOP_ALERTS = "stop_alerts"
COMPARE = "compare"
OFFER = "offer"
OPENING = "opening"
BIG_BILL = "big_bill"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Period:
    #: "day", "range" or "all".
    kind: str
    start: date
    end: date
    #: How to say it: "today", "yesterday", "this week", "Mon 28 Sep".
    label: str
    #: For "this week"-style ranges, what to compare with ("last week").
    before_label: str | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class Query:
    text: str
    intents: list[str] = field(default_factory=list)
    period: Period | None = None
    #: [start, end) hours of the day, e.g. (16, 20) for "evening".
    hours: tuple[int, int] | None = None
    hours_label: str | None = None
    #: SKUs of products named in the question.
    products: list[str] = field(default_factory=list)
    #: For rankings: "qty", "revenue" or "profit"; and how many to list.
    rank_by: str = "qty"
    limit: int = 5
    #: "compare today with yesterday": the older period, set against ``period``.
    compare_to: Period | None = None

    @property
    def intent(self) -> str:
        return self.intents[0] if self.intents else UNKNOWN


# ---- text helpers ------------------------------------------------------------

def normalise(text: str) -> str:
    t = text.lower().replace("₹", " rs ").replace("’", "'")
    t = re.sub(r"(\d),(\d)", r"\1\2", t)             # 1,000 -> 1000
    t = re.sub(r"[^a-z0-9:/'%\-\s]", " ", t)
    t = re.sub(r"\b(today|yesterday|week|month|shop|store|day)'s\b", r"\1", t)
    t = t.replace("'s", "s").replace("'", "")        # what's -> whats
    return re.sub(r"\s+", " ", t).strip()


def _has(t: str, pattern: str) -> bool:
    return re.search(rf"\b(?:{pattern})\b", t) is not None


# ---- when ----------------------------------------------------------------------

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS["sept"] = 9
_WEEKDAYS = {
    "monday": 0, "mon": 0, "somvar": 0,
    "tuesday": 1, "tue": 1, "tues": 1, "mangalvar": 1,
    "wednesday": 2, "wed": 2, "budhvar": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "guruvar": 3,
    "friday": 4, "fri": 4, "shukravar": 4,
    "saturday": 5, "sat": 5, "shanivar": 5,
    "sunday": 6, "sun": 6, "ravivar": 6,
}


def _day_label(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _range(start: date, end: date, label: str, before: str | None = None) -> Period:
    return Period("range", start, end, label, before)


def _day(d: date, label: str) -> Period:
    return Period("day", d, d, label)


def parse_period(t: str, today: date) -> tuple[Period | None, str]:
    """The period named in ``t`` and ``t`` with that phrase removed."""
    rules: list[tuple[str, callable]] = [
        (r"day before yesterday|parso",
         lambda m: _day(today - timedelta(days=2), _day_label(today - timedelta(days=2)))),
        (r"yesterday|yday|kal|last night",
         lambda m: _day(today - timedelta(days=1), "yesterday")),
        (r"(?:last|past|previous|pichle)\s+(\d{1,3})\s+(?:days?|din)",
         lambda m: _range(today - timedelta(days=int(m.group(1)) - 1), today,
                          f"the last {int(m.group(1))} days",
                          f"the {int(m.group(1))} days before")),
        (r"(?:last|past|previous|pichle)\s+(\d{1,2})\s+weeks?",
         lambda m: _range(today - timedelta(days=7 * int(m.group(1)) - 1), today,
                          f"the last {int(m.group(1))} weeks",
                          f"the {int(m.group(1))} weeks before")),
        (r"this week|is (?:hafte|week)|week so far|week to date",
         lambda m: _range(today - timedelta(days=today.weekday()), today,
                          "this week", "last week by the same time")),
        (r"last week|previous week|pichle (?:hafte|week)",
         lambda m: _range(today - timedelta(days=today.weekday() + 7),
                          today - timedelta(days=today.weekday() + 1),
                          "last week", "the week before")),
        (r"this month|is mahine|month so far|month to date",
         lambda m: _range(today.replace(day=1), today, "this month",
                          "last month by the same day")),
        (r"last month|previous month|pichle mahine",
         lambda m: _last_month(today)),
        (r"(?:this |last )?weekend",
         lambda m: _weekend(today, m.group(0).startswith("last"))),
        (r"overall|all time|ever|since (?:the )?(?:start|beginning)|in total",
         lambda m: Period("all", date(2000, 1, 1), today, "overall")),
        (r"(\d{4})-(\d{2})-(\d{2})",
         lambda m: _date(today, int(m.group(3)), int(m.group(2)), int(m.group(1)))),
        (r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(_MONTHS) + r")[a-z]*",
         lambda m: _date(today, int(m.group(1)), _MONTHS[m.group(2)[:3]])),
        (r"(" + "|".join(_MONTHS) + r")[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?",
         lambda m: _date(today, int(m.group(2)), _MONTHS[m.group(1)[:3]])),
        (r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?",
         lambda m: _date(today, int(m.group(1)), int(m.group(2)),
                         int(m.group(3)) if m.group(3) else None)),
        (r"(?:in |for |during |of )?(january|february|march|april|may|june|july|august|"
         r"september|sept|october|november|december)(?!\s*\d)",
         lambda m: _month(today, m.group(1))),
        (r"(last |on |this |past )?(" + "|".join(_WEEKDAYS) + r")",
         lambda m: _weekday(today, _WEEKDAYS[m.group(2)], (m.group(1) or "").strip() in ("last", "past"))),
        (r"today|aaj|so far|right now|now|abhi|till now|tonight|this (?:morning|afternoon|evening)",
         lambda m: _day(today, "today")),
    ]
    for pattern, make in rules:
        m = re.search(rf"\b(?:{pattern})\b", t)
        if m:
            period = make(m)
            if period is not None:
                keep = m.group(0)
                # "this morning" is today *and* a time of day: leave it in.
                if keep == "tonight" or (keep.startswith("this ") and
                                         keep.split()[-1] in ("morning", "afternoon", "evening")):
                    return period, t
                return period, (t[:m.start()] + " " + t[m.end():]).strip()
    return None, t


def _last_month(today: date) -> Period:
    end = today.replace(day=1) - timedelta(days=1)
    return _range(end.replace(day=1), end, f"last month ({end:%B})", "the month before")


def _month(today: date, name: str) -> Period:
    month = _MONTHS[name[:3]]
    year = today.year if month <= today.month else today.year - 1
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    if start <= today <= end:
        return _range(start, today, "this month", "last month by the same day")
    return _range(start, end, start.strftime("%B"), "the month before")


def _weekend(today: date, last: bool) -> Period:
    if today.weekday() >= 5 and not last:
        sat = today - timedelta(days=today.weekday() - 5)
        return _range(sat, today, "this weekend", "last weekend")
    sat = today - timedelta(days=today.weekday() + 2)
    return _range(sat, sat + timedelta(days=1), "last weekend", "the weekend before")


def _weekday(today: date, wd: int, strictly_before: bool) -> Period:
    back = (today.weekday() - wd) % 7
    if back == 0 and strictly_before:
        back = 7
    d = today - timedelta(days=back)
    return _day(d, "today" if back == 0 else ("yesterday" if back == 1 else _day_label(d)))


def _date(today: date, day: int, month: int, year: int | None = None) -> Period | None:
    if year is not None and year < 100:
        year += 2000
    try:
        d = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and d > today:
        d = d.replace(year=d.year - 1)
    if d == today:
        return _day(d, "today")
    if d == today - timedelta(days=1):
        return _day(d, "yesterday")
    return _day(d, _day_label(d))


# ---- which hours -----------------------------------------------------------------

_PARTS = [
    (r"morning|subah", (6, 12), "in the morning"),
    (r"afternoon|dopahar|dopehar", (12, 16), "in the afternoon"),
    (r"evening|shaam|sham", (16, 20), "in the evening"),
    (r"night|tonight|raat", (20, 24), "at night"),
]


def _clock(h: int, suffix: str | None) -> int:
    if suffix == "pm" and h < 12:
        return h + 12
    if suffix == "am" and h == 12:
        return 0
    if suffix is None and 1 <= h <= 7:
        return h + 12            # a shop's "at 6" is 6 in the evening
    return h


def parse_hours(t: str) -> tuple[tuple[int, int] | None, str | None, str]:
    m = re.search(r"\b(?:between|from)\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?\s*(?:and|to|-|till|until)\s*"
                  r"(\d{1,2})(?::\d{2})?\s*(am|pm)?\b", t)
    if m:
        s2 = m.group(4)
        a = _clock(int(m.group(1)), m.group(2) or s2)
        b = _clock(int(m.group(3)), s2)
        if a < b <= 24:
            return (a, b), f"between {a}:00 and {b}:00", t[:m.start()] + t[m.end():]
    m = re.search(r"\b(?:at|around|by)?\s*(\d{1,2})(?::00)?\s*(am|pm|baje)\b", t) or \
        re.search(r"\b(\d{1,2}):00\b", t) or re.search(r"\bat (\d{1,2})\b", t)
    if m:
        suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        h = _clock(int(m.group(1)), None if suffix == "baje" else suffix)
        if 0 <= h <= 23:
            return (h, h + 1), f"at {h}:00", t[:m.start()] + t[m.end():]
    for pattern, span, label in _PARTS:
        if _has(t, pattern):
            return span, label, t
    return None, None, t


# ---- which products --------------------------------------------------------------

#: Everyday words for products whose catalogue names are supplier descriptions.
ALIASES = {
    r"maggi|maggie|masala noodles|instant noodles": "instant masala noodles",
    r"coke|pepsi|cola|thums up|cold ?drinks?|soda": "soft drink",
    r"diet coke|coke zero|zero sugar": "black soft drink",
    r"dahi|yogurt|yoghurt": "curd",
    r"chawal": "rice",
    r"tel|cooking oil": "mustard oil",
    r"sabun|soap": "bathing bar",
    r"perfume|scent": "parfum",
    r"chai": "tea",
    r"chips|wafers": "potato chips",
    r"detergent|surf": "washing powder",
    r"floor cleaner|phenyl": "floor cleaner",
    r"toilet cleaner|harpic": "toilet cleaner",
    r"cheese": "cheese slice",
    r"chocolates?|pralines?": "pralines",
    r"doodh": "milk",
}

#: Words that describe products but never identify one on their own.
_GENERIC = set("""
a an and the of for with from to in on or no not made premium fresh natural rich pure super
classic quality max taste zero sugar diet long gently rolled aromatic grand basics power gold
strength pack mix just heat ready eat indian dish authentic hygienic sticky used visible
cold liquid original complete thick high fibre breakfast evening morning sparkling
min refreshing pulse men farm pressed extracted minute instant goodness iron spices easy cook
nutritious dietary protein promotes system respiratory digestive stamina kills germs multipurpose
texture grainy whole enhances flavour aroma rich mixture relish chinese maida fried 100
""".split())

#: Words the question grammar uses; a product word that is also one of these
#: ("best", "top") is not read as a product.
_QUESTION_WORDS = set("""
how much many what which when who sold sell selling sale sales today yesterday week month
most best top least worst bill bills people visitors customers hour hours day days time
profit margin price cost average avg total number count bought buy came improve increase
did do does is was were are my i me the a of in on at by so far now
""".split())


@dataclass(frozen=True)
class CatalogueItem:
    sku: str
    name: str
    #: What a person would call it: "Butter", "Soft Drink", "Mustard Oil (Organic)".
    short: str


#: Catalogue name heads that describe rather than name the product.
_WEAK_HEADS = {"organic", "capsules", "tablets", "premium"}


def _clip(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def build_catalogue(products) -> list[CatalogueItem]:
    """Supplier names are descriptions ("Butter - Pasteurised"); keep the
    part a shopkeeper would say, and make it unique within the shop."""
    parts_of = {p.sku: [x.strip() for x in re.split(r"\s-\s|,", p.name) if x.strip()]
                for p in products}

    def head(parts: list[str], depth: int) -> str:
        if not parts:
            return ""
        first = parts[0]
        if first.lower() in _WEAK_HEADS and len(parts) > 1:
            first = f"{parts[1]} ({first})"
            parts = parts[1:]
        extra = parts[1:depth]
        return _clip(first + (f" ({', '.join(extra)})" if extra else ""), 48 if extra else 40)

    shorts = {sku: head(parts, 1) for sku, parts in parts_of.items()}
    seen: dict[str, int] = {}
    for v in shorts.values():
        seen[v] = seen.get(v, 0) + 1
    for sku, v in list(shorts.items()):
        if seen[v] > 1:
            shorts[sku] = head(parts_of[sku], 2) or v
    return [CatalogueItem(p.sku, p.name, shorts[p.sku] or p.name) for p in products]


def _match_text(item: CatalogueItem) -> str:
    """The words that name the product: the short name, unclipped."""
    parts = [x.strip() for x in re.split(r"\s-\s|,", item.name) if x.strip()]
    if not parts:
        return item.name
    if parts[0].lower() in _WEAK_HEADS and len(parts) > 1:
        return f"{parts[1]} {parts[0]}"
    return parts[0]


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def match_products(t: str, catalogue: list[CatalogueItem]) -> list[str]:
    """SKUs named in ``t``, best match first. Several when the name is shared
    ("noodles" is three products); none when nothing is named."""
    for pattern, canonical in ALIASES.items():
        t = re.sub(rf"\b(?:{pattern})\b", canonical, t)
    words = set(_tokens(t)) - _QUESTION_WORDS

    # How many products each identifying word appears in: "noodles" (3) says
    # less than "paneer" (1).
    index: dict[str, set[str]] = {}
    for item in catalogue:
        for w in set(_tokens(_match_text(item))) - _GENERIC:
            if len(w) >= 3:
                index.setdefault(w, set()).add(item.sku)
                if w.endswith("s") and len(w) > 4:          # "teas" also answers "tea"
                    index.setdefault(w[:-1], set()).add(item.sku)

    scores: dict[str, float] = {}
    for w in words:
        for sku in index.get(w, ()):
            scores[sku] = scores.get(sku, 0.0) + 1.0 / len(index[w])
    if not scores:
        return []
    # The whole short name written out ("soft drink", "tea") wins outright.
    for item in catalogue:
        if item.sku in scores and re.search(rf"\b{re.escape(_match_text(item).lower())}\b", t):
            scores[item.sku] += 0.75
    # Each word the shopkeeper wrote picks the product(s) it fits best, so
    # "paneer vs butter" finds both, and "green tea" does not also find "Tea".
    chosen: list[str] = []
    for w in words:
        holders = [sku for sku in index.get(w, ()) if sku in scores]
        if not holders:
            continue
        top = max(scores[sku] for sku in holders)
        for sku in sorted(holders, key=lambda k: -scores[k]):
            if scores[sku] >= top - 1e-9 and sku not in chosen:
                chosen.append(sku)
    return sorted(chosen, key=lambda k: (-scores[k], k))


# ---- what is being asked -----------------------------------------------------------

_HOUR_WORDS = r"hours?|time|times|when|kab|samay|baje|slot|timing"
# Days of the week in general -- not "was yesterday a good day", which is
# about one day.
_DAY_WORDS = (r"which days?|what days?|(?:best|busiest|busy|worst|quietest|quiet|slowest|slow|good|bad) days|"
              r"my (?:best|busiest|worst|quietest|slowest) day|days? (?:are|is) (?:slow|quiet|busy|best|good|bad)|"
              r"day of the week|weekdays?|days of the week|kaunsa din|kis din")
_PRODUCT_WORDS = r"products?|items?|things?|sku|skus|goods|selling|seller|sellers|sold|sell|sells|bik\w*|moving|maal|saman|samaan"


def parse(text: str, today: date, catalogue: list[CatalogueItem] | None = None) -> Query:
    t = normalise(text)
    q = Query(text=text)
    if not t:
        q.intents = [HELP]
        return q

    period, rest = parse_period(t, today)
    comparing = _has(t, r"compare\w*|vs|versus|than|against|difference|mukabla|muqabla")
    if period is not None:
        other, rest2 = parse_period(rest, today)
        if other is not None and other != period:
            newer, older = sorted([period, other], key=lambda p: (p.end, p.start), reverse=True)
            period, q.compare_to, rest = newer, older, rest2
            comparing = True
        elif comparing:
            # "sales compared to last week" means this week against last week.
            current = {"yesterday": ("day", today, today, "today"),
                       "last week": ("range", today - timedelta(days=today.weekday()), today,
                                     "this week"),
                       "last month": ("range", today.replace(day=1), today, "this month")}
            key = "last month" if period.label.startswith("last month") else period.label
            if key in current:
                q.compare_to = period
                period = Period(*current[key])
    q.period = period
    hours, hours_label, rest = parse_hours(rest)
    q.hours, q.hours_label = hours, hours_label
    m = re.search(r"\btop\s+(\d{1,2})\b", t)
    if m:
        q.limit = max(1, min(10, int(m.group(1))))
    if _has(t, r"revenue|money|earn\w*|value|rupees|rs|kamai|kamaya"):
        q.rank_by = "revenue"
    if _has(t, r"profit\w*|margin|munafa|fayda"):
        q.rank_by = "profit"
    q.products = match_products(rest, catalogue or [])

    intents: list[str] = []

    def add(*names: str) -> None:
        for n in names:
            if n not in intents:
                intents.append(n)

    short = len(t.split()) <= 4
    # Conversation, not data.
    if short and _has(t, r"hi+|hello|hey|namaste|namaskar|good (?:morning|afternoon|evening)|hola|salaam|yo|whats up|sup"):
        add(GREETING)
    if short and _has(t, r"thanks?|thank you|thx|ty|shukriya|dhanyavad|great|nice|cool|ok|okay|good job|awesome"):
        add(THANKS)
    if _has(t, r"help|what can you (?:do|answer|tell)|what (?:can|should) i ask|commands?|menu|options|"
               r"how (?:do i|to) use (?:you|this)|who are you|what are you|what is this|what do you do"):
        add(HELP)
    if _has(t, r"hourly|every hour|har ghante"):
        add(HOURLY_OFF if _has(t, r"off|stop|disable|no|band|dont|don't|mat") else HOURLY_ON)
    if _has(t, r"(?:stop|unsubscribe|mute|disable|band)\b.*\b(?:alerts?|messages?|notifications?)"):
        add(STOP_ALERTS)

    # Advice before metrics: "how can I increase sales" is not a sales figure.
    if _has(t, r"improve|increase|boost|grow|raise|badha\w*|sell more|more sales|more customers|tips?|"
               r"suggest\w*|advice|advise|recommend\w*|ideas?|what should i do|what (?:can|do) i do|"
               r"how (?:can|do|to|should) (?:i|we) (?:get|make|sell|earn|do better)|kya karu\w*|kya karein"):
        add(ADVICE)
    if _has(t, r"offers?|discounts?|promotions?|promo|deals?|schemes?") and not _has(t, r"bundles?|combos?"):
        add(OFFER)
    if _has(t, r"open (?:earlier|early|later|late|longer)|close (?:earlier|early|later|late)|"
               r"opening (?:time|hours?)|closing (?:time|hours?)|stay open|shop timings?|"
               r"when (?:should|to|do) (?:i |we )?(?:open|close)"):
        add(OPENING)
    if _has(t, r"(?:biggest|largest|highest|top|max\w*) (?:bill|sale|order|purchase|basket)s?"):
        add(BIG_BILL)

    hourish = _has(t, _HOUR_WORDS) or hours_label is not None and _has(t, r"when")
    if hourish and _has(t, r"busiest|busy|peak|rush|most|crowd\w*|bheed|highest|best|maximum|max|zyada"):
        add(PEAK_HOUR)
    if hourish and _has(t, r"quiet\w*|slow\w*|least|lowest|dead|empty|khali|worst|lean|kam|minimum"):
        add(QUIET_HOUR)
    if _has(t, _DAY_WORDS):
        add(BEST_DAY)

    about_products = _has(t, _PRODUCT_WORDS) or _has(t, r"top\s+\d+")
    ranking_up = _has(t, r"most|best|top|popular|highest|fast[- ]?moving|bestsell\w*|best-?sell\w*|"
                         r"sabse (?:zyada|jyada|jada)|zyada|maximum|max")
    ranking_down = _has(t, r"least|worst|lowest|slowest|slow[- ]?moving|not sell\w*|didnt sell|did not sell|"
                           r"no sales|kam bik\w*|sabse kam|dead stock|bottom|poorly|poor")
    if about_products and not hourish and not q.products and BIG_BILL not in intents:
        if ranking_down:
            add(BOTTOM)
        elif ranking_up:
            add(TOP)
    if _has(t, r"price|mrp|rate|daam|kitne ka|how much (?:is|are|does|do)\b.*\bcost|what does\b.*\bcost|"
               r"cost price|selling price|margin on") and q.products:
        add(PRICE)

    about_people = _has(t, r"people|customers?|visitors?|log|grahak|without buying|didnt buy|did not buy")
    if _has(t, r"stock|inventory|reorder|restock|running out|out of stock|khatam|order more|"
               r"left in stock|how much (?:do i|we) have") or (
            not about_people and
            _has(t, r"(?:how much|how many|kitna|kitne)\b.*\b(?:left|remaining|bacha)")):
        add(STOCK)
    if _has(t, r"bundles?|combos?|bought together|frequently bought|pairs?|cross[- ]?sell|"
               r"sold together|together"):
        add(BUNDLES)

    # How the day is going, as a whole.
    if _has(t, r"how(?:s| is| are| was)? (?:today|it|things|the day|business|my (?:day|shop|store|business)|"
               r"we doing|i doing|am i doing|are we doing|sales going)|how am i doing|how are we doing|"
               r"status|update|kaisa (?:chal|raha)|kya haal|on track|by closing|end of (?:the )?day|"
               r"projection|project\w*|forecast|expected|expect|will i (?:make|reach|hit)"):
        add(STATUS if (period is None or period.label == "today") else SUMMARY)
    if _has(t, r"summary|report|hisaab|hisab|overview|recap|how was|kaisa tha|kaisa gaya|"
               r"numbers|figures|stats|statistics|performance|kpis?|dashboard"):
        add(SUMMARY)

    # Figures.
    if _has(t, r"profit\w*|margin|munafa|fayda|gross|markup") and PRICE not in intents and not ranking_up:
        add(PROFIT)
    if _has(t, r"conversion|convert\w*|buying rate|buy rate|(?:percent|percentage|share|%)\b.*\b(?:bought|buy|purchased)|"
               r"how many of them bought|kitne ne kharida|out of"):
        add(CONVERSION)
    if _has(t, r"average (?:bill|basket|spend|sale|order|ticket|purchase|transaction)|avg (?:bill|basket|spend|sale|order)|"
               r"basket size|bill size|per (?:bill|customer|visitor|person)|ticket size|aov|average value"):
        add(AVG_BILL)
    visitors = _has(t, r"footfall|visitors?|visits?|visited|walk[- ]?ins?|walked in|foot traffic|"
                       r"(?:people|customers|log|grahak|anyone|someone)\b.*\b(?:came|come|visit\w*|walk\w*|"
                       r"entered|aaye|aye|aya|left)|kitne log|log aaye|crowd|bheed|"
                       r"without buying|didnt buy|did not buy")
    bills = _has(t, r"bills?|transactions?|orders?|receipts?|invoices?|purchases?|billed|"
                    r"(?:customers?|people|grahak)\b.*\b(?:bought|purchased|paid|kharida)|"
                    r"kitne (?:bill|grahak)") or (
        not visitors and _has(t, r"how many customers|kitne grahak|number of customers"))
    if visitors and PEAK_HOUR not in intents and QUIET_HOUR not in intents:
        add(VISITORS)
    if bills and AVG_BILL not in intents and PEAK_HOUR not in intents and BIG_BILL not in intents:
        add(BILLS)
    salesy = _has(t, r"sales|sale|sold|sell\w*|revenue|earn\w*|income|takings|turnover|collection|business|"
                     r"money|kitna|bech\w*|bikri|bik\w*|kamai|kamaya|galla|made|make|total")
    if q.products and PRICE not in intents and ADVICE not in intents and STOCK not in intents:
        add(PRODUCT)
    elif salesy and not intents:
        add(SALES)

    if q.compare_to is not None and not intents or (q.compare_to is not None and intents and
                                                     set(intents) <= {SALES, SUMMARY, BILLS, VISITORS}):
        intents = [COMPARE]
    # Advice is the question; "profit" or "customers" in it are what to improve.
    if ADVICE in intents:
        intents = [i for i in intents if i in (ADVICE, BUNDLES, GREETING, THANKS)]

    # "any combo suggestions?" is about bundles, not general advice.
    if BUNDLES in intents and ADVICE in intents and not _has(
            t, r"improve|increase|boost|grow|more sales|sell more|badha\w*|do better"):
        intents.remove(ADVICE)

    if not intents:
        if q.products:
            add(PRODUCT)
        elif period is not None or hours is not None:
            add(SUMMARY)
        else:
            add(UNKNOWN)
    q.intents = intents
    return q
