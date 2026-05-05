# Ledger Invariants

These invariants hold for all smart contracts and all transactions recorded in the ledger.

---

## State Model

Smart contracts are **stateless**. To evaluate a smart contract, three orthogonal state objects are supplied as inputs; the contract returns moves to be appended to the ledger and updated state objects.

```
SmartContract(productState, unitState, positionState) → moves, updated states
```

The smart contract is agnostic to whether the ledger persists these state objects or recomputes them on demand from the move history — that is an implementation choice for the ledger.

| Dimension          | Scope                                  | Describes                          | Examples                                                        |
|--------------------|----------------------------------------|------------------------------------|-----------------------------------------------------------------|
| **Product state**  | Per smart contract instance            | *What* the instrument is           | `expiry = 2026-01-10`, `strike = 100`, `underlying = AAPL`      |
| **Unit state**     | Per unit, uniform across all holders   | *What stage of life* it is in      | `Active → Matured → Expired`; `barrier_knocked = true`          |
| **Position state** | Per (unit, wallet, counterparty) tuple | *Who holds how much, and where in the settlement pipeline* | A counter map by settlement bucket (see below)  |

Product state and Unit state are the parameter values and lifecycle flags of the instrument itself; neither depends on who holds the position. Position state is the per-holder view.

**Product-specific shape.** The exact set of unit-state values and any extensions to position state are defined per smart contract. For example, an option carries a `barrier_knocked` flag in unit state; a futures contract carries a running `costBasis` scalar in position state in addition to the bucketed counters described below. See each `smart_contracts/*.md` document for its product-specific state schema.

### Position state: bucketed counters

For each `(unit, wallet, counterparty wallet)` tuple, position state is a counter map keyed by settlement bucket:

| Bucket          | Meaning                                                                                       |
|-----------------|-----------------------------------------------------------------------------------------------|
| `Settled`       | Quantity confirmed settled                                                                    |
| `Pending(date)` | Quantity expected to settle on the given date; one sub-bucket per anticipated settlement date |
| `Failed`        | Quantity for which a settlement attempt has terminally failed (per invariant 8)               |

Example: `{ Settled: 100, Pending(T+1): 20, Pending(T+2): 10, Failed: 40 }`.

### v1: optimistic, aggregated settlement

In v1 there is no settlement-system feed, and many real-world settlements (e.g. cash equity CSD net settlement) cannot be tied back to individual moves. Therefore:

- Per-move CDM settlement states (`Expected`, `Instructed`, `Pending`, `Settled`, `Failed`) are not tracked on individual moves; quantities are aggregated into the position-state buckets above.
- On the anticipated settlement date, the system **optimistically** transitions `Pending(D) → Settled` without external confirmation.
- Users may send reallocation messages between buckets to record exceptions (e.g. `Pending(T+1) → Failed`), subject to invariant 8.
- The richer per-move CDM model remains the target end-state and the reference vocabulary in [events.md](events.md).

### Implications for lifecycle events

Events that depend on holdings consult the relevant bucket of the position state. For example, on a dividend record date, only the `Settled` bucket is eligible for the dividend; quantities still in `Pending(D)` on record date do not receive the dividend.

---

## Core Ledger Invariants

1. **Immutability**: Moves, once written to the ledger, are immutable. State transitions are recorded as new events that reference the original move; the original record is never modified or deleted.

2. **Transaction atomicity**: All moves within a transaction must succeed or fail together. There is no partial execution of a transaction.

3. **Double-entry**: Every transaction is balanced. For any given asset, the sum of units debited across all wallets within a transaction equals the sum of units credited. The net change in total units of any asset across all wallets is zero.

4. **Temporal ordering**: Moves are totally ordered by their time of recording. The ledger provides a complete, immutable, sequenced audit trail.

5. **Wallet type integrity**: Moves may only transfer assets between wallets of compatible types in accordance with the rules of the relevant smart contract. Virtual wallets represent external counterparties and may not hold negative balances from the perspective of the ledger.

6. **Cancellation by reversal**: When a trade that has **already reached `Settled` state** is subsequently cancelled (e.g. a post-settlement booking error or a negotiated unwind), a new transaction is created containing the exact mirror image of the original: every move is reversed (from and to wallets swapped, same asset and quantity), and the reversal moves are written directly as `Settled`. The original and reversal transactions together net to zero. Both remain permanently visible in the ledger. This invariant does not apply to trades that never reached `Settled` state — for those, the `Failed` state itself corrects the balance (see invariant 8).

7. **Amendment as cancel/correct**: A trade amendment must be represented as two sequential transactions: a cancellation (reversal of the original, per invariant 6) followed by a correction (a new transaction reflecting the amended terms). There is no in-place modification of existing moves. The full history — original, cancellation, and correction — is preserved in the ledger, providing a complete audit trail of the trade's evolution.

8. **Two-tier settlement failure and balance exclusion**: A settlement failure notification does not by itself extinguish a trade's legal obligation. Move states therefore distinguish between a non-terminal failed attempt (`TransferStatusEnum.Pending` — the obligation persists and settlement will be retried) and a terminal outcome (`TransferStatusEnum.Failed` — the obligation has been definitively extinguished by mutual agreement or forced resolution such as a buy-in). `Failed` moves are excluded from all wallet balance calculations. Because `Failed` moves never contributed to a settled balance, no reversal transaction is needed when moves reach `Failed` state — the balance is automatically correct. The specific resolution paths — retry, bilateral cancellation, and buy-in — are documented per smart contract.

9. **Wallet balance views**: Two balance views are derived from position state (see State Model). The **settled balance** (the CSD's view) counts only the `Settled` bucket. The **live balance** (the trade-date view consumed by risk, valuation, and operations) counts the `Settled` bucket plus all `Pending(date)` buckets. The `Failed` bucket is excluded from both views (per invariant 8). All downstream systems must specify which view they consume.

---

## Exchange Trade Booking Model

This invariant applies to all exchange-traded products, including cash equities, listed futures, and listed options.

### Structure

**1. Single exchange-facing book per legal entity**

Each legal entity that trades on an exchange maintains exactly one exchange-facing book (a real wallet). This book is the sole internal wallet that faces the exchange's virtual wallet and carries exchange-facing settlement risk. There must not be more than one exchange-facing book per legal entity per exchange venue.

**2. Two-leg transaction per exchange trade**

Every exchange trade notification received by a smart contract generates a single transaction containing two legs, recorded simultaneously:

| Leg | From | To | Nature |
|-----|------|----|--------|
| **Leg 1 — External** | Exchange virtual wallet | Exchange-facing book | Reflects the legal obligation between the entity and the exchange or CCP |
| **Leg 2 — Internal** | Exchange-facing book | Internal wallet (e.g. trader's front book) | Reflects internal allocation of the position to the relevant desk or strategy |

For each leg, there is a corresponding equal-and-opposite move for the cash consideration, ensuring the transaction is balanced.

**3. Simultaneity**

Both legs are part of the same atomic transaction. Neither leg may exist without the other. The internal allocation is never deferred to a separate transaction.

**4. Settlement passes through the exchange-facing book**

Physical settlement at the CSD is always effected against the exchange-facing book. All CSD settlement notifications are applied to the external leg. The internal leg carries the same state transitions in lock-step, ensuring the exchange-facing book always nets to flat (zero position) once both legs have settled.

### Rationale

- The exchange and CCP always face a single, well-capitalised entity book, simplifying margining and default management.
- Internal position management (desk allocation, risk transfer, hedging) is fully reflected in the ledger without affecting the external settlement record.
- Reconciliation between external CSD settlement records and internal books is always possible by inspecting the exchange-facing book, which should carry zero net position after both legs settle.

### Initial Margin — Out of Scope

Initial margin (IM) flows between the entity and a CCP or bilateral counterparty are governed by the relevant derivative smart contract and are **not** in scope for the internal funding facility described in [funding.md](smart_contracts/funding.md). IM represents a segregated collateral obligation, not a cash asset of the desk; it does not create a funding position and is excluded from the revaluation computation that drives the funding notional reset.
