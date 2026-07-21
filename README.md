# ShopFlow — African Commerce Operating System

Monorepo for a multi-tenant commerce platform serving businesses from single
provision stores to multi-branch franchises.

## Status: Phase 4 complete — `payment-service` (Paystack/Flutterwave/Monnify), plus a `packages/auth` extraction

See `docs/PHASES.md` for the full build roadmap, architecture decisions,
and a documented list of bugs found and fixed during self-review. Notably:
every service that verifies JWTs locally (all of them, by design) must be
configured with the **same** `JWT_SECRET_KEY` — see the operational note
at the end of `docs/PHASES.md` before running more than one service.

## Repo layout

```
apps/        # merchant-app, customer-app, admin-app, mobile-app
services/    # api-gateway, auth-service, inventory-service, sales-service, ...
packages/    # shared code: database, auth, shared-types, configuration, ...
infra/       # docker, ci, deployment
docs/        # architecture, ADRs, diagrams
```

## Principles

- Each service is independently deployable, independently testable.
- No service reaches into another service's database. Cross-service
  communication happens via the API gateway or events — never direct DB access.
- Every service validates its environment at startup and fails fast if a
  required variable is missing.
- Multi-tenancy is enforced at the data layer (row-level `business_id`
  scoping), not just in application code, so a bug in one endpoint can't leak
  another merchant's data.
