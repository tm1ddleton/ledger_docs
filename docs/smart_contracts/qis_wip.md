# Quantitative Investment Strategies (QIS) Smart Contract

## Overview

This smart contract governs the lifecycle of Quantitative Investment Strategies: rules-based systematic portfolios whose composition is determined periodically by a **lifecycle engine**. The lifecycle engine computes target portfolio weights according to the strategy rules, generates rebalancing transactions in a simulated wallet, and updates the value of a **composite unit** that references that wallet.

QIS strategies encompass a wide range of products including equity factor strategies, multi-asset risk premia, carry and momentum indices, and futures-roll strategies. The ledger model must accommodate two structurally distinct portfolio representations, addressed in separate sections below.

---

## Core Concepts

### Simulated Wallet as Portfolio

The portfolio underlying a QIS is held in a **simulated wallet** — a wallet representing theoretical (non-real) holdings. The simulated wallet is the canonical ledger record of the strategy's composition at any point in time. All rebalancing transactions write to this wallet.

A simulated wallet may hold two structurally different types of quantity:

- **Physical-proxy units**: discrete counts of fungible asset units (shares, bond units, etc.) identified by security identifier. The quantity is a dimensionless count; the value at any time is count × market price.
- **Return-stream notionals**: the units of each constituent are currency-denominated notional amounts allocated to a named return stream. The quantity IS the notional; the weight of stream `i` in the portfolio is implicit in the notional ratio: `w_i = notional_i / Σⱼ notional_j`. Weights are never stored as a separate field — they are always derived from the ledger notionals at the relevant point in time.  The fixings used to compute the notionals at rebalance are included in the metadata.

There are of course conversion formulae to go between the two models: but we prefer to mirror the respective rulebooks for simplicity.

**Ledger authoritativeness**: the ledger is authoritative for portfolio *composition* — the set of constituents and their quantities — as at the most recent rebalancing event.

### Composite Unit

A **composite unit** is a compound unit whose value is derived from the contents of the simulated wallet at any point in time. It is the instrument that external parties hold: a structured product, TRS, or index certificate may be written on one or more composite units.

Per the ledger definitions in [invariants.md](../invariants.md), a unit may be compound and based on other wallets. The composite unit formalises this: it is identified by a unique strategy identifier and its NAV per unit is recomputed on each fixing or rebalancing event.

### QIS Lifecycle Engine

The QIS lifecycle engine is the rules-based computation layer that drives the QIS. It:
1. Receives market data observations (prices, fixings, rates) on scheduled dates.
2. Applies the strategy rules to compute the target portfolio composition.
3. Outputs rebalancing transactions to the ledger and a new NAV per composite unit.

The lifecycle engine is to QIS what QRL is to options and rate products: it defines what market observations are needed and when, and the smart contract layer translates its output into ledger moves and state transitions. The smart contract does not embed strategy logic; it executes lifecycle engine instructions.

---

## Portfolio Models

### Model A: Constituent-Based Portfolio (Equity and Multi-Asset Indices)

The portfolio is defined as a set of constituents, each held in a specific quantity. The index level at any time is:

```
Index Level(t) = Σ [ quantity_i(t) × price_i(t) ] / Divisor(t)
```

The divisor is adjusted on corporate actions and rebalancing events to maintain continuity of the index level.

**Simulated wallet contents**: equity units, bond units, or other physical-proxy units. Each unit is identified by its security identifier (ISIN or equivalent).

**Rebalancing trigger**: periodic (e.g. quarterly index reconstitution) or event-driven (e.g. corporate action adjusting the divisor). The lifecycle engine computes the new constituent quantities; the smart contract generates the rebalancing transaction.

**Examples**: equity factor indices (momentum, value, quality), multi-asset risk premia baskets, dividend-weighted indices.

### Model B: Return/Fixing-Based Portfolio (Futures and Weights-Based Indices)

The portfolio is defined by a weighted combination of observable return streams. Constituents are not held as discrete unit counts; instead, each constituent is represented as a **notional-based Total Return Swap (TRS)**: a currency-denominated notional allocated to a named return stream. The payout of each constituent position is identical to the payout of a TRS:

```
Payout of constituent i over period [t, T] = N_i × r_i(T)

where N_i = w_i × total_reference_notional
      r_i = total return of constituent i over the period
```

This is exactly the payout of a TRS on constituent `i` with notional `N_i`. The weight is embedded in the notional: no price is needed to set `N_i` at rebalancing time — only the target weight and the reference notional are required. Price observations are needed separately at fixing dates to compute `r_i`. Rebalancing and return computation are therefore fully decoupled, which resolves the weights-known/price-unknown scenario: rebalancing at `T` is deterministic as soon as weights are published, regardless of whether prices are known.

The index level is the cumulative product of period portfolio returns:

```
Index Level(t) = Index Level(t₀) × ∏ₜ [ 1 + Σᵢ( r_i(t) × w_i(t) ) ]
```

where the outer product runs across all fixing periods from inception to the current date, and `w_i(t)` is derived from the ledger notionals at the start of each period (never stored explicitly).

**Simulated wallet contents**: currency-denominated **TRS notional positions** for each constituent return stream (e.g. USD 600,000 allocated to "ES Front-Month Return", USD 400,000 to "3M EURIBOR Excess Return"). The quantity recorded in the ledger for each constituent IS the notional.

The weight of each constituent is implicit in the notional ratio and is never stored as a separate field:

```
w_i(t) = notional_i / Σⱼ notional_j     (evaluated from ledger state at start of each period)
```

Because weights must sum to 1, any rebalancing that increases one constituent's notional must decrease others by an equal total. Double-entry balance holds through the Index Manager virtual wallet.

**Rebalancing trigger**: roll events (constituent reference approaching expiry, e.g. futures roll) or periodic weight resets. In both cases the lifecycle engine publishes new target notionals; the smart contract generates the delta-notional moves. No prices are required.

**Examples**: S&P GSCI (commodity futures rolling return), CTA trend-following indices, equity factor strategies defined in weight space, interest rate carry strategies, volatility risk premium indices.

---

## Parties and Wallets

| Party                        | Wallet Type       | Description                                                                                                 |
|------------------------------|-------------------|-------------------------------------------------------------------------------------------------------------|
| Simulated Portfolio          | Simulated wallet  | Holds the theoretical constituent positions (physical-proxy units or return-stream units) of the strategy   |
| Index Manager                | Virtual wallet    | Represents the strategy administrator / index sponsor; counterparty to all rebalancing moves in the simulated wallet |
| Composite Unit Issuance Pool | Real wallet       | Holds unissued composite units; composite units are transferred from here to investors on subscription       |
| Investor / Desk Book         | Real wallet       | Holds composite units acquired through subscription or secondary trading                                    |
| Cash Account                 | Real wallet       | Holds cash flows associated with subscriptions, redemptions, and income distributions                       |

---

## Lifecycle Events

### 1. Strategy Inception

**Trigger**: Strategy is defined and the first portfolio composition is established by the lifecycle engine.

The lifecycle engine outputs the initial constituent set and quantities (Model A) or the initial return-stream unit allocations and notional amounts (Model B).

**Transaction**: Initial population of the simulated wallet.

For Model A:

| Move                           | From            | To                   | Asset                                  | State    |
|--------------------------------|-----------------|----------------------|----------------------------------------|----------|
| Constituent allocation (× N)   | Index Manager   | Simulated Portfolio  | quantity_i units of security_i (per constituent) | `Settled` |

For Model B:

| Move                              | From          | To                  | Asset                                                      | State     |
|-----------------------------------|---------------|---------------------|------------------------------------------------------------|-----------|
| Return-stream allocation (× N)    | Index Manager | Simulated Portfolio | notional_i [CCY] of return-stream_i (per stream)           | `Settled` |

where `notional_i = index_level(t₀) × w_i(t₀) × composite_units_outstanding`. The sum of all stream notionals equals the total index value at inception. Weights are not stored; they are implicit in the initial notional split.

Initial moves are written directly as `Settled` — the simulated portfolio has no pending settlement; it is a theoretical construct that is in force from inception. The initial NAV per composite unit is set by the lifecycle engine (e.g. 100 or 1000 index points).

CDM: `EventQualificationEnum.Execution`; `PortfolioState` created with initial constituent set.

### 2. Composite Unit Issuance

**Trigger**: An investor subscribes, or an internal desk acquires exposure via the composite unit.

Two funding structures are supported:

**Funded**: the investor pays the full NAV upfront in exchange for composite units. The cash is the investor's at-risk capital.

| Move                    | From                         | To                   | Asset                                   | State                  |
|-------------------------|------------------------------|----------------------|-----------------------------------------|------------------------|
| Composite unit issuance | Composite Unit Issuance Pool | Investor / Desk Book | N composite units                       | `Instructed → Settled` |
| Subscription cash       | Investor / Desk Book         | Cash Account         | Cash (N × NAV per unit at dealing date) | `Pending → Settled`    |

**Unfunded**: the investor gains exposure without paying upfront capital (e.g. via a TRS or unfunded structured note). The composite unit is issued to the desk book as a hedge; the investor's obligation is governed by the overlying product smart contract (see [irs_wip.md](irs_wip.md), [structured_products.md](structured_products.md)). No subscription cash move is created at issuance. Settlement at termination is covered in §7.

| Move                    | From                         | To             | Asset             | State                  |
|-------------------------|------------------------------|----------------|-------------------|------------------------|
| Composite unit issuance | Composite Unit Issuance Pool | Desk Book      | N composite units | `Instructed → Settled` |

CDM: `EventQualificationEnum.Transfer`; new `Position` added to investor's or desk's `PortfolioState`.

### 3. Periodic Rebalancing — Model A (Constituent-Based)

**Trigger**: Scheduled rebalancing date per the strategy rules (e.g. quarterly). The lifecycle engine receives current prices and outputs the new target constituent quantities.

The smart contract computes the delta between the current simulated wallet holdings and the target, and generates a balanced rebalancing transaction. Each constituent change is a pair of moves (one in, one out) to maintain double-entry balance against the Index Manager virtual wallet.

| Move                              | From                | To                   | Asset                                   | State    |
|-----------------------------------|---------------------|----------------------|-----------------------------------------|----------|
| Constituent increase (× M_in)     | Index Manager       | Simulated Portfolio  | Δquantity_i units of security_i         | `Settled` |
| Constituent decrease (× M_out)    | Simulated Portfolio | Index Manager        | Δquantity_j units of security_j         | `Settled` |
| Divisor adjustment cash (if any)  | Index Manager       | Simulated Portfolio  | Cash adjustment to maintain index continuity | `Settled` |

Rebalancing moves in the simulated wallet are written directly as `Settled` — there is no pending settlement in the simulated context. The transaction is atomic: all constituent changes take effect simultaneously.

Following the rebalancing transaction, the lifecycle engine computes a new NAV per composite unit based on the new composition and current prices. The NAV update is a state event on the smart contract; no new moves are created unless the rebalancing also triggers a distribution (see §Income and Distributions).

CDM: `BusinessEvent` with `QuantityChangePrimitive` applied per constituent; produces a new `PortfolioState`.

#### Provisional Rebalancing Scenario (Model A only)

One scenario arises in Model A where the full rebalancing inputs are not available at the scheduled rebalancing time `T`. This is **not within the ledger scope** — the ledger only records definitive, confirmed moves — but is relevant to the smart contract layer.

**Quantity-known, price-unknown rebalance**: The index provider publishes new constituent quantities at or before `T` (e.g. a scheduled index reconstitution announcement), but the execution prices at which those trades clear are not known until later in the trading day (typically at auction close or VWAP). The simulated portfolio's unit quantities can be updated immediately, but NAV computation dependent on execution price must be deferred. The smart contract may create provisional ledger entries using indicative prices and apply a cancel/correct (per [invariant 7](../invariants.md#core-ledger-invariants)) once actual execution prices are confirmed.

Note: the analogous **weights-known, price-unknown** scenario does not arise in Model B. Because Model B constituents are TRS notional positions, rebalancing requires only the new target weights and the reference notional — both of which are known when weights are published. Prices are observed separately at fixing dates to compute returns. The rebalancing and return computation are fully decoupled; no provisional treatment is needed.

### 4. Periodic Rebalancing — Model B (Return/Fixing-Based): Roll Events

**Trigger**: A scheduled roll event (e.g. futures contract expiry window) or a weight reset per strategy rules. The lifecycle engine receives the required fixings and computes the roll mechanics.

A roll replaces the expiring stream's notional with an equivalent notional in the new stream, adjusted for the roll return (the gain or loss from rolling from the expiring to the new contract). The new notional is:

```
notional_new = notional_old × (1 + roll_return)
```

where `roll_return` is the return earned over the roll window, computed by the lifecycle engine from the relevant fixings.

| Move                             | From                | To                   | Asset                                          | State     |
|----------------------------------|---------------------|----------------------|------------------------------------------------|-----------|
| Return-stream exit               | Simulated Portfolio | Index Manager        | notional_old [CCY] of expiring-stream_i        | `Settled` |
| Return-stream entry              | Index Manager       | Simulated Portfolio  | notional_new [CCY] of new-stream_i             | `Settled` |

The notional delta (the roll gain or loss: `notional_new − notional_old`) passes through the Index Manager virtual wallet and maintains double-entry balance. After the roll, the implicit weight of stream `i` is unchanged (the same fraction of total notional), but the total portfolio notional has increased or decreased by the roll gain or loss — this is the return contribution of the roll event, compounded into the index level.

For a **weight reset** (where the lifecycle engine targets new weights `w_i'` rather than just rolling), the move quantities are the full delta between current notionals and target notionals:

```
Δnotional_i = (w_i' × new_total_notional) − notional_i
```

Streams gaining weight receive positive Δnotional (Index Manager → Simulated Portfolio); streams losing weight deliver positive Δnotional back (Simulated Portfolio → Index Manager). The sum of all Δnotionals is zero — the total portfolio notional is unchanged by a pure weight reset.

CDM: `BusinessEvent` with `QuantityChangePrimitive` on the return-stream constituents; new `PortfolioState`.

### 5. Fixing Events and NAV Computation

**Trigger**: A scheduled fixing date (daily, weekly, or monthly per strategy terms). The lifecycle engine receives the required market data observations for each constituent and computes the new index level.

For **Model A**: the lifecycle engine receives constituent prices and computes:
```
New Index Level = Σ [ quantity_i × new_price_i ] / Divisor
New NAV per unit = New Index Level × unit_scaling_factor
```

For **Model B**: the lifecycle engine reads the ledger notionals as at the last rebalancing, derives the implicit weights, receives the fixing for each return stream, and computes:

```
w_i(t)              = notional_i / Σⱼ notional_j       (read from ledger; evaluated at period start)
r_i(t)              = (new_fixing_i / prev_fixing_i) − 1  (or per the stream's return convention)
Portfolio return(t)  = Σᵢ [ r_i(t) × w_i(t) ]
New Index Level      = Prev Index Level × ( 1 + Portfolio return(t) )
New NAV per unit     = New Index Level × unit_scaling_factor
```

The weights `w_i(t)` are derived from the ledger notionals at the start of the period; they are not persisted in the ledger. The lifecycle engine owns this calculation; the smart contract receives the resulting index level as an input, records it as a state event, and writes no new moves unless a rebalancing is also triggered.

If no rebalancing is required, no ledger transaction is created. The updated index level is recorded as a state event on the smart contract. **This is the expression of the authoritativeness boundary**: the ledger holds the composition; the lifecycle engine holds the current valuation.

If a fixing indicates a constituent must be removed (e.g. index deletion due to corporate action, futures contract expiry), a rebalancing transaction is triggered as per §3 or §4.

CDM: `EventQualificationEnum.Observation`; `Reset` primitive records the fixing; `PortfolioState` unchanged unless constituent change required.

### 6. Income and Distributions (Model A)

For constituent-based portfolios that include dividend-paying equities, the simulated portfolio accrues dividend income on ex-dividend dates. The treatment mirrors the cash payments model in [cash_payments.md](cash_payments.md).

On ex-dividend date, the lifecycle engine identifies dividends due on simulated constituent holdings and creates an income accrual:

| Move                        | From             | To                   | Asset                                    | State    |
|-----------------------------|------------------|----------------------|------------------------------------------|----------|
| Dividend accrual            | Index Manager    | Simulated Portfolio  | Cash (dividend per share × held quantity) | `Expected` |

This cash is reinvested in the simulated portfolio on the dividend payment date (for a total return index) or retained as a cash distribution to composite unit holders (for a price return index). For total return: a reinvestment rebalancing transaction is created on payment date that converts the cash into additional constituent units.

Return-based portfolios (Model B) that reference total-return futures already embed dividend returns in the futures price; no separate accrual event is needed.

### 7. Composite Unit Redemption / Termination

**Trigger**: A funded investor redeems at a scheduled dealing date, or an unfunded position reaches its contractual termination date (or is terminated early).

In both cases the composite unit is returned to the issuance pool. The cash settlement direction and amount differ by structure.

#### Funded Redemption

The investor receives cash equal to the current NAV. NAV is always non-negative for a funded product (the investor's maximum loss is the initial subscription amount). The desk is the passive payer; the investor is the passive recipient.

| Move                      | From                 | To                           | Asset                                      | State                  |
|---------------------------|----------------------|------------------------------|--------------------------------------------|------------------------|
| Composite unit return     | Investor / Desk Book | Composite Unit Issuance Pool | N composite units                          | `Instructed → Settled` |
| Redemption cash           | Cash Account         | Investor / Desk Book         | Cash (N × NAV per unit at redemption date) | `Expected → Settled`   |

#### Unfunded Termination

For an unfunded position the settlement amount is the total return of the composite units over the holding period, applied to the reference notional. The direction of the cash move depends on performance:

```
Settlement amount = reference_notional × (NAV_terminal / NAV_initial − 1)
```

**Positive performance** (index has risen — investor is owed):

| Move                      | From                 | To                           | Asset                        | State                  |
|---------------------------|----------------------|------------------------------|------------------------------|------------------------|
| Composite unit return     | Desk Book            | Composite Unit Issuance Pool | N composite units            | `Instructed → Settled` |
| Settlement (gain)         | Cash Account         | Investor / Counterparty      | Cash (positive return × notional) | `Expected → Settled` |

**Negative performance** (index has fallen — investor owes the desk):

| Move                      | From                      | To                           | Asset                         | State                 |
|---------------------------|---------------------------|------------------------------|-------------------------------|-----------------------|
| Composite unit return     | Desk Book                 | Composite Unit Issuance Pool | N composite units             | `Instructed → Settled`|
| Settlement (loss)         | Investor / Counterparty   | Cash Account                 | Cash (negative return × notional) | `Pending → Settled` |

The settlement cash move uses `Expected` when the desk is paying (it knows it owes cash, analogous to a scheduled receipt in [cash_payments.md](cash_payments.md)) and `Pending` when the investor is paying (it is an obligation the desk is instructing). Both settle T+2 or per contract terms.

The sign of the settlement is computed by the lifecycle engine from the terminal NAV and the reference notional. The smart contract creates whichever move direction the lifecycle engine instructs; it does not embed the sign logic itself.

CDM: `EventQualificationEnum.Transfer` (funded); `EventQualificationEnum.ContractTermination` + `Transfer` (unfunded); `Position` removed from holder's `PortfolioState`.

### 8. Strategy Termination

**Trigger**: Strategy reaches its scheduled end date, or is wound up early.

All simulated wallet holdings are unwound: constituent moves from the simulated wallet to the Index Manager, and all outstanding composite units are redeemed at the final NAV. Remaining composite units are redeemed at the terminal NAV. The composite unit `TradeState` is closed.

CDM: `EventQualificationEnum.ContractTermination`; final `PortfolioState` closed.

---

## CDM Representation

### Standard CDM Types

| Concept                         | CDM Type / Field                                                                          | Notes                                                                                      |
|---------------------------------|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| Simulated portfolio composition | `PortfolioState`                                                                          | Snapshot of holdings at a point in time; new `PortfolioState` created on each rebalancing |
| Individual constituent holding  | `PortfolioState.positions` → `Position`                                                  | Each position has a `product` and `quantity`                                               |
| Constituent-based rebalancing   | `BusinessEvent` with `QuantityChangePrimitive`                                            | Applied per constituent that changes; before/after `PortfolioState` pair                   |
| Index / basket definition       | `Basket` → `BasketConstituent[]`                                                          | Defines the composite unit's composition at inception; `BasketConstituent.weight` for weights |
| Composite unit                  | `Index` or `Basket` product type referencing the simulated wallet                        | The composite unit is a CDM `Product` whose underlying is the basket/index                 |
| Fixing observation               | `Observation` primitive with `Observable` referencing the constituent price or fixing      | Standard CDM                                                                               |
| NAV update                      | `Reset` primitive                                                                          | Carries the new index level; linked to `Observation` inputs                                |
| Composite unit issuance         | `Transfer` with `TransferStatusEnum`                                                      | Standard CDM transfer of the basket/index unit                                             |
| Income accrual                  | `ScheduledTransfer` within payout terms                                                   | Per cash_payments.md; `Expected` state (bespoke)                                          |

### CDM Extension Points

**1. Return-stream notional as a `BasketConstituent` (`ReturnStreamConstituent`)**

CDM's `BasketConstituent` expects a `Product` reference with a dimensionless quantity (share count, bond face value, etc.). A return-stream notional is not a CDM product — it is a currency-denominated allocation to a named observable return series, and its quantity is a monetary amount, not a unit count. A bespoke `ReturnStreamConstituent` type is required, extending `BasketConstituent` with:
- `returnStreamId`: identifier of the return stream
- `notionalAmount`: the currency-denominated notional allocation (this IS the quantity field; replaces CDM's dimensionless `quantity`)
- `observableSeries`: the fixing series driving the return computation (e.g. front-month futures settlement price)
- `returnConvention`: how the period return is calculated (price return, total return, excess return)
- `rollConvention`: how the stream rolls at expiry (calendar, open interest, volume-weighted)

The weight field on `BasketConstituent` is not used for Model B constituents — weight is always derived as `notionalAmount_i / Σⱼ notionalAmount_j` and computed by the lifecycle engine at the start of each return period. Storing a weight separately would create a redundant and potentially inconsistent field.

**2. Simulated wallet as a first-class portfolio reference**

CDM `PortfolioState` does not carry a wallet reference. The composite unit's reference to the simulated wallet is a bespoke linkage: `BasketUnderlier.portfolio → SimulatedWalletId`. This identifies which simulated wallet provides the NAV for the composite unit at any given time.

**3. `EventQualificationEnum.Rebalancing`**

CDM does not have an explicit rebalancing event qualification. Portfolio composition changes are represented as `QuantityChangePrimitive` events but are not distinctly qualified. A bespoke `Rebalancing` event qualification is required to unambiguously classify periodic strategy rebalances in the audit trail, distinct from other quantity-change events (e.g. partial terminations, novations).

**4. Roll event as a paired `QuantityChangePrimitive`**

A futures roll is a simultaneous exit of one return-stream unit and entry into another with an adjusted notional. CDM's `QuantityChangePrimitive` supports quantity changes on a single product; a paired exit/entry on two distinct return-stream products in one atomic event requires a bespoke compound primitive or a two-step transaction explicitly linked by a roll reference.

**5. `PortfolioState` continuity via divisor**

For constituent-based indices, the divisor maintains index-level continuity across corporate actions and rebalancing events. CDM `PortfolioState` has no divisor field. A bespoke `IndexDivisor` field is required on the `PortfolioState`, updated as part of each rebalancing `QuantityChangePrimitive`.

---

## Relationship to Other Smart Contracts

| Product                         | Relationship                                                                                                                                                       |
|---------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Total Return Swap (TRS) on QIS  | The TRS references composite units as the underlying; the TRS payer receives the total return on the composite unit. Coupon payments per [irs_wip.md](irs_wip.md). |
| Structured note referencing QIS | The note's redemption amount is linked to composite unit NAV at maturity; structured per [structured_products.md](structured_products.md)                          |
| Equity futures on index         | The futures price references the constituent-based index level; futures lifecycle per [futures.md](futures.md)                                                     |
| Cash dividend income            | Constituent dividends in Model A simulated wallets follow [cash_payments.md](cash_payments.md)                                                                     |

---

## Failure Handling

| Scenario                                              | State / Action                                                                                                    |
|-------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Fixing unavailable on scheduled observation date      | Lifecycle engine holds; fixing rescheduled per the strategy's fallback convention (e.g. last valid fixing carried) |
| Constituent price unavailable on rebalancing date     | Rebalancing deferred; lifecycle engine outputs a partial rebalance excluding the affected constituent              |
| Roll execution fails (return-stream unit)             | Old return-stream unit remains in simulated wallet; lifecycle engine retries on next eligible roll date; no `Failed` state (simulated wallet moves do not follow the two-tier settlement model — they are always `Settled` immediately) |
| Lifecycle engine produces inconsistent target weights | Transaction blocked at smart contract layer; requires lifecycle engine correction and resubmission; no partial rebalancing written |
| Composite unit redemption cash fails                  | Two-tier model per [invariant 8](../invariants.md#core-ledger-invariants); composite unit returned to issuance pool pending cash settlement |

---

## Implementation

This section binds the QIS contract to the [External Message Interface](../implementation.md).

### Inbound

| Family                   | Concrete message(s)                                                                                                                    | Window                        | Triggers                                                       |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------|-------------------------------|----------------------------------------------------------------|
| `MarketObservation`      | Constituent prices, one per fixing date (Model A)                                                                                      | Point (date) ×N               | Index-level / NAV computation; rebalancing valuation.          |
| `MarketObservation`      | Return-stream fixings (Model B); roll-window returns                                                                                   | Point (date) / Range          | Return accrual; roll mechanics.                                |
| `MarketObservation`      | `NAV` / `IndexLevel` — composite level, incl. TWAP/VWAP execution windows                                                              | Point or Range (date + times) | Unit NAV update; rebalancing execution.                        |
| `DateEvent`              | `ScheduledDate` — rebalancing dates, fixing dates, ex-dividend & dividend dates (Model A), dealing dates, strategy end / early wind-up | —                             | Rebalance; income accrual; redemption; termination.            |
| `CorporateAction`        | CA on basket constituents (Model A) → divisor adjustment; index deletion                                                               | —                             | Divisor / composition adjustment to preserve index continuity. |
| `OperationalInstruction` | Lifecycle-engine outputs (target composition, new NAV, roll mechanics); dividend accruals from index manager                           | —                             | Constituent/notional moves in the simulated wallet.            |

### Outbound

| Family               | Concrete message(s)                                                                                                                          | CDM projection                                                      |
|----------------------|----------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| `Payment`            | Dividend accrual cash (Model A); composite-unit subscription / redemption cash; settlement on unfunded terminations; divisor-adjustment cash | `Transfer` / `CashTransfer`                                         |
| `ProductStateChange` | NAV / index-level updates; `PortfolioState` transition on each rebalancing; strategy termination                                             | `Observation` + `Reset` / `Rebalancing` `†` / `ContractTermination` |
| `NewProductTemplate` | Composite unit on strategy inception (simulated wallet populated); composite-unit issuance is a new position, not a new template             | `Execution` / `Transfer`                                            |
