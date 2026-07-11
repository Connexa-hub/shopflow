# ShopFlow — African Commerce Operating System

Monorepo for a multi-tenant commerce platform serving businesses from single
provision stores to multi-branch franchises.

## Status: Phase 1 — `auth-service` foundation

See `docs/PHASES.md` for the build roadmap and `docs/adr/` for architecture
decision records.

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
