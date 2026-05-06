# Equity Options Smart Contract

## Overview

This smart contract governs the lifecycle of equity options: vanilla European and American (and Bermudan), and barrier options (knock-out and knock-in, single and double barrier, discrete and continuous monitoring). It covers both cash-settled and physically-settled variants. The same smart contract serves both long and short sides of a trade — long and short are simply opposite signs of the position state on the relevant `(unit, wallet, counterparty wallet)` tuple.

**Role of QRL**: QRL is the pricing library and event ladder. Given the option's product state, QRL specifies the observation dates and data the smart contract requires (e.g. barrier observations, expiry-date reference fixing) and emits lifecycle events at the appropriate times. The smart contract consumes these events to drive state transitions and produce moves.

---

## Booking Model

Per [invariant 11](../invariants.md#core-ledger-invariants), the booking model is not the responsibility of the smart contract. The canonical example assumes a single internal wallet that holds the option position and any related hedges. Real-world arrangements — listed-option clearing through a CCP and FCM, segregated client accounts, allocation across desks, novation chains — are operational concerns and do not change the smart contract's lifecycle behaviour.

| Party              | Wallet Type     | Description                                                      |
|--------------------|-----------------|------------------------------------------------------------------|
| Internal Wallet    | Real wallet     | Holds the option position and any hedge inventory                |
| Counterparty       | Virtual wallet  | The other party to an OTC option (or the CCP for listed options) |
| Equity CSD / Wallet| Virtual / real  | Counterparty for share delivery in the physical settlement path  |

Margin (initial and variation) is **out of scope** for this smart contract per the IM exclusion in [invariants.md](../invariants.md). The only cash flow created by this contract for a vanilla / barrier option is the premium at inception (and, for cash-settled exercise, the intrinsic-value payment at settlement).

---

## Product Scope

| Product                         | Exercise Style          | Settlement        |
|---------------------------------|-------------------------|-------------------|
| Vanilla call / put              | European                | Cash or physical  |
| Vanilla call / put              | American / Bermudan     | Cash or physical  |
| Single-barrier knock-out (KO)   | European                | Cash or physical  |
| Single-barrier knock-in (KI)    | European                | Cash or physical  |
| Double-barrier KO               | European                | Cash or physical  |
| KO with rebate                  | European                | Cash rebate + termination |

---

## State

The equity options smart contract is stateless. Each invocation receives Product state, Unit state, and Position state per the global [State Model](../invariants.md#state-model).

### Product State

| Field                  | Description                                                                          |
|------------------------|--------------------------------------------------------------------------------------|
| `optionType`           | `Call` / `Put`                                                                       |
| `exerciseStyle`        | `European`, `American`, or `Bermudan` (with exercise calendar)                       |
| `strike`               | Strike price                                                                          |
| `expiry`               | Expiry date                                                                           |
| `underlying`           | Reference equity (single name, basket, or index)                                     |
| `multiplier`           | Contract size (e.g. 100 shares per contract for listed options)                      |
| `settlementType`       | `Cash` / `Physical`                                                                  |
| `settlementCcy`        | Settlement currency                                                                   |
| `premium`              | Premium amount and payment date                                                       |
| `barrier`              | Optional: `{ kind: KI / KO, level(s), monitoring: discrete / continuous, observationSchedule, rebate? }` |

For double-barrier options, `barrier.level` is a pair (upper, lower).

### Unit State

Unit state is compound: a liveliness component and a last-lifecycle-event marker, written together as e.g. `Active | Barrier observed 2026-02-15` or `Active (barrier_knocked_in) | Exercise notice 2026-04-10`.

Liveliness:

| State      | Meaning                                                                                                                |
|------------|------------------------------------------------------------------------------------------------------------------------|
| `Active`   | Option is live; exercisable (American/Bermudan) or pending expiry (European); barrier monitoring (where applicable) ongoing |
| `Matured`  | Contractual end reached (expiry, KO trigger, or final exercise) but outstanding obligations not yet fully settled       |
| `Expired`  | All obligations discharged; option unit fully extinguished                                                              |

Contingent flags carried within the liveliness component:

| Flag                  | Set by                                                                              |
|-----------------------|-------------------------------------------------------------------------------------|
| `barrier_knocked_in`  | A KI barrier observation event in which the barrier is breached (option remains `Active`) |
| `barrier_knocked_out` | A KO barrier observation event in which the barrier is breached (drives `Active → Matured`) |

Last-lifecycle-event marker — examples:

| Marker                              | Set by                                                          |
|-------------------------------------|-----------------------------------------------------------------|
| `Premium paid YYYY-MM-DD`           | Inception (premium settlement)                                  |
| `Barrier observed YYYY-MM-DD`       | A barrier observation event (regardless of breach outcome)      |
| `Exercise notice YYYY-MM-DD`        | Holder exercises (American/Bermudan)                            |
| `Assignment notice YYYY-MM-DD`      | Writer is assigned (mirror of exercise notice)                  |
| `Expiry valuation YYYY-MM-DD`       | Expiry-date fixing observed                                     |
| `Final settlement YYYY-MM-DD`       | Final settlement transaction created (cash or physical)         |
| `Corporate action YYYY-MM-DD`       | A corporate-action adjustment applied to product state          |

Per [invariant 10](../invariants.md#core-ledger-invariants), the smart contract checks the marker before generating moves; a re-fed observation, exercise notice, or expiry already recorded is a no-op.

### Position State

Position state per `(option unit, wallet, counterparty wallet)` is a **two-layer counter**: every quantity is classified along both a settlement dimension and an exercise dimension.

**Settlement dimension** (the global bucketed counter):

| Bucket          | Meaning                                          |
|-----------------|--------------------------------------------------|
| `Settled`       | Option position confirmed settled                |
| `Pending(date)` | Option position settling on the given date       |
| `Failed`        | Settlement attempt terminally failed             |

**Exercise dimension** (option-specific extension):

| Sub-bucket           | Meaning (long side)                                          | Meaning (short side)                                          |
|----------------------|--------------------------------------------------------------|---------------------------------------------------------------|
| `Live`               | Unexercised; full optionality remains                         | Unassigned                                                    |
| `Exercised(date)`    | Exercise notice given; awaiting settlement on `date`          | —                                                             |
| `Assigned(date)`     | —                                                            | Assignment notice received; awaiting settlement on `date`     |

Position state cells the product of the two dimensions. Example for a long American call holder, mid-life:

```
Settled:
  Live:               100
  Exercised(T+1):       5
Pending(T+1):
  Live:                20
Failed:
  Live:                 0
```

Total options held = sum across all cells = 125. Of those, 5 are awaiting underlying delivery on T+1 following an exercise notice; 20 are still settling from a recent purchase.

For European options the `Exercised`/`Assigned` sub-buckets remain empty until the expiry event itself, at which point the `Live` quantity (if ITM) transitions to `Exercised(expiry + n)` automatically. The exercise dimension is therefore degenerate (always `Live`) for European options pre-expiry.

### Data Requirements

| Input                                            | Cadence                                | Source              |
|--------------------------------------------------|----------------------------------------|---------------------|
| Reference equity price observation               | Per the barrier observation schedule   | Market data         |
| Continuous-monitoring barrier breach notification| Real-time (continuous-barrier products only) | Market surveillance |
| Final reference price at expiry                  | At expiry                              | Market data         |
| Exercise / assignment notice                     | Per the exercise calendar              | Counterparty / CCP  |
| Corporate-action adjustment factor (R-value etc.)| On ex-date                             | Exchange / clearing house / calculation agent |

---

## Lifecycle Events

All lifecycle events are delivered to the smart contract by the QRL observation / event ladder. Each invocation consults the unit-state marker for idempotency.

### 1. Inception

**Trigger**: Trade execution. Counterparty and quantity supplied.

The option unit is created and the premium cash flow is generated in a single atomic transaction:

| Move          | From            | To              | Asset                            | State     |
|---------------|-----------------|-----------------|----------------------------------|-----------|
| Option unit   | Counterparty    | Internal Wallet | N option units                   | `Settled` |
| Premium       | Internal Wallet | Counterparty    | Cash (premium amount × N)        | `Pending` |

For a sold option the directions of both moves reverse.

Position state after inception: `Pending(premium settlement date) / Live = N`. Unit state: `Active | Premium paid YYYY-MM-DD` once the premium cash flow settles.

The premium is the only cash flow this smart contract creates at inception; any margin posting is a booking concern per [invariant 11](../invariants.md#core-ledger-invariants).

### 2. Barrier Observation

**Trigger**: Barrier observation date emitted by the QRL observation ladder, or a real-time breach notification for continuously-monitored barriers. The reference equity price is supplied with the event.

State-only event — no cash or unit moves are generated.

- **No breach**: liveliness unchanged. Marker → `Barrier observed YYYY-MM-DD`.
- **KI breach** (first occurrence): contingent flag `barrier_knocked_in` set; liveliness remains `Active`. Marker → `Barrier observed YYYY-MM-DD`.
- **KO breach**: contingent flag `barrier_knocked_out` set; liveliness `Active → Matured`. The KO terminates the option — see §6 KO Termination.

For double-barrier products the smart contract evaluates both levels at each observation. Continuous and discrete monitoring differ only in event source and timing; the smart contract logic is identical.

### 3. Exercise Notice (American / Bermudan)

**Trigger**: Holder submits an exercise notice for `n` units on date `D` (long side); or the writer receives an assignment notice for `n` units (short side).

Bermudan options accept exercise only on dates in the exercise calendar; the smart contract rejects (returns no-op) a notice received outside the calendar.

No moves are generated at notice time. Position state shifts:

- **Long side**: move `n` from `Settled / Live` → `Settled / Exercised(D + settlementLag)`.
- **Short side**: move `n` from `Settled / Live` → `Settled / Assigned(D + settlementLag)`.

Marker → `Exercise notice YYYY-MM-DD` (or `Assignment notice YYYY-MM-DD`). The settlement date `D + settlementLag` is determined by `settlementType` (typically T+1 cash, T+2 physical).

The actual delivery of underlying / cash occurs at the scheduled settlement date — see §5.

### 4. Expiry Valuation

**Trigger**: Expiry date emitted by the QRL event ladder, with the final reference equity price.

The smart contract computes intrinsic value per the option type and product state:

```
Call payoff = max(S_T − strike, 0)
Put  payoff = max(strike − S_T, 0)
```

For a KI option with no `barrier_knocked_in` flag set: payoff is forced to zero (the option never activated).

For all `Live` quantity at expiry:

- **In the money**: auto-exercise. Move `Live → Exercised(expiry + settlementLag)` (long) or `Live → Assigned(expiry + settlementLag)` (short).
- **Out of the money** (or unactivated KI): the option lapses.

| Move (lapse)        | From            | To           | Asset            | State     |
|---------------------|-----------------|--------------|------------------|-----------|
| Option extinguishment | Internal Wallet | Counterparty | N option units   | `Pending` |

Marker → `Expiry valuation YYYY-MM-DD`. Liveliness `Active → Matured`; `Matured → Expired` once the lapse moves settle.

### 5. Final Settlement

**Trigger**: Settlement date for an `Exercised(date)` or `Assigned(date)` quantity (i.e. exercise + settlementLag, or expiry + settlementLag for auto-exercised European options).

#### 5a. Cash settlement

| Move              | From            | To              | Asset                          | State     |
|-------------------|-----------------|-----------------|--------------------------------|-----------|
| Option extinguishment | Internal Wallet | Counterparty | n option units                 | `Pending` |
| Cash payoff       | Counterparty    | Internal Wallet | Cash (payoff × multiplier × n) | `Pending` |

For a sold option the cash leg reverses (Internal Wallet pays the payoff to the counterparty).

#### 5b. Physical settlement

| Move              | From            | To              | Asset                          | State     |
|-------------------|-----------------|-----------------|--------------------------------|-----------|
| Option extinguishment | Internal Wallet | Counterparty | n option units                 | `Pending` |
| Underlying delivery | Counterparty    | Internal Wallet | n × multiplier shares          | `Pending` |
| Strike payment    | Internal Wallet | Counterparty    | Cash (strike × multiplier × n) | `Pending` |

For a put exercised by the long side, the underlying flows from long to short and cash from short to long; the share/cash directions reverse accordingly. The equity delivery follows [equities.md](equities.md).

Position state after settlement: the relevant `Exercised(date)` / `Assigned(date)` cell is cleared. Marker → `Final settlement YYYY-MM-DD`. If no `Live` and no other in-flight `Exercised/Assigned` quantities remain, liveliness `Matured → Expired`.

### 6. KO Termination

**Trigger**: A KO barrier observation breach (per §2).

The option terminates immediately. Any `Live` quantity is extinguished:

| Move                  | From            | To              | Asset            | State     |
|-----------------------|-----------------|-----------------|------------------|-----------|
| Option extinguishment | Internal Wallet | Counterparty    | N option units   | `Pending` |

If the product specifies a **rebate**, the rebate cash flow is added to the same transaction:

| Rebate type       | Timing                     | Ledger treatment                                                      |
|-------------------|----------------------------|------------------------------------------------------------------------|
| Immediate rebate  | At KO trigger              | Cash move in the KO transaction; state `Pending`                       |
| Deferred rebate   | At original expiry date    | Cash move recorded at KO with state `Pending(expiry)`; settles at expiry |

Liveliness `Active → Matured` at trigger; `Matured → Expired` once extinguishment and any rebate settle. Marker → `Barrier observed YYYY-MM-DD` (the KO date).

In-flight `Exercised`/`Assigned` quantities are unaffected by a subsequent KO — they have already left the `Live` sub-bucket and are bound for delivery.

---

## Corporate Actions

Corporate actions on the underlying equity may require adjustments to the option's product state. They do not generate cash moves on the option itself; they are state events on the option product state and are recorded via the marker `Corporate action YYYY-MM-DD`.

### Quantity-Changing Actions (R-Value Adjustments)

Stock splits, reverse stock splits, and scrip dividends adjust the per-contract terms via an R-value (ratio of post- to pre-event shares):

| Term                 | Adjustment                              |
|----------------------|-----------------------------------------|
| `strike`             | New strike = old strike ÷ R             |
| `multiplier`         | New multiplier = old multiplier × R     |

For a 2-for-1 split (R = 2): strike halved, multiplier doubled. Total contract value preserved.

The R-value is determined by the exchange or clearing house (listed) or by the calculation agent per ISDA equity-derivative definitions (OTC). It is delivered as a parameter update on the ex-date.

### Rights Issue (RHTS)

Option holders are not shareholders of record; the option contract is adjusted so that economic value is approximately preserved through the dilution. The adjustment form is event-specific (strike revision, deliverable change, multiplier change, or a combination) and determined by the exchange or calculation agent.

### Spin-Off, Merger, Takeover

Where the underlying's identity or composition changes, the treatment is determined case-by-case:

| Outcome         | Trigger                                                        | Option treatment                                                                        |
|-----------------|----------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| Basket option   | Spin-off or merger producing multiple securities               | `underlying` replaced by a basket; option terms adjusted to the basket composition       |
| Termination     | All-cash merger, delisting, or winding-up of the underlying    | Option terminated; intrinsic value (if any) paid as a final cash settlement              |
| Client election | Action terms offer the holder a choice of outcome              | Option remains `Active` pending election; treatment applied on receipt of election notice |

Where no standard determination applies, parties may agree a bespoke treatment recorded via the marker.

---

## CDM Representation

| Concept                         | CDM Type / Field                                                                                          |
|---------------------------------|-----------------------------------------------------------------------------------------------------------|
| Option product                  | `OptionPayout` within `ContractualProduct`; `BarrierInstructions` for barrier variants                    |
| Inception (long)                | `EventQualificationEnum.Execution`                                                                        |
| Premium                         | `Transfer` in the execution `BusinessEvent`                                                               |
| Barrier observation             | Bespoke `BarrierObservationEvent` (state-only)                                                            |
| Exercise notice                 | `EventQualificationEnum.Exercise`                                                                         |
| Expiry — auto-exercise          | `EventQualificationEnum.Exercise`                                                                         |
| Expiry — lapse                  | `EventQualificationEnum.ContractTermination` with `ClosedStateEnum.Lapsed`                                |
| KO termination                  | `EventQualificationEnum.ContractTermination` with bespoke `ClosedStateEnum.BarrierKnockOut`               |
| Cash settlement                 | `Transfer` in the settlement `BusinessEvent`                                                              |
| Physical settlement             | `Transfer` with `PhysicalSettlementTerms`                                                                 |
| Corporate-action adjustment     | Bespoke parameter-update event on the option `TradeState`                                                 |

### CDM Extensions

The compound unit state and bucketed/exercise-extended position state are global state-model features documented in [invariants.md](../invariants.md#state-model). The product-specific extensions required here are:

1. **`ClosedStateEnum.BarrierKnockOut`** — distinguishes a KO termination from `Lapsed` or `Exercised`.
2. **`EventQualificationEnum.BarrierObservation`** — first-class event type for barrier observations (both breach and non-breach), so the audit trail records the observation regardless of outcome. KI breach is a state event on the unit (sets `barrier_knocked_in` flag); KO breach drives termination.
3. **Exercise sub-bucket extension to position state** — the `Live` / `Exercised(date)` / `Assigned(date)` partition. Required for American/Bermudan products; degenerate (always `Live`) for European.

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [Option Payout](https://cdm.finos.org/docs/product-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Relationship to Other Smart Contracts

| Smart Contract       | Relationship                                                                                                                         |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| Equities             | Underlying delivery in physical settlement (§5b) follows [equities.md](equities.md): DvP at CSD; corporate-action mechanics on the underlying drive option product-state adjustments |
| Cash Payments        | The premium and cash settlements follow [cash_payments.md](cash_payments.md)                                                          |
| Structured Products  | An option payoff component embedded in a structured note (e.g. a knock-in put in a reverse convertible) is governed by this document; lifecycle events propagate to the note via the QRL ladder per [structured_products.md](structured_products.md) |
| QIS                  | A QIS composite unit may serve as the option underlying; the lifecycle is unchanged                                                  |
