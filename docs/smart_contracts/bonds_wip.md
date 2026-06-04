# Bonds Smart Contract

## Overview

This smart contract governs the booking and lifecycle of bond positions from initial acquisition through to final extinction (maturity, early redemption, conversion, or sale). It covers fixed rate bonds, floating rate notes (FRNs), zero coupon bonds, convertible bonds, and callable/putable bonds.

Bonds are debt instruments that confer on the holder a contractual right to receive periodic coupon payments (if any) and the return of principal at maturity. Unlike equities, bond positions carry a finite scheduled life and a stream of known or calculable future cash flows. The ledger must faithfully represent both the settlement of the initial position and the full forward schedule of income events from the point of acquisition.

Bonds may be exchange-traded (predominantly government bonds and some corporate bonds traded on regulated markets) or OTC (the majority of corporate bonds and all structured credit instruments). Settlement for both is effected at a Central Securities Depository (DvP), but the booking model differs: exchange-traded bonds use the exchange-facing book model (see [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model)); OTC bonds are booked directly between the desk book and the counterparty virtual wallet.

---

## Product Scope

| Product Type | Coupon Type | Maturity | Special Feature |
|---|---|---|---|
| Fixed rate bond | Fixed periodic coupon | Scheduled maturity date | None |
| Floating rate note (FRN) | Floating periodic coupon (reference rate + spread) | Scheduled maturity date | Rate fixing on each fixing date |
| Zero coupon bond | None (issued at discount) | Scheduled maturity date | No coupon moves; principal repayment at face value |
| Convertible bond | Fixed periodic coupon | Scheduled maturity date or conversion | Holder's option to convert to equity |
| Callable bond | Fixed or floating periodic coupon | Scheduled maturity or call date | Issuer's option to redeem early |
| Putable bond | Fixed or floating periodic coupon | Scheduled maturity or put date | Holder's option to require early redemption |

Callable and putable features may coexist on the same instrument (a callable putable bond). The lifecycle events for each feature are independent.

---

## Parties and Wallets

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| Exchange | Virtual wallet | Represents the exchange or CCP as counterparty for exchange-traded bonds |
| Exchange-Facing Book | Real wallet | Single book per legal entity per exchange venue (applicable to exchange-traded bonds only; see [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model)) |
| Internal Wallet | Real wallet | Individual desk or strategy book to which the bond position is allocated |
| OTC Counterparty | Virtual wallet | The bilateral counterparty for OTC-traded bonds; faces the desk book directly |
| CSD | Virtual wallet | Central Securities Depository; effects DvP settlement and coupon cash distributions |
| Issuer / Paying Agent | Virtual wallet | Represents the bond issuer or its appointed paying agent; source of coupon and principal payments at the CSD |

For exchange-traded bonds, the CSD virtual wallet and the Exchange virtual wallet are distinct: the Exchange (or CCP) is the trade counterparty, while the CSD is the settlement and custody agent. For OTC bonds settled via the same CSD, the OTC Counterparty is the trade counterparty; CSD settlement is nonetheless effected at the same CSD infrastructure.

---

## Accrued Interest and Dirty Price Settlement

Unlike equity trades, bond trades settle on a **dirty price** basis: the settlement cash amount is the clean price multiplied by face value, plus accrued interest for the settlement date's accrual period. Accrued interest compensates the seller for the coupon income earned since the last coupon date.

The settlement transaction includes exactly two moves:

1. **Bond units move**: delivery of the security (face value × quantity).
2. **Cash move**: a single combined cash amount equal to clean price consideration plus accrued interest.

Accrued interest is **not** represented as a separate move in the settlement transaction. It is embedded within the settlement cash move and is therefore not individually visible as a distinct ledger entry at trade settlement. The allocation of the dirty price into clean consideration and accrued interest is a matter for downstream accounting and P&L systems, which derive it from the trade economics passed at execution.

**Rationale**: separating accrued interest into a distinct move at settlement would be inconsistent with DvP mechanics: the CSD settles a single cash amount against the securities delivery. Representing two cash moves where the CSD processes one would introduce a structural inconsistency between the ledger and the settlement record.

---

## QRL — Coupon Schedule Generation

QRL is an external library responsible for generating all coupon schedules and related date parameters. QRL is invoked by the smart contract at the point of position acquisition (whether by new issue subscription, secondary market purchase, or internal transfer).

QRL returns:

- The complete **coupon schedule**: all coupon payment dates, calculation periods, and day count fractions for the life of the bond (or the remaining life, for secondary market acquisitions).
- For FRNs: the **fixing dates** on which the floating reference rate (e.g. SOFR, €STR) is observed for each calculation period.
- The **maturity date** and the principal repayment amount (face value).
- All dates adjusted for applicable **business day conventions** (Following, Modified Following, Preceding) and **holiday calendars** for the relevant currency and market.
- For callable/putable bonds: the **call/put notification windows**, the earliest and latest permitted exercise dates, and the optional redemption price schedule.

The smart contract consumes QRL's output at inception and uses it to pre-generate the full schedule of `Expected` coupon receipt moves in a single operation (see [Coupon Schedule Generation](#3-coupon-schedule-generation) below). QRL is re-invoked if any event modifies the remaining schedule (e.g. an FRN rate reset, a partial call, or an amendment to the term sheet).

---

## Instrument State Model

The bond position (the bond unit held in the ledger wallet) carries three instrument-level states, distinct from the move states of the individual cash and delivery flows:

| State       | Meaning                                                                                                         |
|-------------|-----------------------------------------------------------------------------------------------------------------|
| `Active`    | Bond position is live; coupon schedule in progress; future cash flow moves visible in the live balance          |
| `Matured`   | Maturity (or early redemption) date reached; redemption transaction created but not yet fully settled           |
| `Terminated`| All obligations discharged; bond units returned to CSD, principal and final coupon settled; position extinguished |

`Active → Matured` on the maturity or early redemption date when the redemption transaction is created. `Matured → Terminated` when all moves in the redemption transaction have reached `Settled`.

---

## Trade Execution and Settlement

### Exchange-Traded Bonds

The booking model for exchange-traded bonds follows the exchange trade booking model (see [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model)) identically to equities. A two-leg transaction is created atomically at execution:

#### Leg 1 — External: Exchange ↔ Exchange-Facing Book

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond delivery | Exchange (virtual wallet) | Exchange-Facing Book | Bond units (face value × quantity, security identifier) | `Instructed` |
| Cash payment | Exchange-Facing Book | Exchange (virtual wallet) | Cash (dirty price: clean consideration + accrued interest) | `Instructed` |

#### Leg 2 — Internal: Exchange-Facing Book ↔ Internal Wallet

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond allocation | Exchange-Facing Book | Internal Wallet | Bond units | `Instructed` |
| Cash allocation | Internal Wallet | Exchange-Facing Book | Cash (dirty price) | `Instructed` |

The initial state is `Instructed` for the same reason as equities: CSD settlement instructions are generated automatically by the exchange mechanism, and the instruction is already in flight by the time the trade notification reaches the smart contract.

Both legs are part of the same atomic transaction per [invariant 2](../invariants.md#core-ledger-invariants). The exchange-facing book nets to flat immediately on recording.

**Settlement timing**: government bonds typically settle T+1; corporate bonds typically settle T+2. The applicable settlement cycle is determined by the market of execution and is a parameter on the settlement instruction; it does not change the ledger structure.

### OTC Bonds

For OTC bonds, there is no exchange-facing book. The desk book faces the OTC counterparty directly. A single-leg transaction is created:

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond delivery | OTC Counterparty (virtual wallet) | Internal Wallet | Bond units | `Pending` |
| Cash payment | Internal Wallet | OTC Counterparty (virtual wallet) | Cash (dirty price) | `Pending` |

The initial state is `Pending` (not `Instructed`) for OTC bonds: there is no automated instruction generation. Settlement instructions are prepared manually or by the operations team and submitted separately to the CSD. The state transitions to `Instructed` when the CSD instruction is confirmed as submitted.

**Transition to `Instructed`**:

```
Pending → Instructed
```

Triggered by confirmation of CSD settlement instruction submission (typically via the operations settlement platform).

### Settlement Confirmation

For both exchange-traded and OTC bonds, settlement is confirmed by CSD notification:

#### State Transitions on Settlement Notification

| Notification | New State | Meaning |
|---|---|---|
| Settlement confirmed (DvP) | `Settled` | Securities delivered, cash exchanged at CSD; terminal |
| Settlement attempt failed | `Pending` | DvP failed; obligation persists; CSD retries; non-terminal |
| Instruction cancelled (bilateral) | `Failed` | Trade cancelled by mutual agreement; terminal — no reversal (moves never `Settled`) |
| Buy-in triggered | `Failed` | Mandatory buy-in; original instruction cancelled; terminal — new buy-in transaction (per equities.md) |

All moves in the transaction transition simultaneously per [invariant 2](../invariants.md#core-ledger-invariants).

For settlement failure resolution paths (retry, bilateral cancellation, buy-in), the same three paths documented in [equities.md](equities.md) apply in full. The `Failed` state removes moves from all balance views without requiring a reversal transaction, per [invariant 8](../invariants.md#core-ledger-invariants).

---

## Lifecycle Events

### 1. Position Acquisition

Position acquisition is the point at which the smart contract first recognises a bond position in the Internal Wallet. This is typically the trade execution event described above, but also applies to bonds acquired by internal transfer, new issue subscription, or receipt as collateral.

On position acquisition:
1. The settlement transaction is created (per [Trade Execution and Settlement](#trade-execution-and-settlement) above).
2. QRL is invoked with the instrument terms and the acquisition date (or settlement date, if settlement date is the value date for coupon entitlement). QRL returns the full remaining coupon schedule.
3. The coupon schedule generation event (see below) runs immediately and atomically with the settlement transaction.

### 2. Settlement Feed (T+0, parallel)

In parallel with the ledger booking, the settlement system submits the DvP instruction to the CSD. This runs independently of the ledger. The ledger does not interact with the settlement system at this stage; it awaits the settlement notification.

### 3. Coupon Schedule Generation

**Trigger**: Position acquisition (steps above). QRL has returned the full coupon schedule.

**Action**: The smart contract pre-generates one `Expected` coupon receipt move per scheduled coupon date, for the Internal Wallet, in a single batch transaction. For zero coupon bonds, no coupon moves are created (there are none to schedule).

Each `Expected` coupon move:

| Move | From | To | Asset | State |
|------|------|----|-------|-------|
| Coupon receipt | CSD (virtual wallet) | Exchange-Facing Book | Cash (calculated coupon amount, currency) | `Expected` |
| Internal allocation | Exchange-Facing Book | Internal Wallet | Cash (same amount) | `Pending` |

For **fixed rate bonds**: the coupon amount is fully calculable at inception (face value × fixed rate × day count fraction). All `Expected` moves are created with their definitive amount.

For **FRNs**: the coupon amount for each period is not known until the fixing date. `Expected` moves are created for all future coupons, but the amount field for unfixed periods carries an estimated amount derived from the current forward curve. The amount is crystallised on each fixing date (see [Floating Rate Fixing](#4-floating-rate-fixing-frn-only)). The move's state remains `Expected`; only the amount updates.

For **zero coupon bonds**: no coupon moves are created. The sole future cash event is principal repayment at maturity.

**Rationale (mirroring the ex-dividend model in cash_payments.md)**: creating `Expected` coupon moves at position acquisition, rather than on each coupon date, ensures that downstream P&L and risk systems have a complete forward income schedule visible in the live balance from the moment the position is opened. If coupon moves were only created at each coupon payment date, the bond position would show a mark-to-market value reflecting expected future income with no corresponding income entries in the ledger — a systematic P&L distortion equivalent to the ex-dividend problem for equities.

The `Expected` state is used (not `Pending`) because the obligation is on the issuer/CSD, not on us. We are the passive recipient; the payer has not yet instructed. This is the same asymmetric treatment as CSD cash distributions in [cash_payments.md](cash_payments.md).

All `Expected` coupon moves are visible in the live balance per [invariant 9](../invariants.md#core-ledger-invariants). They are excluded from the settled balance until they individually reach `Settled`.

### 4. Floating Rate Fixing (FRN Only)

**Trigger**: Each fixing date as returned by QRL. A market data event delivers the observed reference rate (e.g. SOFR, €STR, EURIBOR) for the relevant calculation period.

**Action**: The definitive coupon amount for the relevant calculation period is computed:

`Coupon amount = Face value × (Reference rate + Spread) × Day count fraction`

The `Expected` move for that coupon period is updated: its amount field is revised from the forward-curve estimate to the definitive fixed amount. The state remains `Expected`; this is an amount amendment event, not a state transition.

If the resulting amount differs materially from the estimate, downstream P&L systems will recognise the revision on the fixing date. The ledger records the revision as a state event on the existing move; the original estimated amount and the definitive amount are both preserved in the audit trail.

**CDM mapping**: Fixing maps to `ResetPrimitive` in the CDM event model.

**FRN Fixing State Flow**:

```
Expected (estimated amount) → Expected (definitive amount) → Instructed → Settled
```

No new move is created at the fixing event; only the amount on the existing `Expected` move is updated.

### 5. Coupon Payment

Coupon payment proceeds in three steps, following the same CSD cash distribution model as dividends in [cash_payments.md](cash_payments.md).

#### Step 1 — CSD Pre-Advice

**Trigger**: CSD sends a payment pre-advice (`camt.054` credit notification or equivalent), typically one to two business days before the coupon payment date.

**Action**: The `Expected` coupon receipt move for the relevant coupon date transitions:

```
Expected → Instructed
```

The internal allocation move to the Internal Wallet remains `Pending` — the cash has not yet arrived.

#### Step 2 — CSD Coupon Credit

**Trigger**: Cash credited to the exchange-facing book's account at the CSD on the coupon payment date. Confirmed by the CSD account statement (`camt.053` / MT950 equivalent).

**Action**:

The CSD receipt move transitions:
```
Instructed → Settled
```

The internal allocation move transitions on the same value date:
```
Pending → Instructed → Settled
```

The `Pending → Instructed` transition reflects the intraday release of the internal cash sweep once the CSD credit is confirmed. Both the `Pending → Instructed` and `Instructed → Settled` transitions on the internal allocation are state events on the existing move; no new transaction is created.

The exchange-facing book remains flat after both moves settle.

#### Coupon State Flow Summary

```
Expected → Instructed (pre-advice) → Settled (CSD credit confirmed)
                                    ↘ Failed (payment cancelled or issuer default)
```

### 6. Maturity and Principal Repayment

**Trigger**: The maturity date as returned by QRL. The CSD initiates the redemption process; the paying agent effects the principal payment.

Maturity is a DvP event: bond units are returned to the issuer (via the CSD) and principal cash is received simultaneously. This is recorded as a single atomic transaction.

#### Maturity Transaction

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond units return | Internal Wallet | CSD (virtual wallet) | Bond units (full holding at par) | `Instructed` |
| Principal receipt | CSD (virtual wallet) | Exchange-Facing Book | Cash (face value of holding) | `Expected` |
| Internal allocation | Exchange-Facing Book | Internal Wallet | Cash (face value) | `Pending` |

The bond units move and the principal receipt move are created in the same atomic transaction per [invariant 2](../invariants.md#core-ledger-invariants). The bond units move is initially `Instructed` because the CSD redemption instruction is generated automatically by the paying agent on maturity date. The principal receipt follows the `Expected` → `Instructed` → `Settled` flow as the payment is advised and then credited.

Bond position state: `Active → Matured` on maturity date when the redemption transaction is created; `Matured → Terminated` when all moves in the transaction (bond unit return, principal receipt, internal allocation) have reached `Settled`. After termination the Internal Wallet carries zero bond units and has received the principal cash.

#### Cancellation of Remaining Expected Coupon Moves

On the maturity date, the final coupon payment is typically included in the principal repayment (or has been paid on the same date as a separate scheduled coupon). Any `Expected` coupon moves that remain open (i.e., have not yet reached `Settled`) at the time maturity is processed are cancelled by transitioning their state to `Failed`.

These moves are cancelled to `Failed` (not reversed) because they never reached `Settled` state and therefore never affected the settled balance. This is the correct treatment per [invariant 8](../invariants.md#core-ledger-invariants): `Failed` moves are excluded from all balance views, and no reversal transaction is required.

**Note**: under normal operation, the only `Expected` move outstanding at maturity is the final coupon, which is handled within the maturity transaction. All prior coupons will have reached `Settled` by maturity date. If earlier coupons remain open (e.g. due to an ongoing settlement dispute), those moves transition to `Failed` individually as part of the maturity event.

### 7. Early Redemption — Call (Issuer-Initiated)

**Trigger**: The issuer delivers a call notice within the notification window returned by QRL. The call notice specifies the call date and the redemption price (par, or par plus a call premium per the call schedule).

**Action — Call Notice**:

On receipt of the call notice, the smart contract validates that the call date and price are consistent with the call schedule in QRL's output. No new moves are created at this stage; the call notice is recorded as a state event on the smart contract itself.

**Action — Call Date**:

On the call date, the same structure as maturity applies:

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond units return | Internal Wallet | CSD (virtual wallet) | Bond units (full holding) | `Instructed` |
| Redemption receipt | CSD (virtual wallet) | Exchange-Facing Book | Cash (redemption price × face value, including any call premium) | `Expected` |
| Internal allocation | Exchange-Facing Book | Internal Wallet | Cash (redemption amount) | `Pending` |

All remaining scheduled coupon moves that have not yet reached `Settled` (other than any final coupon included in the redemption) are cancelled to `Failed` on the call date, consistent with the maturity treatment.

**CDM mapping**: Early termination by the issuer maps to `EarlyTerminationProvision` or `OptionalEarlyTermination` in the CDM.

### 8. Early Redemption — Put (Holder-Initiated)

**Trigger**: The holder (Internal Wallet) elects to exercise the put option within the notification window returned by QRL. The put election is communicated to the issuer via the operations team.

The ledger structure on the put date is identical to the call event described above, with the redemption price being the contractual put price (typically par). The distinction is only in who initiates the event; the resulting ledger moves are the same.

All remaining scheduled coupon moves that have not yet reached `Settled` are cancelled to `Failed` on the put date.

**CDM mapping**: Holder-initiated early termination maps to `OptionalEarlyTermination` in the CDM.

### 9. Conversion (Convertible Bonds)

**Trigger**: The holder elects to exercise the conversion option on a convertible bond. The conversion is communicated to the issuer/conversion agent. The conversion ratio (number of equity shares per unit of face value) and any cash adjustment (e.g. fractional share cash settlement) are defined in the instrument terms.

Conversion extinguishes the bond position and creates an equity position. This is recorded as a single atomic transaction:

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond units extinguished | Internal Wallet | CSD (virtual wallet) | Bond units (converted face value) | `Instructed` |
| Equity units created | CSD (virtual wallet) | Exchange-Facing Book | Equity units (face value × conversion ratio) | `Instructed` |
| Equity allocation | Exchange-Facing Book | Internal Wallet | Equity units | `Instructed` |
| Fractional cash (if any) | CSD (virtual wallet) | Exchange-Facing Book | Cash (fractional share cash settlement) | `Expected` |

The equity units received follow the full equity lifecycle from this point, including eligibility for dividends and corporate actions. See [equities.md](equities.md) for the governing lifecycle.

All remaining scheduled coupon moves that have not yet reached `Settled` are cancelled to `Failed` on the conversion date.

**CDM mapping**: Conversion maps to `ConversionFeature` in the CDM product model.

### 10. Bond Sale (Secondary Market)

**Trigger**: Execution of a sale of the bond position in the secondary market. The sale generates a trade notification with the same structure as the original purchase, but with positions and cash flows reversed.

The settlement transaction for a sale mirrors the purchase, with from and to wallets inverted:

#### Exchange-Traded Bond Sale — Leg 1 — External

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond delivery | Exchange-Facing Book | Exchange (virtual wallet) | Bond units | `Instructed` |
| Cash receipt | Exchange (virtual wallet) | Exchange-Facing Book | Cash (dirty price: clean consideration + accrued interest) | `Instructed` |

#### Exchange-Traded Bond Sale — Leg 2 — Internal

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Bond deallocation | Internal Wallet | Exchange-Facing Book | Bond units | `Instructed` |
| Cash credit | Exchange-Facing Book | Internal Wallet | Cash (dirty price) | `Instructed` |

For OTC sales, the single-leg structure applies with `Pending` as the initial state, as for OTC purchases.

#### Accrued Interest on Sale

As with purchases, accrued interest is embedded within the dirty price cash move. The seller receives a single cash amount representing clean consideration plus accrued interest for the period from the last coupon date to the settlement date. Downstream accounting systems decompose the dirty price into clean consideration and accrued income for P&L attribution.

#### Cancellation of Remaining Expected Coupon Moves

On the sale settlement date, all remaining `Expected` (and any `Pending` or `Instructed`) coupon moves associated with the sold position that have not yet reached `Settled` are cancelled to `Failed`. This reflects the fact that the seller is no longer entitled to future coupons from the settlement date onwards.

For partial sales (where only part of the holding is sold), the remaining coupon moves are revised pro-rata using an amendment per [invariant 7](../invariants.md#core-ledger-invariants): the original coupon moves are cancelled by reversal (if already `Settled`) or transitioned to `Failed` (if not yet `Settled`), and new coupon moves are created for the revised outstanding face value.

**Accrued interest embedded in cash move — sale**:

The accrued interest received by the seller on sale is not a separate move; it is the embedded component of the dirty price cash receipt. The corresponding `Expected` coupon moves represent the full coupon entitlement for the period. The period from the last coupon date to the settlement date generates accrued income that is realised through the sale proceeds, not through the coupon schedule. Downstream P&L systems are expected to reconcile the settlement dirty price against the open `Expected` coupon position to avoid double-counting.

---

## Accrual and P&L

Coupon income accrues continuously between coupon dates. The ledger does not create daily accrual entries — it records only discrete event-driven moves. However, the `Expected` coupon moves created at position acquisition by QRL provide the complete input required for downstream P&L accrual:

- The `Expected` move amount is the full coupon cash amount for the period.
- The calculation period start and end dates (from QRL) define the accrual period.
- The day count fraction (from QRL) defines how the coupon is apportioned across calendar days.

Downstream P&L systems derive the daily accrual as:

`Daily accrual = Coupon amount × (Days elapsed since period start / Total days in period)`

This is computed by the P&L system, not the ledger. The ledger's role is to ensure that `Expected` moves are present with correct amounts, correct calculation period dates, and correct currency from the point the position is acquired. The `Expected` move's presence in the live balance ensures that the full period's income is visible to P&L and treasury from day one of the position.

For FRNs, the daily accrual is computed on the estimated coupon amount until the fixing date, and on the definitive amount thereafter. The P&L impact of a fixing that differs from the estimate is recognised by P&L systems on the fixing date, when the `Expected` move amount is updated.

**The ledger does not create daily accrual moves.** All daily accrual computation is delegated to downstream systems. This is a deliberate design choice: daily accrual entries would multiply the number of ledger moves by a factor of the number of calendar days in the bond's life without adding information that is not already derivable from the scheduled coupon moves and QRL's calculation period data.

---

## Failure Handling

### Settlement Failure on Purchase or Sale

Settlement failure follows the same two-tier model as equities (see [equities.md](equities.md) and [invariant 8](../invariants.md#core-ledger-invariants)):

| Scenario | State | Resolution |
|----------|-------|------------|
| Settlement attempt failed | `Pending` | Non-terminal; CSD retries next business day; no new moves |
| Bilateral cancellation agreed | `Failed` | Terminal; no reversal required (moves never `Settled`); coupon schedule moves remain unaffected until cancellation is confirmed |
| Mandatory buy-in triggered | `Failed` | Terminal; buy-in constitutes a new trade with its own transaction; cash compensation move created for price differential |

For a bilateral cancellation of a purchase that was already `Settled`, [invariant 6](../invariants.md#core-ledger-invariants) (cancellation by reversal) applies: a mirror-image reversal transaction is created, and the coupon schedule moves created at position acquisition are all transitioned to `Failed` (they were never settled and never affected a balance).

### Coupon Payment Failure

| Scenario | State | Action |
|----------|-------|--------|
| CSD pre-advice delayed | Remains `Expected` | Investigation; no state change until pre-advice received |
| CSD payment delayed past coupon date | Remains `Instructed` | Escalate to CSD and paying agent; state retained pending investigation |
| Coupon definitively cancelled (e.g. issuer announces non-payment) | `Failed` | `Expected` or `Instructed` moves transition to `Failed`; excluded from all balances; no reversal required |
| Coupon recalled after settlement | Reversal transaction | `Settled` move requires reversal per [invariant 6](../invariants.md#core-ledger-invariants); new `Pending` repayment move created |

### Issuer Default

In the event of issuer default:

1. All remaining `Expected` coupon moves that have not yet reached `Settled` transition to `Failed`. These moves are excluded from all balance views. No reversal is required.
2. Any `Instructed` coupon moves (pre-advice received but not yet credited) also transition to `Failed` unless the CSD confirms the credit will proceed (i.e. the paying agent has already transferred funds to the CSD).
3. The principal repayment move, if already scheduled (i.e. on or after maturity date), transitions to `Failed`.
4. The bond units in the Internal Wallet remain in `Settled` state until a recovery event or write-off instruction is processed. Recovery proceedings (claims in administration, debt restructuring, distressed exchange) are out of scope for the ledger. The ledger will reflect the outcomes of those proceedings only when a formal instruction is received (e.g. a debt-for-equity swap would generate a conversion transaction; a write-off would generate a units extinguishment transaction).

---

## CDM Representation

| Lifecycle Event | CDM Business Event Qualification | CDM Transfer State | Notes |
|---|---|---|---|
| Trade execution (exchange) | `EventQualificationEnum.Execution` | `TransferStatusEnum.Instructed` | Two-leg transaction; dirty price in cash leg |
| Trade execution (OTC) | `EventQualificationEnum.Execution` | `TransferStatusEnum.Pending` | Single-leg transaction; manual CSD instruction |
| Settlement confirmed | — (state transition only) | `TransferStatusEnum.Settled` | Terminal |
| Settlement attempt failed | — (state transition only) | `TransferStatusEnum.Pending` | Non-terminal; retry expected |
| Bilateral cancellation | — (state transition only) | `TransferStatusEnum.Failed` | Terminal; no reversal |
| Buy-in triggered | — (state transition only) | `TransferStatusEnum.Failed` | Terminal; new buy-in transaction generated |
| Coupon schedule generated | — (anticipatory booking; no CDM business event) | `Expected` (bespoke) | QRL invoked; full schedule of `Expected` moves created |
| Floating rate fixing | `ResetPrimitive` | `Expected` (amount updated; state unchanged) | Amount revised from estimate to definitive; CDM deviation: amount update on existing move |
| CSD coupon pre-advice | — (state transition only) | `TransferStatusEnum.Instructed` | Triggered by `camt.054` |
| CSD coupon credited | — (state transition only) | `TransferStatusEnum.Settled` | Triggered by `camt.053` |
| Coupon payment failed | — (state transition only) | `TransferStatusEnum.Failed` | Terminal; excluded from all balances |
| Maturity — bond units returned | `PrincipalExchange` | `TransferStatusEnum.Instructed` | DvP; bond extinguished |
| Maturity — principal received | `PrincipalExchange` | `Expected` → `Instructed` → `Settled` | As per CSD cash distribution model |
| Remaining coupon cancellation at maturity | — (state transition only) | `TransferStatusEnum.Failed` | Expected moves cancelled; no reversal |
| Call notice received | `EarlyTerminationProvision` | — (no move created) | Contract state event only; recorded on smart contract |
| Call/put redemption | `OptionalEarlyTermination` | `TransferStatusEnum.Instructed` → `Settled` | Same structure as maturity; CDM `OptionalEarlyTermination` for put; `EarlyTerminationProvision` for call |
| Conversion exercised | `ConversionFeature` | `TransferStatusEnum.Instructed` | Bond units extinguished; equity units created; cross-reference equities.md |
| Bond sale | `EventQualificationEnum.Execution` | `TransferStatusEnum.Instructed` (exchange) / `Pending` (OTC) | Dirty price in cash leg; remaining Expected coupon moves cancelled |
| Issuer default | — (state transition only) | `TransferStatusEnum.Failed` | All outstanding Expected/Instructed income moves; terminal |
| Post-settlement recall | `EventQualificationEnum.Transfer` | Reversal: `TransferStatusEnum.Settled` | Reversal transaction required per invariant 6 |

**CDM deviation notes**:

1. **`Expected` state**: CDM's `TransferStatusEnum` has no pre-instruction state for anticipated receipts. The `Expected` state is a bespoke extension. The closest CDM concept is `ScheduledTransfer` within the payout framework (indicating a known future transfer not yet converted to a live instruction), but `ScheduledTransfer` is a contract term, not a live ledger entry. This ledger promotes anticipated coupon receipts to first-class ledger moves in `Expected` state from position acquisition, to provide a complete forward income schedule to downstream consumers.

2. **Floating rate amount update**: CDM's `ResetPrimitive` is designed to represent the fixing event in the context of a swap's reset schedule. For bonds, no CDM primitive directly models the updating of an existing ledger move's amount on a fixing date. The ledger records the fixing as an amount-update event on the existing `Expected` move rather than creating a new move, which has no direct CDM equivalent.

3. **Dirty price settlement**: CDM's `SettlementTerms` with `DeliveryVersusPayment` represents the settlement mechanism. CDM does not separately model the accrued interest component of dirty price at the transfer level; the full dirty price is the `settlementAmount`. This ledger follows CDM in treating the dirty price as a single undivided cash amount in the settlement transaction.

4. **Coupon schedule as ledger moves**: CDM models the coupon schedule within `InterestRatePayout` as contract terms (`FixedCoupon` or `FloatingCoupon` under the payout), not as individual ledger transfers. This ledger deviates by materialising each scheduled coupon as a discrete `Expected` move at inception, to provide forward visibility in the live balance. The contractual schedule (QRL output) and the ledger schedule should always be consistent; any discrepancy is an error.

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [Process Model](https://cdm.finos.org/docs/process-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Implementation

This section binds the bonds contract to the [External Message Interface](../implementation.md).

### Inbound

| Family                   | Concrete message(s)                                                                                                                  | Window        | Triggers                                                        |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------|---------------|-----------------------------------------------------------------|
| `MarketObservation`      | `Fixing` — reference rate (`SOFR`, `€STR`, `EURIBOR`) for a single calculation period (FRNs)                                         | Point (date)  | Crystallises the amount on the existing `Expected` coupon move. |
| `MarketObservation`      | `Fixing` (compounded) — RFR compounded-in-arrears over the interest period                                                           | Range (dates) | Floating coupon amount where the period is set in arrears.      |
| `DateEvent`              | `ScheduledDate` — coupon date, fixing date, maturity, call/put exercise window, settlement-date arrival (T+1 / T+2)                  | —             | Coupon/redemption flow; fixing; optimistic settle.              |
| `CorporateAction`        | `EarlyRedemption` (issuer call / holder put); `BespokeEvent`                                                                         | —             | Early-redemption transaction; `Active → Matured`.               |
| `OperationalInstruction` | CSD pre-advice (`camt.054`); CSD account statement (`camt.053`); DvP settlement confirmed/failed; buy-in; CSD redemption instruction | —             | Position-state bucket transitions; redemption booking.          |

### Outbound

| Family               | Concrete message(s)                                                                                                                    | CDM projection                                        |
|----------------------|----------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| `Payment`            | Coupon cash; principal repayment; early-redemption cash (call/put); fractional cash on conversion; accrued interest within dirty price | `InterestPayment` / `CashTransfer`                    |
| `ProductStateChange` | Fixing crystallised on `Expected` move; `Active → Matured → Terminated`; conversion extinguishes bond / creates equity                 | `Reset` / `ContractTermination` / `ConversionFeature` |
| `NewProductTemplate` | Equity units on convertible-bond conversion (face value × conversion ratio)                                                            | `Execution`                                           |
