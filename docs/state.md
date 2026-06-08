# State Concepts: Product, Unit, and Position

## Overview

This document is the canonical reference for the state model used by all smart contracts in this repository. Three orthogonal state objects — **Product state**, **Unit state**, and **Position state** — together with the ledger, constitute the complete state of the system at any point in time.

**Smart contracts are stateless.** Each invocation receives the three state objects as inputs and returns the moves to be appended to the ledger along with updated state objects:

```
SmartContract(productState, unitState, positionState) → moves, updated states
```

The smart contract is agnostic to whether the ledger persists these state objects or recomputes them on demand from the move history — that is an implementation choice for the ledger. See [invariants.md](invariants.md) for the rules that constrain how the ledger is maintained.

| Dimension          | Scope                                          | Describes                                                  | Examples                                                                       |
|--------------------|------------------------------------------------|------------------------------------------------------------|--------------------------------------------------------------------------------|
| **Product state**  | Per smart contract instance                    | *What* the instrument is                                   | `expiry = 2026-01-10`, `strike = 100`, `underlying = AAPL`, `ccp = LCH`        |
| **Unit state**     | Per unit, uniform across all holders           | *What stage of life* the unit is in                        | `Active \| Coupon paid 2026-10-01 \| CAs: [split 2018-06-01, split 2022-08-15]` |
| **Position state** | Per `(unit, wallet, counterparty wallet)` tuple | *Who holds how much, and where in the settlement pipeline* | A counter map by settlement bucket (see [Position State](#position-state))     |

Product state and Unit state are the parameter values and lifecycle indicators of the instrument itself; neither depends on who holds the unit. Position state is the per-holder view.

---

## Product Registry

Products are **pre-existing templated entities**, not artefacts created by the first trade that references them. A futures contract month is listed by the exchange before anyone trades it; an OTC option's terms are agreed and registered before the position is booked. The registry is the canonical store of those templates.

Each registry entry is keyed by `(productId, version)` and lives at the **payout layer** — it holds the terms (the contract logic) and the bound parameter values (the [Product State](#product-state)) for one version of one product. **Trades and units reference the product; the product never references the trade.** This inversion is what lets many trades share one set of terms by construction (see [Position State](#position-state) and the position key).

| Registry field        | Description                                                                                                          |
|------------------------|----------------------------------------------------------------------------------------------------------------------|
| `productId`            | Stable identifier for the product across all its versions.                                                            |
| `version`              | Monotonic version number; a new version is a new registry entry, the prior version remains queryable.                |
| `listing`              | Listed-vs-OTC and venue metadata (exchange, CCP, ISIN where applicable). **Metadata on the entry, not a structural fork at the payout layer.** |
| `lifecyclingGrain`     | `trade` or `position` — the grain at which this product is lifecycled (see [Lifecycling Grain](#lifecycling-grain)). |
| `capabilities`         | Declared optional features that gate lifecycle behaviour — e.g. a barrier (`{ kind: KI/KO, ... }`), an autocall ladder, a call/put schedule. The *capability* is template metadata; the *occurrence* of a contingent event (e.g. `barrier_knocked`) is runtime [Unit State](#unit-state). |
| `productState`         | The bound parameter values for this version (see [Product State](#product-state)).                                   |

Listed-vs-OTC is metadata on the registry entry, not a structural fork of the payoff template: the same option payoff is the same template whether it clears at a CCP or faces a bilateral counterparty. The booking topology *does* legitimately differ by listing — exchange-traded products use the two-leg [Exchange Trade Booking Model](invariants.md#exchange-trade-booking-model); OTC products book directly against the counterparty wallet — but that is a property of the settlement and wallet layer, not of the product template.

### Lifecycling Grain

A product is lifecycled at one of two grains, declared on its registry entry:

| Grain      | Applies to                                                                  | Mechanism                                                                                                                                            |
|------------|-----------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `position` | Fungible / listed products where one product version is shared across many trades (cash equities, futures, cleared IRS). | Lifecycle events service the **position** keyed by `(product version, internal wallet, counterparty wallet)`. Per-trade CDM events are produced by [down-allocation](events.md#projection-and-down-allocation) only at the interop boundary. |
| `trade`    | Bespoke OTC products where the product version is unique per trade (OTC options, bilateral structured notes). | Lifecycle events apply per trade. Because the product version is unique per trade, `position == trade` by construction, and no down-allocation is needed. |

Grain is a **consequence of fungibility**, surfaced as an explicit flag rather than inferred. The two cases meet at the boundary: a `trade`-grained product is simply the degenerate case of a `position`-grained one in which every position contains exactly one trade. This is also why the position key in [Position State](#position-state) is consistent across both — for a `trade`-grained product the `product version` component of the key is unique per trade, so the position cannot aggregate more than one.

---

## Product State

A smart contract's **terms** are encoded in the contract logic itself: a futures contract has *some* expiry date, *some* multiplier, *some* CCP; a barrier option has *some* knock-in barrier. **Product state** is the set of concrete parameter values bound to those terms for a specific instance.

| Unit type             | Product state                                                                                                                                |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| Cash equity           | Identifier, ISIN, listing currency, lot multiplier.                                                                                          |
| Futures               | Underlying, multiplier, expiry date, settlement convention (cash / physical), last trading date, CCP.                                        |
| Equity option         | Underlying, strike, expiry, settlement type (cash / physical), option style (European / American), barriers, calculation agent.              |
| Structured note       | Full term sheet: principal, observation schedule, payoff function, autocall barriers, coupon mechanics.                                       |
| OTC IRS               | Notional, fixed/floating leg conventions, day-count, fixing schedule, payment dates, calculation agent.                                       |

Product state is versioned and stored bi-temporally as a [registry](#product-registry) entry `(productId, version)`, so the product as bound at any historical time is recoverable. It changes through two routes only: (a) a **corporate action** that revises the product terms — for example a stock split that changes the strike or multiplier of an option — appended to the unit's corporate-actions-applied list (see [Corporate Actions Applied](#corporate-actions-applied)); and (b) **correction of a misbooking**, applied via the cancel-and-correct amendment pattern (see [invariant 7](invariants.md#core-ledger-invariants)). In both cases a new version is written; the prior version remains queryable.

When a corporate action revises the terms of a **fungible** underlying — one whose product version is shared across many positions — the new version is applied **in place and atomically across every subscribed position** within a single ledger transaction (see [invariant 12](invariants.md#core-ledger-invariants) and the [Corporate Action Orchestration](invariants.md#corporate-action-orchestration) model). The unit identifier is stable through the action; positions are not re-bucketed. This is deliberate: re-bucketing a fungible position across a version boundary would strand per-position state that has no natural migration rule — the futures `costBasis`, open `Pending(date)` settlement sub-buckets, and option exercise sub-buckets all attach to the position, not to the version. In-place atomic application reaches the same observable end state without that migration, while the prior version remains queryable for audit.

---

## Unit State

Unit state is **compound** with three parts, all uniform across every holder of the unit:

1. A **liveliness** component.
2. A **last-lifecycle-event marker** recording the most recent scheduled lifecycle event applied to the unit.
3. A **corporate actions applied** list recording every corporate action ever applied to the unit.

The canonical written form combines all three, e.g. `Active | Coupon paid 2026-10-01 | CAs: [split 2018-06-01, split 2022-08-15]`.

A unit's state cannot differ by counterparty: a listed future cannot be `Active` for one party and `Matured` for another. That is the test for membership of Unit state — anything that varies by holder belongs in Position state instead.

### Liveliness

| Liveliness | Meaning                                                                                                                       |
|------------|-------------------------------------------------------------------------------------------------------------------------------|
| `Active`   | The unit is live: trading and lifecycle events are permitted; positions represent real economic exposures.                    |
| `Matured`  | The unit's final lifecycle event has been triggered (e.g. expiry, final fixing, full close-out) but settlement of the final move(s) is still open. |
| `Expired`  | The unit's final settlement is complete; no further events are possible; the unit identifier is retained only for audit.      |

`Active → Matured` on the contractual trigger. `Matured → Expired` once all final settlement moves reach `Settled`. CDM `closedState` is set at `Expired`.

For some contracts (e.g. cash equities, perpetual instruments) there is no contractual maturity: the unit remains `Active` until a corporate action or delisting extinguishes it.

### Last-Lifecycle-Event Marker

The marker records the most recent lifecycle event applied to the unit — e.g. coupon payment on a bond, autocall observation on a structured note, EOD settlement on a future, floating-rate fixing on an IRS.

Lifecycle events are generated from QRL with some augmentation from QRLPM (e.g. QRL 'Termination' maps to 'Matured' in QRLPM and once QRLPM has completed the final payments QRLPM will move the state to 'Expired'.  Lifecycle events generated by QRL are produced in a defined order, and once applied do not change, so only the last lifecycle event need be retained. The full history is recoverable from the ledger by walking back through the chain of lifecycle-event transactions on the unit, each of which references its predecessor.

**Corporate action that changes the lifecycle ladder.** A corporate action may be significant enough to change the QRL event ladder itself — e.g. a merger that re-dates the coupon schedule, or a restructuring that adds or removes observation dates. This is handled within the existing version mechanism rather than by a special case: applying the corporate action writes a **new product version** (per [Product State](#product-state)) whose terms generate a new ladder. On application the smart contract re-derives the ladder from the new version and reconciles it against the events already actioned on the prior version (recoverable by walking the ledger): events that survive unchanged keep their marker; events that are dropped are recorded as cancelled; newly-introduced future events are scheduled as `Expected`. The single last-lifecycle-event marker remains sufficient for idempotency because it is always interpreted relative to the current product version — a re-fed event carrying the prior version's ladder identity does not match the new version's ladder and is therefore correctly treated as superseded rather than replayed. No separate full-event-history component is required on unit state; the history is, as before, recoverable from the ledger.

Example markers:

| Marker                          | Set by                                                                       |
|---------------------------------|------------------------------------------------------------------------------|
| `Coupon paid 2026-10-01`        | A scheduled coupon payment on a bond or structured note                      |
| `EOD settled 2026-05-04`        | A futures `DailySettlementEvent` for that business day                       |
| `Fixing observed 2026-05-04`    | An IRS or QIS scheduled fixing observation                                   |
| `Final settlement 2026-12-15`   | A contract-expiry final settlement event                                     |

The marker is the primary mechanism by which the smart contract enforces idempotent event delivery for scheduled events (see [invariant 10](invariants.md#core-ledger-invariants) and [Idempotent Event Delivery](#idempotent-event-delivery)).

### Corporate Actions Applied

The CA list is an **append-only** record of every corporate action ever applied to the unit. Each entry records the action type (per CDM `CorporateActionTypeEnum`; see [equities.md](smart_contracts/equities.md)), the effective date, the action terms (e.g. split ratio, dividend per share, election outcomes), the resolution mode (`Automated` / `Override`), and a reference to the orchestrated ledger transaction that implemented it.

The full history is retained — not just the latest — because corporate actions:

- are not generally known at inception (unlike scheduled lifecycle events);
- are order-independent across distinct events; and
- may be retroactively corrected (a restated dividend, a corrected R-value).

Adjustments to a previously-applied corporate action are **never** in-place edits of the existing list entry; they arrive as a separate event with its own identifier and append to the CA list as a new entry, with the underlying ledger correction following the cancel-and-correct pattern of [invariant 7](invariants.md#core-ledger-invariants). The CA history is therefore monotonic — entries are appended, never mutated.

Corporate actions apply atomically across all instances of the unit per [invariant 12](invariants.md#core-ledger-invariants) and the [Corporate Action Orchestration](invariants.md#corporate-action-orchestration) section. Recording the history once per unit avoids duplicating it across every position and makes it impossible for two holders to disagree on which actions have been applied. The list is also the basis for adjustments propagated to derivative units referencing the affected underlying — see [equity_options.md](smart_contracts/equity_options.md).

### Why these are Unit-Level, Not Position-Level

The defining test for placing state at the unit level rather than the position level is **atomicity of application across all holders**: if an event affects every instance of the unit simultaneously and identically, then the state it produces is global to the unit, and there is no value in replicating it across every position. Liveliness transitions, scheduled lifecycle events, and corporate actions all satisfy this test. Settlement bucket movements and cost-basis updates do not — they are intrinsically per-holder and therefore belong on the position.

---

## Position State

A **position** is the aggregation of moves on the ledger that share the same `(unit, wallet, counterparty wallet)` tuple. The triple key matters: a holding of an OTC option facing Counterparty A is a distinct position from one facing Counterparty B even when the underlying terms are identical, so exposures facing different counterparties are not netted. For centrally cleared and exchange-settled products the counterparty is fixed (e.g. the CCP, the CSD) and the keying degenerates to `(unit, wallet)`.

Positions are supplied to the smart contract as input, just like Product state and Unit state. Whether the ledger persists positions or computes them on demand from move history is an implementation detail.

### Bucketed Counters

For each `(unit, wallet, counterparty wallet)` tuple, position state is a counter map keyed by settlement bucket:

| Bucket          | Meaning                                                                                       |
|-----------------|-----------------------------------------------------------------------------------------------|
| `Settled`       | Quantity confirmed settled.                                                                   |
| `Pending(date)` | Quantity expected to settle on the given date; one sub-bucket per anticipated settlement date. |
| `Failed`        | Quantity for which a settlement attempt has terminally failed (per [invariant 8](invariants.md#core-ledger-invariants)). |

Example: `{ Settled: 100, Pending(T+1): 20, Pending(T+2): 10, Failed: 40 }`.

Each bucket total is signed: a long position contributes positive quantity, a short position contributes negative.

### Moves Are Fungible: A Deliberate Departure From CDM

Settlement state lives **on the position**, not on individual moves. This is a deliberate departure from CDM, which carries a `TransferStatusEnum` per `Transfer`. The CDM per-move model is fictional whenever settlement is netted: a CSD that nets ten clips of ten shares each into a single delivery instruction and reports a 50-share fail does not, and cannot, tell us which of the ten underlying transfers failed. Recording a settlement state per individual move therefore requires the implementer to invent an allocation rule (FIFO, pro-rata, operational override) whose result is fictional with respect to the source data and will diverge between systems applying different rules.

We treat moves as **fungible** within a `(unit, wallet, counterparty wallet)` position. The counter model records exactly what the CSD said — `Failed` increments by 50 on the relevant position — and pushes per-clip attribution out of the canonical state and into a downstream reconciliation activity.

Operational consequences:

- Per-move CDM settlement states (`Expected`, `Instructed`, `Pending`, `Settled`, `Failed`) are not tracked on individual moves; quantities are aggregated into the position-state buckets above. CDM `TransferStatusEnum` values remain useful as the **vocabulary** for events in [events.md](events.md), but the canonical state is the position-state bucket.
- On the anticipated settlement date, the system transitions `Pending(D) → Settled` optimistically; settlement-feed messages, where available, drive exceptions back out (e.g. `Pending(T+1) → Failed`), subject to [invariant 8](invariants.md#core-ledger-invariants).
- Users may also send reallocation messages directly between buckets to record exceptions.

### Balance Views

Two balance views are derived from position state per [invariant 9](invariants.md#core-ledger-invariants):

- **Settled balance** (the CSD's view) = the `Settled` bucket.
- **Live balance** (the trade-date view, consumed by risk, valuation, and operations) = `Settled` + Σ all `Pending(date)` sub-buckets.

The `Failed` bucket is excluded from both views.

### Implications for Lifecycle Events

Events that depend on holdings consult the relevant bucket of position state. For example, on a dividend record date, only the `Settled` bucket of the recipient's `(unit, wallet, counterparty wallet)` position is eligible for the dividend; quantities still in `Pending(D)` on record date do not receive the dividend, and the seller — whose `Settled` balance has not yet been reduced — retains eligibility for those shares.

---

## Product-Specific State Extensions

The schema above is the global skeleton. Each smart contract may extend it with product-specific fields. The extensions live alongside the global components; they do not replace them.

### Unit State Extensions

Examples of product-specific unit-state flags:

| Smart contract                                            | Flag(s)                                                              |
|-----------------------------------------------------------|----------------------------------------------------------------------|
| [Equity options](smart_contracts/equity_options.md)       | `barrier_knocked`                                                    |
| [Structured products](smart_contracts/structured_products.md) | `barrier_knocked`, autocall trigger flags                        |

### Position State Extensions

Examples of product-specific position-state scalars:

| Smart contract                                | Extension              | Purpose                                                                                                                  |
|-----------------------------------------------|------------------------|--------------------------------------------------------------------------------------------------------------------------|
| [Futures](smart_contracts/futures.md)         | `costBasis` (scalar)   | Running `Σ (price × multiplier × quantity)` for the current position. Drives daily VM; reset to `S × multiplier × N` at each EOD. |

The futures cost basis is the canonical example: a delivery-settled product needs only the bucketed counters because once units are `Settled` the position is a static holding, but a daily-margined product crystallises P&L continuously and so requires a per-position scalar against which today's mark can be differenced.

### Per-Contract Summary

| Smart contract                                                  | Position-state extension | Unit-state flags                                  | Notes                                                                                            |
|-----------------------------------------------------------------|--------------------------|---------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [Cash equities](smart_contracts/equities.md)                    | —                        | —                                                 | T+1 standard cycle in most markets. Dividend eligibility uses the `Settled` bucket on record date. |
| [Futures](smart_contracts/futures.md)                           | `costBasis`              | —                                                 | Unit moves written `Settled` at execution; bucketed counters collapse to a single `Settled` total. |
| [Bonds](smart_contracts/bonds.md)                               | —                        | —                                                 | T+2 standard cycle; failure resolution paths as for equities.                                    |
| [Equity options](smart_contracts/equity_options.md)             | exercise sub-bucket      | `barrier_knocked`                                 | Per-position exercise state layered onto the settlement-bucket counters.                         |
| [FX (spot, forward, swap, NDF)](smart_contracts/fx.md)          | —                        | —                                                 | Cycle length depends on value date; payment netting compresses the counter across counterparties. |
| [IRS](smart_contracts/irs.md)                                   | —                        | —                                                 | Each periodic payment passes through the bucket cycle on its payment date.                       |
| [Structured products](smart_contracts/structured_products.md)   | —                        | `barrier_knocked`, autocall flags                 | Per-coupon and final-redemption cash flows pass through the bucket cycle on their value dates.    |
| [QIS](smart_contracts/qis.md)                                   | —                        | —                                                 | Simulated wallet movements are recorded but settle off-cycle per the strategy definition.        |
| [Cash payments](smart_contracts/cash_payments.md)               | —                        | —                                                 | The `Expected → Pending → Instructed → Settled` flow (where tracked) drives the bucket transitions. |
| [SBL](smart_contracts/stock_borrow_loan.md)                     | —                        | —                                                 | Collateral margin call and return cycle map onto bucket movements.                               |
| [Funding](smart_contracts/funding.md)                           | —                        | —                                                 | Notional reset and IFR rate changes do not require an extension.                                 |

Where a contract introduces a new margining mechanism (e.g. initial margin recorded on the ledger, or future VM extensions to cleared OTC contracts), the cost-basis pattern documented for futures is to be applied.

---

## Idempotent Event Delivery

Per [invariant 10](invariants.md#core-ledger-invariants), feeding the same event to a smart contract must produce no additional moves and must leave the returned states unchanged. The unit-state components are the mechanism by which smart contracts enforce this:

- For **scheduled lifecycle events** (coupon, fixing, EOD settlement, expiry), the smart contract consults the **last-lifecycle-event marker**. If the marker already records the event being delivered, the invocation returns a no-op.
- For **corporate actions**, the smart contract consults the **corporate-actions-applied list**. If the event's identifier is already in the list, the invocation returns a no-op.

This protects against duplicate notifications from upstream feeds (a fixing republished, a settlement price re-fed, a CA event re-delivered) without conflating them with deliberate corrections. Deliberate corrections arrive as separate events with their own identifiers and follow the cancel-and-correct pattern.

---

## State Versus Ledger

The ledger is canonical; all three state objects are derivable from it.

| State element                | Derivation                                                                                                                                                      |
|------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Product state                | Bound at unit creation; versioned bi-temporally. Updated by (a) corporate-action events appended to the unit's CA list, or (b) cancel-and-correct corrections of misbookings.       |
| Liveliness                   | Set at unit creation as `Active`; advanced by lifecycle events recorded as transactions on the ledger.                                                          |
| Last-lifecycle-event marker  | Updated each time a scheduled lifecycle event is recorded against the unit; reflects only the most recent event by reference.                                   |
| Corporate-actions applied    | Appended each time a corporate-action transaction is recorded against the unit; entries reference the transaction(s) that implemented the action.               |
| Position bucketed counters   | Aggregation of moves on the ledger by `(unit, wallet, counterparty wallet)`, partitioned by current settlement bucket.                                          |
| Position cost basis (futures) | `Σ (price × multiplier × quantity)` over the contributing trades. The EOD reset is recorded on the ledger as part of the daily settlement event.               |

State is therefore a view computed over the ledger; it is not a separate authoritative store. Every change to state is the consequence of a recorded move or state transition on the ledger.
