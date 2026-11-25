# Certificate Lifetimes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every certificate in a freshly created byoda network gets the
lifetime in the spec's table. No certificate can outlive its issuer, and the
CAs sign only EC P-256 keys.

**Architecture:** There are two kinds of change:

- **Policy.** Each CA's `_ACCEPTED_CSRS` table becomes the only source of
  lifetimes for the certificates it signs. The root CA's lifetime lives on
  `NetworkRootCaSecret`. Every hard-coded `expire` override is removed.
- **Enforcement.** `CaSecret.sign_csr` enforces the issuer-expiry cap.
  `CaSecret.review_csr` enforces EC P-256. `Secret.review_expiration`
  computes the renewal warnings at load time.

**Tech Stack:** Python 3.14, `cryptography` (x509, ec), `unittest`
(`IsolatedAsyncioTestCase`), run with `uv run --no-sync python -m unittest`.

**Spec:** `docs/superpowers/specs/2026-11-25-cert-lifetimes-design.md`

## Global Constraints

- Lifetimes, in days:
  - root CA: `100 * 365`
  - `ACCOUNTS_CA`, `SERVICES_CA`, `NETWORK_DATA`: `5 * 365`
  - `SERVICE_CA`: `4 * 365`
  - `MEMBERS_CA`, `APPS_CA`: `3 * 365`
  - `SERVICE`, `SERVICE_DATA`, `ACCOUNT`, `ACCOUNT_DATA`, `MEMBER`,
    `MEMBER_DATA`, `APP`, `APP_DATA`: `365`
- No certificate's `not_valid_after` may be later than its issuer's
  `not_valid_after`.
- If the issuer's certificate has already expired, `sign_csr` raises
  `ValueError`. There is no minimum-validity floor.
- Only EC keys on `SECP256R1` are accepted in CSRs. The only accepted
  signature algorithm is `ecdsa-with-SHA256`.
- Renewal thresholds: end-entity certificates use 180 days (wanted) and
  30 days (needed). CAs use 365 days and 90 days.
- Commit messages must not name the AI agent and must not carry a
  co-author trailer.
- `tests/unit/auth_test.py` needs `https://dir.byoda.net` and
  `secret_test.TestAccountManager` needs Postgres. Neither runs offline, so
  neither is used as a gate. The gate is the new module plus these
  `secret_test.py` classes: `TestSecretBase`, `TestCaSecretBase`,
  `TestCaSecretSubclasses`, `TestDataSecretBase`,
  `TestNetworkDataSecretBase`, `TestMemberSecretBase`, `TestAppSecretBase`,
  `TestAppDataSecretBase`, `TestMemberDataSecretBase`.

## Review Focus

1. A CA created late in its issuer's life (for example, a service registered
   4.5 years after the reset). Its certificate and everything below it must
   stop at the services CA's expiry, not later. Covered by
   `test_cap_is_transitive` in Task 1.
2. An existing caller that still passes `expire=` (tests,
   `tools/sign_csr.py`) must still be capped. An explicit value must not
   bypass the cap. Covered by `test_explicit_expire_is_capped` in Task 1.
3. A pod or service still holding an RSA key sends a CSR after the reset. It
   must get a clear `ValueError`, not an RSA certificate. Covered by
   `test_rejects_rsa_csr` in Task 3, which also covers the `CertStore` path.
4. A long-running server (the directory server runs for months) must
   compute renewal warnings against the current time, not the time the
   module was imported. Covered by `test_thresholds_use_current_time` in
   Task 4, which moves "now" forward with a patch.

Not covered, and out of scope: running `Network.create` a second time on an
existing directory. Today that fails, for two reasons. It reloads the root
CA key with the caller's password, but the key was saved under a random
one. And it refuses to re-create existing intermediate CAs. The reset
creates the network once, into an empty directory.

---

### Task 1: Issuer-expiry cap in `CaSecret.sign_csr`

**Files:**
- Modify: `byoda/secrets/ca_secret.py`. In `sign_csr`, after the
  `expiration` value is computed and before the cert builder runs.
- Create: `tests/unit/cert_lifetimes_test.py`

**Interfaces:**
- Produces: the `CaSecret.sign_csr(csr, expire=None) -> CertChain` contract.
  The returned leaf's `not_valid_after_utc` is never later than
  `self.cert.not_valid_after_utc`. The method raises `ValueError` if
  `self.cert.not_valid_after_utc <= datetime.now(tz=UTC)`.
- Produces: test helpers in `tests/unit/cert_lifetimes_test.py`. Later tasks
  add tests to this module and reuse the helpers:
  - `TEST_DIR = '/tmp/byoda-tests/cert-lifetimes'`, `NETWORK = 'test.net'`
  - `def lifetime_days(secret: Secret) -> float`: returns
    `(not_valid_after_utc - not_valid_before_utc).total_seconds() / 86400`.
  - `async def make_network() -> Network`: removes `TEST_DIR`, then returns
    `await Network.create(NETWORK, TEST_DIR, 'byoda')`.

- [ ] **Step 1: Write the failing tests**

  Add class `TestIssuerCap(unittest.IsolatedAsyncioTestCase)` with these
  tests:
  - `test_child_capped_to_short_lived_issuer`:
    - `network = await make_network()`.
    - Sign a `NetworkServicesCaSecret` CSR with
      `network.root_ca.sign_csr(csr, expire=30)`, giving a services CA
      `short_ca` that expires in 30 days.
    - Sign a `ServiceCaSecret(1234, SimpleNamespace(name=NETWORK,
      paths=copy(network.paths)))` CSR with `short_ca.sign_csr(csr)`. The
      table would give 4 years. Pass a copy, because `ServiceCaSecret`
      overwrites `paths.service_id` on the object it's given.
    - Assert `service_ca.cert.not_valid_after_utc ==
      short_ca.cert.not_valid_after_utc`.
    - Wrap the signing in `self.assertLogs('byoda.secrets.ca_secret',
      'WARNING')`.
  - `test_cap_is_transitive`:
    - Using `short_ca` as above, sign `ServiceCaSecret` → `MembersCaSecret`
      → `MemberSecret(uuid4(), 1234, paths=network.paths,
      network_name=NETWORK)`.
    - Assert that each certificate's `not_valid_after_utc` is at most its
      issuer's, and at most `short_ca.cert.not_valid_after_utc`.
  - `test_explicit_expire_is_capped`: sign with `short_ca.sign_csr(csr,
    expire=10 * 365)` and assert the result equals the issuer's
    `not_valid_after_utc`.
  - `test_expired_issuer_raises`:
    - Sign a services CA with `expire=timedelta(seconds=1)`, then
      `await asyncio.sleep(1.5)`.
    - Assert `self.assertRaises(ValueError)` on that CA's `sign_csr` of a
      `ServiceCaSecret` CSR.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `uv run --no-sync python -m unittest tests.unit.cert_lifetimes_test.TestIssuerCap -v`

  Expected: FAIL. The cap and transitive assertions fail, because today the
  service CA gets 15 years. `test_expired_issuer_raises` fails with "no
  exception raised".

- [ ] **Step 3: Implement the cap in `CaSecret.sign_csr`**

  - If the issuer is expired, raise `ValueError(f'Issuing CA
    {self.common_name} expired at {issuer_expiry}')`.
  - Otherwise, set `expiration = min(expiration, issuer_expiry)`. When the
    cap applies, call `_LOGGER.warning` with the common name of the CSR, the
    requested date and the capped date.
  - Use `self.cert.not_valid_after_utc` as `issuer_expiry`.

- [ ] **Step 4: Run the tests to verify they pass**

  Run the Step 2 command. Expected: 4 tests OK.

  Then run the `secret_test.py` gate classes listed in Global Constraints.
  Expected: all OK.

- [ ] **Step 5: Commit**

  ```bash
  git add byoda/secrets/ca_secret.py tests/unit/cert_lifetimes_test.py
  git commit -m "Cap signed certificates at the issuing CA's expiry"
  ```

### Task 2: One source of truth for lifetimes

**Files:**
- Modify `_ACCEPTED_CSRS` values in:
  - `byoda/secrets/networkrootca_secret.py`
  - `byoda/secrets/networkservicesca_secret.py`
  - `byoda/secrets/serviceca_secret.py`
- Modify: `byoda/secrets/networkrootca_secret.py`:
  - Add the class constant `LIFETIME_DAYS: int = 100 * 365`.
  - Change `create(self, expire: int = LIFETIME_DAYS)`.
- Modify: `byoda/datamodel/network.py`:
  - Line 188: call `root_ca.create()` with no argument.
  - Line 267: call `issuing_ca.sign_csr(csr)`, without `expire`.
- Modify: `byoda/datastore/certstore.py:89`: call
  `cert_auth.sign_csr(csr)`.
- Modify: `tools/sign_csr.py:135`: call `secret.sign_csr(csr)`.
- Modify: `byoda/secrets/secret.py`:
  - `get_csr_signature`: `expire: int | None = None`.
  - `create_selfsigned_cert(self, expire: int | datetime | timedelta,
    ca: bool = False, ...)`: `expire` becomes required, the 3650-day
    fallback is removed, and the docstring matches.
- Modify: `byoda/secrets/network_data_secret.py` and
  `byoda/secrets/member_data_secret.py`:
  - `create(self, expire: int | None = None) -> None`. The 1085 and 109500
    defaults are removed, and `expire` is passed through to
    `super().create`.
  - Production never self-signs these. Only tests that set
    `is_root_cert = True` do, and they must now pass `expire`.
- Modify: `byoda/secrets/secret.py`, in `create_selfsigned_cert`: when
  `expire` is `None`, raise
  `ValueError('expire is required for self-signed certificates')`.
- Modify: `tests/unit/secret_test.py`:
  - Every `create_selfsigned_cert(...)` call passes `expire=10950`
    (lines 100, 108, 142, 1671, 1713, 2040).
  - `secret.create()` at lines 940 and 1225 becomes
    `secret.create(expire=365)`.
  - `auth_test.py:102` (`root_ca.create()`) needs no change.
- Keep the explicit `review_csr` at `network.py:266`. It now duplicates the
  review inside `sign_csr`, but it is harmless.
- Test: `tests/unit/cert_lifetimes_test.py`

**Interfaces:**
- Consumes: `make_network`, `lifetime_days` (Task 1).
- Produces: `NetworkRootCaSecret.LIFETIME_DAYS`, and the lifetimes in
  Global Constraints for every creation path.

- [ ] **Step 1: Write the failing tests**

  Add class `TestCreatedLifetimes`. Each assertion uses
  `assertAlmostEqual(lifetime_days(x), expected, delta=1)`.
  - `test_network_create`: after `make_network()`:
    - `root_ca` is 36500;
    - `accounts_ca`, `services_ca` and `data_secret` are 1825 each.
  - `test_service_create_secrets`:
    - Copy `tests/collateral/addressbook.json` into `TEST_DIR`.
    - Set `network.roles = [ServerRole.Pod]`.
    - `service = Service(network=network)`, then
      `await service.examine_servicecontract('addressbook.json')`, then
      `await service.create_secrets(network.services_ca, local=True)`.
    - Assert `service_ca` is 1460; `members_ca` and `apps_ca` are 1095;
      `tls_secret` and `data_secret` are 365.
  - `test_certstore_sign`. Using `CertStore(ca).sign(csr_pem, id_type,
    ip_address('127.0.0.1'))`, where `csr_pem` comes from
    `secret.csr_as_pem(await secret.create_csr(...))`:
    - a `ServiceCaSecret` CSR signed by `network.services_ca` gives 1460;
    - an `AccountSecret(account_id=uuid4(), network=network)` CSR signed by
      `network.accounts_ca` gives 365;
    - a `MemberSecret(uuid4(), service.service_id, paths=network.paths,
      network_name=NETWORK)` CSR signed by `service.members_ca` gives 365.
      The member must use the addressbook service's id, because the
      members CA rejects CNs for other services.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `uv run --no-sync python -m unittest tests.unit.cert_lifetimes_test.TestCreatedLifetimes -v`

  Expected: FAIL, because today the intermediates are 365 days, the service
  CA is 5475 days, and `CertStore` gives 1095 days.

- [ ] **Step 3: Implement the edits listed under Files**

  The table values come from Global Constraints. Use `IdType` keys exactly
  as they are today; only the values change.

- [ ] **Step 4: Run the tests to verify they pass**

  Run the Step 2 command, then the `secret_test.py` gate classes.

  Expected: all OK.

- [ ] **Step 5: Commit**

  ```bash
  git add byoda tools tests/unit
  git commit -m "Make CA tables the single source of certificate lifetimes"
  ```

### Task 3: EC P-256 only

**Files:**
- Modify: `byoda/secrets/ca_secret.py`:
  - `VALID_SIGNATURE_ALGORITHMS = {'ecdsa-with-SHA256'}`.
  - After the signature-algorithm check, `review_csr` rejects a CSR whose
    public key is not an `ec.EllipticCurvePublicKey` with
    `curve.name == 'secp256r1'`. It raises
    `ValueError('CSR public key must be EC P-256')`.
  - The class docstring and parameter docs say EC, not RSA.
- Modify docstrings that say "Creates an RSA private key" in:
  - `byoda/secrets/secret.py` (`create_csr`)
  - `networkservicesca_secret.py`, `networkaccountsca_secret.py`,
    `serviceca_secret.py`, `networkrootca_secret.py`, `appsca_secret.py`
  - `service_secret.py`, `app_secret.py`, `account_secret.py`
  - `member_secret.py`, `membersca_secret.py`
- Modify: `tests/unit/secret_test.py`. Replace every
  `rsa.generate_private_key(...)` with
  `ec.generate_private_key(ec.SECP256R1())`, at lines 138, 163, 218, 248,
  1477, 1667 and 1709. Remove the `rsa` import and `RSA_KEY_SIZE` if they
  become unused.
- Test: `tests/unit/cert_lifetimes_test.py`

**Interfaces:**
- Consumes: `make_network` (Task 1).
- Produces: `CaSecret.review_csr` raises `ValueError` for non-P-256 keys.

- [ ] **Step 1: Write the failing tests**

  Add class `TestEcOnly`:
  - `test_rejects_rsa_csr`:
    - Build a CSR for a valid service CA common name (`service-ca.service-ca-1234.test.net`),
      signed with an RSA-2048 key, using `x509.CertificateSigningRequestBuilder`
      with a matching DNS SAN.
    - Assert `assertRaisesRegex(ValueError, 'Invalid algorithm')` from both
      `network.services_ca.review_csr(csr)` and
      `CertStore(network.services_ca).sign(pem, IdType.SERVICE_CA,
      ip_address('127.0.0.1'))`.
  - `test_rejects_ed25519_csr`: the same, with an Ed25519 key.
  - `test_rejects_p384_csr` and `test_rejects_p521_csr`: the same, with
    `ec.SECP384R1()` and `ec.SECP521R1()`, asserting with the regex
    `'EC P-256'`. These CSRs carry an `ecdsa-with-SHA256` signature, so they
    pass the algorithm check and reach the new public-key check.
  - `test_all_generated_keys_are_p256`:
    - Create a network and a service the same way as `test_network_create`
      and `test_service_create_secrets` in Task 2.
    - For each of the four network secrets and the five service secrets,
      assert `secret.cert.public_key().curve.name == 'secp256r1'`.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `uv run --no-sync python -m unittest tests.unit.cert_lifetimes_test.TestEcOnly -v`

  Expected: the three rejection tests FAIL. The P-256 test passes.

- [ ] **Step 3: Implement the edits listed under Files**

- [ ] **Step 4: Run the tests to verify they pass**

  Run the Step 2 command, the whole new module, and the `secret_test.py`
  gate classes.

  Expected: all OK. A failure in a gate class means a test helper still
  builds an RSA CSR. Convert it to EC; do not weaken the check.

- [ ] **Step 5: Commit**

  ```bash
  git add byoda tests/unit
  git commit -m "Accept only EC P-256 keys in certificate signing requests"
  ```

### Task 4: Renewal thresholds computed at load time

**Files:**
- Modify: `byoda/secrets/secret.py`:
  - `RENEW_WANTED: timedelta = timedelta(days=180)` and
    `RENEW_NEEDED: timedelta = timedelta(days=30)`.
  - Move the check at lines 606-619 into the new method
    `def review_expiration(self) -> None`, which `load()` calls when
    `with_private_key` is set.
- Modify: `byoda/secrets/ca_secret.py`: `RENEW_WANTED = timedelta(days=365)`
  and `RENEW_NEEDED = timedelta(days=90)`.
- Delete the `RENEW_WANTED` and `RENEW_NEEDED` overrides in these files, so
  each class inherits from `Secret` or `CaSecret`. For the root CA, this
  replaces "never warn" with the generic 365/90-day CA thresholds. That is
  harmless for a 100-year certificate.
  - `account_data_secret.py`, `account_secret.py`, `data_secret.py`
  - `membersca_secret.py`, `networkservicesca_secret.py`,
    `networkaccountsca_secret.py`
  - `networkrootca_secret.py`, `serviceca_secret.py`, `appsca_secret.py`
- Test: `tests/unit/cert_lifetimes_test.py`

**Interfaces:**
- Produces: `Secret.review_expiration(self) -> None`. It logs:
  - a WARNING `"Certificate <file> expires in <n> days"` when the time left
    is less than `RENEW_NEEDED`;
  - an INFO message with the same text when it is less than `RENEW_WANTED`;
  - nothing otherwise.

  The time left is computed as `not_valid_after_utc - datetime.now(tz=UTC)`.

- [ ] **Step 1: Write the failing tests**

  Add class `TestRenewalThresholds`. All `assertLogs` and `assertNoLogs`
  calls use the logger `'byoda.secrets.secret'`, which is where
  `review_expiration` logs.
  - `test_leaf_needed_warns`: a member cert signed with `expire=20` days
    logs a WARNING from `review_expiration()`.
  - `test_leaf_wanted_info`: `expire=100` logs INFO, not WARNING.
  - `test_apps_ca_needed_warns`: an `AppsCaSecret` signed with `expire=60`
    logs a WARNING.
  - `test_ca_quiet_when_fresh`: `network.services_ca` logs nothing. Use
    `assertNoLogs`.
  - `test_thresholds_use_current_time`:
    - Take a fresh 365-day member cert.
    - Patch `byoda.secrets.secret.datetime` with a `datetime` subclass whose
      `now(tz=None)` returns the real now plus 340 days.
    - Assert that `review_expiration()` logs a WARNING. That only happens if
      "now" is read at call time.

- [ ] **Step 2: Run the tests to verify they fail**

  Run: `uv run --no-sync python -m unittest tests.unit.cert_lifetimes_test.TestRenewalThresholds -v`

  Expected: FAIL with `AttributeError: review_expiration`.

- [ ] **Step 3: Implement the edits listed under Files**

- [ ] **Step 4: Run the tests to verify they pass**

  Run the whole new module and the `secret_test.py` gate classes.

  Expected: all OK.

- [ ] **Step 5: Commit**

  ```bash
  git add byoda tests/unit
  git commit -m "Compute certificate renewal warnings at load time"
  ```

## After the plan

These steps are not part of this branch's tasks. Once the branch is merged:

- Rebuild the `byoda-directory` image.
- Then run the reset runbook, which is a separate document.
- `tests/collateral/network-byoda.net-root-ca-cert.pem` must be replaced
  with the new root CA cert as part of the reset.
