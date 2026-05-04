# Interest Rate Swap Smart Contract

## Overview

An Interest Rate Swap (IRS) is an over-the-counter derivative in which two parties agree to exchange a series of cash flows over a defined term, based on a notional principal amount. One party typically pays a fixed rate and receives a floating rate (or, in a basis swap, two different floating rates are exchanged). Cross-currency swaps additionally exchange notional in different currencies at the start and end of the trade.

Unlike exchange-traded instruments, IRS trades are bilateral agreements governed by an ISDA Master Agreement and a trade-specific term sheet (the economic terms). The smart contract encodes the term sheet as an executable set of rules and is the authoritative source of all future cash flow obligations arising from the trade.

This contract covers three product variants:

1. **Vanilla IRS** — fixed leg vs. floating leg in a single currency (e.g. pay fixed 4.5% annually, receive 3-month SOFR quarterly)
2. **Basis swap** — floating leg vs. floating leg in a single currency (e.g. pay 3-month SOFR, receive 6-month SOFR)
3. **Cross-currency swap (XCS)** — fixed or floating leg in one currency vs. floating leg in another currency, with notional exchange at inception and maturity

---

## Parties and Wallets

### Bilateral (Uncleared) Trade

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| IRS Desk Book | Real wallet | The trading desk's front book; holds the internal position and is the source of all outgoing payments and recipient of all incoming payments |
| Counterparty | Virtual wallet | The external counterparty facing the desk directly; represents the counterparty's claim on or obligation to the desk |
| Collateral Wallet | Real wallet | Holds collateral posted by or to counterparties under a Credit Support Annex (CSA); a separate wallet per CSA relationship |

### Cleared Trade (Post-Novation)

After clearing, the original bilateral counterparty is replaced by the CCP on both sides. The desk book faces the CCP's virtual wallet, not the original counterparty.

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| IRS Desk Book | Real wallet | Unchanged from the bilateral booking |
| CCP | Virtual wallet | Represents the Central Counterparty (e.g. LCH SwapClear, CME Clearing); faces the desk in place of the original counterparty after novation |
| Initial Margin Wallet | Real wallet | A dedicated collateral wallet holding cash or securities posted as initial margin to the CCP |
| Variation Margin Wallet | Real wallet | A dedicated collateral wallet from which daily variation margin calls are debited or credited |

---

## Schedule Generation: QRL

At trade inception, the smart contract invokes **QRL**, an external scheduling library, to generate the complete set of future cash flow obligations from the trade economics. QRL is not invoked again during the ordinary life of a trade unless the economics change (see [Partial Termination](#7-partial-termination) and [Amendment as cancel/correct invariant](../invariants.md#core-ledger-invariants)).

QRL consumes the trade's economic parameters and returns:

| QRL Output | Description |
|---|---|
| Calculation periods | Start date, end date, and day count fraction for each coupon period on each leg |
| Payment dates | The date on which each coupon payment is due, per leg, adjusted for business day conventions |
| Fixing dates | For each floating-rate period, the date on which the reference rate is observed (typically two business days before the start of the calculation period, per ISDA conventions) |
| Notional exchange dates | For XCS only: the exchange of notional at inception and return at maturity |
| Holiday calendars | The business day convention and calendar(s) used for all date adjustments |

The smart contract stores the full QRL-generated schedule and uses it to create `Expected` moves at inception covering the entire life of the trade. All downstream lifecycle events — rate fixings, payment dates, margin calls — are triggered by the dates in this schedule, not by external event notifications.

---

## Payment Netting

For vanilla IRS and basis swaps where both legs are in the same currency, fixed and floating payments that fall on the same value date are **netted to a single payment**. A single net move is created in the ledger rather than two gross moves. The direction and amount of the net move are determined at fixing time when both amounts are known.

**Rationale**: Both legs are governed by the same ISDA Master Agreement and netting confirmation. Creating gross moves would misrepresent the actual payment obligation and the credit exposure between parties. The net move accurately reflects the single payment obligation that exists.

**Exception — Cross-currency swaps**: Legs denominated in different currencies cannot be netted. Gross moves are created for each leg, reflecting the independent currency payment obligations.

**Exception — Gross settlement under specific CSA terms**: Where the parties have explicitly agreed to gross settlement in their netting confirmation, gross moves are created and the netting flag on the smart contract is set to `false`. This is rare for standard IRS.

For cleared trades, netting is performed by the CCP across all trades in the same currency within the same clearing member account. The CCP publishes a single net payment per currency per value date. Moves created in the ledger for cleared trades therefore always reflect the CCP net instruction, not the individual trade-level gross amounts.

---

## Instrument State Model

| State         | Meaning                                                                                                                                    |
|---------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| `Active`      | IRS contract is live; coupon schedule in progress; all future `Expected` moves visible in the live balance                                 |
| `Matured`     | Final payment date reached; last period's moves have entered the payment state flow but have not yet all reached `Settled`                 |
| `Terminated`  | All obligations discharged; final coupon and (for XCS) notional exchange moves have reached `Settled`; contract extinguished               |

CDM `closedState` is set only on the transition to `Terminated`. The `Matured` state is carried as a bespoke field on `TradeState` without setting `closedState` (see [equity_options.md](equity_options.md) CDM Extension 3 for the general `Matured` state pattern).

---

## Lifecycle Events

### 1. Trade Execution

**Trigger**: Trade execution notification received from the trading system or confirmation platform (e.g. MarkitWire, ICE Swap Trade, DTCC).

**Action**: The smart contract is created with the full economic terms of the trade. QRL is invoked and the complete payment schedule is generated. The smart contract creates a single atomic transaction containing all future expected moves for the full life of the trade.

For a vanilla IRS, the moves created at inception are:

| Move | From | To | Asset | State | Notes |
|------|------|----|-------|-------|-------|
| Fixed coupon payment (per period) | IRS Desk Book | Counterparty | Cash (fixed amount: notional × fixed rate × DCF) | `Expected` | One move per calculation period; amount is known at inception |
| Floating coupon receipt (per period) | Counterparty | IRS Desk Book | Cash (estimated amount; TBC at fixing) | `Expected` | One move per calculation period; amount is unknown until rate fixing |

For a **pay-fixed** desk position, the desk book has outgoing `Expected` moves for each fixed coupon and incoming `Expected` moves for each floating coupon. For a **receive-fixed** position, the directions are reversed.

**On the use of `Expected` state at inception**: All future coupon moves are booked at `Expected` rather than `Pending` because the desk is the passive party for the floating receipts (the floating amounts are determined by market rates, not by the desk's action) and the payment obligations have not yet been instructed. The `Expected` state makes the full forward cash position of the trade visible to risk and treasury from day one (see [invariant 9](../invariants.md#core-ledger-invariants)).

**Initial state for both pay and receive legs**: both are booked as `Expected`. The distinction between payer and receiver determines the direction of the move (from/to), not the initial state.

**Double-entry at inception**: The transaction is balanced. For each fixed coupon move debiting the desk book, there is an equal-and-opposite credit to the counterparty virtual wallet. For each floating coupon move crediting the desk book, there is an equal-and-opposite debit to the counterparty virtual wallet. Net across all wallets is zero (see [invariant 3](../invariants.md#core-ledger-invariants)).

**For a basis swap**: Both legs are floating. Both sets of moves are created as `Expected` with estimated amounts (if a current forward curve is applied at booking) or with a zero placeholder amount, to be crystallised at each leg's fixing date.

**For a cross-currency swap**: In addition to coupon moves, two notional exchange transactions are created at inception:

| Move | From | To | Asset | State | Notes |
|------|------|----|-------|-------|-------|
| Initial notional payment (Leg 1) | IRS Desk Book | Counterparty | Cash (CCY1 notional) | `Expected` | Settles on trade start date |
| Initial notional receipt (Leg 2) | Counterparty | IRS Desk Book | Cash (CCY2 notional) | `Expected` | Settles on trade start date |
| Final notional receipt (Leg 1) | Counterparty | IRS Desk Book | Cash (CCY1 notional) | `Expected` | Settles on maturity date |
| Final notional payment (Leg 2) | IRS Desk Book | Counterparty | Cash (CCY2 notional) | `Expected` | Settles on maturity date |

Notional exchange moves are not subject to netting and are settled gross in each respective currency.

---

### 2. CCP Clearing and Novation

**Trigger**: The trade is submitted to a CCP for clearing (e.g. LCH SwapClear or CME Clearing). Most standard vanilla IRS are subject to the EMIR/Dodd-Frank clearing obligation. Clearing may be mandatory or voluntary.

**Mechanism**: On acceptance by the CCP, the bilateral trade between the desk and the original counterparty is **novated**: it is legally replaced by two new cleared trades — one between the desk and the CCP, and one between the original counterparty and the CCP. The desk's original bilateral smart contract is closed; two new cleared smart contracts are created. After novation, the desk book no longer faces the original counterparty; it faces only the CCP.

**Ledger representation of novation**:

*Step 1 — Cancel the bilateral trade*: All `Expected` moves on the original bilateral smart contract that have not yet reached `Settled` state are transitioned to `Failed` (terminal). These moves never settled, so the `Failed` state alone corrects all balances — no reversal transaction is required (see [invariant 8](../invariants.md#core-ledger-invariants)). A novation event is recorded as a state event referencing the CCP clearing instruction.

*Step 2 — Create the cleared trade*: A new smart contract is created between the desk book and the CCP virtual wallet. QRL is invoked with the same economic terms (the trade economics are unchanged; only the counterparty changes). The full schedule of future `Expected` moves is recreated, now with the CCP virtual wallet as counterparty.

The novation is treated as a single atomic operation: the cancellation of the bilateral moves and the creation of the cleared moves succeed or fail together (see [invariant 2](../invariants.md#core-ledger-invariants)).

**Initial margin posting**: Upon clearing, the CCP calculates the required initial margin for the position. The desk must post this margin before the cleared trade is accepted. An initial margin posting creates a move:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| Initial margin post | Initial Margin Wallet | CCP | Cash (or eligible securities) | `Pending` → `Instructed` → `Settled` |

The initial margin wallet is a real wallet segregated from the trading book. The CCP holds the margin as collateral against the desk's cleared exposure. Initial margin is recalculated daily by the CCP (SIMM or portfolio-based model); additional calls or returns are processed as further moves (see [Variation Margin](#5-variation-margin-calls) for the daily call mechanism).

---

### 3. Rate Fixing

**Trigger**: On each floating leg fixing date in the QRL-generated schedule, the relevant reference rate is observed from the fixing source (e.g. SOFR from the Federal Reserve; EURIBOR from EMMI; Term SOFR from CME). The rate is applied to the calculation period to determine the floating payment amount for that period.

**Action**: Rate fixing is a **calculation event**, not a payment event. It does not create a new move or transaction. Instead, it crystallises the amount on the existing `Expected` move for that calculation period.

For the floating coupon move covering the fixing period:
- The amount field is updated from the estimated or placeholder amount to the definitive calculated amount: `notional × (fixed rate spread ± floating rate) × day count fraction`
- A fixing event is recorded against the move, capturing the fixing date, the reference rate observed, and the resulting payment amount
- The move state remains `Expected` — rate fixing alone does not advance the state; that occurs at the payment instruction step (see [Coupon Payment](#4-coupon-payment))

For netted payments: if both legs have now been fixed for the same value date, the net amount is calculated and the single net move is updated to reflect the definitive net cash obligation.

**Basis swap fixing**: Each leg has its own fixing date (which may differ, e.g. 3M SOFR fixes two days before the 3-month period start; 6M SOFR fixes two days before the 6-month period start). Each leg's `Expected` move is updated independently as each fixing occurs.

**CDM representation**: Rate fixing maps to the CDM `Reset` primitive / `ResetPrimitive` and is represented as a `BusinessEvent` with a `ResetInstruction`. The fixed-for-floating rate and the resulting payment amount are captured in the reset record.

---

### 4. Coupon Payment

**Trigger**: The payment date for a given calculation period arrives (as per the QRL-generated schedule). This event applies to all three product variants.

**Pre-condition**: For a floating leg payment, the fixing event (section 3) must have occurred on or before the payment date. In standard ISDA conventions, the fixing date precedes the payment date by the settlement lag (typically two business days), so the amount is always known before payment is due. If a fixing has not occurred by the expected payment date (e.g. due to a market data failure), the payment is held at `Expected` pending resolution.

**State transition for a standard coupon payment**:

```
Expected → Pending → Instructed → Settled
```

The transitions occur as follows:

| Step | Trigger | State Transition | Notes |
|------|---------|------------------|-------|
| Payment date arrives | QRL schedule | `Expected → Pending` | Obligation now due; payer must instruct |
| Payment instruction sent | Operations / payment system | `Pending → Instructed` | ISO 20022 pacs.008/009 or CCP net payment instruction |
| Payment confirmed | Correspondent bank or CCP confirms receipt | `Instructed → Settled` | Terminal |

For **cleared trades**, the CCP publishes a single net payment instruction per currency per value date across all cleared trades in the clearing member account. The `Pending → Instructed` transition is triggered by the CCP's payment instruction rather than by the desk's own payment system.

For **vanilla IRS** with same-currency netting: a single net move is advanced through the state flow. The net move amount will have been crystallised at the most recent fixing date.

For **cross-currency swaps**: each currency leg advances through its state flow independently. The gross notional exchange moves (if on the same date) also advance, in a separate transaction from the coupon moves.

**Double-entry check**: When the move reaches `Settled`, the settled balance of the desk book reflects the net impact of the payment. The counterparty or CCP virtual wallet records the equal-and-opposite credit (see [invariant 3](../invariants.md#core-ledger-invariants)).

---

### 5. Variation Margin Calls

**Trigger**: Daily, the CCP (for cleared trades) or the counterparty under the CSA (for bilateral trades) publishes a variation margin call based on the mark-to-market of outstanding positions. Variation margin compensates for the daily change in fair value of the portfolio.

**Mechanism**: Variation margin is a standalone cash payment (or receipt) that is independent of the coupon schedule. It does not affect the notional or the economic terms of the IRS smart contract. Variation margin flows are governed by the [Standalone Cash Payments smart contract](cash_payments.md).

**For cleared trades**: The CCP publishes a daily end-of-day price. The resulting variation margin call or return is:

- A **margin call** (desk must pay): a new `Pending` cash move from the Variation Margin Wallet to the CCP virtual wallet
- A **margin return** (desk receives): a new `Expected` cash move from the CCP virtual wallet to the Variation Margin Wallet

Both are processed as standalone cash payments per [cash_payments.md](cash_payments.md). They are cross-referenced to the cleared IRS smart contract but are not part of it.

**For bilateral trades under a CSA**: The margin call is calculated bilaterally using agreed-upon valuation methodology (typically ISDA SIMM for IM; MTM for VM). The same `Expected` / `Pending` pattern applies, referencing the counterparty's virtual wallet.

**Margin call failure**: A failure by the desk to meet a variation margin call by the CCP's deadline is an event of default under the clearing agreement. This is immediately reportable to the risk management function and constitutes a **credit event trigger** that must be escalated before the next margin cycle. The failed move is recorded as `Failed`; a risk alert is generated as a side-effect of the state transition. A failed margin receipt from the CCP is treated symmetrically — it is reportable to risk as a potential CCP credit concern, though CCP default is treated as a systemic event (see [CCP Default](#ccp-default) below).

---

### 6. Initial Margin — Returns and Calls

**Trigger**: The CCP recalculates initial margin requirements daily (or intraday under stress). Additional calls or returns are published as part of the end-of-day margin cycle.

**Margin call (additional posting required)**:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| IM top-up | Initial Margin Wallet | CCP | Cash | `Pending` → `Instructed` → `Settled` |

**Margin return (excess margin returned)**:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| IM return | CCP | Initial Margin Wallet | Cash | `Expected` → `Instructed` → `Settled` |

Initial margin moves are standalone cash payments and follow the same state model as [cash_payments.md](cash_payments.md). They are cross-referenced to the cleared IRS smart contract.

**At maturity**: When the last cleared trade referencing an initial margin account reaches `Settled`, the CCP returns the full remaining initial margin balance. This final return is a new `Expected` move and follows the receipt state flow.

---

### 7. Partial Termination

**Trigger**: The parties agree to reduce the notional of an outstanding IRS trade (e.g. the client partially unwinds a structured product hedge, or a compression exercise reduces notional across a portfolio).

**Mechanism**: Partial termination is an amendment to the economic terms of the trade — specifically, a reduction in notional. Per [invariant 7](../invariants.md#core-ledger-invariants), this is treated as a cancel/correct: the existing future moves are cancelled and replaced with corrected moves reflecting the reduced notional.

The cancel/correct applies only to **future unsettled moves**. Past settled moves are immutable (see [invariant 1](../invariants.md#core-ledger-invariants)) and are unaffected.

**Step-by-step**:

*Step 1 — Cancellation*: All `Expected` moves for calculation periods beyond the partial termination effective date are transitioned to `Failed` (terminal). These moves have not settled, so the `Failed` state corrects all balances without a reversal transaction.

*Step 2 — Correction*: QRL is invoked with the amended notional amount and the remaining term. A new set of `Expected` moves is created for the remaining calculation periods, reflecting the reduced notional. A break fee or termination payment (if agreed between the parties) is created as a separate `Pending` cash move.

*Step 3 — Any in-period partial termination*: If the partial termination is effective mid-period (i.e. the current calculation period has started but the coupon has not yet paid), the current period's `Expected` move is also cancelled and replaced with a corrected move reflecting the stub period accrual on the original notional from period start to termination date, plus a new move for the remaining sub-period on the reduced notional.

The cancellation and correction are executed as a single atomic operation (see [invariant 2](../invariants.md#core-ledger-invariants)).

**CDM representation**: Partial termination maps to the CDM `QuantityChangePrimitive`, capturing the change in notional, the effective date, and any associated termination payment.

---

### 8. Full Termination (Early Break)

**Trigger**: The parties agree to terminate the IRS trade in full before its scheduled maturity (a mutual termination), or a unilateral termination right is exercised (e.g. an optional early termination date, or a termination following an ISDA event of default or credit event).

**Mechanism**: Full termination cancels all remaining future obligations. Unlike partial termination, there is no corrected replacement — the trade is extinguished.

*Step 1 — Cancel all future `Expected` moves*: Every `Expected` move for periods that have not yet settled is transitioned to `Failed` (terminal). These moves have not settled and have never affected a settled balance, so the `Failed` state alone correctly removes them from all balance views (see [invariant 8](../invariants.md#core-ledger-invariants)). No reversal transaction is created.

*Step 2 — Termination payment*: The parties agree (or calculate under ISDA close-out netting rules) a single net termination amount representing the fair value of all cancelled future obligations. This amount is booked as a new standalone cash move:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| Termination payment | Party owing | Party receiving | Cash (close-out amount) | `Pending` → `Instructed` → `Settled` |

The termination payment is processed as a standalone cash payment per [cash_payments.md](cash_payments.md).

*Step 3 — Return of initial margin (cleared trades)*: If the terminated trade is the last cleared trade in the CCP account, the initial margin is returned (see [Initial Margin — Returns and Calls](#6-initial-margin---returns-and-calls)).

**Distinction from amendment**: Full termination does not use the cancel/correct mechanism of [invariant 7](../invariants.md#core-ledger-invariants) because there is no correction — the trade is gone. The cancellation of future moves and the creation of the termination payment are executed as a single atomic operation.

---

### 9. Maturity

**Trigger**: The scheduled maturity date of the trade (the termination date in the term sheet, as held in the smart contract).

**Standard maturity**: Maturity is the natural conclusion of a trade that has run to its scheduled end. It is not a special event — it is simply the final coupon payment date. The final period's `Expected` moves progress through the standard payment state flow (section 4). IRS contract state: `Active → Matured` on the final payment date when the last period's moves enter the payment state flow; `Matured → Terminated` once all final moves (coupon and, for XCS, the notional exchange) have reached `Settled`.

**Cross-currency swap — final notional exchange**: On the maturity date, the notional exchange that was created at inception (in the opposite direction) is also due. These are existing `Expected` moves created at trade inception and advance through the payment state flow simultaneously with the final coupon:

```
Expected → Pending → Instructed → Settled
```

The final notional exchange and the final coupon payment are settled in separate transactions (they may settle at different times intraday and involve different payment systems), but both must settle for the trade to be fully closed.

**For cleared trades**: The CCP confirms trade maturity. The initial margin return (if no remaining exposure) follows as described in section 6.

---

## State Model Summary

### Coupon Payment State Flow

```
Expected (inception) → [rate fixing: amount crystallised, state unchanged]
                     → Pending (payment date)
                     → Instructed (payment instruction sent)
                     → Settled (confirmed)
                       ↘ Failed (definitively cancelled; excluded from all balances)
```

### Variation and Initial Margin — Payment (desk pays)

```
Pending → Instructed → Settled
                      ↘ Failed (credit event trigger)
```

### Variation and Initial Margin — Receipt (desk receives)

```
Expected → Instructed → Settled
                       ↘ Failed
```

### Novation (Clearing)

```
[Bilateral] Expected → Failed (novation cancels all bilateral future moves)
[Cleared]   → [New smart contract] Expected (full schedule recreated vs. CCP)
```

### Partial Termination

```
[Future moves] Expected → Failed (cancelled portion)
               → [New moves] Expected (corrected reduced-notional moves created)
```

### Full Termination

```
[All future moves] Expected → Failed (all cancelled; no correction)
[Termination payment] → Pending → Instructed → Settled
```

---

## Failure Handling

### Coupon Payment Failure

The two-tier failure model from [invariant 8](../invariants.md#core-ledger-invariants) applies:

| Scenario | State | Resolution |
|----------|-------|------------|
| Payment attempt failed (transient) | `Pending` | Retry; no new move created; same move re-instructed |
| CCP payment instruction rejected (transient) | `Pending` | CCP re-submits; state cycles `Pending → Instructed → Pending` |
| Payment definitively failed (bilateral) | `Failed` | Terminal; excluded from all balances; new move created for agreed resolution |
| CCP net payment definitively rejected | `Failed` | Terminal; CCP default management procedures initiated (out of scope for this contract) |

### Margin Call Failure

A margin call failure is a higher-severity event than a coupon payment failure:

| Scenario | State | Action |
|----------|-------|--------|
| Margin call missed (transient) | `Pending` | Retry within CCP grace period |
| Margin call definitively failed by desk | `Failed` | **Credit event trigger**: immediate risk escalation; CCP may declare default; cleared position liquidation procedures begin |
| Margin return not received from CCP | Remains `Instructed` | Risk escalation; CCP credit concern notification |

### CCP Default

A CCP default is a systemic event outside the scope of this smart contract. In the event of a CCP default, the outstanding cleared positions and margin assets are subject to the CCP's default management process (porting, auction, or tear-up). This contract makes no attempt to represent those outcomes. The relevant regulatory and legal framework (e.g. EMIR Article 48 for EU CCPs) governs the resolution process. Cleared trade moves remain in their last recorded state until an instruction is received from the default manager or successor entity.

---

## CDM Representation

| Lifecycle Event | CDM Business Event Qualification | CDM Primitive / Type | Notes |
|---|---|---|---|
| Trade execution | `EventQualificationEnum.Execution` | `ContractFormationPrimitive`; `InterestRatePayout` (fixed leg); `FloatingRatePayout` (floating leg) | QRL schedule creates all `Expected` moves at this point |
| Rate fixing | `EventQualificationEnum.Reset` | `ResetPrimitive`; `ResetInstruction` | State transition on existing move only; no new move; amount crystallised |
| Coupon payment | `EventQualificationEnum.CashTransfer` | `TransferPrimitive`; `TransferStatusEnum` | Net or gross per netting terms; state flow `Expected → Pending → Instructed → Settled` |
| CCP clearing / novation | `EventQualificationEnum.ClearingInstruction` | `ClearingInstruction`; `NovationInstruction` | Bilateral moves to `Failed`; new cleared smart contract created |
| Initial margin post | `EventQualificationEnum.MarginCall` | `TransferPrimitive`; `MarginCallInstructionTypeEnum.PostInitialMargin` | Standalone cash payment; cross-referenced to cleared contract |
| Initial margin return | `EventQualificationEnum.MarginCall` | `TransferPrimitive`; `MarginCallInstructionTypeEnum.ReturnInitialMargin` | Standalone cash receipt |
| Variation margin call | `EventQualificationEnum.MarginCall` | `TransferPrimitive`; `MarginCallInstructionTypeEnum.DailyVariationMargin` | See [cash_payments.md](cash_payments.md) |
| Partial termination | `EventQualificationEnum.QuantityChange` | `QuantityChangePrimitive` | Cancel/correct per invariant 7; QRL reinvoked |
| Full termination | `EventQualificationEnum.Termination` | `TerminationInstruction` | Future moves to `Failed`; termination payment is new `Pending` move |
| Maturity | — (final payment; no special event) | `TransferStatusEnum.Settled` | Natural conclusion; last coupon + XCS notional return |

**CDM deviation notes**:

1. **`Expected` state**: The ledger's `Expected` state for anticipated receipts and pre-fixed floating coupons has no direct equivalent in `TransferStatusEnum`. CDM represents anticipated transfers as `ScheduledTransfer` within the payout framework — a contract-level construct rather than a live ledger entry. This ledger promotes anticipated transfers to first-class ledger entries in `Expected` state to provide a complete forward cash position to risk and treasury from trade inception. See also [cash_payments.md](cash_payments.md) for the canonical description of this deviation.

2. **Full schedule at inception**: CDM's event model is incremental — events are generated as they occur. This ledger deviates by pre-generating the full schedule of `Expected` moves at inception via QRL. This enables complete forward cash-flow visibility without requiring downstream systems to reconstruct the schedule from trade terms.

3. **Novation as cancel/recreate**: CDM's `NovationInstruction` treats novation as a single event transforming the trade. In this ledger, novation is represented as explicit cancellation of bilateral moves (to `Failed`) and creation of a new smart contract and schedule. This preserves a complete and auditable ledger trail of the change in counterparty.

4. **Netted coupon moves**: CDM's payout model represents fixed and floating legs as separate `Payout` objects. This ledger creates a single net move for same-currency same-date payments, accurately reflecting the single payment obligation that will be settled.

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [Process Model](https://cdm.finos.org/docs/process-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Cross-References

| Related Contract / Document | Relevance |
|---|---|
| [cash_payments.md](cash_payments.md) | Variation margin, initial margin, and termination payments are governed by the standalone cash payments contract |
| [invariants.md](../invariants.md) | Invariants 1–9 all apply; specifically invariants 6 (cancellation by reversal), 7 (amendment as cancel/correct), 8 (two-tier failure), and 9 (balance views) |
| [funding.md](funding.md) | Internal funding flows to support initial margin posting and collateral management |
| [equity_options.md](equity_options.md) | Cross-reference for structured products that embed IRS-like coupon mechanics (e.g. capped floaters, range accruals) |
| [structured_products.md](structured_products.md) | Structured products may reference IRS legs; the IRS smart contract governs the hedging instruments |
