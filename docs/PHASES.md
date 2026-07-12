# Build Phases

Each phase must build, pass tests, and be documented before the next begins.

- [x] Phase 0 — Monorepo scaffold, shared configuration package
- [x] Phase 1 — `auth-service`: multi-tenant users, JWT, RBAC, Docker
- [x] Phase 2 — `packages/database` core + `inventory-service` (catalog + stock ledger)
- [ ] Phase 3 — `sales-service` (POS transaction engine, receipts)
- [ ] Phase 4 — `payment-service` (Paystack/Flutterwave/Monnify adapters)
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
only the negative-stock guard has a narrow race window. Flagged as a
Phase 3+ follow-up once `sales-service` exists and real concurrent load
patterns are known, rather than guessed at now.

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

### Operational note: shared JWT secret across services

`auth-service` and `inventory-service` (and every future service) must be
configured with the **exact same** `JWT_SECRET_KEY`. inventory-service
verifies tokens locally rather than calling auth-service per-request (see
Phase 1's auth model), which only works if both services agree on the
signing secret. In `docker-compose.yml` this means both `.env` files need
the same value — there's no automatic sync, so a fresh `openssl rand -hex
32` copy-pasted into only one service's `.env` will produce confusing
"Invalid or expired token" errors on every cross-service request. Worth a
shared-secrets-manager approach (e.g. Doppler, or Postgres-stored config)
before this goes past a handful of services; noted as a Phase 10
(deployment hardening) follow-up.
