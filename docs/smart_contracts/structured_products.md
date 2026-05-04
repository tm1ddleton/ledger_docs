# Structured Products Smart Contract

## Overview

This smart contract governs the lifecycle of structured notes issued by the bank: compound instruments that embed one or more derivative payoffs within a fixed-income wrapper. The canonical example throughout this document is a **reverse convertible** (RC): a coupon-bearing note whose principal redemption is linked to an equity barrier knock-in put option. If the barrier is never triggered the investor receives coupons and full principal; if the barrier is triggered and the stock finishes below the strike, the investor receives shares at a below-market delivery price.

The model generalises to other structures — capital-protected notes, autocallables, range accruals — that share the same two-book booking pattern and compound unit decomposition.

---

## Booking Model

Structured products use a two-book model that differs from all other smart contracts in this repository, which use a single exchange-facing book:

| Book           | Role                                                                                         |
|----------------|----------------------------------------------------------------------------------------------|
| Issuance Book  | Represents the note issuance programme. Holds the bond component; manages coupon payments and principal redemption. Records the bank's liability to note holders |
| Hedging Book   | The trader's risk management book. Holds note inventory for client distribution; accumulates option risk as notes are distributed; manages delta hedge against the embedded barrier put |

Both books are real wallets. The client wallet (note holder) is a virtual wallet.

This two-book structure is necessary because the bank acts simultaneously as issuer (Issuance Book) and risk manager (Hedging Book). The bank's obligations to the client are tracked in the Issuance Book; the risk arising from those obligations is managed in the Hedging Book.

---

## Product Structure — Reverse Convertible

A reverse convertible decomposes into two instruments that are created and tracked separately in the ledger:

| Component      | Product Type     | Holder after creation | Description                                                                              |
|----------------|------------------|-----------------------|------------------------------------------------------------------------------------------|
| Bond unit      | Bond             | Issuance Book         | Coupon-bearing bond: funds the enhanced coupon stream and principal return                |
| Option unit    | Barrier KI put   | Hedging Book          | Knock-in put option on the reference equity; bank is long the put (investor is short it) |
| Note unit      | Structured note  | Hedging Book          | Compound instrument = bond + short put; held as inventory for client distribution        |

The note is a compound unit whose value equals `bond_PV + option_PV`. From the investor's perspective, holding the note is economically equivalent to holding the bond and having sold the put to the bank; the option premium is embedded in the enhanced coupon.

The bank holds the long put (embedded in the note structure). The bank's exposure is: long put + short bond (net after distributing notes to clients). The put is managed by the Hedging Book; the bond obligation is managed by the Issuance Book.

---

## Parties and Wallets

| Party             | Wallet Type    | Description                                                                                        |
|-------------------|----------------|----------------------------------------------------------------------------------------------------|
| Issuance Book     | Real wallet    | Holds bond unit; manages coupon and principal cashflows per [bonds.md](bonds.md)                   |
| Hedging Book      | Real wallet    | Holds note inventory and option unit; accumulates net risk as notes are distributed to clients     |
| Issuance Pool     | Virtual wallet | Unissued note units; source of new note units on each distribution                                 |
| Client / Investor | Virtual wallet | External note holder; recipient of coupons, principal, or shares at maturity                       |
| CSD / Exchange    | Virtual wallet | Counterparty for equity delivery at maturity in the physical settlement scenario                   |

---

## Lifecycle Events

### 1. Product Creation

**Trigger**: The structuring desk creates a new note programme. A single atomic transaction is generated containing three double-sided moves. All moves are written directly as `Settled` — there is no external settlement risk for an internal creation event.

The transaction simultaneously creates and routes the bond unit, the option unit, and the note unit. The cash consideration on each move is the fair value of the transferred instrument; because both books are internal and the note is priced as `bond_PV + option_PV`, all cash flows net to zero across the two books.

| Move | From          | To             | Asset                                    | State     |
|------|---------------|----------------|------------------------------------------|-----------|
| 1a   | Issuance Pool | Hedging Book   | Note unit (face value, N units)          | `Settled` |
| 1b   | Hedging Book  | Issuance Book  | Cash [CCY] (note face value × N)         | `Settled` |
| 2a   | Hedging Book  | Issuance Book  | Bond unit (face value, N units)          | `Settled` |
| 2b   | Issuance Book | Hedging Book   | Cash [CCY] (bond PV × N)                 | `Settled` |
| 3a   | Issuance Book | Hedging Book   | Option unit (N barrier KI puts)          | `Settled` |
| 3b   | Hedging Book  | Issuance Book  | Cash [CCY] (option premium × N)          | `Settled` |

Net cash per book: `(note face value) − (bond PV) + (option premium) = 0` (by construction, since note is priced at par).

**State after creation:**

| Book          | Assets held                                  | Net risk                                                                    |
|---------------|----------------------------------------------|-----------------------------------------------------------------------------|
| Issuance Book | -Note unit (N units) - Option unit (N units) + Bond unit (N units)| Flat: short note / short put / long bond = 0 (Note = Bond + Short Put) |
| Hedging Book  | Note unit (N units) + Option unit (N units) − Bond unit (N units) | Flat: long note / long put / short bond = 0 (Note = Bond + Short Put) |

CDM: `EventQualificationEnum.Execution` on all three products; `TradeState` created for Note, Bond, and Option; linked by a common `StructuredProductId` reference.

---

### 2. Note Distribution to Clients

**Trigger**: The Hedging Book sells note units to investors. Each distribution is a separate transaction.

For each note unit sold to a client:

| Move | From         | To              | Asset                                 | State                  |
|------|--------------|-----------------|---------------------------------------|------------------------|
| 1    | Hedging Book | Client          | Note unit (M units)                   | `Instructed → Settled` |
| 2    | Client       | Hedging Book    | Cash [CCY] (M × note issue price)     | `Instructed → Settled` |


For each note distributed, HB accumulates one unit of `−Bond + Long Put`:
- **Short 1 bonds**: Hedging Book has net short exposure to the bond component
- **Long 1 puts**: Hedging Book holds the aggregate knock-in put risk

This is the risk the trader must actively manage:
- Bond risk: duration-managed via bond hedges or interest rate derivatives
- Option risk: delta-hedged via equity positions; vega/barrier risk managed as per [equity_options.md](equity_options.md)

The delta hedge for a long barrier put (as stock falls toward the barrier) requires the Hedging Book to be **long equity** in increasing size. This long equity position is the hedge that will be unwound or delivered at maturity in the physical settlement scenario.

CDM: `EventQualificationEnum.Transfer`; `Position` created in client `PortfolioState`.

---

### 3. Coupon Payments

**Trigger**: Scheduled coupon date per the bond component's payment schedule. The bond component is held by the Issuance Book; coupon payments flow from the Issuance Book to clients via the Hedging Book.

The coupon lifecycle follows [bonds.md](bonds.md) for the bond unit held in the Issuance Book. On each coupon date, the Issuance Book generates a cash payment per outstanding note unit. The Hedging Book aggregates and distributes to note holders.

| Move | From          | To           | Asset                                          | State                |
|------|---------------|--------------|------------------------------------------------|----------------------|
| 1    | Issuance Book | Hedging Book | Cash [CCY] (coupon × N outstanding units)      | `Expected → Settled` |
| 2    | Hedging Book  | Each Client  | Cash [CCY] (coupon × client's note holdings)   | `Expected → Settled` |

The `Expected` state is used: the coupon amount and date are known from the note terms. Both moves are created on the coupon record date and transition to `Settled` on the coupon payment date.

CDM: `EventQualificationEnum.Coupon`; `Transfer` per the bond `PaymentSchedule`.

---

### 4. Barrier Observation (KI Monitoring)

**Trigger**: Each barrier observation date during the note's life. Continuous or discrete monitoring per note terms (see [equity_options.md](equity_options.md) for detailed barrier mechanics).

The barrier event is observed on the option unit held by the Hedging Book. The option unit remains `Active` throughout — the pre-KI and post-KI distinction is carried in the pricing model, not in the ledger state.

No new ledger moves are created on a barrier observation unless the barrier is breached. On KI breach:
- Option unit: state event recorded on the `TradeState` with timestamp; unit remains `Active`
- Note unit: `Active → BarrierBreached` (state event, bespoke note state — see CDM extensions)

The `BarrierBreached` state on the note does not change any cash flows during the remaining life. It signals to downstream systems that the equity delivery scenario at maturity is now possible.

CDM: `EventQualificationEnum.BarrierEvent` (bespoke; see extension 3 below); `TradeState` updated for both option and note units.

---

### 5. Maturity — No KI (Option Expires Worthless)

**Trigger**: Note reaches maturity date with no barrier breach having occurred.

The put option never became active; it expires worthless. The note redeems at par: each note unit returns face value in cash to the client.

**Option expiry** (per [equity_options.md](equity_options.md)):

| Move | Action                                                                                               |
|------|------------------------------------------------------------------------------------------------------|
| —    | Option unit: `Active → Matured` on expiry date; `Matured → Terminated` when note redemption settles |

**Note redemption** (principal return):

| Move | From          | To            | Asset                                       | State                |
|------|---------------|---------------|---------------------------------------------|----------------------|
| 1    | Issuance Book | Hedging Book  | Cash [CCY] (face value × M outstanding)     | `Expected → Settled` |
| 2    | Hedging Book  | Each Client   | Cash [CCY] (face value × client's holdings) | `Expected → Settled` |
| 3    | Client        | Issuance Pool | Note unit (M units returned)                | `Instructed → Settled`|

The bond unit in the Issuance Book matures simultaneously per [bonds.md](bonds.md), generating the principal cash flow that funds move 1.

After maturity: all note units retired, bond unit terminated, option unit terminated. Hedging Book unwinds residual delta hedge. Both books flat.

CDM: `EventQualificationEnum.ContractTermination` on all three product `TradeState`s.

---

### 6. Maturity — KI Triggered, Stock Above Strike (Option Lapses)

**Trigger**: Note reaches maturity. Barrier was breached during the life (`BarrierBreached` state on note unit), but the reference equity closes above the strike at maturity observation.

The put is in-the-money only if S_T < K. Since S_T ≥ K, the put expires worthless even though it was activated.

The redemption proceeds identically to §5. The only difference is the option unit's final state transition:

| Move | Action                                                                                               |
|------|------------------------------------------------------------------------------------------------------|
| —    | Option unit: `Active → Matured` on expiry date; `Matured → Terminated` when note redemption settles |

Note redemption and bond maturity follow the same moves as §5.

CDM: `EventQualificationEnum.ContractTermination`; `ClosedStateEnum.Expired` on the option `TradeState`.

---

### 7. Maturity — KI Triggered, Stock Below Strike (Put Exercised, Equity Delivery)

**Trigger**: Note reaches maturity. Barrier was breached during the life (`BarrierBreached` state on note unit), and the reference equity closes below the strike at maturity observation (S_T < K).

The embedded put is exercised. The client receives shares instead of cash principal. The number of shares delivered equals the note's physical settlement ratio:

```
Shares delivered = floor(face_value / strike_price)     per note unit
Cash residual    = face_value − (shares_delivered × strike_price)   [fractional amount, may be zero]
```

**Option exercise** (per [equity_options.md](equity_options.md)):

| Move | From         | To       | Asset                                                | State               |
|------|--------------|----------|------------------------------------------------------|---------------------|
| 1    | Hedging Book | Client   | Equity shares (shares_delivered × M outstanding)     | `Pending → Settled` |
| 2    | Hedging Book | Client   | Cash [CCY] (cash_residual × M, if non-zero)          | `Pending → Settled` |
| 3    | Client       | Issuance Pool | Note unit (M units retired)                     | `Pending → Settled` |

The equity shares in move 1 are sourced from the Hedging Book's delta hedge position (the long equity accumulated as the barrier was approached and the put delta increased). If the hedge is perfect, the delivered shares exactly match the hedge inventory. In practice there is a residual:

```
Residual equity = hedge_long_shares − shares_delivered
```

A positive residual (more hedge than required): Hedging Book is net long equity, to be unwound at market.
A negative residual (hedge shortfall): Hedging Book is net short equity, to be covered at market.

**Accounting note**: the client does not pay separately for the shares. The delivery extinguishes the principal obligation embedded in the note (the client effectively "paid" for the shares at the strike price when they purchased the note and agreed to the put terms). No additional cash flows from client to bank on exercise.

**Bond at maturity**: the Issuance Book's bond does NOT pay principal to the client in this scenario — the principal obligation was discharged via share delivery. The bond unit's final cash flow (principal) is instead used internally:

| Move | From          | To            | Asset                                         | State                |
|------|---------------|---------------|-----------------------------------------------|----------------------|
| 4    | Issuance Book | Hedging Book  | Cash [CCY] (face value, bond maturity proceeds)| `Expected → Settled` |

This cash flows to the Hedging Book to fund the delta hedge position wind-down or to offset the cost of sourcing any shortfall shares.

**Final states**: option unit `Active → Matured` on exercise; `Matured → Terminated` when equity delivery settles. Note unit `BarrierBreached → Matured → Terminated` concurrently. Bond unit matured per [bonds.md](bonds.md). Hedging Book retains any residual equity position for market unwind.

CDM: `EventQualificationEnum.OptionExercise` (on option unit) + `EventQualificationEnum.ContractTermination` (on note unit + bond unit); `TransferPrimitive` with `PhysicalSettlementTerms` for equity delivery.

---

## Failure Handling

| Scenario                                              | Action                                                                                                                        |
|-------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Creation transaction partially fails                  | Full rollback per [invariant 2](../invariants.md#core-ledger-invariants) — all three moves are atomic; none settle unless all succeed |
| Coupon payment fails                                  | Two-tier model per bonds.md; `Pending` retry, `Failed` if definitively unresolvable                                           |
| Barrier observation source unavailable               | Smart contract holds at last valid observation; observation deferred per the fallback convention specified in note terms; option state unchanged until confirmed observation available |
| Equity delivery fails at maturity (shares not sourced) | `Pending` state on share delivery move; Hedging Book sourcing shortfall in market; `Failed` only on definitive delivery failure; escalated to operations |
| Client fails to return note unit                     | Note unit remains with client wallet; cash/equity moves blocked pending note return; legal escalation outside ledger scope     |
| Hedge unwind results in material residual position   | Residual booked as a normal equity position in Hedging Book; funded per [funding.md](funding.md); separate from the note lifecycle |

---

## CDM Representation

### Standard CDM Types

| Concept                          | CDM Type / Field                                                                       | Notes                                                               |
|----------------------------------|----------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| Bond component                   | `Bond` product type                                                                    | Standard per bonds.md; `PaymentSchedule` drives coupon events      |
| Option component                 | `EquityOption` with `BarrierInstructions`                                              | Standard per equity_options.md; KI observation is a state event only — option stays `Active` |
| Note lifecycle state             | `TradeState` with bespoke note state extension                                         | See CDM extension 1                                                 |
| Product creation                 | `BusinessEvent` with three `TransferPrimitive`s in a single `EventInstruction`         | One event creates all three product `TradeState`s                   |
| Client distribution              | `EventQualificationEnum.Transfer`                                                      | Standard CDM transfer                                               |
| Coupon payment                   | `EventQualificationEnum.Coupon`; `Transfer` per bond `PaymentSchedule`                 | Per bonds.md                                                        |
| Barrier observation              | `BarrierObservationEvent` (bespoke) linked to option `TradeState`                      | See CDM extension 3                                                 |
| Option expiry (worthless)        | `EventQualificationEnum.ContractTermination`; `ClosedStateEnum.Expired`                | Standard CDM                                                        |
| Option exercise (equity delivery)| `EventQualificationEnum.OptionExercise`; `PhysicalSettlementTerms`                     | CDM supports physical settlement; compound linkage is bespoke       |
| Note termination                 | `EventQualificationEnum.ContractTermination`                                           | Standard CDM                                                        |

### CDM Extension Points

**1. Note unit as a compound `TradeState` (`StructuredProductUnit`)**

CDM does not provide a product type that represents a compound note whose value is derived from two separately-tracked sub-instruments (a bond and an option) with their own independent `TradeState` lifecycles. A bespoke `StructuredProductUnit` product type is required, extending `ContractualProduct` with:

- `bondComponent`: reference to the bond `TradeState` held in the Issuance Book
- `optionComponent`: reference to the option `TradeState` held in the Hedging Book
- `physicalSettlementRatio`: shares per unit delivered at maturity (`face_value / strike_price`)
- `settlementCurrency`: the currency in which cash residuals are paid

This creates a three-way linkage: note `TradeState` ↔ bond `TradeState` ↔ option `TradeState`. Lifecycle events on any component (e.g. KI on the option) must propagate to the note state.

**2. Note state model (`NoteStateEnum`)**

CDM `TradeState` has `ClosedState` for terminated trades but no intermediate states during the trade's life that reflect compound lifecycle milestones. A bespoke `NoteStateEnum` is required:

| State              | Description                                                                             |
|--------------------|-----------------------------------------------------------------------------------------|
| `Active`           | Note outstanding, coupons in schedule, barrier not yet breached                         |
| `BarrierBreached`  | Knock-in has occurred on the option component; equity delivery at maturity now possible  |
| `Matured`          | Maturity date reached; redemption in progress                                           |
| `Terminated`       | Fully redeemed; all obligations extinguished                                             |

State transitions on the note `TradeState` are driven by events on the component instruments and are not independently initiated.

**3. Barrier event propagation from option to note (`BarrierPropagationEvent`)**

When the `BarrierKnockIn` state event is recorded on the option component (per equity_options.md CDM extension 2), this must propagate to the note `TradeState` as a `NoteStateEnum.BarrierBreached` transition. CDM has no mechanism for cascading lifecycle events across linked `TradeState`s. A bespoke `BarrierPropagationEvent` is required, carrying:

- `sourceTradeId`: the option `TradeState` on which the barrier event occurred
- `targetTradeId`: the note `TradeState` whose state is being updated
- `observationDate`: the barrier breach date
- `observedLevel`: the reference equity price that triggered the breach

**4. Three-product creation as a single `BusinessEvent`**

CDM `BusinessEvent` supports a set of `PrimitiveEvent`s, but the standard model expects a single product to be created per `Execution` event. The structured product creation requires three distinct products (note, bond, option) to be instantiated atomically in a single `BusinessEvent`. A bespoke `StructuredProductCreationPrimitive` is required that wraps three `ExecutionPrimitive`s and enforces:

- Atomicity: all three product `TradeState`s are created or none are
- The inter-product linkage via `StructuredProductId` is established at creation
- The balancing cash flows between Issuance Book and Hedging Book net to zero

**5. Physical settlement equity delivery linked to note termination**

CDM `PhysicalSettlementTerms` on `EquityOption` supports share delivery on exercise. However, it models the delivery as the option holder delivering cash and receiving shares (vanilla put exercise). In the reverse convertible structure, there is no cash from the option buyer at exercise — the principal obligation is being discharged in shares. The delivery is a `TransferPrimitive` for shares out of the Hedging Book and a concurrent `ContractTermination` on the note, where the termination is the consideration for the share delivery. A bespoke `NotePhysicalRedemptionEvent` is required linking:

- Share delivery `Transfer` (Hedging Book → Client)
- Cash residual `Transfer` (if non-zero)
- Note unit `ContractTermination`
- Bond principal `Transfer` (Issuance Book → Hedging Book, internal funding of the hedge unwind)

---

## Relationship to Other Smart Contracts

| Smart Contract | Relationship                                                                                                                                                       |
|----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Bonds          | The bond component is governed by [bonds.md](bonds.md): coupon schedule generated at creation, FRN fixing if applicable, bond maturity. Bonds.md events on the bond unit propagate into the note lifecycle |
| Equity Options | The option component is governed by [equity_options.md](equity_options.md): barrier monitoring (continuous or discrete), KI observation recorded as a state event (option remains `Active`), physical settlement at expiry. Option events propagate to note state |
| Equities       | Equity delivery at maturity (§7) is a share transfer following the mechanics of [equities.md](equities.md): delivery vs. payment, settlement T+2, CSD notification |
| Funding        | Both Issuance Book and Hedging Book are subject to funding per [funding.md](funding.md). The bond unit in the Issuance Book is a funded asset; the note inventory and equity hedge in the Hedging Book are funded assets; the option unit is unfunded (derivative) |
| Cash Payments  | Coupon distributions to clients (§3) follow [cash_payments.md](cash_payments.md): `Expected` state booked on coupon record date; `Settled` on payment date |
| QIS            | QIS composite units may serve as the reference underlying of a structured note; the note decomposition model is the same, with the option referencing the QIS NAV per [qis.md](qis.md) |
