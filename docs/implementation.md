# Implementation: The External Message Interface

## Overview

This document is the canonical reference for the **contract between smart contracts and the external systems around them**. Where [state.md](state.md) defines *what state* a smart contract consumes and [invariants.md](invariants.md) defines *what rules* it must honour, this document defines *how the outside world talks to it* and *how it talks back*.

Smart contracts are stateless and message-driven. The signature from [state.md](state.md) —

```
SmartContract(productState, unitState, positionState) → moves, updated states
```

— is the *core*. The *boundary* wraps it:

```
inbound message ─▶ [ route to subscribed product instances ]
                       ─▶ SmartContract(product, unit, position)
                             ─▶ moves + updated states          (to the ledger)
                             ─▶ outbound messages               (to external systems)
```

Every smart contract invocation is caused by exactly one inbound message and may emit zero or more outbound messages alongside the moves it appends to the ledger. The [QRL observation / event ladder](events.md#qrl-issued-events) is the *internal router*: it normalises inbound messages, fans them out to the subscribed product instances, and drives the invocation. The message families defined here are the wire format crossing the boundary on either side of QRL.

---

## Relationship to CDM: projection, not adoption

This repository builds a model that is **projectable onto** the [Common Domain Model](https://github.com/finos/common-domain-model) but is **not** CDM itself. The reason is deliberate and is the organising principle of this document:

- **CDM is event-centric and lifecycle-complete but asset-servicing-incomplete.** It models the *business events* that a trade undergoes (executions, transfers, resets, quantity changes, terminations, exercises) and the *result* of a corporate action expressed as one of those events. It does **not** provide first-class inbound messages for *asset servicing* — the ingestion of an observed market level, the arrival of a date, or a corporate-action announcement *as a cause* rather than an already-computed result.
- **We invert CDM.** Our inbound messages are the **causes** — a corporate-action announcement, the passage of time to a date, an observed market level. The smart contract turns those causes into moves and into outbound **CDM-projected results**. Every outbound product-state change carries a CDM qualification (see [events.md](events.md)); where CDM has no qualification we mark a bespoke extension (`†`).

So the inbound side is the half CDM does not cover (asset servicing and observation ingestion); the outbound side projects back onto the half CDM does cover (trade lifecycle). The two halves meet at the smart contract.

---

## Message Envelope

Every message — inbound or outbound — carries a common envelope. The payload differs by family; the envelope does not.

| Field           | Meaning                                                                                                                                                        |
|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `messageId`     | Globally unique identifier. This is the **idempotency key** per [invariant 10](invariants.md#core-ledger-invariants); replays are no-ops.                      |
| `messageType`   | The family and concrete type (e.g. `MarketObservation.DailySettlement`, `CorporateAction.CashDividend`, `Payment.Coupon`).                                     |
| `effectiveTime` | The business time the message takes effect (the observation timestamp, the date that arrived, the value date of a payment).                                    |
| `recordedTime`  | The wall-clock time the message entered the system. `effectiveTime` and `recordedTime` together give the bi-temporal coordinate.                               |
| `provenance`    | Source system and authority (e.g. `Exchange:Eurex`, `CSD:Euroclear`, `CalcAgent`, `Treasury`, `UI:override`), plus `Official`/`Provisional`/`Restated` status. |
| `target`        | The selector that routes the message: a listing/ISIN, a product instance, a unit, or a `(unit, wallet, counterparty wallet)` position.                         |
| `cdmProjection` | The CDM qualification this message projects to, or `†` where a bespoke extension is required.                                                                  |
| `payload`       | The family-specific body (see below).                                                                                                                          |

`messageId` + the relevant unit-state component is how idempotency is enforced: a replayed `DateEvent` or `MarketObservation` is absorbed by the **last-lifecycle-event marker**, a replayed `CorporateAction` by the **corporate-actions-applied list** (see [state.md](state.md#idempotent-event-delivery)). A *restatement* is never an in-place edit; it arrives as a **new** `messageId` and follows the cancel/correct path of [invariant 7](invariants.md#core-ledger-invariants).

---

## Inbound Messages

Three primary families drive every smart contract. A fourth, operational family carries the settlement and instruction feedback that the existing per-contract documents already describe; it is catalogued here for completeness so the taxonomy is closed.

### 1. `CorporateAction` — asset-servicing announcements

A corporate-action announcement on a listing, ready for application. This family covers **every** corporate-action type enumerated by CDM `CorporateActionTypeEnum`; the announcement is the *cause* that this repository adds on top of CDM (which models only the *result*). Application is orchestrated atomically across all subscribed positions per [invariant 12](invariants.md#core-ledger-invariants) and the [Corporate Action Orchestration](invariants.md#corporate-action-orchestration) model.

| `actionType` (CDM `CorporateActionTypeEnum`) | ISO 15022 | Causes (representative)                                                    |
|----------------------------------------------|-----------|----------------------------------------------------------------------------|
| `CashDividend`                               | DVCA      | Cash distribution; per-position withholding resolved at application time.  |
| `StockDividend`                              | DVSE      | Scrip shares delivered; optional cash component handled as `CashDividend`. |
| `StockSplit`                                 | SPLF      | Quantity multiplied; R-value adjustment propagated to derivatives.         |
| `ReverseStockSplit`                          | SPLR      | Quantity divided; R-value adjustment propagated.                           |
| `SpinOff`                                    | SOFF      | Basket / termination / client election; case-by-case.                      |
| `Merger`                                     | MRGR      | Share exchange, cancellation, or conversion; case-by-case.                 |
| `Takeover`                                   | TEND      | Acquisition; share exchange or cash cancellation.                          |
| `RightsIssue`                                | RHTS      | Rights units delivered; spawns a rights product template (see Outbound).   |
| `BonusIssue`                                 | BONU      | Free shares delivered (capitalisation issue).                              |
| `StockReclassification`                      | CHAN      | Reclassification into a different share class.                             |
| `StockNameChange`                            | CHAN      | Issuer trading-name change; identifier may follow.                         |
| `StockIdentifierChange`                      | CHAN      | Trading code / ISIN change with no change to the underlying security.      |
| `Delisting`                                  | —         | Removal from venue; positions closed or transferred.                       |
| `EarlyRedemption`                            | MCAL      | Pre-maturity redemption (e.g. preference shares).                          |
| `Liquidation`                                | LIQU      | Dissolution and distribution of residual assets.                           |
| `ClassAction`                                | —         | Collective restitution proceeding.                                         |
| `BankruptcyOrInsolvency`                     | —         | Issuer insolvency; positions typically written down to zero.               |
| `IssuerNationalization`                      | —         | Government acquisition; shares cancelled or converted.                     |
| `Relisting`                                  | —         | Primary listing transferred to a different venue/segment.                  |
| `BespokeEvent`                               | —         | Custom action agreed separately; not covered by the above types.           |

**Payload**: `actionType`, `listing`/`ISIN`, `exDate`, `recordDate`, `payDate`, and the per-listing adjustment values (R-value, cash-per-share, share ratio, deliverable substitutions, withholding rate). The full enumeration above is the asset-servicing surface; the canonical equity treatment of each type lives in [equities.md](smart_contracts/equities.md), and the derivative-adjustment treatment in [equity_options.md](smart_contracts/equity_options.md).

### 2. `DateEvent` — passage of time

A pure temporal trigger: time has advanced to a named point, with **no** market data attached. It is the message that turns the calendar into invocations. Two subtypes:

| Subtype           | Carries                                                       | Causes (representative)                                                                                                                              |
|-------------------|---------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `BusinessDayRoll` | `eventDate`, `businessCenter`                                 | EOD roll driving futures daily settlement, accrual ticks, `Pending(D)` optimistic settle.                                                            |
| `ScheduledDate`   | `eventDate`, `scheduleRef`, `businessCenter`, `dayConvention` | A QRL ladder date arriving: payment / coupon date, fixing date, observation date, ex-date, value date, exercise date, recall date, expiry, maturity. |

**Payload**: `eventDate` plus, for `ScheduledDate`, the `scheduleRef` identifying which entry of the QRL ladder generated at inception has now matured. A `DateEvent` carries no value; where a date *also* requires an observed level (a fixing date that needs the fixing), the `DateEvent` and a `MarketObservation` are correlated by `scheduleRef`. Idempotency is via the last-lifecycle-event marker: a replayed `ScheduledDate` whose `scheduleRef` is already recorded against the unit returns a no-op.

### 3. `MarketObservation` — observable market data

An observed value of a named observable. This is the second half of asset servicing CDM does not model as a first-class inbound message. The defining requirement is that the **observation window** is explicit, and supports **both a single point and a range**.

```
MarketObservation {
  observableId   : <RIC | ISIN | index code> + <priceType>
  observationType: Close | SOQ | EDSP | DailySettlement | Fixing
                 | NAV | IndexLevel | ReferencePrice | BarrierLevel
                 | CollateralMark | DividendPerShare | ...
  window         : Point | Range          // see below
  value(s)       : <observed level(s)>
  status         : Provisional | Official | Restated
}
```

**Window — Point**: a single observation, identified by a `date` and an **optional** `timestamp`. The timestamp distinguishes observations that occur at a specific moment (an opening auction, a closing auction) from end-of-day prints where only the date matters.

| `observationType` | Example                                                         | Window                   |
|-------------------|-----------------------------------------------------------------|--------------------------|
| `Close`           | Official close, AAPL, 2026-05-04                                | Point (date)             |
| `SOQ`             | Special Opening Quotation, SPX, 2026-05-15 08:30 (open auction) | Point (date + timestamp) |
| `EDSP`            | Exchange Delivery Settlement Price, Eurostoxx 50, 2026-06-19    | Point (date)             |
| `DailySettlement` | Exchange daily settlement price, per business day               | Point (date)             |
| `Fixing`          | €STR / SOFR / EURIBOR fixing, single calculation period         | Point (date)             |

**Window — Range**: an observation over a window, identified by a `startDate` and `endDate` with **optional** `startTime` and `endTime`. A range observation carries either the set of constituent observations or the reduced statistic (average, min, max, compounded rate), per `payload.reduction`.

| `observationType`      | Example                                                           | Window               |
|------------------------|-------------------------------------------------------------------|----------------------|
| `Fixing` (compounded)  | RFR compounded-in-arrears over an interest period (FRN / OIS leg) | Range (dates)        |
| `ReferencePrice` (avg) | Average-rate / Asian observation window                           | Range (dates)        |
| `BarrierLevel` (cont.) | Continuous-monitoring barrier window                              | Range (date + times) |
| `IndexLevel` / `NAV`   | TWAP / VWAP execution window for a rebalancing                    | Range (date + times) |

A point is the degenerate case of a range where `startDate == endDate` and the times, if present, coincide; smart contracts that only ever consume point observations need not handle the range reduction. Idempotency is via the last-lifecycle-event marker keyed by `(observableId, window)`.

### 4. Operational and settlement messages (supporting family)

The three families above are the asset-servicing and time drivers. The smart contracts additionally consume the operational feedback already documented per contract; it is enumerated here so nothing in those documents contradicts this taxonomy.

| Message                  | Carries / effect                                                                                                                                                                                         |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `TradeNotification`      | An externally-generated trade (exchange fill, OTC confirmation) — the Trade that opens a position.                                                                                                       |
| `SettlementFeedback`     | CSD / CLS / correspondent confirmation or failure driving the position-state bucket transitions (`Pending → Settled`, `Pending(D) → Pending(D+1)`, `→ Failed`). See [state.md](state.md#position-state). |
| `MarginCall`             | CCP / CSA initial- or variation-margin call or return.                                                                                                                                                   |
| `OperationalInstruction` | Exercise notice, assignment notice, recall notice, collateral substitution, novation/clearing instruction, early-termination notice.                                                                     |
| `OverrideConfiguration`  | A pre-ex-date position-level corporate-action override from an upstream UI (see [CA Orchestration](invariants.md#override-timing)).                                                                      |

These are projectable onto CDM where a qualification exists (e.g. `ClearingInstruction`, `Exercise`, `MarginCall`) and carry `†` where bespoke (e.g. `RecallEvent`, `CollateralSubstitutionEvent` — see [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md)).

---

## Outbound Messages

A smart contract emits three families of outbound message alongside the moves it writes to the ledger.

### 1. `Payment` — instructions to the settlement rails

Every cash obligation the contract crystallises is projected outward as a payment instruction to the relevant rail. The move is written to the ledger in the appropriate position-state bucket; the `Payment` message is what asks an external system to actually move the cash. The subsequent `SettlementFeedback` inbound message drives the bucket from `Pending`/`Instructed` to `Settled` or `Failed`.

| Field           | Meaning                                                                                         |
|-----------------|-------------------------------------------------------------------------------------------------|
| `payer`         | The wallet debited (real or virtual).                                                           |
| `payee`         | The wallet credited.                                                                            |
| `amount`        | Signed amount and `currency`.                                                                   |
| `valueDate`     | The intended settlement date; the `Pending(valueDate)` bucket the move sits in until confirmed. |
| `channel`       | `DvP` / `DvD` / `PvP` / `FoP` / `Internal` — the settlement mechanism.                          |
| `originMoves`   | The ledger move(s) this instruction settles.                                                    |
| `cdmProjection` | `Transfer` / `CashTransfer` / `InterestPayment`, etc.                                           |

Representative payments by contract: premium, coupon, dividend, variation margin, net FX settlement, redemption, manufactured payment, rebate, funding advance/repayment — catalogued in each contract's `## Implementation` section.

### 2. `ProductStateChange` — CDM-projected lifecycle

A notification that the product, unit, or position advanced through a state transition, **projected onto a CDM business event or primitive**. This is the lifecycling half that projects cleanly onto CDM. The message references the [events.md](events.md) qualification.

| `transition`            | Projects to (CDM)                                                        | Example                                                                  |
|-------------------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Liveliness advance      | `ContractTermination` / `closedState`                                    | `Active → Matured → Expired` on expiry / final settlement.               |
| Lifecycle marker set    | `Reset` / `Observation` / `InterestPayment` / `DailySettlementEvent` `†` | `EOD settled 2026-05-04`, `Coupon paid 2026-10-01`, `Fixing observed …`. |
| Position-state movement | — (settlement transition, no new BusinessEvent)                          | `Pending(D) → Settled`, exercise/assignment sub-bucket.                  |
| Contingent flag set     | `BarrierKnockIn` / `BarrierKnockOut` `†`                                 | `barrier_knocked`, autocall trigger.                                     |
| Product-state version   | `QuantityChange` / cancel+`Execution`                                    | CA applied (R-value, multiplier) or cancel/correct of a misbooking.      |

The full event-to-CDM mapping for every contract is the [CDM Event Reference](events.md#cdm-event-reference) in `events.md`; this message family is the runtime emission of those rows.

### 3. `NewProductTemplate` — product creation

Emitted when a smart contract brings a **new product instance into existence**. The message carries the product **template** (the terms), the initial **product-state** binding (the concrete parameter values per [state.md](state.md#product-state)), and the **corporate-action subscriptions** to register against referenced listings (per [CA Orchestration](invariants.md#subscription)).

| Field           | Meaning                                                                        |
|-----------------|--------------------------------------------------------------------------------|
| `template`      | The contract terms (payoff, conventions, schedule shape) — the reusable shape. |
| `productState`  | The concrete parameter values bound for this instance.                         |
| `subscriptions` | One `(productInstance → listing)` subscription per referenced listing.         |
| `initialMoves`  | The execution/transfer moves that mint the new units, and their initial state. |
| `cdmProjection` | `Execution` / `Transfer`, or a bespoke creation primitive (`†`).               |

Representative creations: the rights instrument on a `RightsIssue`; the cleared trade on a CCP novation; equity units on a convertible-bond conversion; basket constituents on a spin-off; the three simultaneous products of a structured-product creation (`†`); the composite unit on a QIS strategy inception. Each is catalogued in the relevant contract's `## Implementation` section.

---

## Idempotency, Ordering, and Restatement

The boundary inherits the ledger's guarantees:

- **Idempotency** ([invariant 10](invariants.md#core-ledger-invariants)): a replayed inbound message — same `messageId` and payload — produces no additional moves and leaves the returned states unchanged. The smart contract enforces this by consulting the unit-state component appropriate to the family: the **last-lifecycle-event marker** for `DateEvent` and `MarketObservation`, the **corporate-actions-applied list** for `CorporateAction`.
- **Ordering**: moves are totally ordered by recording time ([invariant 4](invariants.md#core-ledger-invariants)). Inbound messages are processed in `recordedTime` order; an out-of-order `effectiveTime` (a late fixing for an earlier period) is admissible and is reconciled against the relevant `scheduleRef`.
- **Restatement**: a corrected observation, re-stated dividend, or amended trade is **never** an in-place edit. It arrives as a new `messageId` and the contract applies the cancel/correct pattern of [invariant 7](invariants.md#core-ledger-invariants), keeping the audit trail monotonic.

---

## Per-Contract Interface

Each smart-contract document carries an `## Implementation` section that specialises this interface: the concrete inbound messages it subscribes to (which observables, which date events, which corporate actions), and the concrete outbound messages it emits (which payments, which state changes, which product templates, if any). This document is the shared vocabulary; the per-contract sections are the bindings.

| Contract                                                      | Distinctive inbound observable(s)                       | Creates new product templates?                              |
|---------------------------------------------------------------|---------------------------------------------------------|-------------------------------------------------------------|
| [Cash equities](smart_contracts/equities.md)                  | `Close`; corporate actions (full set)                   | Rights instrument (on `RightsIssue`); basket (on `SpinOff`) |
| [Futures](smart_contracts/futures.md)                         | `DailySettlement`, `EDSP`, `SOQ`                        | No                                                          |
| [Funding](smart_contracts/funding.md)                         | Portfolio MtM (`Close` set), desk cash balance          | `Loan` product per `(book, currency)`                       |
| [Equity options](smart_contracts/equity_options.md)           | `ReferencePrice`, `BarrierLevel` (point + range)        | No (adjusts on CA)                                          |
| [Bonds](smart_contracts/bonds.md)                             | RFR `Fixing` (point + compounded range)                 | Equity units (on convertible conversion)                    |
| [FX](smart_contracts/fx.md)                                   | NDF `Fixing`                                            | No                                                          |
| [IRS](smart_contracts/irs.md)                                 | RFR/IBOR `Fixing` (point + compounded range)            | Cleared trade (on novation)                                 |
| [QIS](smart_contracts/qis.md)                                 | Constituent prices, `NAV`, `IndexLevel` (point + range) | Composite unit (on strategy inception)                      |
| [Structured products](smart_contracts/structured_products.md) | `ReferencePrice`, `BarrierLevel`                        | Note unit (on creation); three products `†`                 |
| [Cash payments](smart_contracts/cash_payments.md)             | — (date- and feed-driven)                               | No                                                          |
| [SBL](smart_contracts/stock_borrow_loan.md)                   | `CollateralMark`, `DividendPerShare`                    | No                                                          |
