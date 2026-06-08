# Structured Products Smart Contract

## Overview

This smart contract governs the lifecycle of structured notes issued by the bank: compound instruments whose payoff is composed of one or more nested payoffs — typically a bond combined with one or more derivative components.

The canonical example throughout this document is a **reverse convertible** (RC): a coupon-bearing note whose principal redemption is linked to an equity barrier knock-in put option. If the barrier is never triggered the investor receives coupons and full principal; if the barrier is triggered and the stock finishes below the strike, the investor receives shares at a below-market delivery price.

The model generalises to other structures — capital-protected notes, autocallables, range accruals — that share the same compound-payoff pattern.

---

## Products in Scope

The structured products in scope (Germany MVP) and their decompositions are listed below. Each note is a **package** of a bond component (governed by [bonds_wip.md](bonds_wip.md)) and one or more option components (governed by [equity_options.md](equity_options.md)); lifecycle events on the components surface to this contract via the QRL observation / event ladder. The template column is the QRL payoff template.

> *Transcribed from the "Products in scope" page; the event matrix below should be confirmed against that page.*

### Catalogue

| Product                          | Decomposition                                                                                                                                     | Template                      |
|----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------|
| Barrier Reverse Convertible      | Long bond + short barrier option (European exercise, continuous barrier monitoring)                                                               | `BarrierRevCon`               |
| Barrier Reverse Convertible Pro  | Long bond + short barrier option (European exercise, discrete barrier monitoring)                                                                 | `BarrierRevConPro`            |
| Bonus Certificate                | Zero bond + down-and-in put + plain vanilla call                                                                                                  | `BonusCertificate`            |
| Capped Bonus Certificate         | Zero bond + down-and-in put (continuous monitoring, European exercise)                                                                            | `CappedBonusCertificate`      |
| Capped Bonus Pro Certificate     | Zero bond + down-and-in put (discrete monitoring, European exercise)                                                                              | `CappedBonusCertificatePro`   |
| Capped Warrant                   | Package of two vanilla options                                                                                                                    | `CappedWarrant`               |
| Discount Certificate             | Long zero bond + short plain vanilla European put                                                                                                 | `DiscountCertificate`         |
| Knock-Out Warrant                | Down/up-and-out call/put; continuous monitoring; European exercise; fixed expiry                                                                  | `BarrierOption`               |
| Reverse Capped Bonus Certificate | Long zero bond + 1 vanilla call − 1 up-and-in barrier call (continuous monitoring, European exercise)                                             | `RevCappedBonusCertificate`   |
| Reverse Convertible              | Long bond + short plain vanilla put                                                                                                               | `ReverseConvertible`          |
| Option / Warrant (Plain Vanilla) | Plain vanilla European or American option on stock or equity index (HTUB or third-party issuer)                                                   | `Vanilla`                     |
| Mini Certificate                 | Like Open End Turbo with barrier above/below strike for call/put; continuous barrier; intraday issuance                                           | `BarrierOption` (approx.)     |
| Open End Turbo                   | Perpetual knock-out warrant (down-and-out / up-and-out), strike = barrier, exercisable for intrinsic value; continuous barrier; intraday issuance | `BarrierOption` (approx.)     |
| Factor Certificate               | 1:1 tracker of a factor index (index calculation required)                                                                                        | TBD — on hold until clarified |

### Lifecycle-event applicability

`✅` = handled by the lifecycle engine (a QRL-driven lifecycle event this contract processes into moves/payments). `⚠` = impacts lifecycle events but is applied as a **change in product state** — a corporate action on the underlying that feeds through as an R-value / strike / multiplier adjustment via the [Corporate Action Orchestration](../invariants.md#corporate-action-orchestration) model, not as a direct cash move on the note.

| Product                          | Expiry | Coupon | Cont. barrier | Disc. barrier | Exercise   | Dividend | Stock split |
|----------------------------------|--------|--------|---------------|---------------|------------|----------|-------------|
| Barrier Reverse Convertible      | ✅      | ✅      | ✅             | —             | European   | ⚠        | ⚠           |
| Barrier Reverse Convertible Pro  | ✅      | ✅      | —             | ✅             | European   | ⚠        | ⚠           |
| Bonus Certificate                | ✅      | —      | —             | ✅             | European   | ⚠        | ⚠           |
| Capped Bonus Certificate         | ✅      | —      | ✅             | —             | European   | ⚠        | ⚠           |
| Capped Bonus Pro Certificate     | ✅      | —      | —             | ✅             | European   | ⚠        | ⚠           |
| Capped Warrant                   | ✅      | —      | —             | —             | European   | ⚠        | ⚠           |
| Discount Certificate             | ✅      | —      | —             | —             | European   | ⚠        | ⚠           |
| Knock-Out Warrant                | ✅      | —      | ✅             | —             | European   | ⚠        | ⚠           |
| Reverse Capped Bonus Certificate | ✅      | —      | ✅             | —             | European   | ⚠        | ⚠           |
| Reverse Convertible              | ✅      | ✅      | —             | —             | European   | ⚠        | ⚠           |
| Option / Warrant (Plain Vanilla) | ✅      | —      | —             | —             | Euro/Amer  | ⚠        | ⚠           |
| Mini Certificate                 | ✅      | —      | ✅             | —             | —          | ⚠        | ⚠           |
| Open End Turbo                   | perp.  | —      | ✅             | —             | continuous | ⚠        | ⚠           |
| Factor Certificate               | —      | —      | —             | —             | —          | —        | —           |

**Scope notes:**

- **Coupon** applies only to the coupon-bearing reverse convertibles; the certificates are built on **zero** bonds and pay no periodic coupon (their return is delivered at redemption).
- **Continuous vs discrete barrier** distinguishes continuous (intraday) monitoring from discrete observation-date monitoring — the same distinction as the `barrier.monitoring` field in [equity_options.md](equity_options.md). The "Pro" variants use discrete monitoring. The smart-contract logic is **agnostic** to which is used: the two differ only in the source and timing of the barrier-observation event (a `MarketObservation` Point vs Range), not in the payoff logic, so the continuous/discrete flag matters for the feed, not the breach evaluation. The column is therefore indicative; e.g. the Bonus Certificate is treated here as discrete.
- **Dividend and stock split are `⚠`** for every equity-underlying note: they are not note-level cash events but corporate actions that re-strike / re-size the embedded option via product state. This is exactly the inbound `CorporateAction` → outbound `ProductStateChange` path in [implementation.md](../implementation.md).
- **Mini Certificate / Open End Turbo** are modelled as a `BarrierOption` approximation. They are issued intraday on a rolling basis, so barrier monitoring is **issuance-time-aware**: each tranche carries an `issuanceTimestamp` and a continuous-barrier breach affects only units already in existence — see [Issuance-time-aware monitoring](equity_options.md#2-barrier-observation). The Open End Turbo is **perpetual** (no scheduled expiry — it terminates on knock-out).
- **TBD — daily financing / strike roll (open-end leveraged certificates).** Open-end turbos roll funding cost (and dividends) into the strike (= barrier) on a daily basis; this recurring re-strike is **not yet modelled** and is parked pending a decision on how it will be represented (likely a scheduled product-state `Reset`). Until then these products are covered for issuance, barrier monitoring, and knock-out only.
- **Factor Certificate** is on hold pending the factor-index calculation and is not yet modelled.
- **Hedging instruments** referenced on the same scope page — stock, futures, barrier options, IR futures/options, FX cash/option/swap, and SBL — are not structured products; they are governed by their own contracts ([equities.md](equities.md), [futures.md](futures.md), [equity_options.md](equity_options.md), [irs_wip.md](irs_wip.md), [fx_wip.md](fx_wip.md), [stock_borrow_loan_wip.md](stock_borrow_loan_wip.md)).

---

## Booking Model

Per [invariant 11](../invariants.md#core-ledger-invariants), the booking model is not the responsibility of the smart contract. For the canonical example we assume the simplest case: the note is booked as a single entity on a single internal wallet, and any hedge instruments are also held on that same wallet. Whether a real implementation splits issuance from hedging, routes through an SPV, or distributes through a primary syndicate is a booking decision and does not change the smart contract's lifecycle behaviour.

| Party        | Wallet Type     | Description                                                       |
|--------------|-----------------|-------------------------------------------------------------------|
| Issuer Book  | Real wallet     | Holds the issued note position and any hedge instruments          |
| Client       | Virtual wallet  | External note holder; recipient of coupons, principal, or shares  |
| CSD          | Virtual wallet  | Counterparty for equity delivery in the physical settlement path  |

---

## State

The structured products smart contract is stateless. Each invocation receives Product state, Unit state, and Position state per the global [State Model](../state.md).

### Product State

The product state for a structured note is the payoff specification. Payoffs may be **compound**: composed of nested payoff components governed by other smart contracts.

| Field          | Description                                                                  |
|----------------|------------------------------------------------------------------------------|
| `payoff`       | The compound payoff specification: a tree of nested payoff components        |
| `currency`     | Settlement currency                                                          |
| `inceptionDate`| Date of note inception                                                       |
| `maturityDate` | Final settlement date                                                        |

For the canonical Reverse Convertible, the `payoff` decomposes into:

- A **bond component** specifying the coupon schedule, accrual basis, and principal repayment terms (governed by [bonds_wip.md](bonds_wip.md)).
- A **knock-in put option component** specifying the strike, barrier level, observation schedule, and physical-settlement ratio (governed by [equity_options.md](equity_options.md)).
- A **redemption rule** combining the two: at maturity, deliver cash at par if the put is out of the money (or never knocked in); else deliver shares at the physical settlement ratio.

Nested payoff components are inputs to the structured product's payoff function — they are not separately materialised as ledger units. Lifecycle events on the components (e.g. a barrier observation date, a coupon date) are surfaced via the QRL observation / event ladder and consumed by this smart contract.

### Unit State

Unit state is compound with three parts — liveliness, last-lifecycle-event marker, and corporate-actions-applied list — per the global model in [state.md](../state.md), written together as e.g. `Active | Coupon paid 2026-01-15 | CAs: []` or `Active (barrier_knocked) | Barrier observed 2026-02-15 | CAs: [split 2025-08-15]`. Where the product references one or more equity underlyings, corporate actions on those underlyings propagate to the structured product via the [Corporate Action Orchestration](../invariants.md#corporate-action-orchestration) model and are appended to the product unit's CA list.

Liveliness:

| State      | Meaning                                                                                          |
|------------|--------------------------------------------------------------------------------------------------|
| `Active`   | Note outstanding; coupons in schedule; barrier monitoring (where applicable) ongoing              |
| `Matured`  | Maturity date reached; final redemption transaction created but not yet fully settled             |
| `Expired`  | Fully redeemed; all obligations extinguished                                                      |

Contingent flags carried within the liveliness component (product-specific):

| Flag             | Set by                                                          |
|------------------|-----------------------------------------------------------------|
| `barrier_knocked`| A barrier observation event in which the barrier is breached    |

Last-lifecycle-event marker — examples for the canonical RC:

| Marker                            | Set by                                                     |
|-----------------------------------|------------------------------------------------------------|
| `Inception YYYY-MM-DD`            | The inception event                                        |
| `Coupon paid YYYY-MM-DD`          | A coupon event from the QRL coupon ladder                  |
| `Barrier observed YYYY-MM-DD`     | A barrier observation event (regardless of breach outcome) |
| `Final settlement YYYY-MM-DD`     | The maturity event                                         |

Per [invariant 10](../invariants.md#core-ledger-invariants), the smart contract checks the marker before generating moves. A re-fed coupon date or barrier observation already recorded in the marker produces a no-op.

### Position State

For the canonical Reverse Convertible the position state is the global bucketed counters only (`Settled`, `Pending(date)`, `Failed`) — there are no product-specific extensions. Where a structured product carries optional client-initiated exercise (e.g. an investor put on an autocallable variant), the position state extends to track exercise inventory; that pattern is covered in [equity_options.md](equity_options.md) and applies only to those structures.

### Data Requirements

| Input                                       | Cadence                              | Source             |
|---------------------------------------------|--------------------------------------|--------------------|
| Reference equity price observation          | Per the barrier observation schedule | Market data        |
| Final equity reference price at maturity    | At maturity                          | Market data        |
| Coupon dates and amounts                    | Per the bond component schedule      | QRL coupon ladder  |
| Maturity event                              | At maturity                          | QRL event ladder   |

---

## Lifecycle Events

All lifecycle events for the structured note are generated by the QRL observation / event ladder. The smart contract is invoked per event, consults the unit state's last-event marker for idempotency, and produces the resulting moves.

### 1. Note Inception

**Trigger**: A new note instance is created.

The note unit is minted on the issuer book.

| Move | From   | To          | Asset                            | State     |
|------|--------|-------------|----------------------------------|-----------|
| 1    | (mint) | Issuer Book | Note unit (N units, face value)  | `Settled` |

Unit state: `Active | Inception YYYY-MM-DD`. How the note subsequently reaches the client (direct sale, primary syndicate, secondary trade) is a booking matter governed by [invariant 11](../invariants.md#core-ledger-invariants), not by this smart contract.

### 2. Coupon Payment

**Trigger**: Coupon date emitted by the QRL coupon ladder.

| Move | From        | To     | Asset                                    | State     |
|------|-------------|--------|------------------------------------------|-----------|
| 1    | Issuer Book | Client | Cash [CCY] (coupon × outstanding notes)  | `Pending` |

Unit state: liveliness unchanged; marker → `Coupon paid YYYY-MM-DD`.

The coupon amount is computed from the bond component of the product state.

### 3. Barrier Observation

**Trigger**: Barrier observation date emitted by the QRL observation ladder, with the observed reference equity price.

The smart contract evaluates the price against the barrier level. No cash or unit moves are generated — this is a state-only event.

- **No breach**: liveliness unchanged. Marker → `Barrier observed YYYY-MM-DD`.
- **Breach** (first occurrence): contingent flag `barrier_knocked` set on liveliness. Marker → `Barrier observed YYYY-MM-DD`. The smart contract records that physical delivery at maturity is now possible.
- **Subsequent observations after breach**: marker advances; the `barrier_knocked` flag is already set and is not toggled off.

### 4. Maturity

**Trigger**: Maturity event emitted by the QRL event ladder, with the final reference equity price.

The smart contract evaluates the redemption rule against the unit state and product state, and produces one of two outcomes.

#### 4a. No knock-in, or knocked in but `S_T ≥ strike`

The put is out of the money. Redemption is in cash at par.

| Move | From        | To          | Asset                                          | State     |
|------|-------------|-------------|------------------------------------------------|-----------|
| 1    | Issuer Book | Client      | Cash [CCY] (face value × outstanding notes)    | `Pending` |
| 2    | Client      | Issuer Book | Note unit (outstanding notes)                  | `Pending` |

Unit state: `Active → Matured | Final settlement YYYY-MM-DD`; `Matured → Expired` once both moves reach `Settled`.

#### 4b. Knocked in and `S_T < strike`

The embedded put is in the money. Redemption is in shares at the physical settlement ratio:

```
Shares delivered = floor(face_value / strike_price)              per note unit
Cash residual    = face_value − shares_delivered × strike_price  (per note unit; may be zero)
```

| Move | From        | To          | Asset                                                | State     |
|------|-------------|-------------|------------------------------------------------------|-----------|
| 1    | Issuer Book | Client      | Equity shares (shares_delivered × outstanding)        | `Pending` |
| 2    | Issuer Book | Client      | Cash [CCY] (cash_residual × outstanding, if non-zero) | `Pending` |
| 3    | Client      | Issuer Book | Note unit (outstanding notes)                         | `Pending` |

The shares are sourced from whatever hedge inventory the issuer book holds. Hedge sourcing, residual market unwind, and any internal funding flows are booking and risk-management concerns outside this smart contract.

Unit state: `Active (barrier_knocked) → Matured | Final settlement YYYY-MM-DD`; `Matured → Expired` once all moves reach `Settled`.

---

## CDM Representation

| Concept                        | CDM Type / Field                                                                                                                          |
|--------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| Compound payoff                | Composition of CDM payoffs (`FixedRatePayout`, `EquityPayout`, `OptionPayout` with `BarrierInstructions`) within a single `ContractualProduct` |
| Inception                      | `EventQualificationEnum.Execution` on the note `TradeState`                                                                               |
| Coupon payment                 | `EventQualificationEnum.Coupon` per the bond component's `PaymentSchedule`                                                                |
| Barrier observation            | Bespoke `BarrierObservationEvent` (see [equity_options.md](equity_options.md)); state-only, no transfer                                   |
| Maturity — cash redemption     | `EventQualificationEnum.ContractTermination`; cash `TransferPrimitive` for principal                                                      |
| Maturity — physical redemption | `EventQualificationEnum.ContractTermination` + `EventQualificationEnum.OptionExercise`; share `TransferPrimitive` with `PhysicalSettlementTerms` |

### CDM Extension — Compound Unit State

CDM `TradeState` does not natively express a compound liveliness + last-event marker; this is a global state-model feature documented in [state.md](../state.md). The structured products contract requires no further extensions beyond those already defined for its component instruments (bond, option).

---

## Relationship to Other Smart Contracts

| Smart Contract | Relationship                                                                                                                                     |
|----------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| Bonds          | The bond payoff component is governed by [bonds_wip.md](bonds_wip.md): coupon schedule, accrual, principal repayment                             |
| Equity Options | The option payoff component is governed by [equity_options.md](equity_options.md): barrier monitoring, knock-in observation, physical settlement |
| Equities       | Equity delivery at maturity (4b) is a share transfer following [equities.md](equities.md)                                                        |
| Cash Payments  | Coupon and cash redemption distributions follow [cash_payments.md](cash_payments.md)                                                             |
| QIS            | A QIS composite unit may serve as the reference underlying of the embedded option; the lifecycle is unchanged                                    |

---

## Implementation

This section binds the structured-products contract to the [External Message Interface](../implementation.md).

### Inbound

| Family                   | Concrete message(s)                                                              | Window       | Triggers                                                  |
|--------------------------|----------------------------------------------------------------------------------|--------------|-----------------------------------------------------------|
| `MarketObservation`      | `ReferencePrice` — reference equity price on a barrier-observation date          | Point (date) | Barrier-breach evaluation (`barrier_knocked`).            |
| `MarketObservation`      | `ReferencePrice` — final reference price at maturity                             | Point (date) | Redemption determination (cash at par vs share delivery). |
| `DateEvent`              | `ScheduledDate` — coupon dates, barrier-observation dates, maturity, inception   | —            | Coupon payment; observation; final settlement.            |
| `CorporateAction`        | CA on the equity underlying (propagated to the note's CA list via orchestration) | —            | Product-state adjustment of the embedded option leg.      |
| `OperationalInstruction` | QRL coupon ladder; observation / event ladder                                    | —            | Schedule-driven invocation.                               |

### Outbound

| Family               | Concrete message(s)                                                                                                                                                                                                                                        | CDM projection                                         |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| `Payment`            | Coupon cash; redemption at par; cash residual on share delivery                                                                                                                                                                                            | `InterestPayment` / `CashTransfer`                     |
| `ProductStateChange` | `Coupon paid` / `Barrier observed` markers; `barrier_knocked` contingent flag; `Active → Matured → Expired`                                                                                                                                                | `BarrierKnockIn` `†` / `ContractTermination`           |
| `NewProductTemplate` | Note unit at inception. Structured-product **creation** mints three products simultaneously (note + bond + option components) under the `StructuredProductCreationPrimitive`; the component contracts then service their own lifecycles via the QRL ladder | `Execution` (`StructuredProductCreationPrimitive` `†`) |
