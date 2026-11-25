# Certificate lifetimes for the byoda.net reset

## Intent

byoda.net is being reset. A new network root CA, new intermediate CAs and new
service secrets will be generated, all with EC P-256 keys, and existing pods
will be deleted. Before the new secrets are generated, certificate lifetimes
must be made consistent. Today, hard-coded `expire` values override the
validity tables of the CAs. As a result, many certificates outlive their
issuer: for example, the 1-year network services CA signs 3-year service CAs.
A certificate stops being trusted when its issuer expires, so the actual
lifetimes are shorter than the configured ones.

## Goals

- Every certificate created for the new network gets the lifetime in the
  table below.
- No certificate can outlive the CA that signed it.
- Each CA's lifetime rules live in one place, its `_ACCEPTED_CSRS` table.

## Non-goals

- Automatic renewal of certificates. This is a separate follow-up project.
  The first end-entity certificates expire 1 year after the reset, so renewal
  must ship well before then.
- Migrating existing RSA secrets. They are discarded by the reset.
- The reset itself: network creation, service registration, deploying the
  directory server and the dir.byoda.net proxy on homeai. That is a separate
  runbook, carried out after this change is merged and the images are rebuilt.

## Lifetimes

| Tier | Certificates | Validity | Signed by |
|---|---|---|---|
| Root | network root CA | 100 years | self-signed |
| Network intermediates | network accounts CA, network services CA, network data | 5 years | root CA |
| Service CA | service CA (one per service) | 4 years | network services CA |
| Service sub-CAs | members CA, apps CA | 3 years | service CA |
| End-entity | service TLS, service data | 1 year | service CA |
| End-entity | account TLS, account data | 1 year | network accounts CA |
| End-entity | member TLS, member data | 1 year | members CA |
| End-entity | app, app data | 1 year | apps CA |

## Approaches considered

- **A. One source of truth per CA (chosen).** Each CA's `_ACCEPTED_CSRS`
  table holds the lifetimes above. Hard-coded overrides are removed, and
  `CaSecret.sign_csr` caps every certificate at its issuer's
  `not_valid_after`. This is a larger diff, but the lifetimes can't drift
  apart again.
- **B. Edit the values in place.** This is a smaller diff. However, it keeps
  two sources of truth, and it doesn't stop a certificate from outliving its
  issuer.

## Design

1. **Tables.** Set `_ACCEPTED_CSRS` to the lifetimes in the table above:
   - `NetworkRootCaSecret`: `ACCOUNTS_CA`, `SERVICES_CA` and `NETWORK_DATA`
     are 5 years each.
   - `NetworkServicesCaSecret`: `SERVICE_CA` is 4 years.
   - `ServiceCaSecret`: `MEMBERS_CA` and `APPS_CA` are 3 years; `SERVICE` and
     `SERVICE_DATA` are 1 year.
   - `NetworkAccountsCaSecret`, `MembersCaSecret`, `AppsCaSecret`: all
     entries are 1 year. These already match.
2. **Remove overrides.** Callers stop passing an `expire` value, so
   `sign_csr` reads the table:
   - `Network._create_secret` (`network.py`, currently `expire=365`).
   - `CertStore.sign` (`certstore.py`, currently `365*3`).
   - `tools/sign_csr.py` (currently `730`).
   - `Secret.get_csr_signature` (its default is currently `365`; the default
     becomes `None`).

   The root CA keeps its explicit 100-year `expire`, because it is
   self-signed and has no issuer table.
3. **Cap at the issuer's expiry.** In `CaSecret.sign_csr`, after computing
   the expiration date, set it to
   `min(expiration, self.cert.not_valid_after_utc)`. This applies to explicit
   `expire` values as well as table lookups, and the cap is logged when it
   applies.
4. **Docstrings.** Replace "Creates an RSA private key" with "EC private key"
   in the secret classes touched by this change.

## Tests

Unit tests in `tests/unit/` cover the following:

- Build the full chain (root CA → network intermediates → service CA →
  members and apps CAs → end-entity certificates) and assert each
  certificate's `not_valid_after` against the table, within a 1-day
  tolerance.
- A CSR signed by a CA that expires sooner than the table value gets the
  CA's `not_valid_after`.
- All generated keys are EC P-256.
- The existing `tests/unit/auth_test.py` and `secret_test.py` still pass.
  Their explicit `expire` arguments are fine, because the cap still applies.

## Left to the builder

- Wording of the log message emitted when a certificate is capped.
- Whether the expiry test builds the chain in a new test module or extends
  `auth_test.py`.
