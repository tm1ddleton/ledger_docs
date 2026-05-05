# Structured Products Smart Contract

## Overview

This smart contract governs the lifecycle of structured notes issued by the bank: compound instruments whose payoff is composed of one or more nested payoffs — typically a bond combined with one or more derivative components.

The canonical example throughout this document is a **reverse convertible** (RC): a coupon-bearing note whose principal redemption is linked to an equity barrier knock-in put option. If the barrier is never triggered the investor receives coupons and full principal; if the barrier is triggered and the stock finishes below the strike, the investor receives shares at a below-market delivery price.

The model generalises to other structures — capital-protected notes, autocallables, range accruals — that share the same compound-payoff pattern.

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

The structured products smart contract is stateless. Each invocation receives Product state, Unit state, and Position state per the global [State Model](../invariants.md#state-model).

### Product State

The product state for a structured note is the payoff specification. Payoffs may be **compound**: composed of nested payoff components governed by other smart contracts.

| Field          | Description                                                                  |
|----------------|------------------------------------------------------------------------------|
| `payoff`       | The compound payoff specification: a tree of nested payoff components        |
| `currency`     | Settlement currency                                                          |
| `inceptionDate`| Date of note inception                                                       |
| `maturityDate` | Final settlement date                                                        |

For the canonical Reverse Convertible, the `payoff` decomposes into:

- A **bond component** specifying the coupon schedule, accrual basis, and principal repayment terms (governed by [bonds.md](bonds.md)).
- A **knock-in put option component** specifying the strike, barrier level, observation schedule, and physical-settlement ratio (governed by [equity_options.md](equity_options.md)).
- A **redemption rule** combining the two: at maturity, deliver cash at par if the put is out of the money (or never knocked in); else deliver shares at the physical settlement ratio.

Nested payoff components are inputs to the structured product's payoff function — they are not separately materialised as ledger units. Lifecycle events on the components (e.g. a barrier observation date, a coupon date) are surfaced via the QRL observation / event ladder and consumed by this smart contract.

### Unit State

Unit state is compound: a liveliness component and a last-lifecycle-event marker, written together as e.g. `Active | Coupon paid 2026-01-15` or `Active (barrier_knocked) | Barrier observed 2026-02-15`.

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

CDM `TradeState` does not natively express a compound liveliness + last-event marker; this is a global state-model feature documented in [invariants.md](../invariants.md#state-model). The structured products contract requires no further extensions beyond those already defined for its component instruments (bond, option).

---

## Relationship to Other Smart Contracts

| Smart Contract  | Relationship                                                                                                                                       |
|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| Bonds           | The bond payoff component is governed by [bonds.md](bonds.md): coupon schedule, accrual, principal repayment                                        |
| Equity Options  | The option payoff component is governed by [equity_options.md](equity_options.md): barrier monitoring, knock-in observation, physical settlement   |
| Equities        | Equity delivery at maturity (4b) is a share transfer following [equities.md](equities.md)                                                          |
| Cash Payments   | Coupon and cash redemption distributions follow [cash_payments.md](cash_payments.md)                                                                |
| QIS             | A QIS composite unit may serve as the reference underlying of the embedded option; the lifecycle is unchanged                                      |
