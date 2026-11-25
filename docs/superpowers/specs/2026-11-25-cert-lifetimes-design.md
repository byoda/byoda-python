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
- Each certificate's lifetime is set in one place: the issuing CA's
  `_ACCEPTED_CSRS` table, or, for the self-signed root CA, its class.
- The new CAs sign only EC P-256 keys. RSA and Ed25519 CSRs are rejected.

## Non-goals

- Automatic renewal of certificates. This is a separate follow-up project.
  The first end-entity certificates expire 1 year after the reset, so renewal
  must ship well before then. Renewal covers more than TLS certificates:
  - Data certificates sign documents and claims.
  - A claim stores the expiry date of the certificate that signed it, and
    fails verification once that date has passed (`byoda/datamodel/claim.py`).
  - Data certificates are cached by fingerprint.

  So renewal must also re-issue claims and refresh cached data-certificate
  chains. With a 1-year service data certificate, every claim a service
  issues stops verifying within a year unless it is re-issued.
- Migrating existing RSA secrets. They are discarded by the reset.
- The reset itself: network creation, service registration, deploying the
  directory server and the dir.byoda.net proxy on homeai. That is a separate
  runbook, carried out after this change is merged and the images are rebuilt.

## Lifetimes

| Tier | Certificates | Validity | Signed by |
|---|---|---|---|
| Root | network root CA | 100 years | self-signed |
| Network intermediate CAs | network accounts CA, network services CA | 5 years | root CA |
| Service CA | service CA (one per service) | 4 years | network services CA |
| Service sub-CAs | members CA, apps CA | 3 years | service CA |
| Network data | network data certificate | 5 years | root CA |
| End-entity | service TLS, service data | 1 year | service CA |
| End-entity | account TLS, account data | 1 year | network accounts CA |
| End-entity | member TLS, member data | 1 year | members CA |
| End-entity | app, app data | 1 year | apps CA |

The network data certificate is not a CA, but it gets 5 years rather than the
1 year of other data certificates. It signs every service contract in the
network, so replacing it means re-signing all of them, and that should happen
on the same schedule as the network intermediate CAs.

## Approaches considered

- **A. One source of truth per CA (chosen).** Each CA's `_ACCEPTED_CSRS`
  table holds the lifetimes above. Hard-coded overrides are removed, and
  `CaSecret.sign_csr` caps every certificate at its issuer's
  `not_valid_after`. This is a larger diff, but the lifetimes can't drift
  apart again.
- **B. Edit the values in place.** This is a smaller diff. However, it keeps
  several sources of truth, and it doesn't stop a certificate from outliving
  its issuer.

## Design

1. **Tables.** Set `_ACCEPTED_CSRS` to the lifetimes in the table above:
   - `NetworkRootCaSecret`: `ACCOUNTS_CA`, `SERVICES_CA` and `NETWORK_DATA`
     are 5 years each.
   - `NetworkServicesCaSecret`: `SERVICE_CA` is 4 years.
   - `ServiceCaSecret`: `MEMBERS_CA` and `APPS_CA` are 3 years; `SERVICE` and
     `SERVICE_DATA` are 1 year.
   - `NetworkAccountsCaSecret`, `MembersCaSecret`, `AppsCaSecret`: all
     entries are 1 year. These already match.
2. **Root CA lifetime lives in its class.** `NetworkRootCaSecret.create`
   defaults to 100 years, as a class constant. `Network.create` stops passing
   `expire`. `Secret.create_selfsigned_cert` takes `expire` as a required
   argument: its 10950-day default and its 3650-day fallback are removed, and
   its docstring is fixed. Callers in the tests pass `expire` explicitly.
3. **Remove every other override.** Callers stop passing an `expire` value,
   so `sign_csr` reads the table:
   - `Network._create_secret` (`network.py`, currently `expire=365`).
   - `CertStore.sign` (`certstore.py`, currently `365*3`). This is the path
     the directory server uses to sign service CAs and account certificates,
     and the service server uses to sign member certificates.
   - `tools/sign_csr.py` (currently `730`).
   - `Secret.get_csr_signature`, which has no callers. Its `365` default
     becomes `None`.
   - The `expire` parameter is removed from `NetworkDataSecret.create`
     (currently 1085 days) and `MemberDataSecret.create` (currently 109500
     days, about 300 years). Both defaults are unreachable today, because
     `Secret.create` refuses to self-sign anything other than a root CA, but
     they are a second source of truth.
4. **Cap at the issuer's expiry.** In `CaSecret.sign_csr`, after computing
   the expiration date:
   - If the issuer's certificate has already expired, raise `ValueError`. Do
     not mint a certificate that is dead on arrival.
   - Otherwise, set the expiration to
     `min(expiration, self.cert.not_valid_after_utc)`. This applies to
     explicit `expire` values as well as table lookups. When the cap shortens
     a certificate, log a warning with both dates.
   - There is no minimum-validity floor. A certificate signed late in its
     CA's life gets a short validity, and the warning makes that visible. A
     floor would instead block signing near the end of the CA's life.
5. **EC P-256 only.** `CaSecret.review_csr` rejects a CSR unless its public
   key is EC on the SECP256R1 curve. `VALID_SIGNATURE_ALGORITHMS` is reduced
   to `ecdsa-with-SHA256`.
6. **Renewal thresholds.** `RENEW_WANTED` and `RENEW_NEEDED` are currently
   computed when the module is imported, so they go stale in long-running
   servers. `AppsCaSecret`'s pair is also inverted (1080 days and 1800 days).
   - Store both as `timedelta` class constants and compare against
     `datetime.now(tz=UTC) + delta` inside `Secret.load`.
   - Use 180 days for `RENEW_WANTED` and 30 days for `RENEW_NEEDED` on
     1-year certificates, and 365 and 90 days on CAs.
   - Make the log messages state the actual number of days left.
   - This only affects warnings. Actual renewal is a non-goal.
7. **Docstrings.** Replace "RSA" with "EC" in every secret docstring that
   describes key creation, including `secret.py` (`create_csr`),
   `networkservicesca_secret.py` and the `CaSecret` class docstring.

## Tests

Unit tests in `tests/unit/` cover the following. Measure lifetimes as
`not_valid_after_utc - not_valid_before_utc`, not against the current time.

- `Network.create()` produces:
  - a root CA of 100 years;
  - network accounts and services CAs of 5 years;
  - a network data certificate of 5 years.
- `Service.create_secrets(local=True)` produces:
  - a service CA of 4 years;
  - members and apps CAs of 3 years;
  - service TLS and data certificates of 1 year.
- `CertStore(ca).sign(...)` yields:
  - a service CA of 4 years, from the network services CA;
  - an account certificate of 1 year, from the network accounts CA;
  - a member certificate of 1 year, from the members CA.
- Capping:
  - A CSR signed by a CA that expires sooner than the table value gets the
    CA's `not_valid_after`, and a warning is logged.
  - Transitive case: a members CA capped by a short-lived service CA cannot
    sign a member certificate that outlives either CA.
  - A CA whose certificate has already expired raises `ValueError`.
- RSA and Ed25519 CSRs are rejected by `review_csr`. All generated keys are
  EC P-256.
- Renewal thresholds: a certificate within its `RENEW_NEEDED` window logs the
  30-day warning, including for the apps CA.
- The existing `tests/unit/auth_test.py` and `secret_test.py` still pass,
  after updating them to pass `expire` explicitly where
  `create_selfsigned_cert` is called.

## Left to the builder

- Wording of the cap and renewal log messages.
- Whether the new tests go in a new module or extend `auth_test.py`.
