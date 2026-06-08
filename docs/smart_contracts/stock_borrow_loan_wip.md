# Stock Borrow / Loan (SBL) Smart Contract

## Overview

This smart contract governs the booking and lifecycle of securities lending transactions: arrangements in which one party (the lender) transfers securities to another party (the borrower) for a defined or open term, against the delivery of collateral (cash or non-cash). Legal title to the securities passes to the borrower; the lender retains an economic interest and the contractual right to recall the securities.

This smart contract covers three principal lending directions:

1. **Desk as borrower (external)** — the structured products desk borrows securities from an external counterparty (prime broker, agent lender, or bilateral lender). The lender is represented by a virtual wallet. Typical use cases: covering short positions accumulated through delta-hedging of barrier puts (see [structured_products.md](structured_products.md)); curing settlement fails where the desk's own inventory is insufficient.
2. **Desk as lender (external)** — the desk holds long inventory and lends securities to an external borrower. The borrower is represented by a virtual wallet. The desk earns a lending spread or fee on the loaned securities.
3. **Internal stock loan (bank as lender)** — one of the bank's own inventory books lends securities from its own holdings to the structured products desk. Both the lender and the borrower are **real wallets** (internal books of the same legal entity). This is the most common lending direction in a structured products business: the inventory book sources the securities and lends them internally so the desk can use them for hedging or settlement. See §Internal Stock Loan for the specific differences that apply in this case.

External SBL transactions (directions 1 and 2) are governed by the **Global Master Securities Lending Agreement (GMSLA)**, published by ISLA. Each bilateral lending relationship operates under a GMSLA; the smart contract encodes the economic terms of individual transactions within that legal framework. Internal stock loans (direction 3) are governed by internal trading policy rather than a GMSLA.

> **Out of scope — inventory held at prime broker with swap to client**: A related arrangement in which the inventory book holds its securities at the bank's own prime broker (custody external to the bank) and places the economic value of those securities on total return swap with a client is acknowledged but out of scope for this specification. In this structure, the internal stock loan sits within a chain of the form: PB (custody) → Inventory Book → Structured Products Desk, with the client holding synthetic exposure via TRS. The additional complexity of PB margin, custody charges, and TRS economic attribution will be specified as an extension to this document when brought in scope.

---

## Instrument Scope

| Instrument         | Typical Collateral      | Fee Structure                           | Term                     |
|--------------------|-------------------------|-----------------------------------------|--------------------------|
| Equity borrow/loan | Cash (USD, EUR, GBP)    | Rebate rate on cash collateral          | Open or term             |
| Equity borrow/loan | Non-cash (bonds, equity)| Lending fee on loan value               | Open or term             |
| Bond borrow/loan   | Cash                    | Rebate rate on cash collateral          | Open or term             |
| Bond borrow/loan   | Non-cash                | Lending fee on loan value               | Open or term             |

Commodity securities, ETFs, and ADRs are in scope if the underlying is a security eligible under the GMSLA. Repo (repurchase agreement) on bonds is **out of scope** for this contract — repo is an economically distinct instrument governed by a GMRA and is specified separately.

---

## Key Concepts

### Open vs. Term Loans

An **open loan** has no fixed maturity. Either party may terminate by giving standard notice (typically T+2 for equities, T+2 for bonds). Open loans are the most common structure for equity SBL. The smart contract tracks the loan indefinitely until a recall or return event terminates it.

A **term loan** has a fixed maturity date specified at execution. The loan automatically terminates on the maturity date unless extended by bilateral agreement. Both parties can still give early return/recall notice subject to contractual provisions.

### Loan Value and Collateral Margin

The **loan value** is the mark-to-market value of the loaned securities at each observation date:

```
Loan Value = N_securities × Market Price × FX rate (if cross-currency)
```

The **collateral amount** required from the borrower incorporates a margin (haircut) above the loan value to protect the lender against an adverse price move between a margin call and the return of securities:

```
Required Collateral = Loan Value × (1 + Margin %)
```

Typical margins: 102% (cash, USD/GBP equity), 105% (cash, EM equity), 105–108% (non-cash). The margin percentage and collateral eligibility criteria are specified in the GMSLA and the trade confirmation.

### Cash Collateral and the Rebate

When the borrower posts cash collateral, the lender holds the cash and pays the borrower a **rebate rate**:

```
Rebate = Cash Collateral × Rebate Rate × (Days / 360)
```

The rebate rate is a negotiated fraction of the risk-free overnight rate (e.g. Fed Funds for USD, €STR for EUR). The lender's economic fee is the spread between the risk-free rate and the rebate rate — known as the **lending spread**. A "special" security commands a high lending spread (low or negative rebate); a "general collateral" (GC) security commands a spread close to zero.

### Non-Cash Collateral and the Lending Fee

When the borrower delivers non-cash collateral (typically bonds or other equities), the borrower pays the lender a direct **lending fee**:

```
Lending Fee = Loan Value × Fee Rate × (Days / 360)
```

The fee rate is agreed at execution and may be fixed for the term or reset periodically.

### Manufactured Payments

When securities are on loan over a **record date** for a corporate income event (dividend, coupon), the borrower must manufacture an equivalent cash payment to the lender. The manufactured payment is not a dividend from the issuer; it is a contractual obligation of the borrower, payable on or before the original payment date. The borrower receives the actual dividend/coupon from the issuer (since legal title has passed to them), and the net position is zero.

Manufactured payments preserve the lender's economic entitlement to income on the loaned security. The state model for manufactured payments mirrors the ex-date/payment-date model in [cash_payments.md](cash_payments.md), adapted for the fact that the payer is the borrower (not the CSD).

### Collateral Substitution

The borrower may substitute non-cash collateral with different eligible securities, subject to the lender's consent and the GMSLA eligibility criteria. Substitution is a same-day operation: the new collateral is delivered before or simultaneously with the return of the old collateral. No net collateral shortfall is permitted during substitution.

---

## Parties and Wallets

| Party                 | Wallet Type    | Description                                                                                                                              |
|-----------------------|----------------|------------------------------------------------------------------------------------------------------------------------------------------|
| Lender / Borrower     | Virtual wallet | External counterparty (prime broker, agent lender, or bilateral counterparty) for directions 1 and 2. One virtual wallet per counterparty |
| Inventory Book        | Real wallet    | The bank's own inventory book acting as internal lender (direction 3). One real wallet per inventory-holding desk within the legal entity  |
| Securities Book       | Real wallet    | The structured products desk's securities holding book. Receives securities (when borrowing) or delivers securities (when lending)         |
| Collateral Book       | Real wallet    | The desk's collateral book. Delivers collateral to the counterparty (when borrowing externally) or receives it (when lending externally)   |
| CSD / Custodian       | Virtual wallet | Settlement agent for external securities legs; holds securities in custody on behalf of the desk. Not used for internal stock loans        |

The desk does not use an exchange-facing book for SBL — SBL is a bilateral OTC arrangement. External settlement is effected directly between counterparty custodians (or via a tri-party agent) without passing through an exchange order book. Internal stock loans settle on the ledger without a CSD instruction.

**Tri-party arrangements**: Where a tri-party agent (e.g. BNY Mellon, Euroclear) manages collateral for an external SBL, the tri-party agent is modelled as an additional virtual wallet between the Collateral Book and the counterparty. The tri-party agent holds and manages the collateral pool on behalf of both parties; the smart contract sees it as the settlement destination for collateral moves. Not applicable to internal stock loans.

---

## Instrument State Model

The loan position carries three instrument-level states, distinct from the move states of individual cash and securities flows:

| State        | Meaning                                                                                                    |
|--------------|------------------------------------------------------------------------------------------------------------|
| `Active`     | Loan is open; securities are on loan; collateral is posted; fee accrual is running                         |
| `Matured`    | Return or termination is in progress; return and collateral release moves have been created but not yet fully settled |
| `Terminated` | All obligations discharged; securities returned, collateral released, all fees settled; loan extinguished  |

`Active → Matured` on the return/recall/maturity date when the settlement moves are created. `Matured → Terminated` when all moves — securities return, collateral return, final fee — have reached `Settled`.

For open loans with no contractual maturity, `Active → Matured` is triggered by:
- A recall notice from the lender (desk is borrowing), or
- A return notice from the desk (desk is borrowing), or
- A termination instruction received bilaterally.

---

## Lifecycle Events

### 1. Loan Open — Execution

**Trigger**: Trade confirmation received (GMSLA trade confirmation, electronic matching via EquiLend, or voice confirmation). A trade notification is delivered to the smart contract.

**Timing**: Execution is typically same-day (T+0). Settlement of securities and collateral is typically T+2 from execution (T+0 for same-day borrowing to cover fails).

The smart contract creates a single **atomic transaction** containing all moves for the loan opening. The initial state is `Pending` for all legs — SBL is a bilateral OTC arrangement with no automatic CSD instruction generation at execution.

#### When the Desk is the Borrower (securities received)

| Move                    | From                        | To                    | Asset                                             | Initial State |
|-------------------------|-----------------------------|-----------------------|---------------------------------------------------|---------------|
| Securities receipt      | Lender (virtual wallet)     | Securities Book       | N securities (identified by ISIN, quantity)       | `Pending`     |
| Cash collateral posted  | Collateral Book             | Lender (virtual)      | Cash [CCY] (Loan Value × margin %)                | `Pending`     |

For non-cash collateral:

| Move                    | From                        | To                    | Asset                                             | Initial State |
|-------------------------|-----------------------------|-----------------------|---------------------------------------------------|---------------|
| Securities receipt      | Lender (virtual wallet)     | Securities Book       | N securities (ISIN, quantity)                     | `Pending`     |
| Collateral delivered    | Collateral Book             | Lender (virtual)      | Collateral securities (ISIN, quantity, MtM value) | `Pending`     |

#### When the Desk is the Lender (securities delivered)

| Move                    | From                        | To                    | Asset                                             | Initial State |
|-------------------------|-----------------------------|-----------------------|---------------------------------------------------|---------------|
| Securities delivered    | Securities Book             | Borrower (virtual)    | N securities (ISIN, quantity)                     | `Pending`     |
| Cash collateral received| Borrower (virtual)          | Collateral Book       | Cash [CCY] (Loan Value × margin %)                | `Expected`    |

The cash collateral receipt is `Expected` because the lender is the passive recipient — the borrower initiates the collateral payment and the lender awaits it. This follows the asymmetric treatment in [cash_payments.md](cash_payments.md).

For non-cash collateral received:

| Move                    | From                        | To                    | Asset                                             | Initial State |
|-------------------------|-----------------------------|-----------------------|---------------------------------------------------|---------------|
| Securities delivered    | Securities Book             | Borrower (virtual)    | N securities (ISIN, quantity)                     | `Pending`     |
| Collateral received     | Borrower (virtual)          | Collateral Book       | Collateral securities (ISIN, quantity)            | `Expected`    |

**State after settlement**: All moves transition `Pending → Instructed → Settled` (or `Expected → Instructed → Settled` for receipt legs) upon CSD / custodian confirmation. Loan instrument state: `Active`.

**QRL**: QRL is invoked at execution to generate the manufactured payment schedule (one `Expected` move per anticipated income event over the loan term, where calculable). For open loans, QRL returns any known income events within the next standard horizon (e.g. 60 days); the schedule is extended on a rolling basis as new ex-dates are declared.

---

### 2. Settlement

**Trigger**: Settlement date arrives. Operations submit settlement instructions to the relevant custodians / CSDs.

```
Pending → Instructed  (settlement instruction submitted)
Instructed → Settled  (CSD / custodian confirms DvD or DvP)
```

All legs of the opening transaction transition simultaneously per [Transaction atomicity invariant](../invariants.md#core-ledger-invariants). Securities delivery and collateral delivery are concurrent (delivery versus delivery, DvD, for non-cash; delivery versus payment, DvP, for cash collateral).

Settlement failure follows the standard two-tier model per [invariant 8](../invariants.md#core-ledger-invariants). A failed attempt is `Pending` (non-terminal; retry on the next settlement cycle). A definitively cancelled loan is `Failed` on all legs (terminal; no reversal required if moves never reached `Settled`).

---

### 3. Daily Mark-to-Market (Collateral Margin Call)

**Trigger**: End of each business day. The smart contract receives the closing price of the loaned securities and recomputes the required collateral amount.

```
New Collateral Required = Closing Price × N_securities × (1 + Margin %)
ΔCollateral             = New Collateral Required − Current Collateral Posted
```

**Case A — Securities appreciated (ΔCollateral > 0): margin call**

The borrower must post additional collateral. When the desk is the borrower:

| Move                    | From              | To                 | Asset                     | Initial State |
|-------------------------|-------------------|--------------------|---------------------------|---------------|
| Margin call payment     | Collateral Book   | Lender (virtual)   | Cash [CCY] (ΔCollateral)  | `Pending`     |

When the desk is the lender:

| Move                    | From                 | To                 | Asset                     | Initial State |
|-------------------------|----------------------|--------------------|---------------------------|---------------|
| Margin call receipt     | Borrower (virtual)   | Collateral Book    | Cash [CCY] (ΔCollateral)  | `Expected`    |

**Case B — Securities depreciated (ΔCollateral < 0): margin return**

The lender returns excess collateral. When the desk is the borrower:

| Move                    | From               | To                | Asset                     | Initial State |
|-------------------------|--------------------|-------------------|---------------------------|---------------|
| Margin return receipt   | Lender (virtual)   | Collateral Book   | Cash [CCY] (|ΔCollateral|)| `Expected`    |

**Case C — No change (ΔCollateral = 0)**

No move created. The collateral amount is confirmed unchanged as a state event on the loan `TradeState`.

For **non-cash collateral** the same logic applies but the collateral is valued at the market price of the pledged securities less the applicable haircut. If the collateral value falls below the loan MtM, the borrower must substitute or top up the collateral (see [Collateral Substitution](#5-collateral-substitution)).

Margin call moves settle same-day or next morning per bilateral agreement. Failure to meet a margin call by the agreed deadline is a significant credit event (see [Failure Handling](#failure-handling)).

CDM: `MarkToMarketCollateralCall` (bespoke; see §CDM Extensions).

---

### 4. Fee and Rebate Payments

#### Cash Collateral — Rebate Payment

**Trigger**: Each rebate payment date as agreed in the trade confirmation (typically monthly, or on each business day for daily rebate trades).

Interest accrues daily on the outstanding cash collateral at the negotiated rebate rate:

```
Daily Rebate = Cash Collateral × Rebate Rate × (1 / Day Count Denominator)
```

Day count: Act/360 for USD, EUR, CHF; Act/365 for GBP.

The rebate is payable by the lender to the borrower. When the desk is the borrower (lender pays us):

| Move               | From               | To              | Asset                       | Initial State   |
|--------------------|--------------------|-----------------|-----------------------------|-----------------|
| Rebate receipt     | Lender (virtual)   | Collateral Book | Cash [CCY] (accrued rebate) | `Expected`      |

When the desk is the lender (desk pays borrower):

| Move               | From            | To                    | Asset                       | Initial State |
|--------------------|-----------------|-----------------------|-----------------------------|---------------|
| Rebate payment     | Collateral Book | Borrower (virtual)    | Cash [CCY] (accrued rebate) | `Pending`     |

`Expected` is used for the receipt because the amount is deterministic from the agreed rebate rate and the posted collateral balance. This follows the cash_payments.md model for anticipated receipts.

CDM: `EventQualificationEnum.InterestPayment`; the rebate is structurally identical to an interest payment on a cash deposit, consistent with the CDM model.

#### Non-Cash Collateral — Lending Fee

**Trigger**: Each fee payment date (typically monthly, or on each business day).

```
Daily Fee = Loan Value × Lending Fee Rate × (1 / Day Count Denominator)
```

Lending fee is payable by the borrower to the lender. When the desk is the borrower:

| Move            | From            | To                 | Asset                       | Initial State |
|-----------------|-----------------|--------------------|-----------------------------| --------------|
| Fee payment     | Collateral Book | Lender (virtual)   | Cash [CCY] (accrued fee)    | `Pending`     |

When the desk is the lender:

| Move            | From                  | To              | Asset                       | Initial State |
|-----------------|-----------------------|-----------------|-----------------------------|---------------|
| Fee receipt     | Borrower (virtual)    | Collateral Book | Cash [CCY] (accrued fee)    | `Expected`    |

CDM: `EventQualificationEnum.InterestPayment`.

---

### 5. Collateral Substitution

**Trigger**: The borrower elects to substitute non-cash collateral with different eligible securities (subject to lender consent and GMSLA eligibility criteria). Common reasons: collateral is needed for another transaction; original collateral approaches maturity.

Substitution is a same-day settlement. The new collateral is delivered before the old collateral is released (or simultaneously on a locked exchange). No collateral shortfall is permitted during the substitution window.

The smart contract creates a single atomic transaction:

| Move                           | From                 | To                    | Asset                                      | Initial State |
|--------------------------------|----------------------|-----------------------|--------------------------------------------|---------------|
| New collateral delivered       | Collateral Book      | Lender (virtual)      | New collateral securities (ISIN, quantity) | `Pending`     |
| Old collateral returned        | Lender (virtual)     | Collateral Book       | Old collateral securities (ISIN, quantity) | `Expected`    |

Both legs settle simultaneously on the substitution date (`Pending → Settled`, `Expected → Settled`). The loan `TradeState` is updated to reference the new collateral ISIN. No change to the securities leg; the loan value and required collateral amount are unchanged.

CDM: `CollateralSubstitutionEvent` (bespoke; see §CDM Extensions).

---

### 6. Manufactured Payment (Income on Loaned Securities)

**Trigger**: The ex-date for a dividend, coupon, or other income event on a security that is currently on loan. The smart contract identifies the entitlement from the QRL-generated income schedule.

When a security goes ex-dividend while on loan, the borrower holds the securities and receives the actual income from the issuer. The borrower must remit an equivalent manufactured payment to the lender on or before the original payment date.

**Booking at ex-date** (when the desk is the lender — we are owed the manufactured payment):

| Move                        | From                  | To              | Asset                                | State       |
|-----------------------------|-----------------------|-----------------|--------------------------------------|-------------|
| Manufactured receipt        | Borrower (virtual)    | Collateral Book | Cash [CCY] (dividend equivalent)     | `Expected`  |

`Expected` is used: the amount is calculable from the confirmed dividend per share and the on-loan quantity. The borrower has not yet instructed but will do so by payment date.

**Booking at ex-date** (when the desk is the borrower — we owe the manufactured payment):

| Move                        | From            | To                 | Asset                                | State     |
|-----------------------------|-----------------|--------------------|------------------------------------- |-----------|
| Manufactured payment        | Collateral Book | Lender (virtual)   | Cash [CCY] (dividend equivalent)     | `Pending` |

On payment date (when the desk is the lender and expects receipt):

```
Expected → Instructed (borrower sends payment instruction)
Instructed → Settled  (payment received at our account)
```

**Tax treatment**: Manufactured payments may be subject to withholding tax at a different rate than the actual dividend (depending on the borrower's tax jurisdiction). The net manufactured payment after withholding is the amount reflected in the ledger move. Any gross-up or tax reclaim is handled outside the ledger.

**Interaction with actual dividend receipt** (when the desk is the borrower): the desk holds the loaned securities on the record date and receives the actual dividend from the issuer into the Securities Book's cash position. The manufactured payment is the equal and opposite outflow. At the net level, the desk is flat on the dividend income — which is correct, as the economic entitlement belongs to the lender.

CDM: `ManufacturedPaymentEvent` (bespoke; see §CDM Extensions).

---

### 7. Partial Return (Borrower-Initiated)

**Trigger**: The borrower elects to return part of the borrowed securities. This is common when the need for the borrowed shares decreases (e.g. delta hedge unwind on a structured product as underlying moves away from barrier).

A partial return closes a portion of the open loan. The smart contract creates a settlement transaction for the returned portion:

| Move                        | From              | To                  | Asset                                    | Initial State |
|-----------------------------|-------------------|---------------------|------------------------------------------|---------------|
| Securities partial return   | Securities Book   | Lender (virtual)    | N_returned shares                        | `Pending`     |
| Collateral partial release  | Lender (virtual)  | Collateral Book     | Cash (N_returned / N_total × Collateral) | `Expected`    |

The proportional collateral release is calculated as:

```
Collateral Released = (N_returned / N_total) × Current Collateral Posted
```

The loan `TradeState` is updated: outstanding securities quantity is reduced by `N_returned`; the required collateral is recalculated on the new balance.

If the partial return reduces the loan to zero, the loan follows the full termination path (see below).

CDM: `QuantityChangePrimitive` applied to the loan `TradeState`.

---

### 8. Recall (Lender-Initiated)

**Trigger**: The lender issues a recall notice, requesting the return of some or all loaned securities. Standard recall period: T+2 for equities. The smart contract records the recall notice as a state event on the `TradeState` on the notification date; the settlement moves are created on the same date for settlement on the recall date.

The recall is a type of partial or full return, initiated by the lender rather than the borrower. The ledger structure is identical to a borrower-initiated return, but the event qualification is different.

| Move                        | From              | To                  | Asset                                    | Initial State |
|-----------------------------|-------------------|---------------------|------------------------------------------|---------------|
| Securities recalled         | Securities Book   | Lender (virtual)    | N_recalled shares                        | `Pending`     |
| Collateral released         | Lender (virtual)  | Collateral Book     | Cash (proportional)                      | `Expected`    |

**Recall failure**: if the borrower cannot source the securities for return by the recall date, the lender may:

1. **Grant an extension**: recall date deferred; no state change on the settlement moves (they are reset to the new recall date).
2. **Force close — buy-in**: the lender purchases the securities in the open market and charges the cost differential back to the borrower. The original recall settlement moves transition to `Failed` (terminal). A new buy-in transaction is created at the buy-in price; a separate cash penalty move is created for any buy-in premium over the loan value. Both follow the same settlement lifecycle as a standard buy-in (see [equities.md](equities.md)).

CDM: `RecallEvent` (bespoke; see §CDM Extensions).

---

### 9. Full Return / Loan Termination

**Trigger**: Bilateral agreement to terminate the loan (for open loans), or scheduled maturity date (for term loans), or a full recall by the lender.

The smart contract creates a final settlement transaction containing all remaining obligations:

| Move                        | From              | To                  | Asset                                              | Initial State |
|-----------------------------|-------------------|---------------------|----------------------------------------------------|---------------|
| Securities final return     | Securities Book   | Lender (virtual)    | N_total remaining shares                           | `Pending`     |
| Collateral final release    | Lender (virtual)  | Collateral Book     | Cash (full outstanding collateral)                 | `Expected`    |
| Final rebate / fee          | See §4 direction  | See §4 direction    | Cash [CCY] (accrued and unpaid rebate or fee)      | `Expected` / `Pending` |

All three move groups settle simultaneously on the termination date (or as close as settlement conventions allow). The final rebate/fee move is settled alongside the securities and collateral.

Loan instrument state: `Active → Matured` when the final settlement transaction is created. `Matured → Terminated` when all moves (securities return, collateral release, final fee/rebate) have reached `Settled`.

CDM: `EventQualificationEnum.ContractTermination`.

---

## Failure Handling

| Scenario                                             | State                     | Action                                                                                                       |
|------------------------------------------------------|---------------------------|--------------------------------------------------------------------------------------------------------------|
| Opening settlement fails (securities leg)            | `Pending`                 | Two-tier model per [invariant 8](../invariants.md#core-ledger-invariants); retry next business day           |
| Opening settlement fails (collateral leg)            | `Pending`                 | As above; securities leg cannot be released until collateral settles                                         |
| Loan definitively cancelled before settlement        | `Failed`                  | All moves → `Failed`; loan instrument terminated with no `Settled` balance; no reversal required             |
| Margin call not met by agreed deadline               | `Pending`                 | Escalated to credit risk; two-tier model applies; grace period per GMSLA terms                               |
| Margin call definitively unresolvable (credit event) | `Failed`                  | Lender may close out the loan; securities returned on accelerated basis; buy-in of collateral shortfall       |
| Recall — borrower fails to return by recall date     | `Pending`                 | Lender may grant extension or initiate buy-in (see §8 above)                                                 |
| Recall buy-in executed                               | Original → `Failed`       | New buy-in transaction created (new `Execution`); cash penalty move created                                  |
| Manufactured payment fails                           | `Pending`                 | Two-tier model per invariant 8; escalation to counterparty operations                                        |
| Collateral substitution — new collateral fails       | `Pending`                 | Old collateral not released until new collateral settles; simultaneous DvD maintained                        |
| Return settlement fails (securities)                 | `Pending`                 | Loan remains `Matured`; securities leg retried; borrower accrues fee/rebate until return completes           |
| Return settlement fails (collateral)                 | `Pending`                 | As above; collateral not released until securities return is confirmed                                       |

---

## CDM Representation

### Standard CDM Types

CDM models securities lending under a **composable payout structure** rather than a named product type. There is no `SecurityLending` product type enum; the transaction is qualified functionally by the ISLA CDM working group's qualification functions against the ISDA/ISLA Product Taxonomy. As of CDM v5, approximately two-thirds of GMSLA lifecycle events are representable; the remaining third require bespoke extensions (see §CDM Extensions).

| Concept                          | CDM Type / Field                                                                  | Notes                                                                                               |
|----------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| Loan product                     | `ContractualProduct` with `AssetPayout` (securities leg) + collateral leg         | No explicit `SecurityLending` product type; qualified by economic structure                         |
| Securities leg                   | `AssetPayout` → `AssetDeliveryTerms`                                             | Specifies ISIN, quantity, delivery method, and settlement terms                                     |
| Non-cash collateral leg          | Second `AssetPayout` (collateral securities)                                      | Eligible collateral defined via `EligibleCollateralSpecification`                                   |
| Cash collateral leg              | `InterestRatePayout` or `CashSettlementTerms`                                    | Cash collateral is modelled as a cash deposit generating a rebate                                   |
| Collateral eligibility           | `EligibleCollateralSpecification` → `EligibleCollateralCriteria[]`               | Specifies eligible asset types, issuers, maturities, ratings, haircuts                              |
| Loan value / margin              | `MarginCallInstructionTypeEnum` / `CollateralPortfolio`                          | Margin percentage encoded in `EligibleCollateralCriteria.haircutPercentage`                         |
| Rebate payment                   | `Transfer` with `EventQualificationEnum.InterestPayment`                          | Standard CDM cash transfer                                                                          |
| Lending fee payment              | `Transfer` with `EventQualificationEnum.InterestPayment`                          | Standard CDM cash transfer                                                                          |
| Trade execution                  | `EventQualificationEnum.Execution`                                                | Standard CDM                                                                                        |
| Return (full)                    | `EventQualificationEnum.ContractTermination` + `Transfer` (securities + cash)    | Standard CDM termination                                                                            |
| Partial return                   | `QuantityChangePrimitive`                                                         | CDM supports quantity reduction                                                                     |
| Allocation / block trade         | `EventQualificationEnum.Allocation`                                               | Standard CDM (for agent lending structures)                                                         |

### CDM Event Representation

| Lifecycle Event              | CDM Business Event Qualification             | CDM Transfer State             | Notes                                                                              |
|------------------------------|----------------------------------------------|--------------------------------|------------------------------------------------------------------------------------|
| Loan open — execution        | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Pending`   | Smart contract creates all opening moves                                           |
| Settlement confirmed         | — (state transition only)                    | `TransferStatusEnum.Settled`   | DvD or DvP confirmed by CSD / custodian                                            |
| Settlement attempt failed    | — (state transition only)                    | `TransferStatusEnum.Pending`   | Non-terminal; retry next business day                                              |
| Loan cancelled pre-settlement| — (state transition only)                    | `TransferStatusEnum.Failed`    | Terminal; no reversal                                                              |
| Margin call                  | `MarkToMarketCollateralCall` (bespoke)        | `TransferStatusEnum.Pending`   | Cash: borrower posts additional cash. Non-cash: substitution or top-up            |
| Margin return                | `MarkToMarketCollateralCall` (bespoke)        | `Expected` (bespoke)           | Lender returns excess collateral to borrower                                       |
| Rebate payment               | `EventQualificationEnum.InterestPayment`     | `Expected` / `Pending`         | Direction depends on desk role                                                     |
| Lending fee payment          | `EventQualificationEnum.InterestPayment`     | `Expected` / `Pending`         | Direction depends on desk role                                                     |
| Collateral substitution      | `CollateralSubstitutionEvent` (bespoke)       | `Pending` (new) / `Expected` (old) | Atomic DvD exchange                                                            |
| Manufactured payment         | `ManufacturedPaymentEvent` (bespoke)          | `Expected` / `Pending`         | Dividend equivalent; direction depends on desk role                                |
| Partial return               | `QuantityChangePrimitive`                     | `TransferStatusEnum.Pending`   | Proportional collateral release                                                    |
| Recall notice issued         | `RecallEvent` (bespoke)                       | — (state event only)           | State event on `TradeState`; settlement moves created with recall date             |
| Recall settled               | — (state transition only)                    | `TransferStatusEnum.Settled`   | Securities return + collateral release                                             |
| Recall buy-in triggered      | — (state transition only)                    | `TransferStatusEnum.Failed`    | Original recall moves → `Failed`; new buy-in `Execution` transaction created      |
| Full return / termination    | `EventQualificationEnum.ContractTermination` | `TransferStatusEnum.Pending`   | Securities + collateral + final fee settled; loan `Matured → Terminated`           |

---

## CDM Extensions Required

CDM coverage of SBL lifecycle events is incomplete (approximately one-third of GMSLA events require bespoke extensions, per the ISLA CDM Working Group's assessment). The following bespoke extensions are required for this implementation.

### Extension 1: `MarkToMarketCollateralCall`

CDM's `MarginCall` event is designed for derivative margin calls (initial margin, variation margin against a derivative portfolio). For SBL, the margin call is driven by the mark-to-market of the loaned securities rather than the derivative portfolio's exposure. A bespoke `MarkToMarketCollateralCall` event is required, carrying:

- `observationDate`: the date of the securities price observation
- `loanValue`: the marked securities value (quantity × closing price)
- `requiredCollateral`: loan value × (1 + margin %)
- `currentCollateral`: collateral outstanding before the call
- `collateralDelta`: the call or return amount (signed; positive = margin call, negative = margin return)
- `collateralMove`: the resulting `Transfer` (if delta ≠ 0)

### Extension 2: `RecallEvent`

CDM has no recall event qualification. A lender's recall of loaned securities is a distinct business event with regulatory implications (e.g. under SFTR). A bespoke `RecallEvent` is required, carrying:

- `recallDate`: the date by which securities must be returned
- `recalledQuantity`: number of securities recalled (may be partial)
- `recallReason`: enumeration (e.g. `ClientInstruction`, `CorporateAction`, `CollateralReuse`, `Other`)
- `settlementMoves`: the resulting `Pending` securities return and `Expected` collateral release moves

The recall notice date and the recall settlement date are distinct fields, preserving the notice period in the audit trail.

### Extension 3: `ManufacturedPaymentEvent`

CDM has no formal manufactured payment event type for securities lending income. While the underlying `Transfer` is standard, the event qualification and amount derivation are bespoke. A `ManufacturedPaymentEvent` is required, carrying:

- `exDate`: the ex-dividend / ex-coupon date of the underlying security
- `paymentDate`: the scheduled payment date (borrower must remit by this date)
- `grossAmount`: the full dividend / coupon equivalent per security × on-loan quantity
- `withholdingTax`: applicable withholding tax rate and amount
- `netAmount`: the net manufactured payment (`grossAmount − withholdingTax`)
- `incomeType`: `CashDividend`, `StockDividend`, `Coupon`, `Other`

The `Expected` / `Pending` asymmetry follows the desk role (lender = `Expected` receipt; borrower = `Pending` payment). The manufactured payment lifecycle parallels the CSD cash distribution model in [cash_payments.md](cash_payments.md), with the borrower playing the role of the paying agent.

### Extension 4: `CollateralSubstitutionEvent`

CDM's `QuantityChangePrimitive` does not represent the simultaneous exchange of one collateral security for another as a single atomic event. A bespoke `CollateralSubstitutionEvent` is required, carrying:

- `oldCollateral`: the securities being returned (ISIN, quantity, MtM value)
- `newCollateral`: the replacement securities (ISIN, quantity, MtM value)
- `settlementDate`: the date on which both legs settle simultaneously
- `deliveryVersusDelivery`: boolean confirming simultaneous settlement; if `false`, the new collateral must be received before the old is released

### Extension 5: `OpenLoan` termination type

CDM `economicTerms.terminationDate` requires a definitive date. Open SBL loans have no such date. A bespoke `OpenLoan` flag on the `TradeState` is required, indicating that:

- There is no scheduled `terminationDate`
- The loan continues until either party gives notice
- The notice period (e.g. T+2 for equities) is encoded on the `TradeState` and governs the minimum interval between recall/return notice and the resulting settlement date

---

## Internal Stock Loan (Bank as Internal Lender)

### Overview

In this scenario the bank's own inventory book (e.g. the equity trading desk, prime services desk, or securities finance desk) lends securities from its own holdings to the structured products desk. Both parties are real wallets within the same legal entity. The principal differences from an external SBL are:

| Attribute                  | External SBL (directions 1 & 2)         | Internal Stock Loan (direction 3)                 |
|----------------------------|-----------------------------------------|---------------------------------------------------|
| Counterparty wallet type   | Virtual wallet (external)               | Real wallet (internal book)                       |
| Legal framework            | GMSLA                                   | Internal trading policy / interdesk agreement     |
| Settlement system          | CSD / custodian (DvP or DvD)            | Internal ledger transfer; no CSD instruction      |
| Settlement timing          | T+2 equities, T+1 bonds                 | T+0 or same-day                                   |
| Collateral posting         | Required (cash or non-cash)             | Not required; economic attribution via fee        |
| Margin call                | Daily MtM per §3                        | Not applicable (no posted collateral)             |
| Fee structure              | Rebate on cash / lending fee on non-cash| Internal lending charge (transfer price)          |
| Recall                     | GMSLA notice period (T+2)               | Internal instruction; no contractual notice period|

### Loan Open — Internal

The smart contract creates a single atomic transaction:

| Move                | From             | To               | Asset                         | Initial State |
|---------------------|------------------|------------------|-------------------------------|---------------|
| Securities transfer | Inventory Book   | Securities Book  | N securities (ISIN, quantity) | `Pending`     |

No collateral leg is created. Economic attribution between the two books is managed through an internal lending fee (see below). The securities move transitions `Pending → Settled` on bilateral internal confirmation from operations on both desks; no CSD instruction is generated.

The loan instrument state transitions to `Active` upon settlement of the securities leg.

### Internal Lending Fee

In place of the external rebate / lending fee model (§4), an internal lending charge is assessed on each fee period:

```
Internal Lending Fee = Loan Value × Internal Transfer Rate × (Days / Day Count Denominator)
```

The internal transfer rate may reflect the external lending market rate for the security (ensuring the inventory desk is made whole for the opportunity cost of lending internally rather than externally) or a flat internal funding rate agreed by the desks. The rate is set by the securities finance / treasury desk and is reviewed periodically.

| Move                 | From            | To               | Asset                              | Initial State |
|----------------------|-----------------|------------------|------------------------------------|---------------|
| Internal fee payment | Securities Book | Inventory Book   | Cash [CCY] (accrued internal fee)  | `Pending`     |

Fee payments follow the same periodicity as external SBL fees (typically monthly). CDM: `EventQualificationEnum.InterestPayment`.

### Recall (Internal)

The inventory book may recall securities at any time per internal instruction. The GMSLA T+2 notice period does not apply. Settlement is same-day or next business day per internal agreement.

| Move               | From            | To               | Asset                | Initial State |
|--------------------|-----------------|------------------|----------------------|---------------|
| Securities recalled| Securities Book | Inventory Book   | N_recalled shares    | `Pending`     |

If the structured products desk cannot return securities immediately (for example, they are committed to a live hedge), the recall is escalated internally between risk management and the relevant desk heads. No buy-in mechanism applies to internal recalls; resolution is by internal negotiation. Final fee accrual runs until the recall settles.

### Manufactured Payments (Internal)

Manufactured payments for securities on internal loan follow the same ex-date / payment-date model as external SBL (§6), but both payer and payee are real wallets. No `Expected` asymmetry applies: the Securities Book is the active payer and the payment is instructed internally on the ex-date.

| Move                 | From            | To               | Asset                              | Initial State |
|----------------------|-----------------|------------------|------------------------------------|---------------|
| Manufactured payment | Securities Book | Inventory Book   | Cash [CCY] (dividend equivalent)   | `Pending`     |

Tax treatment follows the same gross / net logic as §6. Since both books are within the same legal entity, there is typically no withholding tax complication.

### Full Return / Termination (Internal)

The termination transaction is structurally the same as §9 but with the wallet directions reversed for an internal loan:

| Move                      | From            | To               | Asset                                         | Initial State |
|---------------------------|-----------------|------------------|-----------------------------------------------|---------------|
| Securities final return   | Securities Book | Inventory Book   | N_total remaining shares                      | `Pending`     |
| Final internal fee        | Securities Book | Inventory Book   | Cash [CCY] (accrued and unpaid fee)           | `Pending`     |

There is no collateral release leg. Loan instrument state: `Active → Matured → Terminated` per the standard state model.

### Inventory Held at Prime Broker with Swap to Client (Out of Scope)

Where the inventory book holds its securities at the bank's own prime broker (custody external to the bank) and the economic value of those securities is placed on total return swap with a client, the internal stock loan sits within the chain:

```
PB (external custody) → Inventory Book (real) → Securities Book (real)
```

with the client holding synthetic exposure to the inventory via TRS. The additional complexity of PB margin terms, custody charges, PB recall rights, and TRS economic attribution is **out of scope** for this specification and will be addressed as an extension when brought in scope.

---

## Relationship to Other Smart Contracts

| Smart Contract      | Relationship                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
|---------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Equities            | Borrowed securities are equities. The buy-in mechanism for failed recalls mirrors the [equities.md](equities.md) buy-in model. Securities received via borrow are treated as equity holdings in the Securities Book                                                                                                                                                                                                                                                                                                                                       |
| Bonds               | Bond borrow/loan follows the same lifecycle as equity SBL. Coupon manufactured payments follow the same mechanics as equity dividend manufactured payments                                                                                                                                                                                                                                                                                                                                                                                                |
| Funding             | Securities received via borrow create funded positions in the Securities Book. The cash collateral posted (when borrowing) represents a secured liability that offsets the funded asset: the net funding requirement for the desk is approximately zero for a fully collateralised borrow. The interaction with [funding.md](funding.md) is: the Securities Book's non-cash position triggers funding inception; the collateral outflow reduces the cash balance available to the desk; both effects feed into the funding revaluation at each reset date |
| Structured Products | The Hedging Book borrows equity to source shares for delta-hedging short barrier-put positions. The recall event is the primary operational risk: if the lender recalls securities while the Hedging Book holds them for delivery at note maturity (physical settlement scenario in [structured_products.md](structured_products.md)), operations must source replacement securities immediately                                                                                                                                                          |
| Cash Payments       | Fee, rebate, manufactured payment, and margin call moves all follow the [cash_payments.md](cash_payments.md) `Expected` / `Pending` state model for asymmetric receipt vs. payment treatment                                                                                                                                                                                                                                                                                                                                                              |
| FX                  | Cross-currency SBL (securities in one currency, cash collateral in another) creates a residual FX exposure from the difference between the loan currency and the collateral currency. This FX exposure is managed via [fx_wip.md](fx_wip.md) and is not in scope for this contract                                                                                                                                                                                                                                                                        |

---

## Implementation

This section binds the SBL contract to the [External Message Interface](../implementation.md). It is the contract with the most bespoke inbound surface, reflecting CDM's partial GMSLA coverage (see CDM Extensions above).

### Inbound

| Family                   | Concrete message(s)                                                                                                                                                     | Window       | Triggers                                                                                |
|--------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------|-----------------------------------------------------------------------------------------|
| `MarketObservation`      | `CollateralMark` — closing price of the loaned securities (daily EOD)                                                                                                   | Point (date) | Daily MtM: `Collateral = Close × N × (1 + margin%)`; margin call.                       |
| `MarketObservation`      | `DividendPerShare` — dividend amount on the loaned security at ex-date                                                                                                  | Point (date) | Manufactured-payment amount (`div/share × on-loan qty`).                                |
| `DateEvent`              | `ScheduledDate` — ex-date, payment date, loan maturity, recall date, rebate/fee date, substitution date                                                                 | —            | Manufactured payment; return; rebate/fee; substitution.                                 |
| `CorporateAction`        | Dividend / coupon on the loaned security (income event over the loan term)                                                                                              | —            | `ManufacturedPaymentEvent` `†`.                                                         |
| `OperationalInstruction` | Trade confirmation (GMSLA / EquiLend); DvD/DvP settlement confirmation/failure; margin-call deadline; recall notice; buy-in notice; collateral-substitution instruction | —            | `MarkToMarketCollateralCall` `†`, `RecallEvent` `†`, `CollateralSubstitutionEvent` `†`. |

### Outbound

| Family               | Concrete message(s)                                                                                                                                       | CDM projection                                                                        |
|----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `Payment`            | Margin call / return; rebate (pay/receive); lending fee (pay/receive); manufactured payment (pay/receive); internal lending fee; final accrued rebate/fee | `InterestPayment` / `ManufacturedPaymentEvent` `†` / `MarkToMarketCollateralCall` `†` |
| `ProductStateChange` | `Active → Matured → Terminated`; `QuantityChangePrimitive` on partial return/recall; collateral ISIN updated on substitution                              | `ContractTermination` / `QuantityChange` / `RecallEvent` `†`                          |
| `NewProductTemplate` | None — SBL is a bilateral OTC instrument, not product-creating.                                                                                           | —                                                                                     |
