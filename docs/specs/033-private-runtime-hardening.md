# Spec 033 — Private pilot runtime hardening

Add an idempotent one-shot schema bootstrap for all existing stores, a schema
version marker, and read-only readiness separate from liveness. Readiness checks
required tables/version and database availability; Redis outage is explicitly
degraded, not a loss of durable readiness. No provider call or credential echo.

Optional RADAR_API_TOKEN protects API/docs routes with constant-time comparison.
Dashboard forwards it only from server environment. Health exposes sanitized status
only. Private pilot binds dashboard/API to loopback; no public exposure/login/TLS
claim. Production deployment requires a generated token; tests/development can
remain token-disabled. No NEXT_PUBLIC secret or build-time credential is allowed.

Pin Python dependency wheels by hashes and base images by registry-resolved digest.
Run API/dashboard nonroot, with read-only filesystems, ephemeral /tmp, dropped
capabilities and no-new-privileges. One-shot initialize precedes API/workers.
Add API/dashboard readiness/health probes. Keep all provider/sending/paper profiles
opt-in and sending false. Runtime image installs pinned dependencies without a
second unpinned build resolution. Source still lives outside Command Center.

Acceptance: auth/unauthorized/error sanitization, idempotent real PostgreSQL bootstrap
and readiness, Redis degraded state, hash-locked container builds, full frontend
build/browser checks, Compose configuration and actual isolated stack smoke.
