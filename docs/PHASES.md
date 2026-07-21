# Build Phases

Each phase must build, pass tests, and be documented before the next begins.

- [x] Phase 0 — Monorepo scaffold, shared configuration package
- [x] Phase 1 — `auth-service`: multi-tenant users, JWT, RBAC, Docker
- [x] Phase 2 — `packages/database` core + `inventory-service` (catalog + stock ledger)
- [x] Phase 3 — `sales-service` (POS transaction engine, receipts) + inventory-service batch extensions
- [x] Phase 4 — `payment-service` (Paystack/Flutterwave/Monnify adapters)
- [ ] Phase 5 — `sync-service` (offline-first sync + conflict resolution)
- [ ] Phase 6 — `merchant-app` mobile skeleton wired to auth-service
- [ ] Phase 7 — `customer-app`, `admin-app` (platform owner mobile app)
- [ ] Phase 8 — `analytics-service`, `ai-service`, `notification-service`
- [ ] Phase 9 — Merchant branding/theming engine end-to-end
- [ ] Phase 10 — CI/CD, staging deploy (Render/Railway + Supabase + Cloudflare)

## Phase 1 decisions

**Multi-tenancy model:** Shared database, shared schema, `business_id` on
every tenant-scoped table, enforced via SQLAlchemy mixin + repository layer
(not just app-level filtering) so future Postgres RLS policies can be added
without a data model change.

**Auth model:** JWT access + refresh tokens. Access token carries
`user_id`, `business_id`, `role`, and `permissions` claims so downstream
services can authorize without calling back into `auth-service` on every
request. Refresh tokens are stored hashed in Postgres and are revocable
(needed for staff offboarding — a real requirement for shops with turnover).

**RBAC roles (v1):** `platform_owner`, `business_owner`, `manager`,
`cashier`, `staff`. Permissions are a separate table so new roles/permissions
can be added without code changes — franchise businesses will need custom
roles later.

## Phase 2 decisions

**`packages/database` — per-service isolated metadata.** Exports a
`create_base()` *factory*, not a shared `Base` instance. SQLAlchemy ties
`MetaData` to the specific declarative base class — sharing one instance
across services would mean every service's models register into the same
metadata registry, and Alembic autogenerate for one service would see (and
try to manage) another service's tables. Each service calls
`Base = create_base()` once and gets its own isolated registry. (Caught
during Phase 2 self-review before shipping — the first draft exported a
singleton `Base`, which would have quietly broken this isolation the
moment a second service imported it.)

**No SQLAlchemy `relationship()` declarations in inventory-service models.**
In async SQLAlchemy, lazily accessing an unloaded relationship attribute
raises `MissingGreenlet` unless the query explicitly eager-loaded it via
`selectinload`/`joinedload`. Rather than requiring every future contributor
to remember that rule at every call site, inventory-service's repositories
join explicitly and return plain tuples instead — fewer footguns, and every
query's cost is visible at the call site.

**Stock quantity updates are a single atomic `UPDATE ... SET quantity =
quantity + delta`,** not a `SELECT ... FOR UPDATE` followed by an `UPDATE`
in Python. An UPDATE statement takes a row lock for the duration of the
transaction on every mainstream SQL backend, same as an explicit
`FOR UPDATE` would, but in one round-trip instead of two and with no
dialect-specific locking syntax to get wrong — `FOR UPDATE` support and
semantics vary enough across backends (notably SQLite, used in this test
suite) that avoiding it entirely removes a whole class of
"works on Postgres, breaks in CI" bugs. Documented limitation: the
insufficient-stock *check* reads quantity and computes the prospective
result before issuing that UPDATE, so it's optimistic, not pessimistic —
under heavy concurrent load two simultaneous sales could both pass the
check against a stale read. The ledger itself stays internally consistent
either way (every movement recorded, every `resulting_quantity` accurate);
only the negative-stock guard has a narrow race window.

**Every stock movement is preceded by an ownership check** — see "Bugs
found and fixed" below.

### Bugs found and fixed during Phase 2 self-review

Documenting these rather than quietly patching them, since the fixes
change public method signatures other services will eventually call:

1. **Cross-tenant stock read/write.** `StockService` accepted `product_id`
   and `location_id` directly and used them to read or write stock without
   ever checking they belonged to the caller's `business_id`. A valid
   token from Business A could read or write Business B's stock by UUID.
   Fixed by injecting `ProductRepository`/`LocationRepository` into
   `StockService` and verifying ownership of both IDs before every
   operation, read or write (`get_current_quantity`, `record_movement` and
   all its wrappers, `list_movements`). New exception
   `InvalidStockReferenceError` → HTTP 404, deliberately not distinguishing
   "doesn't exist" from "not yours" in the message, same reasoning as auth
   returning one generic invalid-credentials error.
2. **Two routes had no tenant scoping at all.** `GET /stock/level` and
   `GET /stock/movements` didn't even accept a `business_id` — any
   authenticated user from any business could query stock levels and full
   movement history for any product/location UUID in the system. Fixed
   alongside (1); both routes now require `BusinessContext`.
3. **Same class of bug in the product catalog.** `ProductService.
   create_product`/`update_product` accepted `category_id`/`supplier_id`
   without checking they belonged to the same business as the product.
   Fixed the same way: `ProductService` now takes `CategoryRepository`/
   `SupplierRepository` and verifies both before assigning them. New
   exception `InvalidProductReferenceError` → HTTP 400.

Regression tests were added for all three (`TestTenantIsolation` in
`test_stock_service.py`, `TestCrossTenantIsolationThroughAPI` in
`test_inventory_api.py`, `TestCategoryAndSupplierOwnership` in
`test_product_service.py`) specifically so these can't silently regress.

### Bugs found and fixed after Phase 3 shipped (CI round-trips)

1. **`passlib`/`bcrypt>=4.0` incompatibility** (auth-service). passlib's
   bcrypt backend reads `bcrypt.__about__.__version__` to detect the
   installed version — a submodule `bcrypt>=4.0` removed entirely.
   Without it, passlib's internal self-calibration test crashes before
   ever touching a real password. passlib is effectively unmaintained;
   fixed by calling `bcrypt` directly instead of pinning to an older,
   unverifiable-from-here bcrypt version.

2. **Cross-service atomicity was contingent on caller session discipline,
   not a property of the method itself** (inventory-service +
   sales-service). `record_batch_sale`/`record_batch_return`/`transfer`/
   `record_movement` only committed once at the end, but never explicitly
   rolled back on failure — relying on the caller to discard the session.
   That's true for a real FastAPI request (fresh session per request,
   discarded on any unhandled exception) but not guaranteed for any other
   caller (a Celery worker reusing a session, or simply a test that shares
   one session across a whole test case — which is exactly how this was
   caught). Fixed by explicit `try/except: rollback(); raise` in all four
   methods, and the equivalent local-persistence-failure branches in
   sales-service's `create_sale`/`void_sale`.

3. **That same rollback fix exposed a real SQLAlchemy async gotcha in the
   test suite itself**: `Session.rollback()` unconditionally expires
   every object in the session's identity map (a safety measure — after a
   rollback, previously-loaded attribute values may no longer be valid).
   Four tests that reuse a fixture ORM object's `.id` attribute *after* a
   call that triggers this rollback hit `MissingGreenlet`, because async
   SQLAlchemy can't silently perform the resulting implicit reload outside
   an explicit `await`. This is a test-design issue, not a production bug
   — real route handlers only ever work with plain UUIDs parsed from the
   request body, never a lingering ORM object reference, so they never
   hit this. Fixed by capturing `.id` values as plain variables before any
   risky call in the four affected tests, which is also just better test
   hygiene independent of this specific bug. Traced every `pytest.raises`
   block in the file against this pattern before concluding these four
   were the only ones affected.

4. **`sales-service`'s `create_sale`/`void_sale` rollback branches are
   currently untested**, flagged honestly rather than left silent: both
   only run when a *local* DB write fails after the *remote* inventory
   call already succeeded, and the current test suite's fault injection
   (`FakeInventoryClient.fail_batch_sale_with` etc.) only targets the
   remote side. Forcing a clean local-DB-failure scenario needs fault
   injection at the repository layer, which doesn't exist yet — worth
   building before this code path is trusted in production, not before.

### Operational note: shared JWT secret across services

`auth-service` and every downstream service (`inventory-service`,
`sales-service`, and every future one) must be configured with the
**exact same** `JWT_SECRET_KEY`. Downstream services verify tokens locally
rather than calling auth-service per-request (see Phase 1's auth model),
which only works if all services agree on the signing secret. In
`docker-compose.yml` this means every service's `.env` needs the same
value — there's no automatic sync, so a fresh `openssl rand -hex 32`
copy-pasted into only one service's `.env` will produce confusing "Invalid
or expired token" errors on every cross-service request. Worth a
shared-secrets-manager approach (e.g. Doppler, or Postgres-stored config)
before this goes past a handful of services; noted as a Phase 10
(deployment hardening) follow-up.

## Phase 3 decisions

**First real service-to-service integration.** sales-service never touches
inventory-service's database — it calls inventory-service's HTTP API,
forwarding the cashier's own bearer token rather than minting a separate
service-account credential. inventory-service already gated
`/stock/batch-sale` behind `SALES_CREATE` and `/stock/batch-return`/`/stock/
return` behind `SALES_REFUND` specifically for this (a Phase 2 decision
paying off now) — a cashier's token naturally has the right permissions
for their own actions, enforced exactly as if they'd called inventory-
service directly. This stops being sufficient the moment something needs
to call inventory-service without a live user request in flight (a
scheduled job, a webhook) — noted in `inventory_client.py` rather than
silently assumed to generalize.

**inventory-service gained three endpoints this phase**, extending a
previously-shipped service rather than duplicating its logic:
- `POST /products/batch` — authoritative current price/name lookup for a
  whole checkout in one round trip. sales-service NEVER trusts a client-
  supplied price; it fetches current data fresh and computes totals
  server-side.
- `POST /stock/batch-sale` / `POST /stock/batch-return` — atomic multi-item
  stock deduction/restoration. A multi-item checkout must never partially
  apply (sell items 1-2, discover item 3 is out of stock, leave 1-2
  already deducted). Implemented by extracting a no-commit `_apply_movement`
  core from `record_movement` and committing once at the end of a whole
  batch — which also fixed a latent bug in `transfer()`, which previously
  committed each leg independently via two separate `record_movement`
  calls and was NOT actually atomic across its two legs.
- `POST /stock/return` — wires up `MovementType.RETURN`, defined in
  Phase 2's enum but never exposed through any method until voiding a sale
  needed it.

**Snapshotting.** `SaleItem` stores `sku`, `product_name`, and `unit_price`
as they were at the moment of sale, not a live reference to inventory-
service's current product data — a receipt printed a year from now must
show what was actually sold, even if the product was renamed, repriced, or
deleted since. Same reasoning e-commerce order-line-items use industry-wide.

**Cross-service failure ordering.** Both `create_sale` and `void_sale` call
inventory-service (the remote system of record for stock) BEFORE writing
anything locally. "Sale recorded, stock never deducted" silently corrupts
a merchant's inventory count in a way that's nearly impossible to detect
later; "stock deducted, no local sale row" is at least detectable by
cross-referencing inventory-service's movement `reference_id`s against
sales-service's sale IDs. Known, stated-plainly limitation: there is no
true distributed transaction across the two services' separate databases.
If the remote deduction succeeds but the local DB write then fails,
`create_sale` makes a best-effort *compensating* call to reverse the
deduction before re-raising — which can itself fail. Building a reliable
retry/outbox mechanism is real distributed-systems work that deserves a
design informed by actual production failure data, not a guess made now;
a future sync-service/reconciliation job (Phase 5 territory) is the honest
long-term fix.

**Testability of the cross-service dependency.** `SaleService` depends on
`InventoryClientProtocol`, not the concrete HTTP client — the same
Repository Pattern already used for the database, applied to an external
service dependency. Tests substitute an in-memory `FakeInventoryClient`
(`tests/fakes.py`) so the business logic — including the compensating-
reversal-on-local-failure path — is verified without a live
inventory-service process.

**Known duplication, flagged rather than silently repeated a third time
without comment.** sales-service's `app/core/security.py` is now the
*third* copy of the same ~50-line JWT-verification module (auth-service
issues tokens; inventory-service and sales-service both verify them
identically). Worth extracting into `packages/auth` — it exists as an
empty placeholder in the monorepo already — now that three occurrences
confirm the pattern is stable. Deliberately NOT done as an unplanned
mid-phase refactor touching two already-shipped, green services; flagged
here for prioritization instead.

### Bug fixed mid-phase: passlib/bcrypt incompatibility (auth-service)

See item 1 under "Bugs found and fixed after Phase 3 shipped" above — not
a Phase 3 design decision, but fixed during this phase after a real CI
failure. Hashing/verification behavior is otherwise identical from every
caller's perspective; the fix only changed what happens underneath
`hash_password`/`verify_password`.

## Phase 3 fix: MissingGreenlet in inventory-service's test suite

Documented separately from the rest because it's a genuinely interesting
async SQLAlchemy gotcha, not a design decision: the same commit that fixed
the rollback-on-failure gap above caused four tests to fail with
`sqlalchemy.exc.MissingGreenlet`. `Session.rollback()` unconditionally
expires every object in the session's identity map (a safety measure —
after a rollback, previously-loaded attribute values may no longer be
valid). Tests that reuse a fixture ORM object's `.id` attribute *after* a
call that triggers this rollback hit the error, because async SQLAlchemy
can't silently perform the resulting implicit reload outside an explicit
`await`. Not a production bug — real route handlers only ever work with
plain UUIDs parsed from the request body, never a lingering ORM reference.
Fixed by capturing `.id` values as plain variables before any risky call
in the four affected tests. Every `pytest.raises` block in the file was
traced against this pattern before concluding these four were the only
ones at risk.

## Phase 4 decisions

**Adapter pattern, verified against current docs, not solely training
data.** Payment provider API details — endpoint paths, field names,
webhook signature schemes — are exactly the kind of thing that drifts, and
getting one wrong silently mishandles real money. Before writing
`app/providers/{paystack,flutterwave,monnify}.py`, each provider's current
documentation was searched and (for the two most load-bearing details —
Flutterwave's webhook signature scheme and Monnify's endpoint paths)
fetched directly, rather than trusting recollection. Two genuine
uncertainties surfaced and are flagged in code comments rather than
asserted with false confidence:
- Flutterwave's **own current docs page** is internally inconsistent — the
  prose describes HMAC-SHA256 verification, but the runnable code examples
  further down the same page do a plain string comparison with no HMAC at
  all. Implemented the HMAC approach (the more secure, explicitly-described
  mechanism) but this should be confirmed against a real dashboard + live
  test webhook before trusting it in production.
- Monnify's exact webhook HMAC algorithm and its transaction-status
  endpoint's exact reference parameter (their `transactionReference` vs.
  our `paymentReference`) couldn't be confirmed with full certainty during
  research. Implemented with the most likely answer (matching Paystack's
  pattern) but flagged for verification before going live.

**payment-service is for *provider-mediated* payments only** — online
checkout links, wallet top-ups, invoice payments — a different concern
from sales-service's `SalePayment.method` (cash/card/credit recorded
directly at the POS, settled via physical hardware, no provider API
involved). A sale paid for online would use `purpose=SALE_PAYMENT` with
`related_sale_id` set, linking the two records without either service
reaching into the other's database.

**Idempotent webhook handling**, not just "check the transaction's current
status": every provider explicitly retries on non-200 responses, and
Flutterwave's own docs warn a single legitimate event can be delivered
more than once. `WebhookEvent` rows are keyed by `(provider,
provider_event_key)` and checked *before* any processing — a retried or
duplicate delivery is recognized and acknowledged with 200 without
re-running anything, rather than relying solely on `PaymentTransaction`'s
status already being terminal (which would still work for "already
succeeded," but wouldn't distinguish a legitimate duplicate from a
malformed retry worth investigating).

**Rollback-on-failure applied from the start**, not rediscovered a third
time: every write-then-commit method explicitly rolls back on an
unhandled exception, following the pattern already fixed in
inventory-service and sales-service this same day.

**Fourth identical copy of the JWT-verification module.** Three
occurrences was flagged as worth extracting into `packages/auth`; four
is past the point where deferring further is reasonable. This should be
the first thing done at the start of Phase 5, before a fifth copy exists.

**Two bugs found via my own test-writing, not a reported CI failure**:
`webhook_routes.py` didn't catch `PaymentValidationError` at all (an
unconfigured provider named in the webhook URL would have crashed with a
raw 500 instead of a clean 400) — caught while writing the "unconfigured
provider" test, before it ever reached CI. The same gap existed in the
`/verify` route for the same reason (a provider disabled after a
transaction was created against it). Both fixed before this phase shipped.

**Known gap, flagged rather than silently left untested**:
`initialize_payment`'s failure-after-provider-success path (the provider
transaction now exists with no local record) has no automated test, for
the same reason sales-service's equivalent gap doesn't — forcing a clean
local-DB-failure scenario needs fault injection at the repository layer
that doesn't exist yet. A reconciliation job comparing each provider's
recent transactions against local records is the honest long-term fix,
and is Phase 5+ territory once sync-service exists.

## `packages/auth` extraction (between Phase 4 and Phase 5)

Extracted the JWT-verification/RBAC module that had accumulated three
near-identical copies (inventory-service, sales-service, payment-service —
auth-service is structurally different, since it issues tokens rather
than verifying them, and keeps its own security.py for hashing/issuance).

**Factories, not a shared settings instance.** Every service has its own
`Settings` class and `get_settings()` — there's no single shared config
object to import. `packages/auth` exports `create_principal_dependency(get_settings)`,
`create_permission_checker(...)`, and `create_business_context_dependency(...)`;
each service calls these once at import time with its own `get_settings`,
binding the shared logic to its own JWT secret/algorithm. Same reasoning
as `packages/database`'s `create_base()` factory for the same underlying
issue — no shared state that would let one service's config leak into
another's.

**Every existing route file was left untouched.** Each service's own
`app/core/security.py` became a thin wiring file re-exporting the exact
same names (`Principal`, `BusinessContext`, `require_permission`, and
`CurrentPrincipal` for sales-service specifically) that route files
already imported — checked via a repo-wide grep for every
`from app.core.security import ...` line before writing a single line of
the new package, specifically so this refactor wouldn't need to touch
route files at all.

**`Principal.raw_token`** is now populated uniformly for every service
(not conditionally), even though only sales-service actually uses it
(forwarding a cashier's token to inventory-service). Simpler than making
it conditional per-service, and harmless for services that never read it.

Verified via real editable-installs across all 8 packages/services after
the migration, plus an isolated exec-based test of the actual
`Principal.has_permission()` logic (extracting just that class from the
file and running it directly, since `fastapi`/`jose` can't be installed
in this sandbox) rather than only a syntax check — the full JWT decode
path through `jose` itself still needs a real CI run to confirm, same
limitation as everything else built in this sandbox.
