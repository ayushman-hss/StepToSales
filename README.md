# StepToSales

[![codecov](https://codecov.io/github/ayushman-hss/StepToSale/graph/badge.svg?token=JQS7H5KRVD)](https://codecov.io/github/ayushman-hss/StepToSale)

**Retail analytics for small neighbourhood shops.**

StepToSales is a retail intelligence platform built around a simple question:

> **Are you above the line?**

For a small shop, that question can mean very different things:

- Are enough of the people entering the shop actually buying?
- Which products are naturally bought together?
- Can nearby shops combine demand to unlock better wholesale prices?

StepToSales turns ordinary retail data into actionable answers across all three, and then keeps watching the shop's day as it happens, messaging the owner's phone when an hour goes slow or the day falls behind.

Built with **Python + FastAPI + PostgreSQL** on the backend and **React + TypeScript + Vite** on the frontend, shipped as one Docker image.

## Live demo

**https://steptosales.onrender.com**

| Username | Password | Shop |
|---|---|---|
| `s1` | `s1shop` | S1, residential kirana |
| `s2` | `s2shop` | S2, station kiosk |
| `s3` | `s3shop` | S3, pool-only shop (no sales data) |

A quick tour:

1. Log in as `s2`, open **Sales vs footfall** and pick **Today**. The shop is trading live, and a live strip appears above the charts.
2. In the live strip, set **Demo day** to *Slow* and the speed to **60×**. Within about a minute the next hour ends and a *Slow hour* alert appears under **Phone alerts** (linked from the strip).
3. On **Phone alerts**, type a question into *Ask about your shop*, e.g. *what sold most today?* or *aaj kitna becha*.
4. Tap **Open the till** (`/pos`) on a phone, logged in as the same shop, and ring up a bill. It shows on the dashboard within seconds.

The demo runs on Render's free plan: after 15 minutes without visitors it sleeps, and the first visit then takes about a minute to wake it. See [Hosting](#hosting).

---

## What StepToSales does

StepToSales contains three retail analytics tools, plus a live layer on top of them:

| | Question it answers | Where |
|---|---|---|
| **1. Sales vs Footfall** | People are coming in. Are they buying? | Sales vs footfall |
| **2. Bundles** | What do customers already buy together? | Bundles |
| **3. Group Buying** | Can nearby shops get a better wholesale price together? | Group buying |
| **4. Live mode** | How is today going, right now? | Sales vs footfall → Today, the till |
| **5. Phone alerts & questions** | Tell me when something needs attention, and answer my questions in plain words. | Phone alerts, Telegram |

### 1. Sales vs Footfall

**"People are coming in. Are they actually buying?"**

The dashboard combines hourly visitor counts with actual transactions and sales to calculate:

- Conversion rate
- Average basket value
- Hourly sales patterns
- Footfall patterns
- Day-of-week behaviour
- Concentration of visitors into peak hours

Instead of only showing charts, the system turns the numbers into simple observations such as:

> **18:00 is your busiest hour, but conversion is 12% vs 21% average.**

or:

> **62% of your footfall happens in 3 hours.**

These observations can be forwarded as a WhatsApp-ready message.

The important distinction is that **footfall and sales are treated as different signals**.

A POS system knows who bought something.

It does not know how many people walked past the counter, entered the shop and left without buying.

StepToSales therefore models footfall separately and uses it to expose opportunities that sales data alone cannot show.

---

### 2. Bundles

**"What are my customers already buying together?"**

StepToSales analyses transaction line items using **market-basket analysis**.

It looks for product pairs that occur together more frequently than would be expected by chance.

For each suggested bundle, the system shows:

- How frequently the products appear together
- Association strength
- Lift over random co-occurrence
- A suggested bundle price
- The resulting margin

The pricing engine also respects a configurable **minimum margin floor**.

So the system does not simply say:

> "These two products sell together."

It can instead answer:

> "These products are already commonly purchased together. Here is a bundle price that preserves your required margin."

The merchant remains in control:

**Approve → Edit → Reject**

Nothing is automatically applied.

---

### 3. Group Buying

**"Can neighbouring shops combine demand to get a better wholesale price?"**

Small retailers often cannot reach supplier volume tiers individually.

For example:

| Quantity | Supplier price |
|---:|---:|
| 1–19 kg | ₹45/kg |
| 20–49 kg | ₹40/kg |
| 50+ kg | ₹35/kg |

Suppose:

- Shop S1 needs 15 kg
- Shop S2 needs 20 kg

Individually:

- S1 pays ₹45/kg
- S2 pays ₹40/kg

Together they need **35 kg**, crossing the ₹40/kg tier.

The technical problem then becomes:

> **How should the resulting saving be divided?**

StepToSales calculates multiple allocation methods, including:

- Flat unit price
- Pro-rata allocation
- Shapley allocation

The important part is not simply reaching a cheaper supplier tier.

It is producing a settlement where:

- every shop's payable amount is explicit,
- the allocation rule is deterministic,
- the totals reconcile exactly,
- and the supplier invoice is fully accounted for.

Every state transition is also recorded in an append-only event log, allowing a pool to be reconstructed instead of relying entirely on mutable state.

---

### 4. Live mode

**"How is today going, right now?"**

The first three tools look back at history. Live mode keeps each shop trading while the app runs: visitors arrive, some of them buy, and the dashboard's **Today** view moves every couple of seconds.

The simulated day is learned from the shop's own last eight weeks, so it lands inside that shop's usual range. The dashboard shows:

- pace against a usual same weekday, by the same time of day,
- likely takings by closing,
- the hour in progress against its usual,
- a band showing the usual range of cumulative sales, with today's line gliding along it.

A speed control (Pause, Real time, 10×, 60×, 300×) runs a whole day in minutes for a demo, and a **Demo day** switch makes the rest of the day *Slow* or *Busy* on demand. A phone **till** (`/pos`) rings up real bills into the same stream.

Details in [7. Live mode](#7-live-mode).

---

### 5. Phone alerts and questions

**"Tell me when something needs my attention."**

A shopkeeper is behind the counter, not in front of a dashboard. StepToSales watches each shop's day and sends a Telegram message when:

- an hour is **slow** (far fewer visitors than usual, or far fewer of them buying, and it says which),
- an hour is **busy**,
- the day is well **behind** or **ahead** of a usual one,
- the day is over (a **summary**),
- and, if the owner opts in, after **every hour**.

The owner can also just ask, in English or everyday Hinglish: *how much did I sell today?*, *what sold most this week?*, *aaj kitna becha*, *how can I improve sales?* The answers come from the shop's own numbers, compared like with like.

The assistant is **rule-based and runs entirely on the server**. No AI service is called, so neither the questions nor the shop's figures leave it.

Details in [8. Phone alerts (Telegram)](#8-phone-alerts-telegram).

---

# Architecture

StepToSales separates the user interface, API layer, retail analytics, group-buying domain logic, the live layer and persistence.

![StepToSales system architecture](docs/architecture.png)

*Architecture diagram generated from the repository structure using GitDiagram. It predates live mode and phone alerts; the request flow below is current.*

### Request flow

```text
Store Operator (browser, phone till)
      │
      ▼
React Application
      │
      ▼
Typed API Client
      │
      ▼
FastAPI Routes
      │
      ├──────────────────────┬──────────────────────┐
      ▼                      ▼                      ▼
Retail Analytics        Group Buying           Live layer
      │                      │                      │
      ├── Metrics            ├── Price Tiers        ├── Simulator
      ├── Insights           ├── Money Arithmetic   ├── Event engine
      ├── Associations       └── Savings            ├── Pace
      ├── Pricing                Allocation         └── Background runner
      └── Bundles                                          │
              │                                            ▼
              ▼                                 Alert watcher + Telegram bot
         PostgreSQL                                        │
                                                    ├── Alert rules
                                                    └── Assistant (plain questions)
                                                           │
                                                           ▼
                                                  Shop owner's phone
```

The live runner and the alert watcher are background tasks inside the API process, so the whole app is one process and one database.

### Separation of responsibilities

**Frontend**

React pages handle the user-facing experience and communicate with the backend through a typed API client.

**API layer**

FastAPI routes expose application capabilities without putting the business logic directly inside HTTP handlers.

**Retail analytics**

The analytics layer contains independent services for metrics, insights, market-basket associations, bundle pricing and bundle generation.

**Group-buying domain**

Group buying has a separate domain layer responsible for tier calculations, money arithmetic and savings allocation. This keeps the financial rules independent from the HTTP/API layer.

**Live layer**

The simulator, the event engine (which records every visit and bill once and recomputes the hourly rollups from them) and the pace calculations live in `services/live`. The alert rules, the Telegram client and the watcher live in `services/alerts`; the plain-language assistant lives in `services/assistant`. None of them depends on FastAPI, so they are tested directly.

**Persistence**

PostgreSQL stores the retail and pooling models, while repositories handle persistence for the group-buying domain.

---

# The demo data simulation

A common problem with synthetic dashboards is:

> **Random numbers that happen to look like business data.**

StepToSales instead generates synthetic retail data using explicit behavioural assumptions.

This is **not claimed to be a statistically representative dataset of Indian retail**.

Instead, it is a controlled simulation designed around recognizable neighbourhood-retail behaviours so that the application has realistic-looking, reproducible data with known underlying patterns.

The generator currently models:

- Time of day
- Day of week
- Monthly salary cycle
- Store format
- Product mix
- Price sensitivity
- Basket sizes
- Product affinities
- Day-to-day variation

---

## How the simulation works

### Time of day

Stores have their own operating hours and peak periods.

A residential kirana and a station kiosk therefore do not receive identical traffic patterns.

Peak hours are weighted more heavily rather than being the only hours in which purchases occur.

---

### Day of week

The two simulated stores behave differently across the week.

The residential kirana becomes busier towards the weekend, while the station kiosk is heavily dependent on weekday commuter traffic.

This creates different weekly demand patterns between stores instead of applying one generic distribution everywhere.

---

### Monthly salary cycle

The kirana receives an additional demand boost around the beginning of the month.

The generator also increases quantities of staple products during this period, representing household restocking behaviour.

The station kiosk deliberately does not receive the same salary-cycle effect.

---

### Store format

The stores have different product mixes.

**Residential kirana**

- Foodgrains, oil and masala
- Dairy and bakery products
- Snacks
- Beverages
- Cleaning and household products
- Beauty and hygiene products

**Station kiosk**

- Snacks
- Drinks
- Biscuits
- Quick bakery purchases

The kiosk has very little simulated demand for products such as rice or detergent because its shopping context is based around quick grab-and-go purchases.

---

### Price sensitivity

Products are not sampled with equal probability.

The generator uses a price-weighting model:

```text
purchase weight ∝ price^(-elasticity)
```

Different categories have different elasticity values.

Everyday necessities therefore experience a weaker price effect, while discretionary products are more sensitive to price.

This prevents an expensive product from unrealistically outselling low-cost everyday goods simply because both were assigned the same random probability.

The station kiosk also has a higher price-sensitivity factor because its purchases are modelled as smaller, more discretionary impulse purchases.

---

### Basket sizes

Customers do not always buy one product.

Different store formats use different basket-size distributions.

The kirana therefore produces more multi-item household baskets, while the station kiosk produces a much larger share of single-item purchases.

---

### Product affinities

Multi-item baskets are not simply random combinations.

The generator defines category-level relationships such as:

- Snacks + beverages
- Biscuits + dairy
- Bread + beverages
- Oil + masala
- Household staples + cleaning products
- Personal-care combinations

A subset of these relationships becomes **signature pairings** that occur more frequently than the rest.

The strongest pairing is sampled more frequently than weaker pairings, creating a long-tail distribution of co-purchases instead of making every possible product combination equally likely.

This gives the market-basket engine meaningful associations to discover.

---
## Why didn't you just use random numbers?

"Random numbers don't reflect real retail behavior. By modeling salary cycles, store profiles, and price elasticity, our market-basket analysis and footfall models actually have meaningful patterns to detect."

## Why this simulation is useful

The generator creates a controlled dataset where several independent signals interact:

```text
Store format
     │
     ├── Product catalogue
     │
     ├── Customer behaviour
     │
     ├── Time-of-day patterns
     │
     ├── Day-of-week patterns
     │
     ├── Monthly salary cycle
     │
     ├── Price sensitivity
     │
     ├── Basket size
     │
     └── Product affinities
             │
             ▼
       Synthetic transactions
             │
       ┌─────┴─────┐
       ▼           ▼
   Sales data   Footfall model
       │           │
       └─────┬─────┘
             ▼
       StepToSales analytics
```

This is particularly useful for a demo because the dataset has **known underlying behaviour**.

For example:

- The generator intentionally creates stronger snack + beverage relationships.
- The kirana and station kiosk have intentionally different demand patterns.
- Monthly demand changes are intentionally introduced for the kirana.
- Product purchase frequencies are influenced by price.
- Basket sizes vary according to store format.

This makes the demo reproducible while still giving the analytics system non-uniform patterns to discover.

---

## What is deliberately not simulated yet

The current generator does **not** attempt to model every factor affecting real retail demand.

In particular:

- Weather
- Festivals and holidays
- Promotions
- Competitor pricing
- Stock-outs
- Local events
- Individual customer demographics

are currently outside the simulation.

Weather and festival effects are intended to be introduced as separate inputs rather than hidden inside the existing randomisation.

---

# Sales and footfall are separate signals

The transaction generator creates the **actual sales history**.

The footfall generator then reads that history and derives:

- Transaction count
- Sales

directly from the sale lines, while modelling **only the missing variable: visitors**.

This prevents an important class of demo inconsistency:

> The dashboard cannot claim that 100 transactions happened while the transaction dataset contains only 80.

Transactions and sales are therefore grounded in the same underlying sales data.

Footfall is then generated around those transactions according to each store's conversion profile.

For example:

```text
Residential kirana
        │
        ▼
Higher purchase intent
        │
        ▼
Higher conversion
        │
        ▼
Moderate footfall
```

while:

```text
Station kiosk
        │
        ▼
Large passing crowd
        │
        ▼
Lower purchase intent
        │
        ▼
High footfall + lower conversion
```

This produces two stores that behave differently for a reason rather than because one happened to receive a larger random number.

---

# Data generation pipeline

The demo dataset is generated in two stages.

### Stage 1 — Transaction generation

```text
Product catalogue
       +
Store profile
       +
Behavioural rules
       ↓
sales_lines_S1.xlsx
sales_lines_S2.xlsx
```

The transaction generator creates approximately twelve weeks of history, ending at the current time.

Each sale line contains:

```text
date
hour
transaction_id
sku
qty
unit_price
```

The current day is truncated at the present moment so the demo does not contain future transactions.

---

### Stage 2 — Footfall generation

The footfall generator reads the transaction history and aggregates it by:

```text
date + hour
```

It then models visitors using each store's conversion profile.

The result is:

```text
sample-data.xlsx
```

containing:

```text
date
hour
footfall
transactions
sales
store_id
```

This means the dashboard's transaction and sales values originate from the same underlying sales lines used by the bundle engine.

---

# Why the numbers are trustworthy

Retail analytics becomes useless if the numbers do not reconcile.

StepToSales therefore treats financial correctness as a first-class concern.

### Integer money

Money is represented in **integer paise** rather than floating-point currency values.

This prevents rounding errors from silently entering settlements.

### Exact allocation

Discounts and savings are allocated using the **largest-remainder method**.

The resulting amounts are asserted to sum exactly to the required total.

If the books do not balance, the settlement fails instead of returning an apparently valid but incorrect result.

### Rotating remainder

When two shops have identical claims, the leftover paisa does not permanently go to the same shop.

The pool cycle affects the tie-breaking position so repeated pools do not systematically favour one participant.

### Versioned supplier prices

Supplier price lists are versioned.

A closed pool records the exact price-list version used during settlement.

Changing a supplier's prices later therefore cannot rewrite the financial history of an already-closed pool.

---

# Tech stack

### Backend

- Python 3.11+
- FastAPI
- SQLModel
- PostgreSQL
- Alembic
- Pytest
- Pandas
- Telegram Bot API (through the standard library, no bot framework)

### Frontend

- React 19
- TypeScript
- Vite
- Tailwind CSS
- Zustand (state)
- ECharts

### Hosting

- Docker (one image: the API serves the built website)
- Render (blueprint in `render.yaml`)

### Analytics

- Rule-based retail insights
- Hourly/daily aggregation
- Market-basket association analysis
- Margin-floor pricing
- Tiered supplier pricing
- Pro-rata allocation
- Shapley allocation
- Pace against a usual weekday, by the same time of day
- Alert rules for slow and busy hours and the day's pace
- Rule-based English and Hinglish question parsing

The current analytics do **not require machine learning**, and nothing is sent to an outside AI service.

---

# Project structure

```text
StepToSales/
│
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI application; starts the live runner and
│   │   │                        alert watcher, serves the built website
│   │   ├── config.py            Settings from environment / backend/.env
│   │   ├── dependencies.py      Login check shared by every shop route
│   │   ├── models.py            Retail, login, live and alert SQLModel tables
│   │   ├── models_pooling.py    Group-buying SQLModel tables
│   │   ├── live.py              The one live runner for this process
│   │   ├── alerts.py            The one alert watcher and Telegram bot
│   │   │
│   │   ├── routers/
│   │   │   ├── auth.py          Login, logout and "who am I"
│   │   │   ├── dashboard.py     Dashboard API routes (with today's live pace)
│   │   │   ├── bundles.py       Bundle API routes
│   │   │   ├── products.py      Product API routes
│   │   │   ├── pools.py         Group-buying API routes
│   │   │   ├── live.py          Live status, speed, demo day and the till
│   │   │   ├── alerts.py        Phone alerts: connect Telegram, list alerts
│   │   │   └── assistant.py     "Ask about your shop"
│   │   │
│   │   └── services/
│   │       ├── auth.py          Password hashing and sessions
│   │       ├── metrics.py       Hourly/daily/heatmap aggregates
│   │       ├── insights.py      Rule-based business observations
│   │       ├── associations.py  Market-basket analysis
│   │       ├── pricing.py       Margin-floor bundle pricing
│   │       ├── bundles.py       Bundle generation
│   │       ├── pooling/         Group-buying domain logic
│   │       ├── live/            Simulator, event engine, pace, background runner
│   │       ├── alerts/          Alert rules, Telegram client, watcher and bot
│   │       └── assistant/       Plain-language question parsing and answers
│   │
│   ├── alembic/                 Database migrations
│   ├── scripts/
│   │   ├── generate_bundle_sample.py
│   │   ├── generate_sample.py
│   │   ├── create_user.py       Add a shop login or reset its password
│   │   ├── demo_pool.py         Walk through a group-buying pool on the console
│   │   ├── reset_demo.py        Rebuild the demo data and logins
│   │   ├── boot.py              Container start: seed an empty database or migrate
│   │   └── start.sh             Container entry point
│   │
│   └── tests/                   Backend tests
│
├── frontend/
│   └── src/
│       ├── pages/               Dashboard, Products, Bundles, Group buying,
│       │                        Till, Phone alerts, Login
│       ├── components/          Feature-specific components (live panel, ask box...)
│       ├── lib/
│       │   ├── ui/              Design system
│       │   └── charts/          ECharts configuration
│       ├── api.ts               Typed API client (adds the login token)
│       ├── auth.ts              Who is logged in
│       └── store.ts             Dashboard filter state
│
├── docs/
│   └── architecture.png         System architecture diagram
│
├── Dockerfile                   One image: builds the website, runs the API
├── render.yaml                  Render blueprint (web service + Postgres)
├── docker-compose.yaml          Local PostgreSQL
├── start.bat                    One-click local start on Windows
└── README.md
```

---

# Running locally

## Prerequisites

- Python 3.11+
- Node.js 20.19+ (22 recommended; Vite 8 needs it)
- PostgreSQL 15+
- Docker (optional)

---

## Quick start on Windows: `start.bat`

Once the one-time setup below is done (PostgreSQL running, `backend\.venv`
created and `backend\.env` filled in), double-click **`start.bat`** in the
repository root. It:

1. stops anything still running from last time,
2. runs `alembic upgrade head`,
3. resets the demo data (`start.bat keep` keeps today's live data instead),
4. installs the frontend packages on the first run,
5. starts the API and the website in their own windows,
6. opens Chrome at `http://localhost:5173/login`.

To stop, close the *StepToSales API* and *StepToSales Web* windows. The steps
below are the same thing by hand, for any OS.

---

## 1. Start PostgreSQL

Using Docker:

```bash
docker compose up -d db
```

Or create the database manually:

```sql
CREATE USER footfall WITH PASSWORD 'footfall' LOGIN;
CREATE DATABASE footfall OWNER footfall;

\c footfall

GRANT ALL ON SCHEMA public TO footfall;
ALTER SCHEMA public OWNER TO footfall;
```

The schema permissions are important for PostgreSQL 15+ because otherwise Alembic may fail with:

```text
permission denied for schema public
```

---

## 2. Set up the backend

```bash
cd backend

python -m venv .venv
```

### Windows

```powershell
.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the environment file (the example lives in the repository root; the
app reads `backend/.env`):

```bash
cp ../.env.example .env
```

On Windows PowerShell: `Copy-Item ..\.env.example .env`.

Update `DATABASE_URL` if necessary, and add `TELEGRAM_BOT_TOKEN` if you want
phone alerts (see [8. Phone alerts](#8-phone-alerts-telegram)).

If you'll run the tests, install the test tools too:
`pip install -r requirements-dev.txt`.

Run migrations:

```bash
alembic upgrade head
```

---

## 3. Generate the demo data

```bash
python scripts/reset_demo.py
```

The reset process regenerates the coherent demo dataset used by the application.

The transaction generator creates the historical sale lines first, after which the footfall dataset is generated from those sales.

---

## 4. Start the API

```bash
uvicorn app.main:app --reload --port 8000
```

API documentation:

```text
http://localhost:8000/docs
```

---

## 5. Start the frontend

In another terminal:

```bash
cd frontend

npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

---

## 6. Log in

Every page with a shop's numbers needs a login, and each login belongs to one
shop: it sees that shop's dashboard, products and bundles and nobody else's.
The group-buying pool is shared, but a shop can only order or withdraw for
itself.

`reset_demo.py` creates one login per shop:

| Username | Shop | Password |
|---|---|---|
| `s1` | S1, residential kirana | `s1shop` |
| `s2` | S2, station kiosk | `s2shop` |
| `s3` | S3, pool-only shop (no sales data) | `s3shop` |

Usernames are not case-sensitive, so `S1` works too. Re-running
`reset_demo.py` resets these and logs everyone out.

To add a real login (8+ character password), or reset a password (which also
signs that login out):

```bash
cd backend
python scripts/create_user.py S1 ramesh
```

Sessions last 7 days. The browser keeps a random token; the database keeps
only its SHA-256 and a PBKDF2 hash of the password. In `/docs`, use
**Authorize** with a token from `POST /api/auth/login` to try the protected
routes.

---

## 7. Live mode

While the API runs, every shop with history keeps trading in the background:
visitors arrive, some buy, and the dashboard's **Today** view refreshes every
few seconds. Nothing to start separately.

- **The simulator learns from the shop's own history.** Visitors per weekday
  and hour, the chance of buying in each hour, and whole baskets at the prices
  actually paid all come from the last 8 weeks. So today lands inside the
  usual range for that weekday, and bundle suggestions keep seeing the same
  pairings.
- **Speed control on the dashboard**: Pause, Real time, 10×, 60×, 300×.
  Fast-forward runs the shop's clock ahead of real time and stops at
  midnight. Back at Real time, the shop waits for the real clock to catch up.
- **Demo day** (in the live strip): *Usual*, *Slow* or *Busy* for the rest of
  the simulated day, to show the phone alerts for a bad or a good day on
  demand.
- **Till** (`/pos`, *Open the till* in the live strip): log in on a phone as the same shop, tap products, ring
  up. The bill is priced from that shop's price list and appears on the
  dashboard within seconds. Every bill also counts one visitor.
- **How today is going**: pace against a usual weekday (finished hours only),
  likely takings by closing, the hour in progress, and a band showing the
  usual range of cumulative sales. An alert appears when far fewer visitors
  than usual bought in the last hour.
- **It still reconciles.** Every event is stored once in `live_event`
  (retries are ignored by `event_id`). The live rows in `hourly_data` and
  `sale_line` are recomputed from those events, so all three agree to the
  paisa.
- **Times are IST**, whatever the server's own timezone.
- **After downtime** (a restart or a redeploy), each shop catches up from
  where its data ends, up to 7 days back.

Settings (in `backend/.env`):

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_SIMULATOR` | `true` | Run the background simulator. Run it in **one** API process only. |
| `LIVE_SEED` | `steptosales` | Same seed, same sequence of simulated events. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins, for a separately hosted frontend. |

To use the till from a phone on the same Wi-Fi, run `npm run dev -- --host`
and open the address Vite prints for your network.

`reset_demo.py` also clears live events. Restart the API after running it.

---

## 8. Phone alerts (Telegram)

The API watches every shop's day and messages its phone when something is
worth knowing:

- **Slow hour**: in the hour that just ended, far fewer people came in than
  usual (60% or less), or far fewer of them bought (under 60% of the usual
  share, with at least 8 visitors). Says which, because the fixes differ.
- **Busy hour**: the hour took at least 1.5× its usual, with 5 or more bills.
- **Behind pace** / **Strong day**: the day is 25% behind or 20% ahead of a
  usual weekday, once a quarter of a usual day's takings should be in. Once a
  day each.
- **Day's summary**: after the shop's usual closing time: takings against a
  usual day, bills and visitors, the best hour.
- **Hourly updates** (opt-in per chat): a short line after every trading
  hour, with the day so far.

At most one hourly message per hour. An ordinary day stays quiet on purpose.

Every alert is listed on the **Phone alerts** page (`/alerts`, linked from the
live strip on the dashboard), sent or not. With a Telegram bot set up, each
one is also sent to every chat connected to that shop.

**Seeing it in a demo.** The live strip has a **Demo day** switch: *Usual*,
*Slow* (half the visitors, under half the buying) or *Busy* (1.7× visitors,
more buying). Pick Slow or Busy, then 60×: the next hour that ends sends a
Slow hour or Busy hour alert, about a minute later.

**Set up the bot (once, about two minutes):**

1. In Telegram, message **@BotFather**, send `/newbot`, and pick a name and a
   username ending in `bot`.
2. Put the token it gives you in `backend/.env`:

   ```text
   TELEGRAM_BOT_TOKEN=123456789:AA...
   ```

3. Restart the backend (or run `start.bat` again).

**Connect a phone:** log in as the shop, open **Phone alerts**, tap **Connect
Telegram** and press **Start** in the chat that opens. On another phone, send
the bot the `/start <code>` shown on the page; the code works once, for 15
minutes. A group works too: add the bot to the group and send the same
`/start <code>` there. In the chat:

- `/status`: how today is going, right now, and the last hour.
- `/hourly`: hourly updates on or off (also a tick box on the page).
- `/stop`: stop alerts to that chat.
- `/help`: the list. Typing `/` in the chat shows the same menu.

**Ask it anything, in plain words.** Any message that isn't a command is a
question about the shop, answered from its own data. The same assistant is on
the Phone alerts page (*Ask about your shop*), so it can be tried without
Telegram. It understands English and everyday Hinglish, for example:

- *How much did I sell today?* / *aaj kitna becha* / *kal ki sale*
- *What sold most this week?* / *which products are not selling?*
- *How many people came in yesterday evening?* / *sales between 5 and 8 pm*
- *How many Maggi today?* / *paneer vs butter this week* / *price of tea*
- *Compare today with yesterday* / *how are sales compared to last week?*
- *Busiest hour?* / *which day is slow?* / *when should I run an offer?*
- *Profit last week* / *average bill yesterday* / *biggest bill today*
- *How can I improve sales?* (tips built from the shop's own numbers)

Periods it knows: today, yesterday, a weekday, a date (*25 Sept*, *25/9*), a
month name, this/last week or month, *last 7 days*; and parts of the day
(morning, evening, *at 6pm*, *between 10 and 12*). Every figure is compared
like with like: today so far against a usual same weekday *by the same time*,
a week against the week before.

It is rule-based and runs entirely on the server (`services/assistant/`):
no AI service is called, so neither the questions nor the shop's figures
leave it, and it costs nothing to run. The trade-off is that an unusual
wording gets a list of example questions instead of an answer.

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(empty)* | From @BotFather. Empty: alerts are listed on the page but not sent. |
| `ALERTS_ENABLED` | `true` | Run the alert watcher. Like the simulator, in **one** API process only. |

A bot can only be read by one running copy of the app. If the laptop and a
hosted copy both use the same token, the page shows a warning; give each its
own bot. `reset_demo.py` clears the alert list (so the day raises them again)
but keeps connected chats.

---

# Hosting

The app ships as **one Docker image**: the website is built into it and the
API serves it, so one service with one address is the whole app, with no
CORS to set up. It needs a Postgres database and a host that keeps **one**
process running (the live simulator and the Telegram bot live in it).

On start the container runs `scripts/boot.py`: an empty database gets the demo
data (once, on the first start); an existing one gets `alembic upgrade head`.
Redeploys and restarts keep today's live trading, alerts and connected phones.

## Render (free, about 10 minutes)

`render.yaml` describes the whole setup: a free web service and a free
Postgres database, both in Singapore. The live demo at
[steptosales.onrender.com](https://steptosales.onrender.com) is deployed this
way from `main`.

1. Push the branch you want to host to GitHub (Render builds from GitHub, and
   redeploys on every push to that branch).
2. On [render.com](https://render.com), sign in with GitHub, then
   **New → Blueprint**, pick this repository and the branch (`main`), enter
   `render.yaml` as the blueprint path, **Apply**.
3. When it asks for `TELEGRAM_BOT_TOKEN`, paste the bot's token, or leave it
   empty to run without phone alerts.
4. Wait for the first build (a few minutes). The address is shown at the top
   of the service page, e.g. `https://steptosales.onrender.com`. Log in with
   the demo logins (`s1`/`s1shop`, `s2`/`s2shop`).

Free plan limits, so a demo isn't surprised by them:

- **It sleeps after 15 minutes without visitors**, and the first visit then
  takes about a minute. While asleep there is no simulated trading and no
  Telegram; on waking, each shop catches up on the missed hours. To keep it
  awake for a demo day, point a free uptime checker (UptimeRobot,
  cron-job.org) at `https://<your-address>/api/health` every 10 minutes.
- **750 free instance hours a month**, shared by all free services in the
  workspace. Kept awake all month, one service uses nearly all of them; past
  the limit it is suspended until the month ends. Render may also restart a
  free service at any time (the shops then catch up, as after any restart).
- **The free database expires after 30 days**, with a 14-day grace period
  before it is deleted. It has a 1 GB limit and no backups. Upgrade it, or
  point `DATABASE_URL` at another Postgres (for example a Neon or Supabase
  free database) before then; `boot.py` loads the demo data into the new one.
- **Only one copy may use a bot token.** While the hosted app has the token,
  remove `TELEGRAM_BOT_TOKEN` from your laptop's `backend/.env` (or give the
  laptop its own bot), otherwise the two fight over the bot's messages.

If a build fails, the error is at the end of the deploy's log; the runtime
errors (a traceback, `live tick failed`, `alert check failed`) are under the
service's **Logs**.

For no sleeping, the paid Starter plan (or any host that runs a container
all the time, such as Railway, Fly.io or a small VM) works with the same image.

## Any other host

```bash
docker build -t steptosales .
docker run -p 8000:8000 -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e TELEGRAM_BOT_TOKEN=... steptosales
```

`DATABASE_URL` may be given as `postgres://`, `postgresql://` or
`postgresql+psycopg://`. The container listens on `$PORT` (default 8000) and
answers `GET /api/health` for health checks. Run exactly one instance.

---

# Testing

Run the backend test suite with:

```bash
cd backend

pip install -r requirements-dev.txt

python -m pytest tests/ -q
```

The current suite contains **450 tests** covering areas including:

- Supplier tiers
- Pool lifecycle
- Money calculations
- Allocation rules
- Settlement invariants
- Property-based checks
- Logins and shop isolation
- Live mode: the simulator, catching up after downtime, speed and demo day, reconciliation of live events with the hourly and sale-line tables
- Phone alerts: each rule, de-duplication, the Telegram link flow (with Telegram replaced by a fake)
- The assistant: English and Hinglish questions, periods, products and comparisons
- Hosting configuration (`DATABASE_URL` forms)

The tests use in-memory SQLite, so no database needs to be running.

One of the core financial invariants is:

```text
sum(all shop payables) == supplier invoice
```

If that invariant cannot be satisfied, the settlement should fail rather than produce an incorrect result.

---

# Current limitations

StepToSales is deliberately not pretending to be a complete retail ERP or payment platform.

The following areas are currently modelled at the domain layer but are not fully implemented in the UI/infrastructure.

### Payments

The system calculates exactly what each shop owes.

It does not collect the money.

### Supplier portal

Suppliers, price lists and tiered pricing are represented in the database and demo data.

There is currently no supplier-facing management interface.

### Multiple pools

The schema supports multiple pools.

The current interface focuses on one active pool for simplicity.

### Notifications

Shops get Telegram alerts about their day (see [Phone alerts](#8-phone-alerts-telegram)). Group buying does not use them yet: the pool event log records events such as:

```text
pool crossed a tier
pool approaching closure
```

but nothing sends them to the shops yet.

### Concurrency

Orders are validated before being written, but optimistic locking is not currently implemented.

Two shops committing simultaneously could therefore theoretically price against stale tier information.

### Live data is simulated

Live mode's visitors and most of its bills come from the simulator. The only real input is the phone till. There is no footfall sensor or POS integration yet.

### The assistant is rule-based

It understands the phrasings it was built for, in English and everyday Hinglish. An unusual wording gets a list of example questions instead of an answer. This is the price of keeping the shop's data on the server.

### One process, free hosting

The live simulator and the Telegram bot run inside the API process, so the app runs as exactly one instance. On Render's free plan that instance sleeps when nobody visits, and while it sleeps no alerts are sent.

### Synthetic data

The demo data is intentionally synthetic.

It is designed to reproduce plausible retail behaviours and provide reproducible test/demo conditions; it should **not** be interpreted as a statistically representative sample of Indian retail.

---

# Roadmap

Potential next steps include:

- Real weather data integration
- Official holiday/festival calendars
- Promotion-aware demand simulation
- Supplier-facing portal
- Multi-pool management
- Group-buying notifications (Telegram is already in place for shop alerts)
- Optimistic concurrency control
- Real POS integrations
- Real supplier integrations
- More sophisticated demand forecasting
- Historical price changes
- Stock-out modelling

---

# What makes the project interesting

StepToSales is not just a dashboard showing sales charts.

The three analytics features operate at different levels of the same retail problem:

```text
                    RETAIL DECISIONS
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
   CUSTOMER FLOW      CUSTOMER BASKETS   PURCHASING POWER
        │                 │                 │
        ▼                 ▼                 ▼
     Footfall          Bundles         Group Buying
        │                 │                 │
        ▼                 ▼                 ▼
   "Why aren't       "What can I      "Can we buy
    visitors          sell together?"   cheaper?"
    converting?"
```

The project therefore moves from:

**understanding demand → increasing basket value → reducing procurement cost.**

Live mode and phone alerts then take that analysis to where the shopkeeper actually is: behind the counter, with a phone, in the middle of the day.

---

# License

MIT
