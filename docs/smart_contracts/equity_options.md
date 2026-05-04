# Equity Options Smart Contract

## Overview

This smart contract governs the booking and lifecycle of equity options: vanilla European and American options, and barrier options (knock-out and knock-in, single and double barrier, discrete and continuous monitoring). It covers both cash-settled and physically-settled variants, and the margining model for exchange-listed options.

**Role of QRL**: QRL is the pricing library. Given the option's trade terms, QRL can specify what market data observations it requires and at what dates to value the product from inception to expiry. The smart contract layer consumes QRL's output to determine state transitions (e.g. is a barrier breached? is the option in the money at expiry?) and generates the resulting lifecycle events and moves to the ledger. QRL implicitly defines the smart contract's event schedule.

---

## Product Scope

| Product                         | Exercise Style | Settlement        |
|---------------------------------|----------------|-------------------|
| Vanilla call / put              | European       | Cash or physical  |
| Vanilla call / put              | American       | Cash or physical  |
| Single-barrier knock-out (KO)   | European       | Cash or physical  |
| Single-barrier knock-in (KI)    | European       | Cash or physical  |
| Double-barrier KO               | European       | Cash or physical  |
| KO with rebate                  | European       | Cash rebate + termination |
| Exchange-listed call / put      | American       | Cash or physical via CCP |

---

## Parties and Wallets

| Party                  | Wallet Type    | Description                                                                                      |
|------------------------|----------------|--------------------------------------------------------------------------------------------------|
| Option Desk Book       | Real wallet    | Holds the option unit position and cash flows for the life of the contract                       |
| Counterparty           | Virtual wallet | The other party to an OTC option; seller of the option unit at execution                         |
| CCP                    | Virtual wallet | Exchange-listed options only; the central counterparty post-clearing                             |
| CCP Margin Account     | Real wallet    | Exchange-listed options only; holds posted initial margin against the CCP                        |
| Equity Wallet          | Real wallet    | Physically-settled options only; the desk's equity holding wallet (see [equities.md](equities.md)) |

---

## Option Unit

An option contract is represented in the ledger as an **option unit** — a non-fungible contract unit held in the Option Desk Book. This is consistent with the NDF unit model in [fx.md](fx.md): the contract position is a first-class ledger asset visible in the live balance from execution.

The option unit is created at execution (seller's wallet → buyer's wallet) and extinguished at termination (buyer's wallet → seller's wallet / CCP). CDM represents this position as a `TradeState` rather than a transferable unit; the ledger deviates by representing it as a unit move, while the CDM `TradeState` lifecycle maps onto the option unit's states.

### Option Unit States

These states are carried on the smart contract and are distinct from the payment move states in [invariants.md](../invariants.md), which govern cash and delivery moves.

| State       | Meaning                                                                                                                                                            | CDM Mapping                                                                              |
|-------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| `Active`    | Option is live; exercisable (American) or pending expiry (European); monitoring in progress for barriers                                                           | `TradeState` with no `closedState`                                                       |
| `Matured`   | Contractual lifetime has ended (expiry date reached, KO triggered, or KI expired without activation) but outstanding cash or delivery obligations remain unsettled | **Bespoke extension** — CDM has no intermediate matured state; see §CDM Extensions      |
| `Terminated`| All obligations discharged; option unit fully extinguished                                                                                                          | `TradeState.closedState`; closing reason varies by event (see below)                    |

---

## Premium

The option premium is a standalone cash payment governed by [cash_payments.md](cash_payments.md). It is created simultaneously with the option unit in a single execution transaction:

| Move           | From                    | To                      | Asset                  | Initial State               |
|----------------|-------------------------|-------------------------|------------------------|-----------------------------|
| Option unit    | Counterparty            | Option Desk Book        | 1 option unit          | `Instructed → Settled`      |
| Premium        | Option Desk Book        | Counterparty            | Cash (agreed premium)  | `Pending`                   |

The option unit transitions to `Settled` and `Active` on trade confirmation. The premium follows the standard payment lifecycle (`Pending → Instructed → Settled`) and typically settles T+2 for OTC options.

For exchange-listed options, the premium is either paid upfront (e.g. OCC-cleared US equity options) or settled daily via variation margin (futures-style). The applicable convention is determined by the exchange and CCP; see [Exchange-Listed Margining](#exchange-listed-options-margining).

**Sold options**: the direction of both moves reverses. The desk receives the premium (`Expected` per cash_payments.md) and delivers the option unit.

---

## CDM State Model

### Contract States

The CDM `TradeState` governs the option contract. All terminal paths pass through `Matured` before reaching `Terminated`: the option transitions to `Matured` on the contractual end event and to `Terminated` once all resulting cash and delivery obligations have settled. The following closing reasons apply when the trade reaches `Terminated`:

| Event                                    | CDM `ClosedState.closingReason`      | Standard / Bespoke            |
|------------------------------------------|--------------------------------------|-------------------------------|
| Option exercised (in the money)          | `Exercised`                          | Standard CDM                  |
| Option expired worthless                 | `Lapsed`                             | Standard CDM                  |
| Bilateral early termination              | `Termination`                        | Standard CDM                  |
| KO barrier triggered                     | `BarrierKnockOut`                    | **Bespoke extension**         |
| KI barrier triggered                     | — (state event only; option remains `Active`) | **Bespoke extension** |
| KI expired without barrier activation    | `Lapsed`                             | Standard CDM (same as OTM expiry) |

### Transfer States

Cash and delivery moves use CDM `TransferStatusEnum` per [invariants.md](../invariants.md):

| Move                        | Initial State | Terminal State | Notes                                      |
|-----------------------------|---------------|----------------|--------------------------------------------|
| Premium (outgoing)          | `Pending`     | `Settled`      | T+2 for OTC; same-day or daily VM for listed |
| Cash settlement             | `Pending`     | `Settled`      | T+2 from exercise / expiry date            |
| Physical equity delivery    | `Instructed`  | `Settled`      | DvP at CSD; T+2; see equities.md           |
| Strike payment (physical)   | `Instructed`  | `Settled`      | Paired with equity delivery in same transaction |
| KO rebate                   | `Pending`     | `Settled`      | Created at barrier trigger; see §Rebates   |
| Initial margin              | `Pending`     | `Settled`      | Cash to CCP margin account; listed only    |
| Variation margin            | `Pending`     | `Settled`      | Daily cash flow to/from CCP; listed only   |

### Event Qualifications

| Lifecycle Event              | CDM `EventQualificationEnum`         | Standard / Bespoke      |
|------------------------------|--------------------------------------|-------------------------|
| Trade execution              | `Execution`                          | Standard CDM            |
| Barrier observation (no trigger) | `Observation`                    | Standard CDM            |
| Barrier knock-out triggered  | `BarrierKnockOut`                    | **Bespoke extension**   |
| Barrier knock-in triggered   | `BarrierKnockIn`                     | **Bespoke extension**   |
| Option exercise              | `Exercise`                           | Standard CDM            |
| Expiry (auto-exercise or lapse) | `Exercise`                        | Standard CDM            |
| Margin call                  | `MarginCall`                         | Standard CDM            |

---

## Lifecycle Events: Vanilla European Option

### 1. Execution (T+0)

Execution transaction creates the option unit and premium obligation simultaneously (see §Premium). QRL is invoked with the trade terms; it returns the observation dates and data requirements it needs to value the option (in practice: the expiry date and the reference price source for the settlement valuation fixing).

Option unit state: `Active`.

### 2. Expiry Valuation

On the expiry date, the smart contract collects the required market observation (closing price or settlement reference price per the contract terms) and supplies it to QRL. QRL returns the option's settlement value.

**In the money**: exercise proceeds (see §Settlement).

**Out of the money**: the option expires worthless.

| Move                  | From             | To               | Asset           | State                |
|-----------------------|------------------|------------------|-----------------|----------------------|
| Option unit lapse     | Option Desk Book | Counterparty     | 1 option unit   | `Pending → Settled`  |

Option unit state: `Active → Matured` on expiry date; `Matured → Terminated` when the lapse move settles. CDM `closedState.closingReason = Lapsed`.

---

## Lifecycle Events: Vanilla American Option

### 1. Execution

Identical to European. QRL returns the exercise window (all business days from start date to expiry) and the expiry valuation date.

### 2. Early Exercise

The holder may submit an exercise notice on any business day within the exercise window. The smart contract processes the exercise immediately (see §Settlement).

### 3. Expiry

If not exercised early: at expiry, the smart contract checks the intrinsic value via QRL. If in the money, auto-exercise occurs. If out of the money, the option lapses per the European expiry workflow above.

---

## Lifecycle Events: Barrier Options

### Execution

For all barrier options, execution creates the option unit as per §Premium. QRL is invoked and returns the barrier observation schedule (for discrete monitoring) and the nature of the monitoring (discrete or continuous).

All barrier option types (KO, KI, double KO) create an option unit in `Active` state. The distinction between pre-KI and post-KI is carried in the pricing model, not in the ledger state.

### Discrete Monitoring

QRL specifies the set of observation dates and times (e.g. daily close in the relevant exchange timezone). On each observation date the smart contract collects the closing price and evaluates the barrier condition.

- **Barrier not breached**: no ledger event; observation recorded as a state event against the smart contract.
- **Barrier breached**: trigger event fires (see KO or KI below).

### Continuous Monitoring

QRL specifies that the barrier is monitored continuously. The market surveillance system delivers a real-time barrier breach notification to the smart contract as soon as the underlying price crosses the barrier level. The smart contract processes this as an unscheduled observation. The timestamp of the breach is recorded.

From the smart contract's perspective the processing of a continuous breach is identical to a discrete breach — it is the source and timing of the notification that differs.

### Knock-Out (KO): Barrier Triggered

| Move                  | From             | To               | Asset           | Initial State |
|-----------------------|------------------|------------------|-----------------|---------------|
| Option unit extinguishment | Option Desk Book | Counterparty | 1 option unit   | `Pending`     |

Option unit state: `Active → Matured` on KO trigger; `Matured → Terminated` when the extinguishment move and any associated rebate have both settled. CDM `closedState.closingReason = BarrierKnockOut` (bespoke).

If a **rebate** is payable (see §Rebates below), the rebate cash move is created in the same transaction.

If the KO barrier is not triggered before expiry, the option proceeds to standard expiry valuation as a vanilla option.

### Knock-In (KI): Barrier Triggered

When the KI barrier is breached, the event is recorded as a state event on the option `TradeState`. No cash moves are created and the option unit remains `Active` — the option proceeds to expiry valuation in the normal way. The KI observation is recorded with its timestamp for audit purposes and communicated to the pricing model; the ledger state does not change.

CDM: bespoke `BarrierKnockIn` event qualification (see §CDM Extensions); recorded against the existing `TradeState` with no closure.

If the KI barrier is **never triggered** before expiry, the option expires worthless regardless of the underlying price at expiry.

| Move                  | From             | To               | Asset           | State                |
|-----------------------|------------------|------------------|-----------------|----------------------|
| Option unit lapse     | Option Desk Book | Counterparty     | 1 option unit   | `Pending → Settled`  |

Option unit state: `Active → Matured` on expiry date; `Matured → Terminated` on lapse move settlement. CDM `closedState.closingReason = Lapsed`.

### Double Barrier

A double-barrier option carries both an upper and a lower barrier. For a double KO, the option is extinguished if either barrier is breached. QRL returns both barrier levels and the observation schedule; the smart contract evaluates both levels at each observation. The KO mechanics are identical to the single-barrier case once either barrier is triggered.

### Rebates

Some KO options specify a rebate: a fixed cash amount paid to the option holder when the option is knocked out.

| Rebate Type              | Timing                        | Ledger Treatment                                                               |
|--------------------------|-------------------------------|--------------------------------------------------------------------------------|
| Immediate rebate         | Paid at time of KO trigger    | Cash move created in the same transaction as the KO extinguishment; state `Pending` |
| Deferred rebate          | Paid at the original expiry date | Cash move created at KO trigger with state `Expected`; transitions to `Instructed → Settled` at the deferred payment date |

A deferred rebate uses the `Expected` state (bespoke, per [cash_payments.md](cash_payments.md)) because the amount is known at KO trigger but the payment is not yet instructed. It contributes to the live balance from the trigger date.

---

## Settlement

### Cash Settlement

At exercise or expiry (ITM), the smart contract creates a settlement transaction:

| Move                  | From             | To               | Asset                              | Initial State |
|-----------------------|------------------|------------------|------------------------------------|---------------|
| Option unit           | Option Desk Book | Counterparty     | 1 option unit                      | `Pending`     |
| Cash settlement       | Counterparty     | Option Desk Book | Cash (intrinsic value, per QRL)    | `Pending`     |

Both moves settle T+2 via correspondent bank (`Pending → Instructed → Settled`). Option unit state: `Active → Matured` on exercise date; `Matured → Terminated` when settlement moves have settled. CDM `closedState.closingReason = Exercised`.

### Physical Settlement

At exercise, the smart contract creates a DvP transaction linking the option extinguishment to equity delivery:

| Move                  | From             | To               | Asset                                    | Initial State  |
|-----------------------|------------------|------------------|------------------------------------------|----------------|
| Option unit           | Option Desk Book | Counterparty     | 1 option unit                            | `Pending`      |
| Equity delivery       | Counterparty     | Equity Wallet    | N shares (per contract terms)            | `Instructed`   |
| Strike payment        | Option Desk Book | Counterparty     | Cash (N × strike price)                  | `Instructed`   |

The equity delivery and strike payment legs follow the exchange-facing book two-leg model per [equities.md](equities.md) and settle DvP at CSD on T+2 from exercise date. Option unit state: `Active → Matured` on exercise date; `Matured → Terminated` when the DvP settles. CDM `closedState.closingReason = Exercised`.

---

## Exchange-Listed Options: Margining

Exchange-listed equity options are cleared through a CCP (e.g. OCC, Eurex, LCH). The desk book faces the CCP rather than the original counterparty. The CCP applies a daily margining process.

### CCP Booking Structure

At execution, the bilateral trade is novated to the CCP. The desk book faces the CCP virtual wallet. The original counterparty relationship is extinguished and replaced by two cleared legs (desk → CCP, counterparty → CCP). This is identical to the cleared IRS novation model in [irs.md](irs.md).

### Initial Margin

At execution (and daily thereafter as the risk profile of the position changes), the CCP calls initial margin based on the potential future exposure of the option portfolio. The methodology is exchange-specific (e.g. SPAN for CME/OCC, PRISMA for Eurex).

| Move                | From               | To                     | Asset               | State                 |
|---------------------|--------------------|------------------------|---------------------|-----------------------|
| IM posting          | Option Desk Book   | CCP Margin Account     | Cash                | `Pending → Settled`   |
| IM return           | CCP Margin Account | Option Desk Book       | Cash                | `Expected → Settled`  |

IM postings and returns are standalone cash moves per [cash_payments.md](cash_payments.md). The CCP Margin Account is a real wallet holding posted collateral; it is segregated from the Option Desk Book. IM is returned at position close or at the CCP's discretion.

Daily IM re-calls (where the CCP increases the margin requirement) generate new `Pending` cash moves to top up the margin account. IM reductions generate `Expected` return moves.

### Variation Margin

Listed equity options are subject to daily mark-to-market settlement. At end of day, the CCP calculates the change in value of each position and calls or pays variation margin accordingly.

| Move                | From               | To                     | Asset               | State                 |
|---------------------|--------------------|------------------------|---------------------|-----------------------|
| VM payment (loss)   | Option Desk Book   | CCP                    | Cash                | `Pending → Settled`   |
| VM receipt (gain)   | CCP                | Option Desk Book       | Cash                | `Expected → Settled`  |

VM moves are created daily and settle same-day or next morning per exchange convention. They are standalone cash moves. The asymmetric treatment (`Pending` for outgoing, `Expected` for incoming) follows the model in [cash_payments.md](cash_payments.md).

### Premium Convention

| Convention           | Market Example         | Treatment                                                                                  |
|----------------------|------------------------|--------------------------------------------------------------------------------------------|
| Upfront premium      | OCC (US equity options)| Premium paid at execution per §Premium; T+1 settlement                                    |
| Futures-style (no upfront premium) | Eurex equity options | No premium move at execution; full P&L is settled daily via variation margin |

For futures-style options the initial move table in §Premium does not apply. The option unit is still created as a unit move, but no premium cash move is generated.

### Exercise and Assignment

American-style exchange-listed options: the holder may submit an exercise notice to the CCP. The CCP randomly assigns the exercise to a short position holder. The smart contract receives the exercise assignment notification and processes settlement per §Settlement. For physical settlement, the equity DvP follows the [equities.md](equities.md) model, with the CCP acting as the exchange-facing book counterparty.

---

## CDM Extensions Required

The following bespoke extensions to CDM are required to fully model the barrier option lifecycle.

**1. `ClosedStateEnum.BarrierKnockOut`**
CDM's `ClosedStateEnum` does not include a barrier knock-out closing reason. This value is needed to distinguish an option terminated by a barrier event from one that was exercised or lapsed.

**2. `EventQualificationEnum.BarrierKnockOut` and `EventQualificationEnum.BarrierKnockIn`**
CDM's `EventQualificationEnum` has no barrier-specific event types. Both are required to record barrier events as first-class business events in the audit trail. `BarrierKnockOut` closes the `TradeState` with `ClosedStateEnum.BarrierKnockOut`. `BarrierKnockIn` is a state event against the existing `Active` `TradeState` — it does not close or replace the trade; it records the KI observation timestamp and communicates the activation to the pricing model.

**3. `Matured` instrument state (`OptionUnitStateEnum.Matured`)**
CDM has no intermediate state between a live `TradeState` and a `ClosedState`. The `Matured` state represents the period after the contractual end event (expiry, KO trigger) and before all obligations have settled. It is a bespoke extension carried as a field on the `TradeState` (without setting `closedState`). The `closedState` is only set — with the appropriate closing reason — when the last outstanding move transitions to `Settled`. This state is not specific to options; it applies to all instruments with a maturity date (bonds, IRS, NDFs, structured notes).

**4. Deferred rebate `Expected` state**
The use of `Expected` for a deferred rebate (amount known at KO, payment deferred to original expiry) is a bespoke state not present in CDM's `TransferStatusEnum`, consistent with its use for anticipated cash receipts in [cash_payments.md](cash_payments.md).

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [Option Payout](https://cdm.finos.org/docs/product-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Corporate Actions

### Quantity-Changing Corporate Actions (R-Value Adjustments)

Corporate actions that change the number of shares in issue — stock splits, reverse stock splits, and scrip dividends — do not change the economic value of an option position but alter the per-contract terms. The adjustment uses an **R-value** (the ratio of post-event to pre-event shares):

| Term                     | Adjustment                                    |
|--------------------------|-----------------------------------------------|
| Strike price             | New strike = Old strike ÷ R                   |
| Shares per contract      | New shares per contract = Old shares × R      |

For a 2-for-1 stock split (R = 2): the strike is halved and shares per contract double. The total option delta and economic value are unchanged.

The R-value is determined by the exchange or clearing house for listed options (e.g. OCC, Eurex), or by the calculation agent per ISDA methodology for OTC options. The R-value is delivered to the smart contract as a parameter update on the ex-date; no cash moves are created. The adjustment is recorded as a state event on the option `TradeState`.

### Rights Issue (RHTS)

Option holders are not shareholders of record and do not receive the subscription rights directly. Instead, the option contract is adjusted so that its economic value is approximately preserved after the rights issue dilutes the share price on the ex-rights date.

The adjustment form is event-specific and determined by the exchange or clearing house for listed options, or by the calculation agent per ISDA equity derivative definitions for OTC options. Common forms of adjustment are:

| Adjustment Form    | Description                                                                             |
|--------------------|-----------------------------------------------------------------------------------------|
| Strike revision    | Strike reduced to reflect the theoretical ex-rights price; deliverable unchanged        |
| Deliverable change | Contract delivers additional shares or rights units alongside the original share count  |
| Multiplier change  | Shares per contract increased to maintain total contract value at the revised price      |
| Combination        | Two or more of the above applied together; exact terms per the clearing house notice     |

The adjustment is applied as a state event on the option `TradeState` on the ex-date; no cash moves are created. The definitive contract terms after adjustment must be verified against the official clearing house or calculation agent notice for each specific event, as there is no universal formula.

### Other Corporate Actions — Spin-Off, Merger, and Takeover

Corporate actions that change the identity or composition of the underlying company do not admit a simple R-value adjustment. The treatment is determined on a case-by-case basis:

| Outcome         | Trigger                                                        | Option Treatment                                                                                     |
|-----------------|----------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| Basket option   | Spin-off or merger producing multiple securities               | Underlying replaced by a basket; option terms adjusted to reflect the basket composition.            |
| Termination     | All-cash merger, delisting, or winding-up of the underlying    | Option terminated; intrinsic value (if any) paid; `closedState.closingReason = Termination`.        |
| Client election | Corporate action terms offer the holder a choice of outcome    | Option remains `Active` pending election deadline; treatment applied on receipt of election notice.  |

In some cases the determination is at the client's discretion (e.g. where the counterparty to an OTC option holds the right to elect the adjustment methodology). Where no standard determination applies, the parties may agree a bespoke treatment recorded as a `BespokeEvent`.

---

## Failure Handling

| Scenario                                       | State                              | Action                                                                                         |
|------------------------------------------------|------------------------------------|------------------------------------------------------------------------------------------------|
| Premium fails to settle                        | `TransferStatusEnum.Pending`       | Two-tier retry per [invariant 8](../invariants.md); option unit remains `Active`               |
| Observation unavailable on scheduled date      | Observation deferred               | Smart contract holds; QRL rescheduled per market convention                                    |
| Cash settlement fails                          | Two-tier per invariant 8           | `Pending` (retry) or `Failed`; option unit remains `Matured` until all obligations settle     |
| Physical settlement fails                      | Per [equities.md](equities.md)     | Retry, bilateral cancellation, or buy-in; option unit remains `Matured` until DvP completes  |
| Barrier breach disputed                        | Observation held                   | If confirmed: process as triggered. If retracted: no state change; disputed observation logged |
| Margin call fails (listed options)             | `TransferStatusEnum.Pending`       | Escalated to credit/risk; CCP default waterfall outside ledger scope                          |
