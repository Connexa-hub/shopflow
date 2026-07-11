# Build Phases

Each phase must build, pass tests, and be documented before the next begins.

- [x] Phase 0 — Monorepo scaffold, shared configuration package
- [x] Phase 1 — `auth-service`: multi-tenant users, JWT, RBAC, Docker
- [ ] Phase 2 — `packages/database` core models + `inventory-service`
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
