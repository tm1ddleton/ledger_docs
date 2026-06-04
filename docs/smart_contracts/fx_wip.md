# FX Smart Contract

## Overview

This smart contract governs the booking and lifecycle of foreign exchange transactions from execution through to final settlement or cash settlement. It covers FX Spot, FX Forward, FX Swap, and Non-Deliverable Forward (NDF) instruments.

FX is an over-the-counter (OTC) bilateral market. Unlike exchange-traded instruments, there is no Central Securities Depository (CSD) and no central exchange acting as counterparty. Settlement is effected via the correspondent banking network using nostro accounts. For major currency pairs, settlement occurs through CLS Bank (Continuous Linked Settlement), which provides Payment-versus-Payment (PvP) finality and eliminates Herstatt risk. For currency pairs not included in CLS, bilateral settlement is used and Herstatt risk is present.

The smart contract is responsible for creating the correct ledger transactions at each lifecycle stage, applying the correct state model for the settlement channel in use, and handling the distinct mechanics of NDFs — where no physical exchange of principal occurs and settlement is cash-based.

---

## Instrument Scope

| Instrument | Description | Settlement Basis |
|------------|-------------|------------------|
| **FX Spot** | Exchange of two currency amounts at the spot rate; value date is typically T+2 (T+1 for USD/CAD; same-day for certain pairs) | Physical delivery of both currencies |
| **FX Forward** | Exchange of two currency amounts at an agreed forward rate on a specified future value date | Physical delivery of both currencies |
| **FX Swap** | Two legs sharing a single smart contract: a near leg (spot or short date) and a far leg (forward); effectively a combined spot and forward at rates agreed simultaneously | Physical delivery on each leg independently |
| **NDF** | Non-Deliverable Forward; no physical exchange of the two traded currency principals; at execution the desk books a long NDF unit position and on maturity the NDF unit is extinguished and replaced by a single net cash move in the settlement currency | NDF unit at execution; cash settlement at maturity |

---

## Parties and Wallets

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| FX Desk Book | Real wallet | The internal book of the FX desk; faces external counterparties directly. There is no intermediate exchange-facing book for FX (contrast with [equities.md](equities.md)). |
| External Counterparty | Virtual wallet | The bank, fund, or other entity on the other side of the FX trade. One virtual wallet per counterparty. |
| Nostro (CLS Settlement Member) | Virtual wallet | Represents the CLS settlement member bank through which physical settlement of CLS-eligible pairs is processed via PvP. |
| Nostro (Correspondent Bank) | Virtual wallet | Represents the correspondent bank used for bilateral settlement of non-CLS pairs. One virtual wallet per correspondent banking relationship. |

Two currency wallets are relevant to each FX trade: the FX desk book holds balances in each currency it trades. A trade in EUR/USD involves both the EUR wallet of the FX desk book and the USD wallet of the FX desk book, with the counterparty's EUR and USD virtual wallet positions as the opposite sides.

For NDFs, the FX Desk Book holds an NDF unit from execution through to maturity. At maturity the NDF unit is extinguished and a single cash move in the settlement currency is created in its place. The two traded currency principals do not physically exchange at any point.

---

## Settlement Infrastructure

### CLS Bank (PvP Settlement)

CLS Bank operates a Payment-versus-Payment settlement mechanism across the world's major traded currency pairs (the "CLS-settled pairs"). CLS eliminates Herstatt risk by ensuring that neither leg of a currency exchange is released until both legs are confirmed as funded and available.

CLS operates a narrow settlement window each business day. Each CLS settlement member submits pay-in and receive instructions to CLS before the cut-off. CLS aggregates all instructions across members and settles on a net basis within the window. Each member's net pay-in or receive is a single amount in each currency — individual trades are not settled gross; they are settled as part of the net multilateral position.

From the ledger's perspective:
- The two move legs of a CLS-settled FX trade begin in `Pending` state at execution.
- The smart contract generates settlement instructions to the CLS member bank, transitioning both legs to `Instructed`.
- CLS confirmation of settlement transitions both legs to `Settled` simultaneously.

Because CLS settles both legs atomically at the CLS level, there is no risk of asymmetric settlement within a CLS-settled pair. Both legs of a single trade either settle together or fail together.

### Bilateral Correspondent Bank Settlement

For currency pairs not included in CLS (typically emerging market currencies), settlement is handled bilaterally through the correspondent banking network. Each currency leg is instructed independently to the respective correspondent bank (nostro account).

Bilateral settlement creates **Herstatt risk**: the two legs settle in different time zones, and it is possible for one leg to settle while the other fails. For example, a EUR/TRY trade may have the EUR leg settle in Europe during European banking hours while the TRY leg is not confirmed until Turkish banking hours, or fails entirely.

Herstatt risk and its treatment in the ledger state model are addressed in the [Failure Handling](#failure-handling) section below.

---

## FX Spot and FX Forward

FX Spot and FX Forward share the same booking and settlement structure; they differ only in value date. The lifecycle is described once for both.

### 1. Trade Execution (T+0)

**Trigger**: Trade is agreed bilaterally (voice, electronic platform, or prime brokerage). A trade notification is delivered to the smart contract.

QRL derives the value date from the trade date, currency pair conventions, and any applicable public holiday calendars.

The smart contract creates a single **Transaction** containing two simultaneous moves in opposite directions, one for each currency leg.

#### Transaction Moves at Execution

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Buy leg | External Counterparty (virtual wallet) | FX Desk Book (real wallet) | Currency bought (agreed notional) | `Pending` |
| Sell leg | FX Desk Book (real wallet) | External Counterparty (virtual wallet) | Currency sold (agreed notional) | `Pending` |

Both moves are part of the same atomic transaction (see [Transaction atomicity invariant](../invariants.md#core-ledger-invariants)) and are recorded simultaneously. The transaction is balanced: the net change in any asset across all wallets is zero (see [Double-entry invariant](../invariants.md#core-ledger-invariants)).

**Initial state is `Pending`**: At execution, no settlement instruction has yet been sent. The legal obligation exists; the counterparty has not yet been instructed.

### 2. Settlement Instruction Generated

**Trigger**: Settlement instructions are generated prior to value date (typically one business day before for CLS; timing varies by correspondent for bilateral). The smart contract transitions both moves.

```
Pending → Instructed
```

Both legs transition in the same state event. For CLS-settled pairs, the instruction is submitted to the CLS member bank. For bilateral pairs, separate payment instructions are submitted to the respective correspondent banks (nostros) for each currency.

### 3. Settlement on Value Date

**Trigger**: Settlement confirmation received from CLS or from the correspondent bank(s).

```
Instructed → Settled
```

For CLS-settled pairs, CLS confirms settlement of both legs simultaneously. Both moves transition to `Settled` in the same state event.

For bilateral pairs, confirmations may arrive at different times (see [Failure Handling](#failure-handling)). Subject to the atomicity constraints described there, both moves ultimately transition to `Settled`.

#### State Flow Summary (Spot / Forward)

```
Execution:     Pending  →  Instructed  →  Settled
(buy leg)                                  ↘ Failed
(sell leg)     Pending  →  Instructed  →  Settled
                                           ↘ Failed
```

---

## FX Swap

An FX Swap consists of two legs sharing a single smart contract:

- **Near leg**: an exchange of currencies at the spot rate (or a short-dated forward rate) on the near value date.
- **Far leg**: a reverse exchange of the same principal amounts at a forward rate on the far value date.

The near and far rates are agreed simultaneously at execution. The difference between the two rates reflects the interest rate differential between the two currencies over the swap period.

### 1. Trade Execution (T+0)

**Trigger**: FX Swap agreed bilaterally. A single trade notification covering both legs is delivered to the smart contract.

QRL derives both the near value date and the far value date from trade date, currency pair, and tenor.

The smart contract creates **two separate Transactions** at execution — one for the near leg and one for the far leg — linked by a common smart contract reference. Each transaction contains two moves (one per currency), as with a standard FX Spot or Forward.

#### Near Leg Transaction

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Near buy leg | External Counterparty (virtual wallet) | FX Desk Book (real wallet) | Currency bought (near notional) | `Pending` |
| Near sell leg | FX Desk Book (real wallet) | External Counterparty (virtual wallet) | Currency sold (near notional) | `Pending` |

#### Far Leg Transaction

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| Far buy leg | FX Desk Book (real wallet) | External Counterparty (virtual wallet) | Currency bought at near (now sold back on far) | `Pending` |
| Far sell leg | External Counterparty (virtual wallet) | FX Desk Book (real wallet) | Currency sold at near (now bought back on far) | `Pending` |

Note: the direction of each currency reverses between the near and far legs, reflecting the simultaneous spot sale and forward repurchase (or vice versa).

### 2. Near Leg Settlement

Near leg follows the same instructing and settlement lifecycle as a standard FX Forward (see above). The far leg remains in `Pending` state while the near leg settles.

```
Near leg:  Pending → Instructed → Settled
Far leg:   Pending (no change until far value date approaches)
```

### 3. Far Leg Settlement

As the far value date approaches, the far leg follows the same instructing and settlement lifecycle independently.

```
Far leg:  Pending → Instructed → Settled
```

The two legs are independent transactions and do not depend on each other's settlement state after the initial booking. Failure of the far leg does not retroactively affect a settled near leg; it is treated as a separate settlement failure with its own resolution path (see [Failure Handling](#failure-handling)).

---

## NDF (Non-Deliverable Forward)

An NDF is a cash-settled forward contract. There is no physical exchange of the two traded currency principals. At execution the desk acquires a long NDF unit position — a unit representing the contractual right/obligation under the NDF terms. On maturity (after fixing), the NDF unit is extinguished and replaced by a single net cash payment in the designated settlement currency.

NDFs are used where the non-deliverable currency is subject to capital controls or insufficient liquidity to support physical settlement (e.g. USD/CNH, USD/INR, USD/BRL for certain tenors).

### NDF Instrument State Model

| State         | Meaning                                                                                                                                   |
|---------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `Active`      | NDF position is live; fixing date has not yet passed; contracted rate and notional are in force                                           |
| `Matured`     | Settlement date reached; extinguishment and cash settlement transaction created; moves are in progress but not yet fully settled           |
| `Terminated`  | NDF unit extinguished and cash settlement move has reached `Settled` (or zero-settlement extinguishment has settled); all obligations discharged |

CDM `closedState` is set at the `Matured` trigger: the NDF becomes `Closed` (`positionState = Closed`, `closedState.state = Terminated`, `activityDate =` the settlement date) when the extinguishment and cash-settlement transaction is created. `Matured → Terminated` is therefore **not** a CDM state transition — both liveliness values project to the same `closedState`, differing only in whether the final transfers have settled; the residual settlement tail is carried on the transfers' own `TransferStatusEnum` and on `ClosedState.lastPaymentDate`. See [Projection to CDM State](../state.md#projection-to-cdm-state).

### 1. Trade Execution (T+0)

**Trigger**: NDF agreed bilaterally. Trade notification delivered to the smart contract.

QRL derives the fixing date and the settlement date from the trade date, currency pair, and tenor. For most NDFs, the fixing date is two business days before the settlement date.

At execution, a transaction is created recording the NDF position. The NDF unit represents the contractual long position; the counterparty virtual wallet holds the corresponding short position. The settlement amount is not yet known at this stage — it will be determined on the fixing date — but the position itself is immediately live.

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| NDF position | External Counterparty (virtual wallet) | FX Desk Book (real wallet) | 1 NDF unit (identified by trade reference, notional, contracted rate, settlement currency) | `Instructed` |

The NDF unit transitions to `Settled` on trade confirmation (typically same-day for bilateral OTC). From this point the FX Desk Book holds a live NDF position that is visible in both the live and settled balance views.

### 2. Fixing Date — Rate Observation

**Trigger**: On the fixing date, QRL signals the smart contract. The reference rate is observed from the designated fixing source (e.g. PBOC for USD/CNH, RBI for USD/INR).

CDM representation: the rate observation maps to the `Observation` primitive and a reset event (`EventQualificationEnum.Reset`).

This is a state event on the smart contract — no new ledger transaction is created. The fixing rate and resulting net settlement amount are recorded against the NDF smart contract:

```
Net settlement amount = (Contracted Rate − Fixing Rate) × Notional / Fixing Rate
```

The sign of the result determines the direction of the cash move at maturity: positive means the counterparty pays us; negative means we pay the counterparty. The result is denominated in the settlement currency.

### 3. Settlement Date — Maturity and Conversion

**Trigger**: Settlement date reached (T+2 from fixing date, or per contract terms).

The NDF unit is extinguished and converted to a cash settlement. A single transaction is created containing two moves:

| Move | From | To | Asset | Initial State |
|------|------|----|-------|---------------|
| NDF extinguishment | FX Desk Book | External Counterparty (virtual wallet) | 1 NDF unit | `Pending` |
| Cash settlement (if receiving) | External Counterparty (virtual wallet) | FX Desk Book | Net amount, settlement currency | `Pending` |
| Cash settlement (if paying) | FX Desk Book | External Counterparty (virtual wallet) | Net amount, settlement currency | `Pending` |

Only one of the two cash settlement rows applies, depending on the sign of the net settlement amount. Both moves in the transaction follow the correspondent bank payment lifecycle:

```
Pending → Instructed → Settled
                     ↘ Failed
```

There is no CLS involvement — NDF cash settlement is a single-currency FoP payment through the correspondent bank for the settlement currency.

NDF state: `Active → Matured` on the settlement date when the extinguishment and cash settlement transaction is created. `Matured → Terminated` once both moves have reached `Settled` and all obligations are discharged. The FX Desk Book NDF unit balance returns to zero at termination.

**Zero settlement**: If the net settlement amount is exactly zero (contracted rate equals fixing rate), only the NDF extinguishment move is created. No cash move is needed. The NDF unit is extinguished in a single-move transaction; state transitions `Active → Matured → Terminated` as the extinguishment move settles.

#### NDF Lifecycle Summary

```
Execution:     NDF unit created (Instructed → Settled); desk is long, counterparty is short; NDF state: Active
Fixing date:   Rate observed; settlement amount calculated; no new moves (state event only); NDF state: Active
Settlement:    Extinguishment + cash settlement move created (Pending); NDF state: Active → Matured
               Moves progress through Pending → Instructed → Settled
               Once all moves reach Settled: NDF state: Matured → Terminated
```

---

## Netting

Where multiple FX trades exist between the same counterparty, in the same currency pair, with the same value date, the gross settlement obligations may be netted to a single net amount per currency.

Netting is subject to bilateral agreement (typically governed by an ISDA Master Agreement or equivalent netting schedule) and is settled as a single net payment per currency rather than gross-for-gross.

### Ledger Representation of Netting

Netting is represented by a dedicated **Netting Transaction** created at the point of netting agreement (typically at the time settlement instructions are generated, prior to value date). The netting transaction:

1. **Reverses the relevant gross moves** to `Failed` state (the gross moves are cancelled pre-settlement; since they have not reached `Settled`, no reversal transaction is required — the `Failed` state itself removes them from all balance views per [invariant 8](../invariants.md#core-ledger-invariants)).
2. **Creates new net moves** for each currency in the netted set, linked to the netting transaction. These begin in `Pending` state and follow the standard settlement lifecycle.

The netting transaction preserves the reference to all original gross trades that contributed to the net position, maintaining a complete audit trail.

| Move Type | State Transition | Notes |
|-----------|-----------------|-------|
| Gross moves cancelled into net | `Instructed` → `Failed` | Terminal; excluded from all balances per invariant 8; no reversal required |
| Net move created | `Pending` | Single net amount per currency per counterparty per value date |

Only moves not yet in `Settled` state are eligible for netting. Settled moves have already been exchanged and cannot be unwound through netting.

---

## Early Termination

An FX trade may be terminated early by mutual agreement before value date (e.g. a forward cancelled prior to settlement). Early termination follows the amendment as cancel/correct pattern (see [invariant 7](../invariants.md#core-ledger-invariants)).

### Pre-Settlement Early Termination (moves not yet `Settled`)

If the moves have not yet reached `Settled` state, the smart contract transitions all moves to `Failed` (terminal). Because the moves never contributed to any settled balance, no reversal transaction is required. The `Failed` state automatically removes the moves from all balance views.

```
Pending / Instructed → Failed (early termination agreed)
↑ balance auto-corrected; no reversal transaction
```

### Post-Settlement Early Termination (moves already `Settled`)

If the near leg of an FX Swap has already settled but the far leg is to be terminated early, the far leg follows the pre-settlement path above (transition to `Failed` if not yet settled; or a reversal if already settled).

For a fully settled trade where an unwind is agreed, a new equal-and-opposite transaction is created as a reversal per [invariant 6](../invariants.md#core-ledger-invariants), with the reversal moves written directly as `Settled`.

---

## Failure Handling

### Two-Tier Failure Model

The ledger applies the two-tier failure model (see [invariant 8](../invariants.md#core-ledger-invariants)) to FX settlement failures:

| State | Tier | Meaning |
|-------|------|---------|
| `Pending` | Non-terminal | Settlement attempt failed; obligation persists; will retry |
| `Failed` | Terminal | Obligation definitively extinguished |

### CLS Settlement Failure

CLS failure is rare and distinct from bilateral failure. If CLS is unable to settle a pair on a given day (e.g. due to a member's funding shortfall), CLS will not release either leg. Both move legs remain in `Instructed` state. CLS will retry in subsequent settlement windows within the same day if capacity exists, or the instruction may be returned.

Because CLS settles both legs simultaneously, there is no asymmetric outcome: either both legs settle or neither settles. The atomicity of CLS settlement maps directly to the [Transaction atomicity invariant](../invariants.md#core-ledger-invariants).

| CLS Notification | New State | Action |
|-----------------|-----------|--------|
| Settlement confirmed | `Settled` (both legs) | Terminal |
| Settlement not completed (retry within day) | `Instructed` (both legs) | Retry within CLS window; same moves |
| Instruction returned (failed to settle) | `Pending` (both legs) | Reinstructing required; same moves |
| Trade cancelled by mutual agreement | `Failed` (both legs) | Terminal; excluded from all balances |

### Bilateral Settlement Failure and Herstatt Risk

For non-CLS pairs settled bilaterally, the two currency legs are instructed separately to different correspondent banks in different jurisdictions. This creates the possibility of asymmetric settlement: the leg settling in an earlier time zone may be confirmed before the leg in the later time zone has settled or failed.

**The ledger treats this risk at the transaction level, not the move level.** Each FX trade is a single transaction containing two moves. Per [Transaction atomicity invariant](../invariants.md#core-ledger-invariants), all moves in a transaction must succeed or fail together.

In practice, the settlement system monitors both legs and applies the following rules:

| Scenario | Treatment |
|----------|-----------|
| Both legs settle (confirmations received, possibly at different times) | Both moves transition to `Settled`; transaction complete |
| One leg settles, other leg fails | The failing leg transitions to `Pending` (non-terminal). The settled leg **cannot** be reversed until the outcome of the failing leg is resolved. The transaction remains partially confirmed but is not treated as complete. |
| Failing leg subsequently settled after retry | Both moves reach `Settled`; transaction complete |
| Failing leg definitively fails after one leg has `Settled` | See below — asymmetric failure resolution |

**Asymmetric failure resolution** (one leg `Settled`, other leg `Failed`):

This is the Herstatt risk scenario realised. One currency has been paid; the other has not arrived. Resolution depends on whether the delivered currency can be recovered:

- If the delivered currency can be returned (e.g. by agreeing a reversal with the correspondent bank): the settled leg is reversed per [invariant 6](../invariants.md#core-ledger-invariants), and the failing leg transitions to `Failed`. The net position is zero.
- If the delivered currency cannot be recovered: the delivered leg remains `Settled` and the failing leg is marked `Failed`. This represents a genuine loss; a separate recovery claim is recorded outside the ledger.

In both cases, the ledger records the actual state of each move accurately. The distinction between recoverable and irrecoverable asymmetric failure is an operational determination made by the settlement desk and communicated to the smart contract as a state event.

### NDF Cash Settlement Failure

NDF cash settlement follows the same two-tier model as a standalone cash payment (see [cash_payments.md](cash_payments.md)). Because there is only one cash move, there is no asymmetric failure risk. Failure handling:

| Scenario | State | Action |
|----------|-------|--------|
| Payment attempt failed (transient) | `Pending` | Retry; same move |
| Payment definitively rejected | `Failed` | Terminal; excluded from all balances |
| Fixing source unavailable on fixing date | Move not created | Smart contract holds; fixing rescheduled per market convention (e.g. next available publication) |

---

## QRL Schedule Generation

QRL is the external library responsible for generating payment date and fixing schedules. For FX instruments, QRL is responsible for the following:

| Instrument | QRL Outputs |
|------------|-------------|
| FX Spot | Spot value date, derived from trade date and currency pair convention (T+1, T+2, same-day as applicable); adjusted for currency pair holiday calendars |
| FX Forward | Forward value date, derived from trade date and tenor; adjusted for applicable holiday calendars for both currencies |
| FX Swap | Near value date and far value date; each derived and adjusted independently; must respect both currencies' holiday calendars |
| NDF | Fixing date (typically value date minus 2 business days); settlement date (value date); both adjusted per currency pair convention and applicable holiday calendars |

QRL outputs are consumed by the smart contract at execution and stored as part of the trade record. They are not recalculated after booking. Any change to scheduled dates (e.g. due to a subsequently declared holiday) constitutes a trade amendment and follows [invariant 7](../invariants.md#core-ledger-invariants).

---

## CDM Event Representation

| Lifecycle Event                                 | CDM Business Event Qualification             | CDM Transfer State              | Notes                                                                                                                                                                                  |
|-------------------------------------------------|----------------------------------------------|---------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FX Spot / Forward execution                     | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Pending`    | Smart contract creates the transaction with both currency moves; CDM product type `ForeignExchange`                                                                                    |
| FX Swap execution                               | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Pending`    | Two transactions created (near and far legs); linked by common smart contract reference                                                                                                |
| Settlement instruction generated                | — (state transition only)                    | `TransferStatusEnum.Instructed` | Applies to both moves in the transaction                                                                                                                                               |
| CLS settlement confirmed                        | — (state transition only)                    | `TransferStatusEnum.Settled`    | Both legs transition simultaneously                                                                                                                                                    |
| Bilateral settlement confirmed                  | — (state transition only)                    | `TransferStatusEnum.Settled`    | Each leg may transition independently as confirmations arrive                                                                                                                          |
| Settlement attempt failed (non-terminal)        | — (state transition only)                    | `TransferStatusEnum.Pending`    | Obligation persists; retry required                                                                                                                                                    |
| Trade cancelled pre-settlement                  | — (state transition only)                    | `TransferStatusEnum.Failed`     | Terminal; no reversal transaction                                                                                                                                                      |
| Settled trade reversed (unwind)                 | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Reversal transaction per invariant 6; moves written directly as `Settled`                                                                                                              |
| NDF execution — position created                | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Instructed` | NDF unit move from counterparty to FX Desk Book; transitions to `Settled` on confirmation                                                                                              |
| NDF fixing observed                             | `EventQualificationEnum.Reset`               | —                               | CDM `Observation` primitive; reference rate recorded; settlement amount calculated; no new moves                                                                                       |
| NDF maturity — unit extinguished + cash created | `EventQualificationEnum.ContractTermination` | `TransferStatusEnum.Pending`    | Two-move transaction: NDF unit returned to counterparty; net cash move in settlement currency; NDF state: `Active → Matured`; CDM `closedState.state = Terminated` set at this trigger |
| NDF maturity — cash settled                     | — (state transition only)                    | `TransferStatusEnum.Settled`    | Both moves settle via correspondent bank; NDF state: `Matured → Terminated`; final transfers `Settled` and `ClosedState.lastPaymentDate` reached (no new `closedState` transition)     |
| Netting: gross moves cancelled                  | — (state transition only)                    | `TransferStatusEnum.Failed`     | Terminal; balance auto-corrected; no reversal                                                                                                                                          |
| Netting: net move created                       | —                                            | `TransferStatusEnum.Pending`    | Single net amount per currency per counterparty per value date                                                                                                                         |
| Early termination (pre-settlement)              | — (state transition only)                    | `TransferStatusEnum.Failed`     | Terminal; no reversal transaction                                                                                                                                                      |
| Early termination (post-settlement)             | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Reversal transaction per invariant 6                                                                                                                                                   |

**CDM deviation notes**:

- CDM's `ForeignExchange` product type covers both deliverable FX and NDFs. In CDM, the NDF is represented as a `TradeState`; there is no concept of a transferable NDF unit that moves between wallets. This ledger deviates by representing the NDF position as a unit move at execution, consistent with the broader model in which all positions are expressed as moves. The NDF unit is a non-fungible contract unit (identified by trade reference) rather than a standardised asset. The CDM `Observation` primitive is used for the fixing event; the maturity conversion (unit extinguishment + cash creation in one transaction) maps to a combination of `ContractTermination` and `TransferPrimitive` in CDM.
- CDM does not have a native representation of CLS bilateral netting as a lifecycle event distinct from standard transfer. The ledger's netting transaction (cancel-gross, create-net) is a bespoke extension.
- The `Expected` state (used for anticipated receipts in [cash_payments.md](cash_payments.md)) is not used for FX. FX trades are initiated bilaterally, and the amounts are known at execution; there is no analogous asymmetric receipt-versus-payment distinction.

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [ForeignExchange product type](https://cdm.finos.org/docs/product-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Implementation

This section binds the FX contract to the [External Message Interface](../implementation.md).

### Inbound

| Family                   | Concrete message(s)                                                                                                                | Window       | Triggers                                                            |
|--------------------------|------------------------------------------------------------------------------------------------------------------------------------|--------------|---------------------------------------------------------------------|
| `MarketObservation`      | `Fixing` — NDF fixing rate from the designated source (e.g. PBOC for USD/CNH, RBI for USD/INR)                                     | Point (date) | Net settlement amount: `(Contracted − Fixing) × Notional / Fixing`. |
| `DateEvent`              | `ScheduledDate` — spot value date, forward value date, near / far value dates (swap), NDF fixing date, NDF settlement date         | —            | Leg settlement; NDF fixing and extinguishment.                      |
| `OperationalInstruction` | CLS PvP settlement confirmation/failure; correspondent-bank per-leg confirmation/failure (Herstatt); mutual-agreement cancellation | —            | Position-state bucket transitions; netting; termination.            |

No `CorporateAction` is consumed.

### Outbound

| Family               | Concrete message(s)                                                          | CDM projection                      |
|----------------------|------------------------------------------------------------------------------|-------------------------------------|
| `Payment`            | Buy-leg cash; sell-leg cash; NDF net settlement (settlement currency)        | `Transfer` (PvP) / `CashTransfer`   |
| `ProductStateChange` | NDF `Active → Matured → Terminated`; CLS netting (cancel-gross / create-net) | `ContractTermination` / netting `†` |
| `NewProductTemplate` | None — the NDF is extinguished at maturity, not replicated.                  | —                                   |
