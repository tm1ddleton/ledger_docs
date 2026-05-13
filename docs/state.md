# State Concepts: Unit, Product, and Position

## Overview

This document defines the three concepts that, together with the ledger, constitute the complete state of the system at any point in time: **Unit**, **Product**, and **Position**. The ledger records moves of units between wallets (see [invariants.md](invariants.md)); this document specifies what those units are, what governs them, and how a holder's exposure to them is summarised.

The ledger is the immutable canonical record. Everything else — what a unit *is*, how it pays out, who holds how much in what settlement state — is derived state. This document specifies how that derived state is partitioned between the three concepts so that each smart contract can be expressed precisely in terms of the same primitives.

---

## Concepts

### Unit

A **Unit** is the representation of a given asset. Units are the things that move between wallets. Every move on the ledger transfers a quantity of a single Unit type from one wallet to another.

Examples of Units:

| Example                                                          | Smart Contract                                                  |
|------------------------------------------------------------------|-----------------------------------------------------------------|
| One share of `AAPL`                                              | [equities.md](smart_contracts/equities.md)                      |
| One ESM6 future contract (E-mini S&P, June 2026)                 | [futures.md](smart_contracts/futures.md)                        |
| One USD of cash                                                  | [cash_payments.md](smart_contracts/cash_payments.md)            |
| One contract under a specific OTC equity option term sheet       | [equity_options.md](smart_contracts/equity_options.md)          |
| One note of a defined structured payout                          | [structured_products.md](smart_contracts/structured_products.md)|

A Unit is identified by an identifier (ISIN, exchange code, internal bespoke id) that all parties in the system agree on. **Unit state is identical for all instances of the Unit**: a share of `AAPL` held by Wallet A is in every respect equivalent to a share of `AAPL` held by Wallet B. When the Unit's state changes — e.g. on expiry — every instance held in every wallet is affected simultaneously.

Units may be **compound**: a Unit may be defined by reference to another wallet (typically simulated) holding other Units — e.g. a total return swap written on a simulated wallet that holds the constituents of an index (see [qis.md](smart_contracts/qis.md)).

### Product

A **Product** is the subset of Unit state that defines the payout and other term-sheet variables of the Unit. It is the part of Unit state that the smart contract evaluates when computing cash flows, deliveries, or other lifecycle outputs.

| Unit type             | Product state                                                                                                                                |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| Cash equity           | Identifier, ISIN, listing currency, lot multiplier.                                                                                          |
| Futures               | Underlying, contract size / multiplier, expiry date, settlement convention (cash / physical), last trading date.                             |
| Equity option         | Underlying, strike, expiry, settlement type (cash / physical), option style (European / American), barriers, calculation agent.              |
| Structured note       | Full term sheet: principal, observation schedule, payoff function, autocall barriers, coupon mechanics.                                      |
| OTC IRS               | Notional, fixed/floating leg conventions, day-count, fixing schedule, payment dates, calculation agent.                                      |

The Product is versioned and stored bi-temporally. The product may change as a consequence of a corporate action (e.g. strike or multiplier change owing to a corporate action), or a misbooking.

### Unit Liveness

Beyond the Product, Unit state carries a **liveness** indicator that reflects where the Unit sits in its overall lifecycle. Liveness is global to the Unit — when the Unit matures, *every* instance held in *every* wallet matures simultaneously.

| Liveness  | Meaning                                                                                                                                            |
|-----------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `Active`  | The Unit is live: trading and lifecycle events are permitted; positions represent real economic exposures.                                         |
| `Matured` | The Unit's final lifecycle event has been triggered (e.g. expiry, final fixing, full close-out) but settlement of the final move(s) is still open. |
| `Expired` | The Unit's final settlement is complete; no further events are possible; the Unit identifier is retained only for audit.                           |

`Active → Matured` on the contractual trigger (expiry date, final fixing, full close-out). `Matured → Expired` once all final settlement moves reach `Settled`. CDM `closedState` is set at `Expired`.

For some contracts (e.g. cash equities, perpetual instruments) there is no contractual maturity: the Unit remains `Active` until a corporate action or delisting extinguishes it.

### Corporate Action History

For Units that may be the subject of corporate actions — equities are the canonical case, but rights, structured notes carrying bespoke amendments, and others apply — the Unit state carries an **append-only history of corporate actions applied to the Unit**. Each entry records the action type (per CDM `CorporateActionTypeEnum`; see [equities.md](smart_contracts/equities.md)), the effective date, the action terms (e.g. split ratio, dividend per share, election outcomes), and a reference to the ledger transaction(s) that implemented it.

The corporate-action history lives at the Unit level rather than the Position level because **every corporate action is applied atomically to all instances of the Unit**: a 2-for-1 stock split affects every share of `AAPL` in every wallet simultaneously, on the same ex-date, with the same multiplier; a cash dividend pays out to every holder on the same record date. Recording the history once per Unit avoids duplicating it across every Position and makes it impossible for two holders to disagree on which actions have been applied.

The corporate-action history is the basis for adjustments applied to derivative Units that reference the affected underlying — see [equity_options.md](smart_contracts/equity_options.md) for the option-level adjustment treatment.

### Last Lifecycle Event

The Unit state also records a reference to the **most recent lifecycle event** applied to the Unit — e.g. coupon payment on a bond, autocall observation on a structured note, corporate action on an equity, floating-rate fixing on an IRS.

As with corporate actions, lifecycle events that act on the Unit (rather than on individual positions) are applied atomically across all instances. Tracking only the *last* event by reference is sufficient: the full history is recoverable from the ledger by walking back through the chain of lifecycle events on the Unit, each of which references its predecessor.

Together with the corporate-action history (the complete set of events of one specific type) and the liveness state (the overall trajectory of the Unit), the last-lifecycle-event reference provides the most operationally useful summary of where the Unit currently sits in its lifecycle: *what just happened*.

### Why These Elements Are Unit-Level, Not Position-Level

The defining test for placing state at the Unit level rather than the Position level is **atomicity of application across all holders**: if an event affects every instance of the Unit simultaneously and identically, then the state it produces is global to the Unit, and there is no value in replicating it across every Position. Corporate actions, scheduled coupon payments, contractual fixings, and final settlement events all satisfy this test. Settlement bucket movements and cost-basis updates do not — they are intrinsically per-holder and therefore belong on the Position.

### Position

A **Position** is the exposure of a single (wallet, unit, counterparty) triple. Where Unit state is global, Position state is per-holder.

Position state answers three questions:

1. *How many units of this Unit does this wallet hold against this counterparty?*
2. *In what settlement state are they?*
3. *(For variation-margined products) what cost basis applies to them?*

The keying of a Position by counterparty matters for any contract where the counterparty determines settlement obligations distinctly: a holding of an OTC option face Counterparty A is a different position from one face Counterparty B, even when the underlying terms are identical. For centrally cleared and exchange-settled products the counterparty is fixed (e.g. the CCP, the CSD) and the Position degenerates to the (wallet, unit) pair.

---

## Position State

Position state has two elements. Both may apply to a given contract, only one may apply, or neither in degenerate cases.

### Settlement-Cycle Bucket Vector

For each (wallet, unit, counterparty), the Position holds a **vector of totals indexed by settlement-cycle bucket**. The bucket structure expresses how much of the position has reached or will reach `Settled` state, and on what value date.

The canonical bucket layout for a T+N settlement product:

| Bucket           | Definition                                                                                                                                                     |
|------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `SettledPrior`   | Total quantity settled on a value date strictly earlier than today.                                                                                            |
| `SettlingToday`  | Total quantity whose contractual value date is today (i.e. T+0 from the holder's perspective today).                                                           |
| `SettlingT+1`    | Total quantity contracted to settle one business day from today.                                                                                               |
| `SettlingT+2`    | Total quantity contracted to settle two business days from today.                                                                                              |
| …                | … one bucket per business day forward, out to the maximum standard cycle for the relevant market.                                                              |
| `Failed`         | Total quantity for which a terminal `Failed` state has been recorded; excluded from all balance views per [invariant 8](invariants.md#core-ledger-invariants). |

Each bucket total is signed: a long position contributes positive quantity, a short position contributes negative.

The bucket vector evolves with two independent drivers:

1. **Time**: at the start of each business day, every forward bucket shifts one position closer — yesterday's `SettlingT+1` becomes today's `SettlingToday`, yesterday's `SettlingT+2` becomes today's `SettlingT+1`, and so on.
2. **State transitions on the ledger**: a `Settled` confirmation moves quantity from `SettlingToday` into `SettledPrior`; a settlement attempt failure (`Instructed → Pending`) leaves the quantity in `SettlingToday` so that retries continue against the live balance; a terminal `Failed` state moves quantity into the `Failed` bucket.

The two balance views defined in [invariant 9](invariants.md#core-ledger-invariants) are derived directly from the bucket vector:

- **Settled balance** = `SettledPrior`.
- **Live balance** = `SettledPrior` + Σ all forward `Settling*` buckets.

`Failed` quantities contribute to neither.

### Total Cost Basis (Variation-Margined Products)

For products where P&L is crystallised through daily cash settlement rather than carried as unrealised gain — i.e. listed futures, and any other contract that implements daily VM against a CCP — the Position also carries a **total cost basis** scalar:

```
TotalCostBasis = Σ (price_i × quantity_i × multiplier)
```

summed over **all trades — settled and unsettled — that contribute to the current position**.

The cost basis is the reference against which VM is computed. For a daily-settled product:

```
Daily VM = (current reference price × quantity × multiplier) − TotalCostBasis
```

After VM is paid at EOD, the cost basis is reset to the day's mark:

```
TotalCostBasis ← settlement_price × quantity × multiplier
```

so that the next day's VM measures the day-on-day change in the reference price only, and not the cumulative P&L since trade date. This reset is the ledger expression of the daily P&L crystallisation that is the defining feature of futures.

### Why the Two Models Are Different

The bucket-vector model and the cost-basis model serve different products because their economic obligations differ.

- For a **delivery-settled product** (equities, bonds, FX spot/forward), the question that matters operationally is *when does each lot settle*. Once settled, the holding is a clean static balance. The bucket vector captures everything needed; cost basis is an accounting concept maintained off-ledger.
- For a **daily-margined product** (futures), the unit moves are written `Settled` at execution (see [Exchange Trade Booking Model](invariants.md#exchange-trade-booking-model)), so the bucket vector degenerates to a single bucket. What matters instead is the cost basis against which VM is computed and reset each evening.

Some products combine both: a physically deliverable future carries a cost basis up to expiry, then triggers a delivery transaction that itself runs through a settlement-bucket cycle (see [futures.md](smart_contracts/futures.md)).

---

## Per-Contract Position State

This section specifies, for each smart contract in the repository, which Position-state elements apply and at what granularity.

| Smart contract                                                | Bucket vector | Cost basis scalar | Notes                                                                                                                    |
|---------------------------------------------------------------|---------------|-------------------|--------------------------------------------------------------------------------------------------------------------------|
| [Cash equities](smart_contracts/equities.md)                  | Yes           | No                | T+1 standard cycle in most markets. Failures are reflected by the `Failed` bucket per invariant 8.                       |
| [Futures](smart_contracts/futures.md)                         | Degenerate    | Yes               | Unit moves written `Settled` at execution; the bucket vector collapses to a single net total. Cost basis resets nightly. |
| [Bonds](smart_contracts/bonds.md)                             | Yes           | No                | T+2 standard cycle; failure resolution paths as for equities.                                                            |
| [Equity options](smart_contracts/equity_options.md)           | Yes           | No                | Premium and exercise/expiry cash flows settle through the bucket cycle.                                                  |
| [FX (spot, forward, swap, NDF)](smart_contracts/fx.md)        | Yes           | No                | Cycle length depends on value date; payment netting compresses the vector across counterparties.                         |
| [IRS](smart_contracts/irs.md)                                 | Yes           | No                | Each periodic payment passes through the bucket cycle on its payment date.                                               |
| [Structured products](smart_contracts/structured_products.md) | Yes           | No                | Per-coupon and final-redemption cash flows pass through the bucket cycle on their value dates.                           |
| [QIS](smart_contracts/qis.md)                                 | Yes           | No                | Simulated wallet movements are recorded but settle off-cycle per the strategy definition.                                |
| [Cash payments](smart_contracts/cash_payments.md)             | Yes           | No                | The `Expected → Pending → Instructed → Settled` flow drives the bucket transitions.                                      |
| [SBL](smart_contracts/stock_borrow_loan.md)                   | Yes           | No                | Collateral margin call and return cycle map onto bucket movements.                                                       |
| [Funding](smart_contracts/funding.md)                         | Yes           | No                | Notional reset and IFR rate changes do not require a cost basis on the ledger.                                           |

Where a contract introduces a new margining mechanism (e.g. initial margin recorded on the ledger, or future VM extensions to cleared OTC contracts), the cost-basis pattern documented here is to be applied.

---

## State Versus Ledger

The ledger is canonical; Unit, Product, and Position state are all derivable from it.

| State element                | Derivation                                                                                                                                                      |
|------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Product                      | Set at Unit creation event; updated only through the cancel-and-correct amendment pattern.                                                                      |
| Liveness                     | Set at Unit creation as `Active`; advanced by lifecycle events recorded as transactions on the ledger.                                                          |
| Corporate-action history     | Appended each time a corporate action transaction is recorded against the Unit; entries reference the transaction(s) that implemented the action.               |
| Last lifecycle event         | Pointer to the most recent lifecycle-event transaction recorded against the Unit; each event references its predecessor so the chain is recoverable.            |
| Position bucket vector       | Aggregation of moves on the ledger by (wallet, unit, counterparty), partitioned by current move state and value date.                                           |
| Position cost basis          | For VM products, Σ (price × quantity × multiplier) over the contributing trades. The EOD reset is recorded on the ledger as part of the daily settlement event. |

Position state is therefore a view computed over the ledger; it is not a separate authoritative store. Every change to Position state is the consequence of a recorded move or state transition on the ledger.
