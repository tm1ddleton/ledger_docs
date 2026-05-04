# Internal Treasury Funding Smart Contract

## Overview

This smart contract governs the internal funding facility through which trading desks borrow cash from, or lend cash to, the internal Treasury desk at the **internal funding rate (IFR)**. The facility funds the acquisition of non-cash assets: when a desk buys a stock, bond, or composite unit, Treasury provides the cash; when the desk sells, the cash is returned.

The defining feature of this facility is the **notional reset**: on a schedule set per legal entity, Treasury revalues the funded book by treating all non-cash assets as if they were liquidated at current mark-to-market and immediately repurchased. The repurchase value becomes the new funding notional. Cash flows for the MtM delta are settled on the revaluation date: if assets have appreciated, Treasury advances the increment; if assets have depreciated, the desk repays the decrement. This is structurally identical to a daily-resetting open repo, but applied to a portfolio rather than a named security, and using Treasury as an internal counterparty rather than an external one.

The result is that the desk's cash balance attributable to funded positions is always approximately zero: funded assets are matched by an equal and opposite outstanding funding notional. The economic cost to the desk is the stream of interest payments charged on the running notional.

This is the funded-assets analogue of variation margin on derivatives. The difference is:

| Feature                         | Variation margin (derivatives)             | Internal funding (cash assets)              |
|---------------------------------|--------------------------------------------|---------------------------------------------|
| Scope                           | Daily MtM change only                      | Full MtM (initial cost + daily change)      |
| First cash flow                 | None at inception                          | Funding advance at asset acquisition        |
| Subsequent cash flows           | Daily delta (VM call/return)               | Daily delta (revaluation advance/repayment) |
| Interest on cash balance        | Charged at IFR; swept into funding at reset | Charged on running funded notional at IFR   |
| Governed by                     | Derivative smart contract (e.g. irs.md)    | This contract (IFR charging)                |

---

## Scope

**In scope**: Internal cash borrowing for funded (non-derivative) long and short asset positions — equities, bonds, QIS composite units, structured product notes held as real assets, and exchange-delivered assets post-settlement. Net cash positions arising from variation margin on derivative contracts are also in scope: VM flows credit or debit the desk's cash book and are swept into the funding facility at each revaluation, funded at IFR.

**Out of scope**:
- Initial margin (IM) posted to a CCP or bilateral counterparty — IM flows are governed by the relevant derivative smart contract and are excluded from this facility; see [invariants.md](../invariants.md)
- External repos, securities lending, or prime brokerage arrangements — these are separate legal agreements
- Variation margin flows themselves — governed by the relevant derivative smart contract; only the resulting net cash balance in the desk book is in scope here for IFR charging
- FVA (funding valuation adjustment) for OTC derivatives — a pricing adjustment, not a ledger position
- FX forward points and cross-currency basis — any cross-currency component of funding is achieved via an FX transaction governed by [fx.md](fx.md); this contract handles single-currency funding only

---

## Key Concepts

### Funding Position

One funding position per (book, currency). All non-cash assets held in that book and denominated in that currency are aggregated into a single notional. This is a **book-level** facility: Treasury faces the book, not individual assets.

For a long book the desk borrows from Treasury (negative cash balance offset by asset holdings). For a short book the desk lends to Treasury (positive cash balance offset by a short asset obligation). Both are represented as a single signed funding position per (book, currency).

### Internal Funding Rate (IFR)

Set by Treasury per currency. Comprises a base reference rate (e.g. SOFR for USD, €STR for EUR, SONIA for GBP) plus an internal credit and liquidity spread. A single IFR applies symmetrically to both long (borrowing) and short (lending) positions: there is no bid-offer spread. The desk pays IFR when net long (borrowing from Treasury) and receives IFR when net short (lending to Treasury).

### Notional Reset

On each revaluation date the lifecycle engine computes the new funding requirement from the MtM of non-cash assets and the desk's net cash balance since the last reset. The outstanding funding notional is reset to this value. The delta is cash-settled on the same value date:

```
Funding_new = MtM_assets − Cash_balance
Δ           = Funding_new − N_old

Δ > 0  →  Treasury advances Δ to the desk     (net funding requirement increased)
Δ < 0  →  Desk returns |Δ| to Treasury         (net funding requirement decreased)
Δ = 0  →  No cash flow; state event only
```

### Revaluation Schedule

Set per legal entity — all books in the same entity share the same schedule. Common schedules: daily end-of-day (most entities), weekly, or monthly. Interest always accrues on the post-reset notional from the reset date. Between reset dates, the notional is fixed and intraday MtM movements do not trigger cash flows.

---

## Parties and Wallets

| Party          | Wallet Type    | Description                                                                             |
|----------------|----------------|-----------------------------------------------------------------------------------------|
| Treasury       | Virtual wallet | Internal Treasury desk; provides and receives all funding cash                          |
| Desk Cash Book | Real wallet    | Receives funding advances; makes repayments and interest payments; carries cash balance |
| Desk Asset Book| Real wallet    | Holds funded non-cash assets; read by the lifecycle engine to compute portfolio MtM     |

---

## Lifecycle Events

### 1. Funding Inception — Asset Acquisition

**Trigger**: A non-cash asset settles into the desk's asset book. The asset smart contract governs the asset acquisition itself (see [equities.md](equities.md), [bonds.md](bonds.md), etc.). This smart contract governs the concurrent funding advance.

**Timing**: The funding advance is aligned to asset settlement date. Before settlement, the funding commitment is `Pending`; it becomes `Settled` on the same value date as the asset move.

**Transaction**: A funding advance equal to the cash consideration paid for the asset:

| Move            | From     | To              | Asset                               | State               |
|-----------------|----------|-----------------|-------------------------------------|---------------------|
| Funding advance | Treasury | Desk Cash Book  | Cash [CCY] (acquisition cost)       | `Pending → Settled` |

The advance replenishes the cash outflow made to acquire the asset, leaving the desk cash-flat with respect to the new position.

If a funding position already exists for the same (book, currency), the advance is additive: no new contract is created; the outstanding notional increases by the acquisition cost. If this is the first funded position in the book and currency, a new funding `TradeState` is created.

**Funding notional after event**: `N = N_prior + acquisition_cost`

CDM: `EventQualificationEnum.Execution` (new position) or `QuantityChangePrimitive` (add to existing); `Loan` `TradeState` created or updated.

---

### 2. Periodic Interest Accrual and Payment

Interest accrues daily on the outstanding funding notional from the last reset date at the applicable IFR:

```
Daily interest = N × IFR_applicable × (1 / day_count_denominator)
```

Day count conventions follow ISDA standards: Act/360 for USD, EUR, CHF; Act/365 for GBP, JPY, CAD.

The interest amount is calculable from the moment the reset notional and rate are known. On each interest payment date (monthly, or per entity convention), the accrued amount is settled:

| Move             | From           | To              | Asset                            | State                |
|------------------|----------------|-----------------|----------------------------------|----------------------|
| Interest payment | Desk Cash Book | Treasury        | Cash [CCY] (accrued interest)    | `Expected → Settled` |

`Expected` state is used: the amount is deterministic from the post-reset notional and the published IFR. The desk can accrue the liability from the reset date. Where the position is net short (desk has deposited cash with Treasury), the direction reverses and Treasury pays the desk at the same IFR.

CDM: `EventQualificationEnum.InterestPayment`; `Transfer` with `TransferStatusEnum`.

---

### 3. Notional Reset — Revaluation Event

**Trigger**: End-of-day on each revaluation date per the entity's schedule.

**Computation**: The lifecycle engine receives end-of-day MtM prices and the desk's net cash balance (including VM settlements, dividends, coupons, and any other cash flows since the last reset) and computes:

```
MtM_assets   = Σᵢ [ quantity_i × price_i ]    (non-cash assets in the book, in the funding currency)
Cash_balance = net cash in desk book since last reset (positive = surplus received; negative = deficit paid out)
Funding_new  = MtM_assets − Cash_balance
Δ            = Funding_new − N_old
```

The cash balance term captures variation margin, dividends, coupons, and any other cash flows that have settled in the book since the last revaluation. A surplus (e.g. VM receipt from a profitable derivative position) reduces the funding requirement; a deficit (e.g. VM payment on a loss-making position) increases it. Both are funded at the same IFR.

All non-cash assets are grouped by currency. Each currency group has its own funding position and revaluation computation; only assets denominated in the relevant currency contribute to each group's MtM sum.

**Case A — Assets appreciated (Δ > 0)**

Treasury advances additional cash to the desk equal to the MtM gain:

| Move                 | From     | To              | Asset              | State               |
|----------------------|----------|-----------------|--------------------|---------------------|
| Revaluation advance  | Treasury | Desk Cash Book  | Cash [CCY] (Δ)     | `Pending → Settled` |

**Case B — Assets depreciated (Δ < 0)**

Desk returns the MtM loss to Treasury:

| Move                   | From           | To       | Asset               | State               |
|------------------------|----------------|----------|---------------------|---------------------|
| Revaluation repayment  | Desk Cash Book | Treasury | Cash [CCY] (|Δ|)    | `Pending → Settled` |

**Case C — No change (Δ = 0)**

No move created. The notional is confirmed unchanged as a state event.

In all cases the funding `TradeState` is updated: `N_new = Funding_new`. Interest from the next period accrues on `N_new`. Any interest accrued on `N_old` since the last reset is crystallised and will be settled on the next interest payment date.

CDM: `EventQualificationEnum.Reset`; `QuantityChangePrimitive` updating the funding principal; concurrent `Transfer` (if Δ ≠ 0).

---

### 4. Partial Release — Asset Sale

**Trigger**: A non-cash asset settles out of the desk's asset book following a sale. The asset smart contract governs the disposal. This smart contract governs the concurrent partial funding repayment.

The repayment amount equals the funded notional attributable to the sold position. For a fully funded book where the notional tracks MtM, this equals the current MtM of the sold position:

```
Repayment = (quantity_sold / quantity_total) × N_current
```

This equals the sale proceeds for a fully funded book sold at the last reset MtM, plus or minus any intraday MtM movement between the last reset and the sale price. The variance from the sale price is captured at the next revaluation event.

| Move              | From           | To       | Asset                                 | State               |
|-------------------|----------------|----------|---------------------------------------|---------------------|
| Partial repayment | Desk Cash Book | Treasury | Cash [CCY] (proportional repayment)   | `Pending → Settled` |

**Funding notional after event**: `N = N_current − repayment`

CDM: `QuantityChangePrimitive` on the funding `TradeState`.

---

### 5. Funding Termination — Book Closed

**Trigger**: All funded assets have been disposed of and the book funding notional reaches zero, or the desk is wound down.

Any residual notional and any accrued but unpaid interest are settled in a final transaction on the termination date:

| Move              | From           | To       | Asset                             | State               |
|-------------------|----------------|----------|-----------------------------------|---------------------|
| Final repayment   | Desk Cash Book | Treasury | Cash [CCY] (residual notional)    | `Pending → Settled` |
| Accrued interest  | Desk Cash Book | Treasury | Cash [CCY] (accrued interest)     | `Expected → Settled`|

The funding `TradeState` transitions to `ClosedState.Terminated`.

CDM: `EventQualificationEnum.ContractTermination`.

---

### 6. IFR Rate Change

**Trigger**: Treasury publishes a new internal funding rate for the currency.

This is a state event on the smart contract. No moves are created. The new rate and its effective date are recorded on the funding `TradeState`. Interest from the effective date is computed at the new rate; interest for prior periods is unaffected.

CDM: No standard business event qualification — bespoke `RateUpdateEvent` required (see CDM extensions below).

---

## Short Positions

For a net short book the mechanics are symmetric but reversed:

- The desk has received cash from the short sale, which is deposited with Treasury.
- Treasury pays interest on the deposit at IFR (the same rate applies in both directions).
- On each revaluation: if the short position has fallen in MtM (a gain on the short), Treasury returns the delta to the desk. If it has risen (a loss), the desk deposits the delta with Treasury.
- On covering the short: the desk withdraws the funded notional from Treasury to fund the buy-back.

The same funding `TradeState` model applies with a negative outstanding notional. The sign of interest flows reverses: Treasury pays the desk.

---

## Multi-Currency Treatment

Non-cash assets and cash flows are grouped by currency. Each currency group is managed as an independent funding position within the same book:

- Separate `TradeState` per (book, currency)
- Separate IFR per currency
- Revaluation events across all currency groups occur on the same entity-level schedule but are computed independently
- Any FX translation risk between a funding currency and the book's reporting currency is a separate FX exposure managed via [fx.md](fx.md)

---

## CDM Representation

### Standard CDM Types

| Concept                        | CDM Type / Field                                                                   | Notes                                                                                          |
|--------------------------------|------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| Funding facility               | `Loan` product type                                                                | Open-term; variable principal; no fixed maturity                                               |
| Outstanding notional           | `Loan.notionalSchedule` → `NotionalStepSchedule`                                  | CDM notional schedule is designed for amortisation, repurposed here for MtM-driven resets     |
| Funding rate                   | `Loan.interestRate` → `FloatingRateSpecification`                                  | References internal benchmark observable rather than a published index                         |
| Interest payment               | `Transfer` with `EventQualificationEnum.InterestPayment`                           | Standard CDM cash transfer; `Expected → Settled`                                               |
| Revaluation cash advance       | `Transfer` with `EventQualificationEnum.Transfer`                                  | `Pending → Settled` on revaluation date                                                        |
| Notional update                | `QuantityChangePrimitive`                                                          | Applied to the `Loan` `TradeState` on each reset                                               |
| Termination                    | `EventQualificationEnum.ContractTermination`                                       | Standard CDM                                                                                   |
| Rate change                    | No standard CDM qualification — bespoke extension required                         | See CDM extension 4 below                                                                      |

### CDM Extension Points

**1. MtM-linked variable-notional loan (`MtMLinkedLoan`)**

CDM `Loan` supports scheduled notional amortisation via `NotionalStepSchedule`, but does not support a notional that is reset on each observation date to an externally-computed portfolio MtM. The `NotionalStepSchedule` requires predetermined amounts and dates; MtM resets are neither predetermined in amount nor necessarily on fixed calendar dates (they follow the entity's business day schedule). A bespoke `MtMLinkedLoan` product type is required, extending `Loan` with:

- `notionalResetFrequency`: the revaluation schedule (e.g. `BusinessDayAdjustmentEnum.FOLLOWING` applied to the entity's revaluation calendar)
- `coveredBookReference`: identifier of the desk's asset book whose non-cash positions are included in the MtM computation
- `coveredAssetFilter`: rules determining which positions contribute to the MtM total — in practice, all positions in the real asset wallet excluding cash, derivatives, and unsettled `Pending` moves
- `notionalObservable`: pointer to the lifecycle engine or risk system function that computes portfolio MtM

The `coveredBookReference` is the key linkage that gives this contract its book-level aggregation property, which has no CDM equivalent.

**2. Notional reset as a business event (`MtMResetEvent`)**

CDM's `QuantityChangePrimitive` supports notional changes but does not carry the observation semantics needed to distinguish an MtM-driven reset from a partial termination or scheduled amortisation. A bespoke `MtMResetEvent` is required, combining:

- `observationDate`: the revaluation date
- `observedMtM`: the portfolio MtM value computed by the lifecycle engine
- `priorNotional`: the notional before the reset
- `notionalDelta`: the resulting cash flow (signed; positive = Treasury advance, negative = desk repayment)
- `nextPeriodRate`: the IFR applicable from the reset date (may differ from the prior period if a rate change took effect)

This event simultaneously qualifies as a `Reset` (the fixing observation of portfolio MtM) and a `QuantityChangePrimitive` (the resulting notional change), with a concurrent `Transfer` for the cash delta. CDM does not have a compound event that combines all three; the bespoke `MtMResetEvent` wraps them.

**3. Internal funding rate as an `Observable` (`InternalFundingRate`)**

CDM `FloatingRateSpecification` references published rate indices (SOFR, €STR, SONIA, etc.) via `FloatingRateIndex`. The internal funding rate is not a published index; it is a proprietary rate set by Treasury and distributed to desk smart contracts via an internal rate publication system. A bespoke `InternalFundingRate` observable is required, extending `FloatingRateIndex` with:

- `currency`: the currency of the funding leg
- `rateSource`: reference to the Treasury system that publishes the IFR (analogous to a screen page reference for market rates)
- `effectiveDate`: the date from which this rate is applicable — enables mid-period rate changes with correct interest proration

A single rate applies in both directions (no bid-offer spread); no `rateType` distinction is needed.

**4. Rate change event (`IFRUpdateEvent`)**

CDM has no business event qualification for a rate change on an existing loan (it has rate resets on floating instruments, but these are scheduled and driven by a market index, not by a discretionary internal change). A bespoke `IFRUpdateEvent` is required with:

- `effectiveDate`: the date from which the new rate applies
- `priorRate`: the previous IFR (for audit and P&L attribution)
- `newRate`: the new IFR
- `currency` and `rateType`: to identify which rate tier is updated

---

## Relationship to Other Smart Contracts

| Smart Contract     | Relationship                                                                                                                          |
|--------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| Equities           | Equity settlement triggers funding inception (§1) and partial release (§4). Ex-date dividend receipts are in [cash_payments.md](cash_payments.md) and do not directly affect funding notional until the next revaluation |
| Bonds              | Bond settlement triggers funding inception and partial release. Coupon cash receipts credit the desk's cash book; their effect on the funding notional is captured at the next revaluation |
| QIS                | Funded composite unit subscription triggers funding inception. NAV changes between subscriptions and redemptions drive revaluation advances and repayments |
| FX                 | Cross-currency asset positions are funded in their asset currency. Any residual FX exposure from the difference between the asset currency and the book's reporting currency is managed via an FX transaction in [fx.md](fx.md), not by this contract |
| IRS / Derivatives  | Unfunded. Initial margin is out of scope for this contract. Variation margin flows governed by the derivative smart contract settle into the desk's cash book and are swept into the funding facility at each revaluation, with the net VM balance funded at IFR |
| Equity Options     | OTC option premium paid upfront creates a funded position at premium settlement. Initial margin for listed options is out of scope for this contract                              |

---

## Failure Handling

| Scenario                                               | Action                                                                                                                   |
|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| MtM unavailable on revaluation date                   | Revaluation deferred to the next business day. Interest continues to accrue on the prior notional. No `Failed` state — this is a data delay, not a payment failure. Operations notified |
| Interest payment fails (insufficient desk cash)        | Two-tier model per [invariant 8](../invariants.md#core-ledger-invariants): `Pending` retry; `Failed` if definitively unresolvable. Escalated to Treasury operations and credit risk |
| IFR not published on expected publication date         | Prior rate continues to apply. A catch-up interest adjustment is computed and applied on the next publication date as an additional `Expected` move |
| Revaluation advance or repayment fails                | Two-tier model as above. Outstanding delta is carried as an `Instructed` move until settled; it does not affect the notional reset, which has already occurred as a state event |
| Book closed with outstanding funding position          | Funding must be terminated before book closure. Any residual notional is force-repaid via a `Pending` move flagged for operations review. Outstanding accrued interest is included in the final settlement |
| Partial sale price differs materially from reset MtM  | The cash flow mismatch (sale price minus last reset MtM of sold position) is an intraday MtM exposure. It is automatically corrected at the next revaluation event and does not require manual intervention |
