# Standalone Cash Payments Smart Contract

## Overview

This smart contract governs standalone cash movements that are not the cash leg of a simultaneous delivery-versus-payment (DvP) exchange. Such payments are Free-of-Payment (FoP): cash moves independently, with no linked security delivery in the same transaction.

Examples include: equity dividends received from the CSD, coupon income, funding flows, fee payments, margin calls, and cash corporate action proceeds (e.g. a cash takeover consideration).

---

## Scope

**In scope**: Any cash move that stands alone — where cash is the only asset in the transaction.

**Out of scope**: The cash leg of an exchange trade (e.g. the consideration leg of a DvP equity settlement). Those cash moves are created atomically within the relevant product smart contract (see [equities.md](equities.md)) and are governed by that contract's lifecycle, not this one.

---

## Parties and Wallets

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| CSD | Virtual wallet | The Central Securities Depository; source of CSD-originated cash distributions (dividends, corporate action proceeds) |
| Exchange-Facing Book | Real wallet | Single book per legal entity (see [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model)); receives CSD cash distributions and holds the internal cash position |
| Internal Wallet | Real wallet | Individual desk or strategy book; receives internally-allocated cash after CSD receipt |
| External Counterparty | Virtual wallet | Any third-party receiving or originating a standalone cash payment (e.g. a prime broker, fee recipient, funding counterparty) |

---

## Asymmetric Treatment: Receipts vs Payments

Standalone cash payments are treated asymmetrically because the direction of initiative differs:

| | Expected Receipts | Expected Payments |
|---|---|---|
| **Who initiates** | External party (CSD, counterparty) — we are passive | We initiate — we are active |
| **When we book** | As soon as the amount is calculable (record date + announcement) — before the cash arrives | When the obligation arises (contract terms, instruction from risk/ops) |
| **Initial state** | `Expected` — we have forecast the receipt but the payer has not yet instructed | `Pending` — obligation exists, we have not yet instructed payment |
| **Instructed state** | Triggered by payer's pre-advice or CSD payment notification | Triggered by our own payment instruction to the correspondent bank |
| **Internal allocation** | Separate subsequent transaction, after CSD settlement | N/A for outgoing payments; internal sourcing is a separate funding flow |

---

## State Model

### Receipt State Flow

```
Expected → Instructed → Settled
                      ↘ Failed
```

| State | Meaning | CDM Mapping |
|-------|---------|-------------|
| `Expected` | Amount calculated and move booked; payer has not yet instructed | **Bespoke extension** — CDM has no pre-instruction state; closest CDM concept is `ScheduledTransfer` within the payout framework, indicating a known future transfer not yet converted to a live instruction |
| `Instructed` | Payer (e.g. CSD) has sent payment instruction; cash is in-flight | `TransferStatusEnum.Instructed` |
| `Settled` | Cash credited to our account; confirmed by bank notification | `TransferStatusEnum.Settled` |
| `Failed` | Payment definitively failed or cancelled | `TransferStatusEnum.Failed` |

`Expected` moves **do** contribute to the live balance (see [invariant 9](../invariants.md#core-ledger-invariants)) — they represent known, calculable future cash and should be visible to risk and treasury. They do **not** contribute to the settled balance until `Settled`.

### Payment State Flow

```
Pending → Instructed → Settled
                     ↘ Failed
```

| State | Meaning | CDM Mapping |
|-------|---------|-------------|
| `Pending` | Obligation exists; payment not yet instructed | `TransferStatusEnum.Pending` |
| `Instructed` | Payment instruction sent to correspondent bank | `TransferStatusEnum.Instructed` |
| `Settled` | Payment confirmed as received by beneficiary | `TransferStatusEnum.Settled` |
| `Failed` | Payment definitively failed or rejected | `TransferStatusEnum.Failed` |

There is no `Expected` state for outgoing payments. We control the timing of our own payment instructions; the obligation either exists (`Pending`) or does not.

---

## CSD Cash Payment Model

### How the CSD handles cash distributions

CSDs do not use a DvP mechanism for cash distributions. Instead, they operate dedicated **cash memorandum accounts** held at a central bank (e.g. ECB TARGET2 for Euroclear/Clearstream; Federal Reserve for DTC). The mechanism is:

1. On payment date, the CSD debits the issuer's (or issuer agent's / paying agent's) cash account and credits the participant's cash account in the same settlement cycle.
2. This is an intra-CSD FoP credit — no exchange of securities takes place.
3. The participant (our exchange-facing book) is notified of the incoming credit via a pre-advice (ISO 20022 `camt.054` credit notification, or legacy MT910). This pre-advice is the trigger for transitioning the move from `Expected` to `Instructed`.
4. End-of-day the credit is confirmed in the participant's account statement (`camt.053` / MT950). This confirms `Settled`.

### Settlement finality

CSD cash credits carry strong settlement finality — they are backed by central bank money and failures are extremely rare (unlike equity DvP, which fails regularly due to securities shortfalls). However the state model accommodates failure for completeness.

### Relevance to our ledger

The exchange-facing book's cash account at the CSD maps directly to the exchange-facing book wallet in our ledger. The CSD virtual wallet represents the CSD as the paying entity. All CSD-originated cash distributions flow:

```
CSD (virtual wallet) → Exchange-Facing Book (real wallet)
```

The exchange-facing book's inbound receipt and the outbound internal allocation to trader front books are created as a single balanced transaction on ex-dividend date (see [Expected Receipt Workflow](#expected-receipt-workflow) below).

---

## Expected Receipt Workflow

The equity dividend is used as the canonical example; the same pattern applies to other CSD-originated cash distributions.

### 1. Ex-Dividend Date — Transaction created

**Trigger**: Ex-dividend date. The stock begins trading without the dividend entitlement. The mark-to-market value of the equity position drops by approximately the dividend amount.

**Why this date matters**: If the trader's book shows a mark-to-market loss from the price drop but no offsetting income, P&L will show a spurious loss on ex-date that unwinds weeks later when the cash arrives. To prevent this, the internal allocation to the internal wallet must be booked as a `Pending` move on ex-date — visible in the live balance from the same moment the price drops.

**Action**: The smart contract calculates the expected dividend:
`dividend per share × confirmed holdings at record date`

A single balanced transaction is created containing both moves:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| Dividend receipt | CSD (virtual wallet) | Exchange-Facing Book | Cash (calculated amount, currency) | `Expected` |
| Internal allocation | Exchange-Facing Book | Internal Wallet | Cash (same amount) | `Pending` |

Both moves are created atomically. The transaction is balanced: the exchange-facing book nets to flat on the live balance (one `Expected` inbound, one `Pending` outbound). The internal wallet shows a `Pending` cash inflow that offsets the mark-to-market equity loss.

Where multiple desks hold the same security, the allocation is split across their front books in proportion to their record-date holdings. All allocation moves are part of the same transaction and must sum to the total CSD receipt.

Holdings used for the calculation are locked at record date. Any subsequent adjustment (e.g. a late equity settlement fail that changes the record-date position) requires a cancel/correct per [invariant 7](../invariants.md#core-ledger-invariants), replacing both the receipt and all allocation moves.

### 2. CSD Pre-Advice Received — CSD receipt moves to `Instructed`

**Trigger**: CSD sends payment pre-advice (`camt.054` credit notification or equivalent), confirming the cash will be credited on payment date.

**Action**: The CSD receipt move transitions:

```
Expected → Instructed
```

The internal allocation moves remain `Pending` — we have not yet received the cash and cannot pay the traders. This is a state event on the existing move; no new transaction is created.

### 3. CSD Credits Account — `Settled`; internal allocation released

**Trigger**: Cash credited to the exchange-facing book's account at the CSD on payment date. Confirmed by account statement (`camt.053` / MT950 equivalent).

**Action**: The CSD receipt move transitions:

```
Instructed → Settled
```

The internal allocation moves transition on the same value date:

```
Pending → Instructed → Settled
```

The `Pending → Instructed` transition reflects the intraday release of the internal cash sweep once the CSD credit is confirmed. Both transitions are state events on the existing moves; no new transaction is created. The exchange-facing book remains flat.

---

## Expected Payment Workflow

### 1. Obligation Arises — `Pending` move created

**Trigger**: Payment obligation confirmed (e.g. fee agreement, contract terms, risk/ops instruction).

**Action**: A move is created:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| Payment | Exchange-Facing Book (or relevant internal wallet) | External Counterparty (virtual wallet) | Cash (agreed amount, currency) | `Pending` |

The `Pending` state represents a known obligation that has not yet been instructed. It is visible in the live balance, reducing the payer's cash position from the point the obligation is booked.

Large or sensitive payments may require an explicit authorisation step before progressing to `Instructed`. This authorisation workflow is external to the ledger; the ledger records only the state transition.

### 2. Payment Instructed — `Instructed`

**Trigger**: Payment instruction sent to the correspondent bank (ISO 20022 `pacs.008` / `pacs.009` or equivalent).

**Action**:

```
Pending → Instructed
```

### 3. Payment Confirmed — `Settled`

**Trigger**: Beneficiary's bank confirms receipt, or our correspondent bank confirms debit (`camt.054` debit notification or equivalent).

**Action**:

```
Instructed → Settled
```

---

## Failure Handling

The same two-tier failure model as equities applies (see [invariant 8](../invariants.md#core-ledger-invariants)):

| Scenario | State | Action |
|----------|-------|--------|
| Payment attempt failed (transient — e.g. bank cut-off missed) | `Pending` | Retry next cycle; no new move |
| Receipt not arrived by expected date | Remains `Instructed` | Investigation; escalate to CSD |
| Payment definitively rejected (e.g. invalid account details) | `Failed` | `Failed` move excluded from all balances; new corrected payment creates a new move |
| CSD cancels a previously advised distribution | `Failed` | `Failed` move excluded from balances; no reversal required (move never reached `Settled`) |
| CSD distribution recalled after settlement | Reversal transaction | `Settled` move requires reversal per [invariant 6](../invariants.md#core-ledger-invariants); new `Pending` move created for repayment |

The last row is the only case where a reversal transaction is created: the CSD credited us, the move reached `Settled`, and the CSD subsequently recalls the payment (e.g. the dividend was declared in error). Because the move did affect the settled balance, a reversal is required.

---

## CDM Representation

| Lifecycle Event | CDM Business Event Qualification | CDM Transfer State | Notes |
|---|---|---|---|
| Expected receipt booked | — (anticipatory booking; no CDM business event) | `Expected` (bespoke) | Closest CDM concept: `ScheduledTransfer` in payout framework |
| CSD pre-advice received | — (state transition only) | `TransferStatusEnum.Instructed` | Triggered by `camt.054` or equivalent |
| CSD cash credited | — (state transition only) | `TransferStatusEnum.Settled` | Triggered by `camt.053` or equivalent |
| Internal allocation created | `EventQualificationEnum.Transfer` | `TransferStatusEnum.Instructed` | Separate transaction from CSD receipt |
| Payment obligation booked | — (anticipatory booking) | `TransferStatusEnum.Pending` | |
| Payment instructed | — (state transition only) | `TransferStatusEnum.Instructed` | Triggered by pacs.008/009 acknowledgement |
| Payment confirmed | — (state transition only) | `TransferStatusEnum.Settled` | Triggered by camt.054 debit notification |
| Transient failure / retry | — (state transition only) | `TransferStatusEnum.Pending` | Non-terminal; same move |
| Terminal failure | — (state transition only) | `TransferStatusEnum.Failed` | Excluded from all balances; no reversal |
| Post-settlement recall | `EventQualificationEnum.Transfer` | Reversal: `TransferStatusEnum.Settled` | Reversal transaction required per invariant 6 |

**CDM deviation note**: The `Expected` state has no direct equivalent in `TransferStatusEnum`. CDM's before/after state transition model treats anticipated transfers as contract terms (`ScheduledTransfer`) rather than live ledger entries. This ledger deviates by promoting the anticipated receipt to a first-class move in `Expected` state, in order to provide a complete forward cash position to downstream consumers (risk, treasury) from the point the amount is calculable.

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [Process Model](https://cdm.finos.org/docs/process-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Implementation

This section binds the standalone cash-payments contract to the [External Message Interface](../implementation.md).

### Inbound

| Family                   | Concrete message(s)                                                                                                            | Window | Triggers                                                             |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------------|--------|----------------------------------------------------------------------|
| `DateEvent`              | `ScheduledDate` — ex-dividend date, record date, payment date                                                                  | —      | Expected-receipt booking; settlement of receipt / payment.           |
| `CorporateAction`        | `CashDividend` declaration; cash corporate-action proceeds (e.g. cash takeover)                                                | —      | Amount-per-share / cash consideration drives the receipt.            |
| `OperationalInstruction` | CSD pre-advice (`camt.054` / MT910); account statement (`camt.053` / MT950); payment acknowledgement (`pacs.008` / `pacs.009`) | —      | `Expected → Instructed → Settled`; `Pending → Instructed → Settled`. |

This contract consumes no `MarketObservation` — it is purely date- and feed-driven.

### Outbound

| Family               | Concrete message(s)                                                                                                    | CDM projection                  |
|----------------------|------------------------------------------------------------------------------------------------------------------------|---------------------------------|
| `Payment`            | Standalone receipt (e.g. dividend from CSD); internal allocation; expected outgoing payment; rebate / margin-call cash | `Transfer` / `CashTransfer`     |
| `ProductStateChange` | Receipt move `Expected → Instructed → Settled`; payment move `Pending → Instructed → Settled` (or `Failed`)            | `TransferStatusEnum` vocabulary |
| `NewProductTemplate` | None — cash payments are standalone, not product-creating.                                                             | —                               |
