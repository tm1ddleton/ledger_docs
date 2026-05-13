# Lifecycle Events

## Overview

This document is the canonical cross-reference of lifecycle events across all smart contracts in this repository and records each event's representation in the FINOS Common Domain Model (CDM). Events that are pure state transitions on existing moves are distinguished from events that create new ledger transactions.

CDM qualifications use `EventQualificationEnum` values unless marked `†` (bespoke extension required). All events are subject to [invariants.md](invariants.md).

---

## QRL-Issued Events

QRL is the observation / event ladder that drives smart contract invocations. Each smart contract subscribes to events relevant to its product state and is invoked when QRL emits one. The supported QRL event types are:

| Event               | Purpose                                                                                                              |
|---------------------|----------------------------------------------------------------------------------------------------------------------|
| `BarrierMonitoring` | A scheduled or continuous-monitoring barrier observation date. Carries the observed reference level. Consumed by smart contracts with barrier features (equity options, structured products) to evaluate breach. |
| `IndexObservation`  | A scheduled observation of an index, NAV, or basket level (e.g. autocall observation, QIS NAV computation, structured-product observation date). |
| `StrikeObservation` | An observation that determines or fixes a strike (e.g. forward-start strike fixing, lookback strike determination, average-strike observation contributing to the strike calculation). |
| `CashPayment`       | A scheduled cash-flow date (coupon, dividend record date, fixed leg payment, principal redemption). Triggers the smart contract to compute and book the cash move per [cash_payments.md](smart_contracts/cash_payments.md). |
| `Termination`       | A scheduled or triggered contract-termination event (expiry, maturity, exercise, knock-out). Drives the unit-state liveliness transition `Active → Matured` and the creation of any final settlement transaction. |
| `PhysicalDelivery`  | The settlement leg of a physically-settled contract (option exercise, futures physical delivery, structured-product share redemption). Triggers the smart contract to book the underlying delivery and any associated cash payment. |
| `CorporateAction`   | An ISIN-level corporate action ready for application. Payload carries the per-listing adjustment values (R-values, cash amounts, deliverable substitutions, withholding rates) and the action type (split, dividend, scrip, rights, spin-off, etc.). Triggers atomic application across all subscribed positions per [invariant 12](invariants.md#core-ledger-invariants) and the [Corporate Action Orchestration](invariants.md#corporate-action-orchestration) model. |

Per [invariant 10](invariants.md#core-ledger-invariants), each event is delivered idempotently: replays are no-ops by virtue of the unit state's last-lifecycle-event marker.

---

## Contract Abbreviations

| Abbr | Smart Contract                                                               |
|------|------------------------------------------------------------------------------|
| Eq   | [Cash Equities](smart_contracts/equities.md)                                 |
| Fut  | [Futures](smart_contracts/futures.md)                                        |
| Fund | [Internal Treasury Funding](smart_contracts/funding.md)                      |
| Opt  | [Equity Options](smart_contracts/equity_options.md)                          |
| Bond | [Bonds](smart_contracts/bonds.md)                                            |
| FX   | [FX — Spot, Forward, Swap, NDF](smart_contracts/fx.md)                       |
| IRS  | [Interest Rate Swaps](smart_contracts/irs.md)                                |
| QIS  | [Quantitative Investment Strategies](smart_contracts/qis.md)                 |
| SP   | [Structured Products](smart_contracts/structured_products.md)                |
| Cash | [Standalone Cash Payments](smart_contracts/cash_payments.md)                 |
| SBL  | [Stock Borrow / Loan](smart_contracts/stock_borrow_loan.md)                  |

---

## Lifecycle Event Cross-Reference

`✓` — event applies to this contract.

### Inception and Booking

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Trade Execution                                | ✓     | ✓     |       | ✓     | ✓     | ✓     | ✓     |       |       |       | ✓     |
| Strategy Inception                             |       |       |       |       |       |       |       | ✓     |       |       |       |
| Structured Product Creation                    |       |       |       |       |       |       |       |       | ✓     |       |       |
| Composite Unit Issuance                        |       |       |       |       |       |       |       | ✓     | ✓     |       |       |
| Note Distribution to Client                    |       |       |       |       |       |       |       |       | ✓     |       |       |
| Funding Inception (asset acquisition)          |       |       | ✓     |       |       |       |       |       |       |       |       |
| QRL Schedule Generation                        |       | ✓     |       | ✓     | ✓     | ✓     | ✓     |       |       |       | ✓     |
| CCP Novation / Clearing                        |       |       |       | ✓     |       |       | ✓     |       |       |       |       |

### Settlement

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Settlement Instruction Generated               | ✓     |       | ✓     | ✓     | ✓     | ✓     | ✓     |       |       | ✓     | ✓     |
| Settlement Confirmed (DvP / DvD / FoP)        | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     |       | ✓     | ✓     | ✓     |
| Settlement Attempt Failed — Pending            | ✓     |       | ✓     | ✓     | ✓     | ✓     | ✓     |       | ✓     | ✓     | ✓     |
| Bilateral Cancellation — Failed (terminal)     | ✓     |       |       | ✓     | ✓     | ✓     | ✓     |       | ✓     | ✓     | ✓     |
| Buy-in Triggered                               | ✓     |       |       |       | ✓     |       |       |       |       |       | ✓     |
| Post-Settlement Reversal                       | ✓     |       |       |       | ✓     | ✓     | ✓     |       |       | ✓     |       |
| Payment Netting                                |       |       |       |       |       | ✓     | ✓     |       |       |       |       |
| Herstatt Risk Resolution (bilateral FX)        |       |       |       |       |       | ✓     |       |       |       |       |       |

### Daily and Periodic Mark-to-Market

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| EOD Settlement — VM Allocation (Tier 1)        |       | ✓     |       |       |       |       |       |       |       |       |       |
| EOD Settlement — VM External Payment (Tier 2)  |       | ✓     |       |       |       |       |       |       |       |       |       |
| NewTrade → RunningPosition Transition          |       | ✓     |       |       |       |       |       |       |       |       |       |
| Notional Reset / Revaluation                   |       |       | ✓     |       |       |       |       |       |       |       |       |
| SBL Collateral Margin Call / Return            |       |       |       |       |       |       |       |       |       |       | ✓     |
| IFR Rate Change                                |       |       | ✓     |       |       |       |       |       |       |       |       |

### Rate Observations and Fixings

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Floating Rate Fixing (FRN / IRS)               |       |       |       |       | ✓     |       | ✓     |       |       |       |       |
| NDF Rate Fixing                                |       |       |       |       |       | ✓     |       |       |       |       |       |
| Barrier Observation (no breach)                |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| NAV / Index Level Computation                  |       |       |       |       |       |       |       | ✓     |       |       |       |

### Income and Cash Payments

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Coupon Schedule Generation (QRL)               |       |       |       |       | ✓     |       | ✓     |       | ✓     |       |       |
| Coupon / Interest Payment                      |       |       | ✓     |       | ✓     |       | ✓     |       | ✓     | ✓     | ✓     |
| Dividend Receipt — Ex-Date Booking             | ✓     |       |       |       |       |       |       | ✓     |       | ✓     |       |
| Manufactured Payment (income on loaned stock)  |       |       |       |       |       |       |       |       |       |       | ✓     |
| CSD Pre-Advice (Expected → Instructed)         | ✓     |       |       |       | ✓     |       |       |       |       | ✓     |       |
| Expected Receipt Booked (standalone)           |       |       |       |       |       |       |       |       |       | ✓     |       |
| Income Distribution (QIS Model A)              |       |       |       |       |       |       |       | ✓     |       |       |       |
| IFR Interest Accrual and Payment               |       |       | ✓     |       |       |       |       |       |       |       |       |

### Margin

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Initial Margin Post                            |       | ✓     |       | ✓     |       |       | ✓     |       |       |       |       |
| Initial Margin Return / Additional Call        |       | ✓     |       | ✓     |       |       | ✓     |       |       |       |       |
| Variation Margin Call / Receipt                |       | ✓     |       | ✓     |       |       | ✓     |       |       |       |       |

### Option Lifecycle

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Knock-Out Barrier Triggered                    |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Knock-In Barrier Triggered                     |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| KO Rebate Payment                              |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Barrier Propagation (Option → Note)            |       |       |       |       |       |       |       |       | ✓     |       |       |
| Option Exercise — Cash Settlement              |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Option Exercise — Physical Settlement          |       |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Option Lapse (OTM / KI never triggered)        |       |       |       | ✓     |       |       |       |       | ✓     |       |       |

### Termination and Maturity

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Maturity (scheduled; final payment)            |       | ✓     |       | ✓     | ✓     |       | ✓     |       | ✓     |       | ✓     |
| Futures Expiry — Cash Settlement               |       | ✓     |       |       |       |       |       |       |       |       |       |
| Futures Expiry — Physical Delivery             |       | ✓     |       |       |       |       |       |       |       |       |       |
| Futures Position Close / Partial Close         |       | ✓     |       |       |       |       |       |       |       |       |       |
| NDF Maturity / Unit Extinguishment             |       |       |       |       |       | ✓     |       |       |       |       |       |
| FX Early Termination (pre-settlement)          |       |       |       |       |       | ✓     |       |       |       |       |       |
| Bond — Early Redemption by Issuer (Call)       |       |       |       |       | ✓     |       |       |       | ✓     |       |       |
| Bond — Early Redemption by Holder (Put)        |       |       |       |       | ✓     |       |       |       |       |       |       |
| Bond Conversion (Convertible)                  |       |       |       |       | ✓     |       |       |       |       |       |       |
| Bond Sale (Secondary Market)                   |       |       |       |       | ✓     |       |       |       |       |       |       |
| Issuer Default                                 |       |       |       |       | ✓     |       |       |       |       |       |       |
| Partial Return / Partial Termination           |       |       | ✓     |       |       |       | ✓     |       |       |       | ✓     |
| Full Termination / Loan Termination            |       |       | ✓     | ✓     |       | ✓     | ✓     |       |       |       | ✓     |
| Recall (lender-initiated)                      |       |       |       |       |       |       |       |       |       |       | ✓     |
| Collateral Substitution                        |       |       |       |       |       |       |       |       |       |       | ✓     |
| Funding Termination (book closed)              |       |       | ✓     |       |       |       |       |       |       |       |       |
| Composite Unit Redemption                      |       |       |       |       |       |       |       | ✓     | ✓     |       |       |
| Strategy Termination                           |       |       |       |       |       |       |       | ✓     |       |       |       |
| Note Redemption — Cash                         |       |       |       |       |       |       |       |       | ✓     |       |       |
| Note Redemption — Physical (share delivery)    |       |       |       |       |       |       |       |       | ✓     |       |       |

### QIS Rebalancing

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Periodic Rebalancing — Model A (constituent)   |       |       |       |       |       |       |       | ✓     |       |       |       |
| Roll Event — Model B (return-stream)           |       |       |       |       |       |       |       | ✓     |       |       |       |

### Corporate Actions

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Cash Dividend                                  | ✓     |       |       |       |       |       |       | ✓     | ✓     | ✓     |       |
| Stock Split / Reverse Split / Scrip Dividend   | ✓     |       |       | ✓     |       |       |       |       |       |       |       |
| Spin-Off                                       | ✓     |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Merger / Takeover                              | ✓     |       |       | ✓     |       |       |       |       | ✓     |       |       |
| Rights Issue                                   | ✓     |       |       | ✓     |       |       |       |       |       |       |       |
| Other Corporate Action                         | ✓     |       |       |       |       |       |       |       |       |       |       |

### Amendments and Corrections

| Event                                          | Eq    | Fut   | Fund  | Opt   | Bond  | FX    | IRS   | QIS   | SP    | Cash  | SBL   |
|------------------------------------------------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| Amendment — Cancel / Correct (Invariant 7)     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     | ✓     |

---

## CDM Event Reference

`†` = bespoke extension required; no standard CDM equivalent.
`—` = state transition on existing move(s); no new transaction created.

### Inception and Booking

| Event                              | CDM Qualification                                    | Ext | Initial Move State / Notes                                   |
|------------------------------------|------------------------------------------------------|-----|--------------------------------------------------------------|
| Trade Execution                    | `Execution`                                          |     | Varies by contract; see individual smart contract docs       |
| Loan Open (SBL)                    | `Execution`                                          |     | `Pending` (securities + collateral legs settle T+2; DvD or DvP) |
| Strategy Inception                 | `Execution` (`PortfolioState`)                       |     | `Settled` (simulated wallet; no pending settlement)          |
| Structured Product Creation        | `Execution` (three products simultaneously)          | †   | `Settled`; `StructuredProductCreationPrimitive` wraps three `ExecutionPrimitive`s |
| Composite Unit Issuance            | `Transfer`                                           |     | `Instructed → Settled`; subscription cash `Pending`          |
| Note Distribution to Client        | `Transfer`                                           |     | `Instructed → Settled`                                       |
| Funding Inception                  | `Execution` (new) / `QuantityChangePrimitive` (add)  |     | `Pending → Settled`                                          |
| QRL Schedule Generation            | — (internal event; no CDM qualification)             |     | Produces `Expected` moves at inception; for SBL produces manufactured payment schedule |
| CCP Novation / Clearing            | `ClearingInstruction` / `NovationInstruction`        |     | Bilateral moves → `Failed`; new cleared moves → `Expected`   |

### Settlement

| Event                              | CDM Qualification             | Ext | Move State Transition                                        |
|------------------------------------|-------------------------------|-----|--------------------------------------------------------------|
| Settlement Instruction Generated   | —                             |     | `Pending → Instructed`                                       |
| Settlement Confirmed               | —                             |     | `Instructed → Settled`                                       |
| Settlement Attempt Failed          | —                             |     | `Instructed → Pending` (non-terminal; obligation persists)   |
| Bilateral Cancellation             | —                             |     | `Pending` / `Instructed → Failed` (terminal; no reversal)    |
| Buy-in Triggered                   | —                             |     | Original → `Failed`; new `Execution` transaction created     |
| Post-Settlement Reversal           | `Execution` (reversal)        |     | New mirror-image moves written directly as `Settled`         |
| Payment Netting                    | —                             | †   | Gross moves → `Failed`; single net move created → `Pending`  |
| Herstatt Risk Resolution           | —                             |     | Settled leg reversed per Invariant 6, or `Failed` if irrecoverable |

### Daily and Periodic Mark-to-Market

| Event                                         | CDM Qualification               | Ext | Move State / Notes                                            |
|-----------------------------------------------|---------------------------------|-----|---------------------------------------------------------------|
| EOD Settlement — VM Allocation (Tier 1)       | `DailySettlementEvent`          | †   | Internal cash move (Desk ↔ EFB); `Settled` immediately        |
| EOD Settlement — VM External Payment (Tier 2) | `DailySettlementEvent`          | †   | External cash move (EFB ↔ CCP); `Expected → Instructed → Settled` |
| NewTrade → RunningPosition Transition         | `DailySettlementEvent`          | †   | — (state event on futures unit; no new move)                  |
| Notional Reset / Revaluation                  | `Reset` / `MtMResetEvent`       | †   | `Pending → Settled` (if Δ ≠ 0); state event only (if Δ = 0)  |
| SBL Collateral Margin Call / Return           | `MarkToMarketCollateralCall`    | †   | `Pending` (additional collateral due) / `Expected` (excess returned) |
| IFR Rate Change                               | `IFRUpdateEvent`                | †   | — (state event on funding `TradeState`; no move created)      |

### Rate Observations and Fixings

| Event                              | CDM Qualification              | Ext | Move State / Notes                                           |
|------------------------------------|--------------------------------|-----|--------------------------------------------------------------|
| Floating Rate Fixing (FRN / IRS)   | `Reset` / `ResetPrimitive`     |     | Amount crystallised on existing `Expected` move; state unchanged |
| NDF Rate Fixing                    | `Reset` / `Observation`        |     | — (state event; net settlement amount recorded; no new move) |
| Barrier Observation (no breach)    | `Observation`                  |     | — (state event only; option unit remains `Active`)           |
| NAV / Index Level Computation      | `Observation` + `Reset`        |     | — (no new moves unless rebalancing also triggered)           |

### Income and Cash Payments

| Event                              | CDM Qualification              | Ext | Initial Move State                                           |
|------------------------------------|--------------------------------|-----|--------------------------------------------------------------|
| Coupon Schedule Generation         | — (anticipatory booking)       |     | `Expected`; full schedule created at inception via QRL       |
| Coupon / Interest Payment          | `InterestPayment` / `CashTransfer` |  | `Expected → Pending → Instructed → Settled`                  |
| SBL Rebate Payment                 | `InterestPayment`              |     | `Expected` (desk is borrower) / `Pending` (desk is lender)   |
| SBL Lending Fee Payment            | `InterestPayment`              |     | `Pending` (desk is borrower) / `Expected` (desk is lender)   |
| Manufactured Payment               | `ManufacturedPaymentEvent`     | †   | `Expected` (desk is lender) / `Pending` (desk is borrower); ex-date trigger |
| Dividend Receipt — Ex-Date Booking | — (anticipatory booking)       |     | CSD receipt `Expected`; internal allocation `Pending`        |
| CSD Pre-Advice                     | —                              |     | `Expected → Instructed`                                      |
| Expected Receipt Booked            | — (anticipatory booking)       |     | `Expected`                                                   |
| Income Distribution (QIS Model A)  | — (anticipatory booking)       |     | `Expected` (dividend accrual on ex-dividend date)            |
| IFR Interest Accrual and Payment   | `InterestPayment`              |     | `Expected → Settled`                                         |

### Margin

| Event                              | CDM Qualification                                        | Ext | Initial Move State                                      |
|------------------------------------|----------------------------------------------------------|-----|---------------------------------------------------------|
| Initial Margin Post                | `MarginCall` (`PostInitialMargin`)                       |     | `Pending → Instructed → Settled`                        |
| Initial Margin Return / Top-up     | `MarginCall` (`ReturnInitialMargin`)                     |     | `Expected → Instructed → Settled`                       |
| Variation Margin Call / Receipt    | `MarginCall` (`DailyVariationMargin`)                    |     | `Pending` (desk pays) / `Expected` (desk receives)      |

### Option Lifecycle

| Event                              | CDM Qualification                         | Ext | Initial Move State / Notes                                   |
|------------------------------------|-------------------------------------------|-----|--------------------------------------------------------------|
| Knock-Out Barrier Triggered        | `BarrierKnockOut`                         | †   | Option unit → `Pending`; rebate (if any) `Pending`/`Expected` |
| Knock-In Barrier Triggered         | `BarrierKnockIn`                          | †   | — (state event; option unit remains `Active`)                |
| KO Rebate Payment                  | —                                         |     | Immediate rebate: `Pending`; deferred rebate: `Expected`     |
| Barrier Propagation (Option → Note)| `BarrierPropagationEvent`                 | †   | Note state → `BarrierBreached` (state event; no new moves)   |
| Option Exercise — Cash Settlement  | `Exercise`                                |     | Option unit + cash settlement → `Pending`; settle T+2        |
| Option Exercise — Physical         | `Exercise` + `PhysicalSettlementTerms`    |     | Option unit `Pending`; equity delivery `Instructed`          |
| Option Lapse                       | `Exercise` (lapsed)                       |     | Option unit → `Pending → Settled`; `Lapsed` closing reason   |

### Termination and Maturity

| Event                                      | CDM Qualification                            | Ext | Initial Move State / Notes                                   |
|--------------------------------------------|----------------------------------------------|-----|--------------------------------------------------------------|
| Maturity (scheduled; final payment)        | — (final coupon; no special qualification)   |     | Existing `Expected` moves advance through payment state flow |
| SBL Maturity / Loan Termination            | `ContractTermination`                        |     | Securities return `Pending`; collateral release `Expected`; final fee `Expected`/`Pending` |
| Futures Expiry — Cash Settlement           | `ContractTermination`                        |     | Extinguishment `Pending`; final VM `Expected`                |
| Futures Expiry — Physical Delivery         | `ContractTermination`                        |     | Per underlying contract (equities.md / bonds.md)             |
| Futures Position Close                     | `Execution` (offsetting trade)               |     | `Settled` (futures unit); `NewTrade` state until EOD         |
| NDF Maturity / Unit Extinguishment         | `ContractTermination`                        |     | `Pending`; NDF state `Active → Matured → Terminated`         |
| FX Early Termination (pre-settlement)      | —                                            |     | `Pending` / `Instructed → Failed`; no reversal               |
| Bond — Early Redemption by Issuer (Call)   | `EarlyTerminationProvision`                  |     | Bond return `Instructed`; redemption cash `Expected`         |
| Bond — Early Redemption by Holder (Put)    | `OptionalEarlyTermination`                   |     | Same move structure as call redemption                       |
| Bond Conversion (Convertible)              | `ConversionFeature`                          |     | Bond units extinguished `Instructed`; equity units created   |
| Bond Sale (Secondary Market)               | `Execution`                                  |     | `Instructed` (exchange) / `Pending` (OTC)                    |
| Issuer Default                             | —                                            |     | All outstanding `Expected` / `Instructed` income → `Failed`  |
| Partial Return / Partial Termination       | `QuantityChange` / `QuantityChangePrimitive` |     | Future `Expected` → `Failed` (IRS/Fund); proportional collateral release (SBL) |
| Full Termination / Early Break             | `Termination` / `ContractTermination`        |     | Future `Expected` → `Failed`; termination / final payment `Pending` |
| Recall (lender-initiated)                  | `RecallEvent`                                | †   | State event on recall date; settlement moves `Pending` / `Expected` with recall date |
| Collateral Substitution                    | `CollateralSubstitutionEvent`                | †   | New collateral `Pending`; old collateral `Expected`; atomic DvD |
| Funding Termination (book closed)          | `ContractTermination`                        |     | Residual notional `Pending`; accrued interest `Expected`     |
| Composite Unit Redemption                  | `Transfer` / `ContractTermination`           |     | Units `Instructed`; redemption cash `Expected` (funded) / `Pending` (unfunded loss) |
| Strategy Termination                       | `ContractTermination`                        |     | Simulated wallet unwound; all units retired                  |
| Note Redemption — Cash                     | `ContractTermination`                        |     | `Expected → Settled`; all three product `TradeState`s closed |
| Note Redemption — Physical (share delivery)| `OptionExercise` + `ContractTermination`     | †   | `NotePhysicalRedemptionEvent`; shares `Pending`; bond principal internal |

### QIS Rebalancing

| Event                                      | CDM Qualification                         | Ext | Move State / Notes                                           |
|--------------------------------------------|-------------------------------------------|-----|--------------------------------------------------------------|
| Periodic Rebalancing — Model A             | `Rebalancing` / `QuantityChangePrimitive` | †   | `Settled` (simulated wallet moves always settle immediately) |
| Roll Event — Model B (return-stream)       | Compound `QuantityChangePrimitive`        | †   | Exit old stream + enter new stream; `Settled`; notional adjusted for roll return |

### Corporate Actions

| Event                                          | CDM Qualification                                    | Ext | Notes                                                                                                   |
|------------------------------------------------|------------------------------------------------------|-----|---------------------------------------------------------------------------------------------------------|
| Cash Dividend                                  | `CashDividend`                                       |     | Tax at wallet and jurisdiction level; withholding may apply to synthetic instruments above a given delta |
| Stock Split / Reverse Split / Scrip Dividend   | `StockSplit` / `ReverseStockSplit` / `StockDividend` |     | Quantity change via CSD move; R-value adjustment applied to options on the affected security            |
| Spin-Off                                       | `SpinOff`                                            |     | Results in basket or termination; case-by-case; may be at client's discretion; see equity_options.md   |
| Merger / Takeover                              | `Merger` / `Takeover`                                |     | Results in basket or termination; case-by-case; may be at client's discretion; see equity_options.md   |
| Rights Issue                                   | `RightsIssue`                                        |     | Rights units via CSD move; new smart contract with exercise event; options adjusted to preserve value   |
| Other Corporate Action                         | Various / `BespokeEvent`                             |     | Per equities.md corporate actions table                                                                 |

### Amendments and Corrections

| Event                              | CDM Qualification         | Ext | Move State / Notes                                           |
|------------------------------------|---------------------------|-----|--------------------------------------------------------------|
| Amendment — Cancel / Correct       | Cancel + new `Execution`  |     | Not-yet-`Settled` moves → `Failed`; `Settled` moves reversed per Invariant 6; corrected moves created |

---

## Invariant Compliance Notes

### 1. Corporate Action Lifecycle — Partially Specified

Cash dividends, stock splits, reverse stock splits, and scrip dividends are now specified in `equities.md` (including dividend tax treatment and index composition considerations) and `equity_options.md` (R-value adjustment to strike and contract size). Spin-offs, mergers, and takeovers have a defined approach (basket or cash termination; determined case-by-case; client discretion possible) in both documents. The remaining corporate action types enumerated in `equities.md` (Delisting, StockNameChange, StockIdentifierChange, BonusIssue, ClassAction, EarlyRedemption, Liquidation, BankruptcyOrInsolvency, IssuerNationalization, Relisting, BespokeEvent) are not yet fully specified.

### 2. SBL CDM Coverage — Partial

CDM v5 covers approximately two-thirds of GMSLA lifecycle events. Four bespoke extensions are required for this implementation (`MarkToMarketCollateralCall`, `RecallEvent`, `ManufacturedPaymentEvent`, `CollateralSubstitutionEvent`) — see [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md) §CDM Extensions. The ISLA CDM Working Group is actively developing the remaining coverage; extensions should be reviewed against future CDM releases as they are merged.

### 3. Core Invariants — All Verified Compliant

All nine core ledger invariants and the Exchange Trade Booking Model invariant are correctly applied across all smart contracts:

- **Invariant 6** (cancellation by reversal): applied only to post-`Settled` cancellations; correctly not applied to pre-`Settled` cancellations.
- **Invariant 7** (amendment as cancel/correct): correctly implemented in IRS partial termination, FX netting, bond partial sale, QIS provisional rebalancing, and SBL loan term amendments.
- **Invariant 8** (two-tier failure): `Failed` used as terminal state consistently; `Pending` as non-terminal retry state. No contract uses `Failed` for a non-terminal outcome.
- **Invariant 9** (wallet balance views): `Expected` state correctly visible in the live balance and excluded from the settled balance in all contracts that use it (bonds, IRS, futures, funding, structured products, cash payments, SBL).
