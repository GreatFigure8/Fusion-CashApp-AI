# Plan: s37-payer-alias-learning

Issue #37. Wave index 2 (with s11, s18; s13 and s21 consume it later). Python only, no web files (the screen is s21). Paths: `cashapp/` = `api/src/cashapp/`. No LLM call in this story.

## Standards followed

- CLAUDE.md layering: router (transmission) → `AliasService` (rules) → `PayerAliasRepository` (the only ORM code). The router imports no SQLAlchemy, the service imports no FastAPI, and the repository flushes but never commits. The caller's unit of work owns the transaction: the router here, s11/s13's StageRunner, and s18's requeue.
- CLAUDE.md *Matching*: "never auto-assign a payer that maps to multiple accounts". `lookup` always returns **every** customer number its matches point at, and a conflicting `learn` deliberately stores a second row, which makes the payer multi-account.
- CLAUDE.md *Auth*: services take `Principal` as a plain argument. Permissions are enforced by `require_permission` in the router and checked again in the service. Every human change is auditable: `ConfigAudit.record(uow, "aliases", …)` (s28) and a work-item history row through `record_history` (s02) with `actor_fields(principal)` (s40).
- PII: bank account numbers are masked to the last 4 digits in API output and in `describe_alias` text, because that text lands in history rows and logs. The full value stays only in the `PAYER_ALIAS` row, inside OCI.
- s02 naming rules: lowercase SQLAlchemy names (physical names upper snake), no reserved words, index names of at most 30 characters, identity PK, `UtcDateTime`.
- `python-web-app:building-python-web-apps`: logic lives in services; deps are `Annotated` aliases (`UowFactoryDep`, `require_permission`); mutations use POST only; s01's single `ApiError` shape.
- DRY: `normalise_payer_name`, `normalise_bank_account`, `validate_reference_pattern`, `AliasMatch` and `describe_alias` exist once, here. s11, s13, s18 and s21 import them.

## Files to touch (all new, owned by this story)

| Path | Content |
|---|---|
| `api/alembic/versions/s37_payer_alias.py` | `revision = "s37_payer_alias"`; creates `PAYER_ALIAS` and its indexes |
| `cashapp/data/models/aliases.py` | ORM `PayerAlias` (picked up by s02 `load_all_models()`) |
| `cashapp/data/repositories/aliases.py` | `PayerAliasRepository(BaseRepository[PayerAlias])` |
| `cashapp/services/aliases.py` | normalisers, `validate_reference_pattern`, `AliasKind`, `AliasMatch`, `AliasLookup` Protocol, `AliasService`, errors, `describe_alias`, `alias_text`, `ALIAS_AUDIT_KEY` |
| `cashapp/api/schemas/aliases.py` | `AliasOut`, `AliasPage`, `RetireAliasIn`, `alias_error_to_api` |
| `cashapp/api/routers/aliases.py` | `GET /aliases`, `POST /aliases/{alias_id}/retire` (auto-discovered by s01) |
| `api/tests/support/aliases.py` | `make_payer_alias(**overrides)`, `FakeAliasLookup` (for s11, s13 and s24 tests) |
| tests in the TEST PLAN | written and run in step 5 only |

Not touched: `main.py`, the lockfiles, `cashapp/domain/status.py` (`InfoFlag.ALIAS_USED` already exists in s02), `services/customer.py` (s11), `services/matching/*` (s13), the requeue code (s18), `services/actor.py` (s40), `services/config.py` (s28).

## Design

### Table shape: one row per alias key

Each `PAYER_ALIAS` row carries **exactly one** key: `PAYER_NAME_NORM`, `PAYER_BANK_ACCOUNT` or `REFERENCE_PATTERN`. The other two are NULL, and the service enforces this (no DB CHECK, following s02's no-CHECK convention). `learn` writes one row for each key it is given. As a result:

- the API's `kind` and `alias_text` are unambiguous;
- retiring a bad name alias doesn't silently retire the payer's bank-account alias;
- the conflict and idempotency rules apply per key.

`kind` is derived from whichever column is non-null: `name`, `bank_account` or `reference`.

### Normalisation (pinned behaviour)

`normalise_payer_name(name)`:

1. Apply Unicode NFKC, then `casefold()`.
2. Replace `&` with ` and `.
3. Delete `.`, `'` and `’` (so "A.B.C." becomes "abc" and "O'Neil" becomes "oneil").
4. Replace any other character that is not alphanumeric or whitespace with a space.
5. Collapse whitespace and strip.
6. Repeatedly drop **trailing** legal-suffix tokens from `LEGAL_SUFFIXES = {inc, incorporated, ltd, limited, llc, llp, plc, pvt, private, gmbh, co, corp, corporation, company, sa, ag, bv, nv, srl, pte, pty, kk}`, but never drop the last remaining token ("Co" stays "co").
7. Return `""` for None, blank or punctuation-only input.

Example: "ACME Pvt. Ltd." becomes "acme".

`normalise_bank_account(value)`: removes whitespace, `-` and `.`, then upper-cases. Returns `""` for None or blank.

### Reference patterns

`validate_reference_pattern(p) -> str` runs at learn time and raises `InvalidReferencePattern(reason)` when:

- the stripped pattern is empty or longer than 200 characters;
- `re.compile` fails;
- `re.fullmatch(p, "")` matches (the pattern matches everything);
- a nested-quantifier ReDoS shape is found (heuristic regex `\([^()]*[+*][^()]*\)[+*{]`).

At lookup time, matching uses `re.fullmatch` (anchored) on each reference after it is stripped and truncated to 100 characters. Compiled patterns are cached with `functools.lru_cache(maxsize=1024)`.

### Lookup

```
keys = name_norm (if non-empty), bank_norm (if non-empty), references (non-blank)
rows = repo.active_by_name(name_norm) ∪ repo.active_by_bank_account(bank_norm)
       ∪ [r for r in repo.active_reference_aliases() if any(fullmatch(r.pattern, ref))]
if rows: repo.mark_used(ids, at=clock.now())       # USES += 1, LAST_USED_AT = now; one Core UPDATE; flush
return AliasMatch(customer_numbers=sorted unique, alias_ids=sorted unique)
```

- Only active rows (`RETIRED_AT IS NULL`) are ever read.
- The usage counter is written in the caller's transaction (the station's). If that transaction rolls back, the counter does too, which is accepted.
- `AliasMatch.customer_number` is set only when exactly one customer matched. With two or more, callers escalate (s11 raises `CUSTOMER_MULTIPLE_ACCOUNTS`).

### Learn

Signature: `learn(uow, *, item_id, payer_name, bank_account, reference_pattern, customer_number, principal)`.

1. Check the principal:
   - it must hold `Permission.ITEMS_WORK`, otherwise `AliasForbidden`;
   - it must not be a system principal (learning comes from human decisions only), otherwise `AliasForbidden`.
2. Strip `customer_number`. If it is blank, raise `AliasValidationError`.
3. Build the keys: the name key from `normalise_payer_name`, the bank key from `normalise_bank_account`, and the reference key from `validate_reference_pattern` (only when a pattern is given). If no key is non-empty, raise `AliasValidationError("no alias key")`.
4. For each key, call `repo.active_for_key(kind, value)`:
   - **Same customer already active:** reuse that row. No new row, no audit and no history (idempotent).
   - **Otherwise:** insert a row with `CREATED_BY=principal.subject`, `CREATED_BY_NAME=principal.display_name`, `CREATED_AT=now`, `USES=0` and `LEARNED_FROM_ITEM_ID=item_id`.
   - **Conflict:** an active row for this key exists with a different customer. The new row is still inserted, and the conflict is recorded.
5. For each new row, call `ConfigAudit.record(uow, "aliases", None, alias_json(row), principal, f"learned from work item {item_id}")`.
6. When at least one row was new, write one `record_history(uow, item_id, HistoryEntry(action=DECISION, **actor_fields(principal), reasoning=…, payload={"event": "alias_learned", "alias_ids": [...], "conflicts": [{"alias_ids": [...], "customer_numbers": [...]}]}))`.
   - Each `reasoning` line comes from `describe_alias`.
   - A conflict adds: "payer now maps to customers A, B; it will not be auto-assigned".
7. Return a `LearnResult`.

### Retire

Signature: `retire(uow, alias_id, principal, reason)`.

1. The principal must hold `CONFIG_WRITE`, otherwise `AliasForbidden`.
2. A blank reason raises `AliasValidationError`.
3. Load the row with `repo.get_for_update(alias_id)`. If there is none, raise `AliasNotFound`.
4. If the alias is already retired, return it unchanged. No audit row (idempotent).
5. Otherwise set `RETIRED_AT=now`, `RETIRED_BY=principal.subject` and `RETIRE_REASON=reason`, then call `ConfigAudit.record(uow, "aliases", old_json, new_json, principal, reason)`.
6. Retiring writes no work-item history row: the alias isn't an item decision, and `CONFIG_CHANGE` is its trail.

## Interfaces provided (pinned)

```python
# cashapp/services/aliases.py
ALIAS_AUDIT_KEY: Final = "aliases"
LEGAL_SUFFIXES: Final[frozenset[str]]
def normalise_payer_name(name: str | None) -> str
def normalise_bank_account(value: str | None) -> str
def validate_reference_pattern(pattern: str) -> str          # returns the stripped pattern; raises InvalidReferencePattern

class AliasKind(StrEnum): NAME = "name"; BANK_ACCOUNT = "bank_account"; REFERENCE = "reference"

class AliasError(Exception): ...
class AliasNotFound(AliasError): alias_id: int
class AliasForbidden(AliasError): permission: Permission | None
class AliasValidationError(AliasError): message: str
class InvalidReferencePattern(AliasValidationError): ...

@dataclass(frozen=True, slots=True)
class AliasMatch:
    customer_numbers: tuple[str, ...] = ()     # sorted, unique; ALL customers the matches point at
    alias_ids: tuple[int, ...] = ()            # sorted, unique
    @property
    def is_empty(self) -> bool                 # no alias matched
    @property
    def customer_number(self) -> str | None    # set only when exactly one customer; callers never auto-assign otherwise
    @property
    def is_ambiguous(self) -> bool             # len(customer_numbers) > 1

class AliasLookup(Protocol):
    async def lookup(self, payer_name: str | None, bank_account: str | None,
                     references: Sequence[str]) -> AliasMatch: ...

@dataclass(frozen=True, slots=True)
class LearnResult:
    aliases: tuple[PayerAlias, ...]            # one per key given (existing row when idempotent)
    created_ids: tuple[int, ...]
    conflict: bool                             # some key now maps to >1 customer

class AliasService:                            # satisfies AliasLookup
    def __init__(self, uow: UnitOfWork, *, clock: Clock | None = None) -> None
    async def lookup(self, payer_name: str | None, bank_account: str | None,
                     references: Sequence[str]) -> AliasMatch          # uses self's uow; marks USES/LAST_USED_AT
    async def learn(self, uow: UnitOfWork, *, item_id: int, payer_name: str | None, bank_account: str | None,
                    reference_pattern: str | None, customer_number: str, principal: Principal) -> LearnResult
    async def retire(self, uow: UnitOfWork, alias_id: int, principal: Principal, reason: str) -> PayerAlias
    async def search(self, uow: UnitOfWork, *, active: bool | None = True, q: str | None = None,
                     offset: int = 0, limit: int = 50) -> Page[PayerAlias]

def alias_kind(alias: PayerAlias) -> AliasKind
def alias_text(alias: PayerAlias) -> str        # name_norm | "••••" + last 4 of bank account | pattern
def describe_alias(alias: PayerAlias) -> str
    # e.g. "alias #12 (bank account ••••6789 → customer 10045; learned from item 881 by J. Stevenson on 2026-10-20)"
    # retired: suffix "; retired 2026-10-22". Used by s11/s13 in DECISION reasoning; payload carries alias_ids.
def alias_json(alias: PayerAlias) -> dict[str, JsonValue]   # audit snapshot (bank account masked)
```

Consumer rules:
- **s11 and s13:** construct `AliasService(ctx.uow, clock=ctx.clock)` and pass it as `aliases: AliasLookup`. When `lookup` returns `is_ambiguous`, never auto-assign. Put `match.alias_ids` in the DECISION payload and `describe_alias` text in the reasoning (load the rows through `uow.repo(PayerAliasRepository).get_many(ids)`).
- **s18:** in the requeue transaction, `await AliasService(uow).learn(uow, item_id=..., payer_name=item.payer_name, bank_account=<extraction payer bank account>, reference_pattern=None, customer_number=hints["customer_number"], principal=principal)`. The story's `-> PayerAlias` becomes `-> LearnResult` (see Assumptions). s18 may ignore the result.

```python
# cashapp/data/models/aliases.py
class PayerAlias(Base):                         # __tablename__ = "payer_alias"
    id: int; payer_name_norm: str | None; payer_bank_account: str | None; reference_pattern: str | None
    customer_account_number: str; learned_from_item_id: int | None
    created_by: str; created_by_name: str; created_at: datetime
    uses: int; last_used_at: datetime | None
    retired_at: datetime | None; retired_by: str | None; retire_reason: str | None

# cashapp/data/repositories/aliases.py
class PayerAliasRepository(BaseRepository[PayerAlias]):
    model = PayerAlias
    async def active_by_name(self, name_norm: str) -> list[PayerAlias]
    async def active_by_bank_account(self, account_norm: str) -> list[PayerAlias]
    async def active_reference_aliases(self) -> list[PayerAlias]          # reference_pattern IS NOT NULL, active
    async def active_for_key(self, kind: str, value: str) -> list[PayerAlias]   # kind in {"name","bank_account","reference"}
    async def get_many(self, ids: Sequence[int]) -> list[PayerAlias]       # ordered by id; empty input → no query
    async def get_for_update(self, alias_id: int) -> PayerAlias | None     # SELECT … FOR UPDATE (wait)
    async def mark_used(self, ids: Sequence[int], *, at: datetime) -> None # Core UPDATE uses = uses + 1, last_used_at
    async def search(self, *, active: bool | None, q: str | None, offset: int, limit: int) -> Page[PayerAlias]
        # active True → retired_at IS NULL; False → NOT NULL; None → all. q: case-insensitive substring over
        # payer_name_norm, payer_bank_account, reference_pattern, customer_account_number. Order created_at DESC, id DESC.
```

```python
# cashapp/api/schemas/aliases.py
class AliasOut(BaseModel):
    id: int; alias_text: str; kind: Literal["name", "bank_account", "reference"]; customer_number: str
    learned_from_item_id: int | None; created_by_name: str; created_at: datetime
    uses: int; last_used_at: datetime | None; retired_at: datetime | None
    @classmethod
    def from_model(cls, alias: PayerAlias) -> "AliasOut"
class AliasPage(BaseModel): items: list[AliasOut]; total: int; offset: int; limit: int
class RetireAliasIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
def alias_error_to_api(exc: AliasError) -> ApiError
    # AliasNotFound → 404 alias_not_found; AliasForbidden → 403 forbidden (details [{"permission": p}]);
    # InvalidReferencePattern / AliasValidationError → 422 invalid_alias (details [{"msg": ...}])
```

```python
# api/tests/support/aliases.py
def make_payer_alias(**overrides: Any) -> PayerAlias     # unsaved; default kind=name ("acme"), customer "10001", created_by "u1"
class FakeAliasLookup:                                   # satisfies AliasLookup
    def __init__(self, result: AliasMatch | Mapping[tuple[str | None, str | None], AliasMatch] = AliasMatch()) -> None
    calls: list[tuple[str | None, str | None, tuple[str, ...]]]
    async def lookup(self, payer_name, bank_account, references) -> AliasMatch
```

### HTTP contract (s21 and s31 consume it)

All errors use s01's shape `{"error": {code, message, request_id, details}}`.

| Method and path | Permission | Success | Errors |
|---|---|---|---|
| `GET /aliases?active=true&q=&offset=0&limit=50` | config:read | 200 `AliasPage` (`active` defaults to true; `limit` 1..200) | 403 |
| `POST /aliases/{alias_id}/retire` body `RetireAliasIn` | config:write | 200 `AliasOut` (`retired_at` set) | 403, 404 `alias_not_found`, 422 (blank reason: framework `validation_error`) |

- The router opens `async with uow_factory() as uow` (s04 `UowFactoryDep`), calls `AliasService(uow)`, commits after a successful retire, and maps `AliasError` through `alias_error_to_api`.
- No learn endpoint: learning happens only inside s18's requeue.

## Migrations

- One revision: `api/alembic/versions/s37_payer_alias.py`, `revision = "s37_payer_alias"`.
- **Expected parent:** the current single head when this story merges. By plan order that is s28's config-tables revision, or a later wave-2 revision if one merges first (s11 `CUSTOMER_RESOLUTION`, s36, s09/s18). The merger re-points `down_revision` and checks that `alembic heads` returns one head.
- The revision is hand-written and goes to DEV ATP only.

`PAYER_ALIAS` columns:

| Column | Type | Null |
|---|---|---|
| ID | NUMBER(19) identity | PK `PK_PAYER_ALIAS` |
| PAYER_NAME_NORM | VARCHAR2(500) | yes |
| PAYER_BANK_ACCOUNT | VARCHAR2(100) | yes |
| REFERENCE_PATTERN | VARCHAR2(200) | yes |
| CUSTOMER_ACCOUNT_NUMBER | VARCHAR2(100) | no |
| LEARNED_FROM_ITEM_ID | NUMBER(19) | yes (no FK, see Assumptions) |
| CREATED_BY, CREATED_BY_NAME | VARCHAR2(255) | no |
| CREATED_AT | TIMESTAMP WITH TIME ZONE | no |
| USES | NUMBER(10) default 0 | no |
| LAST_USED_AT, RETIRED_AT | TIMESTAMP WITH TIME ZONE | yes |
| RETIRED_BY | VARCHAR2(255) | yes |
| RETIRE_REASON | VARCHAR2(1000) | yes |

- Indexes: `IX_PAYER_ALIAS_NAME_NORM (PAYER_NAME_NORM)`, `IX_PAYER_ALIAS_BANK_ACCOUNT (PAYER_BANK_ACCOUNT)` and `IX_PAYER_ALIAS_CUSTOMER (CUSTOMER_ACCOUNT_NUMBER)`. All three names are at most 30 characters.
- `downgrade()` drops the indexes, then the table.

## TEST PLAN (written and run in step 5 only)

Unit tests run on aiosqlite (s02 `uow`, `uow_factory`), with `FrozenClock`, s04 `make_principal`, and s28 config test support where needed.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/integration/test_payer_alias_migration_atp.py::test_payer_alias_upgrade_downgrade_atp` (`-m atp`) | exact 14 columns, types and nullability; identity PK; 3 indexes; downgrade drops; one head |
| 1 | `api/tests/unit/data/test_alias_schema.py::test_payer_alias_model_columns_match_story` | ORM column set equals the AC1 list (upper-cased) |
| 1 | `…::test_alembic_single_head_after_s37` | `ScriptDirectory` has exactly one head |
| 2 | `api/tests/unit/services/test_alias_normalise.py::test_normalise_payer_name_examples` (parametrized) | "ACME Pvt. Ltd." → "acme"; "Acme, Inc." → "acme"; "Müller GmbH" → "müller"; "  A.B.C.  Corp " → "abc"; "Smith & Sons LLC" → "smith and sons"; "Co" → "co"; None/"" /"..." → "" |
| 2 | `…::test_normalise_strips_only_trailing_suffixes` | "Limited Brands Inc" → "limited brands" |
| 2 | `…::test_normalise_bank_account` | "gb12 3456-78.90" → "GB1234567890" |
| 3 | `api/tests/unit/services/test_alias_service.py::test_lookup_matches_by_bank_account_exact` | normalised exact only; partial account doesn't match |
| 3 | `…::test_lookup_matches_by_normalised_name` | "ACME LTD." finds the alias stored as "acme" |
| 3 | `…::test_lookup_matches_reference_pattern_anchored` | `INV-\d{6}` matches "INV-123456", not "XINV-123456" or "INV-1234567" |
| 3 | `…::test_lookup_unions_kinds_and_returns_sorted_unique` | name + bank on the same customer → one customer, two alias ids |
| 3 | `…::test_lookup_multiple_customers_returns_all_never_single` | two customers → `customer_numbers` has both, `customer_number is None`, `is_ambiguous` |
| 3 | `…::test_lookup_increments_uses_and_last_used_at` | USES +1 on every matched row and LAST_USED_AT = frozen now; unmatched rows untouched |
| 3 | `…::test_lookup_no_keys_returns_empty_without_query` | None/""/[] → `AliasMatch()`; nothing marked |
| 3 | `…::test_alias_service_satisfies_alias_lookup_protocol` | `AliasService` and `FakeAliasLookup` both type-check as `AliasLookup` (runtime + pyright via `assert_type`) |
| 3 | `api/tests/unit/services/test_alias_patterns.py::test_validate_reference_pattern_rejects_bad` (parametrized) | "", "(", ".*", "a*", `(a+)+`, a 201-char pattern → `InvalidReferencePattern` |
| 3 | `…::test_validate_reference_pattern_accepts_and_strips` | `"  INV-\d+ "` → `"INV-\d+"` |
| 4 | `test_alias_service.py::test_learn_stores_one_row_per_key_with_who_and_when` | name, bank and pattern → 3 rows with CREATED_BY/NAME/AT, LEARNED_FROM_ITEM_ID and USES=0 |
| 4 | `…::test_learn_same_key_same_customer_is_idempotent` | second learn: no new row, same ids, no extra audit or history row |
| 4 | `…::test_learn_conflicting_customer_stores_second_row_and_notes_conflict` | two active rows for the key; `conflict=True`; DECISION history row whose payload `conflicts` names both customers; next `lookup` is ambiguous |
| 4 | `…::test_learn_records_config_audit_per_new_row` | `CONFIG_CHANGE` rows with key "aliases", old None |
| 4 | `…::test_learn_rejects_system_principal_missing_permission_and_no_keys` | `AliasForbidden` ×2, `AliasValidationError` |
| 4 | `…::test_learn_invalid_pattern_writes_nothing` | `InvalidReferencePattern`; no rows |
| 4 | `…::test_learn_does_not_commit` | rolling back the uow leaves no rows |
| 5 | `…::test_retire_sets_fields_and_audits` | RETIRED_AT/BY/REASON set; one "aliases" audit row with old and new |
| 5 | `…::test_retired_alias_never_matched` | after retire, `lookup` of its name, bank and reference → empty; USES unchanged |
| 5 | `…::test_retire_idempotent_not_found_forbidden_blank_reason` | re-retire is a no-op (no audit row); 404-type `AliasNotFound`; OPERATOR → `AliasForbidden`; blank → `AliasValidationError` |
| 6 | `api/tests/api/test_aliases_api.py::test_list_aliases_active_default_paged` | 200 `{items,total,offset,limit}`; retired excluded; each item has the AC6 fields; masked bank `alias_text` |
| 6 | `…::test_list_aliases_q_filters_and_active_false` | q matches name, customer and account substrings; `active=false` returns retired only |
| 6 | `…::test_list_aliases_requires_config_read` | no token → 401; principal without config:read → 403 single error shape |
| 6 | `…::test_retire_alias_200_and_audited` | ADMIN → 200 `AliasOut.retired_at`; "aliases" `CONFIG_CHANGE` row committed; GET no longer lists it |
| 6 | `…::test_retire_alias_403_404_422` | OPERATOR → 403; unknown id → 404 `alias_not_found`; blank reason → 422 |
| 7 | `test_alias_service.py::test_describe_alias_text` | contains id, kind, masked account (never the full number), customer, item id, creator name and date; retired suffix |
| 7 | `…::test_alias_text_and_kind_per_row` | name → normalised name; bank → "••••6789"; reference → pattern |

Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- **One row per key.** The AC1 column list is kept exactly, but each row holds only one of the three keys. `kind` is derived, so there is no KIND column.
- **`learn` returns `LearnResult`, not `-> PayerAlias`.** One call can create up to three rows, and the conflict flag must be visible to s18. s18 only calls it, so this is non-breaking.
- **`lookup` is `async` and bound to a unit of work.** It reads the DB and writes USES. `AliasService(uow)` binds the uow for `lookup`, which matches s11's `lookup(payer_name, bank_account, references)` Protocol with no uow argument. `learn`, `retire` and `search` keep the explicit `uow` parameter from the AC, and they use the uow that is passed in.
- **"Receipt-match learning"** (from story.md) is stored as a reference-pattern alias plus the bank-account alias. s13 reads `AliasMatch.alias_ids` and customer numbers as soft signals.
- **Bank-account match** is exact after `normalise_bank_account` (spaces, dashes and dots removed, upper-cased). "Exact" is read as "exact on the canonical form".
- **Bank accounts are masked to the last 4 digits** in `AliasOut.alias_text`, `describe_alias` and audit JSON (PII). The search `q` still matches the full stored value.
- **`LEARNED_FROM_ITEM_ID` has no FK.** s45's retention purge may remove work items, and s02 leaves `batch_id` without an FK for the same reason.
- **Learning requires `items:work`**, and a system principal is refused. Aliases come only from human decisions (CLAUDE.md: "never auto-assign" plus "learned from human requeue").
- **History:** `learn` writes one DECISION row on the learned-from item when it creates rows, and the AC4 conflict is noted there. `retire` writes only a `CONFIG_CHANGE` row, because an alias isn't tied to one live item.
- **No `POST /aliases`** (out of scope). s21 builds the tab on GET plus retire.
- **`actor_fields`** comes from s40's `cashapp/services/actor.py`. If the merger moves it, only the import changes.
- **Test file locations** follow the s02 and s40 `api/tests/unit/...` convention. API tests go in `api/tests/api/`.

## Risks

- **Reference-pattern scan:** `active_reference_aliases()` loads every active pattern for each lookup. That's fine at hundreds of rows. If it grows into the thousands, cache per snapshot or add a prefix index. ReDoS is reduced by the validator heuristic and the 100-character input truncation, but Python's `re` has no timeout, so the heuristic is not a proof.
- **Concurrent first learn:** two requeues of the same key at the same moment can both insert. That is harmless: same customer gives a duplicate active row, which lookup dedupes. A different customer is the intended ambiguous state.
- **Legal-suffix stripping** can merge distinct payers ("Acme Ltd" and "Acme Inc" both become "acme"). This is mitigated because a conflict makes the name ambiguous, never auto-assigned, and retire is available.
- **Substring `q` search** uses `lower(col) LIKE '%q%'`, a full scan on ATP. That's acceptable at alias-table scale. `q` is bound as a parameter, and `%`/`_` are escaped.
- **Story file ownership:** the story lists three owned files. The model, migration, schemas and test support are additional new files that no other story touches.
