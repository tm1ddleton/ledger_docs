# Cash Equities Smart Contract

## Overview

Cash equities are exchange-traded instruments. They are settled at a Central Securities Depository (CSD). Where a trade is not executed directly on the exchange order book (e.g. a reported or negotiated trade), it is nonetheless reported to the exchange so that CSD settlement can take place via the normal exchange settlement channel.

The smart contract governs the booking and lifecycle of equity trades from execution notification through to final settlement or failure.

---

## Parties and Wallets

| Party | Wallet Type | Description |
|-------|-------------|-------------|
| Exchange | Virtual wallet | Represents the exchange or CCP as counterparty to the trade |
| Exchange-Facing Book | Real wallet | Single book per legal entity that faces the exchange (see [Exchange Trade Booking Model invariant](../invariants.md#exchange-trade-booking-model)) |
| Trader's Front Book | Real wallet | Individual trader or desk book to which the position is allocated |
| CSD | Virtual wallet | Represents the Central Securities Depository; the exchange-facing book's settlement agent |

---

## Trade Execution Flow

### 1. Trade Notification (T+0)

When a trade is executed at the exchange (or reported to it), a trade notification is delivered to the smart contract. This notification is the triggering event.

The smart contract creates a single **Transaction** containing two simultaneous, balanced legs.

#### Leg 1 — External: Exchange ↔ Exchange-Facing Book

| Move | From | To | Asset | Initial CDM State |
|------|------|----|-------|-------------------|
| Equity delivery | Exchange (virtual wallet) | Exchange-Facing Book | Equity units (quantity × security identifier) | `TransferStatusEnum.Instructed` |
| Cash payment | Exchange-Facing Book | Exchange (virtual wallet) | Cash (trade consideration: price × quantity) | `TransferStatusEnum.Instructed` |

#### Leg 2 — Internal: Exchange-Facing Book ↔ Trader's Front Book

| Move | From | To | Asset | Initial CDM State |
|------|------|----|-------|-------------------|
| Equity allocation | Exchange-Facing Book | Trader's Front Book | Equity units | `TransferStatusEnum.Instructed` |
| Cash allocation | Trader's Front Book | Exchange-Facing Book | Cash (trade consideration) | `TransferStatusEnum.Instructed` |

**On `Instructed` as the initial state**: For exchange trades, the CSD settlement instruction is generated automatically as part of the exchange execution mechanism. By the time the trade notification reaches the smart contract, the settlement instruction is already in flight to the CSD. The initial state is therefore `Instructed` rather than `Pending`. No separate instructing step is required.

Both legs are part of the same atomic transaction (see [Transaction atomicity invariant](../invariants.md#core-ledger-invariants)) and are recorded simultaneously. The exchange-facing book nets to flat immediately upon transaction recording.

### 2. Settlement Feed (T+0, parallel)

In parallel with the smart contract booking, the exchange generates a settlement feed to the external settlement system. The settlement system validates and forwards a settlement instruction to the CSD for delivery versus payment (DvP) of securities and cash at T+1.

The smart contract does not directly interact with the settlement system at this stage; the settlement feed runs independently of the ledger booking.

### 3. Settlement Notification (T+1 onwards)

The settlement system sends a settlement notification to the smart contract on each CSD settlement attempt. This notification triggers a state transition on all four moves in the original transaction simultaneously.

A **settlement fail does not extinguish the legal obligation** between the parties. The trade still exists; only the settlement attempt has failed. The CSD will retry automatically on the next business day. The settlement state therefore has two tiers: a temporary failed state indicating a failed attempt (the obligation persists) and a terminal cancelled state indicating the obligation has been definitively extinguished.

#### Settlement State Transitions

| Notification | New CDM State | Meaning |
|---|---|---|
| Settlement confirmed | `TransferStatusEnum.Settled` | DvP completed at CSD; obligation extinguished. Terminal. |
| Settlement attempt failed | `TransferStatusEnum.Pending` | DvP attempt failed; obligation persists; CSD will retry. Non-terminal. |
| Instruction cancelled (bilateral) | `TransferStatusEnum.Failed` | Trade cancelled by mutual agreement; obligation extinguished. Terminal — reversal required (see below). |
| Buy-in triggered | `TransferStatusEnum.Failed` | Mandatory buy-in initiated; original instruction cancelled. Terminal — new buy-in transaction created (see below). |

All state transitions are applied atomically to all four moves in the transaction.

#### Post-Failure Resolution Paths

There are three distinct resolution paths once a settlement attempt has failed.

**Path 1 — Retry and settle (most common)**

The CSD retries the instruction on each subsequent business day. No new ledger transaction is created. The moves cycle between `Pending` (failed attempt received) and `Instructed` (retry instruction submitted) until the settlement ultimately succeeds (`Settled`) or the instruction is cancelled.

```
Instructed → Pending (fail) → Instructed (retry) → ... → Settled
```

No reversal is created. The original moves are the definitive record.

**Path 2 — Bilateral cancellation**

Both parties agree to cancel the trade. The settlement system sends a cancellation confirmation, transitioning all moves to `TransferStatusEnum.Failed` (terminal). Because `Failed` moves are excluded from all wallet balance views (see [invariant 9](../invariants.md#core-ledger-invariants)), the balances are automatically corrected by this state transition alone — no reversal transaction is required or created. The cancellation is recorded as a state event on the original moves; the ledger retains the full history.

Note: the [Cancellation by reversal invariant](../invariants.md#core-ledger-invariants) does not apply here because the original moves never reached `Settled` state and therefore never affected any balance. A reversal transaction would over-correct.

```
Instructed → Pending (fail) → ... → Failed (cancellation confirmed)
                                     ↑ balance auto-corrected; no reversal transaction
```

**Path 3 — Mandatory buy-in (CSDR / equivalent)**

After a defined number of failed settlement days (typically 4 business days for equities under EU CSDR), a mandatory buy-in is triggered. A buy-in agent purchases the securities in the open market and delivers them to the receiving party. The cost difference is charged back to the failing party.

The original instruction is cancelled, transitioning all original moves to `TransferStatusEnum.Failed` (terminal). As with bilateral cancellation, no reversal of the original transaction is created — the `Failed` state removes the original moves from all balance views. The buy-in constitutes a **new trade** and generates its own new transaction with its own execution and settlement lifecycle. A separate cash compensation move is created for any price differential between the original trade price and the buy-in price.

```
Instructed → Pending (fail) → ... → Failed (buy-in triggered)
                                     ↑ excluded from all balances; no reversal transaction
                                        └→ [New buy-in transaction, Instructed → Settled]
                                        └→ [Cash compensation move, Instructed → Settled]
```

---

## CDM Event Representation

| Lifecycle Event | CDM Business Event Qualification | CDM Transfer State | Notes |
|---|---|---|---|
| Trade notification received | `EventQualificationEnum.Execution` | `TransferStatusEnum.Instructed` | Smart contract creates the transaction and all four moves |
| Settlement confirmed | — (state transition only) | `TransferStatusEnum.Settled` | Terminal. Triggered by settlement system confirmation. |
| Settlement attempt failed | — (state transition only) | `TransferStatusEnum.Pending` | Non-terminal. CSD will retry. No new transaction. |
| Retry instruction submitted | — (state transition only) | `TransferStatusEnum.Instructed` | Non-terminal. Settlement system re-submits CSD instruction. |
| Bilateral cancellation confirmed | — (state transition only) | `TransferStatusEnum.Failed` | Terminal. No reversal transaction — `Failed` state excludes moves from all balances. |
| Buy-in triggered | — (state transition only) | `TransferStatusEnum.Failed` | Terminal. No reversal transaction — `Failed` state excludes moves from all balances. |
| Buy-in trade | `EventQualificationEnum.Execution` | `TransferStatusEnum.Instructed` | New transaction; independent settlement lifecycle. |
| Buy-in cash compensation | — | `TransferStatusEnum.Instructed` | Single cash move for buy-in price differential; settles with buy-in trade. |

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Corporate Actions

The CDM defines the following corporate action types for equities in `CorporateActionTypeEnum`. The authoritative source is the Rosetta enumeration file: [`event-common-enum.rosetta`](https://github.com/finos/common-domain-model/blob/master/rosetta-source/src/main/rosetta/event-common-enum.rosetta). CDM event model documentation: [https://cdm.finos.org/docs/event-model/](https://cdm.finos.org/docs/event-model/).

| CDM Type | ISO 15022 Code | Description |
|----------|----------------|-------------|
| `CashDividend` | DVCA | Distribution of a cash dividend to shareholders |
| `StockDividend` | DVSE | Distribution of additional shares (scrip dividend) in lieu of or alongside cash |
| `StockSplit` | SPLF | Subdivision of existing shares into a greater number at a proportionally reduced price |
| `ReverseStockSplit` | SPLR | Consolidation of existing shares into a smaller number at a proportionally higher price |
| `SpinOff` | SOFF | Distribution of shares in a subsidiary or demerged entity to existing shareholders |
| `Merger` | MRGR | Combination of two or more companies; shares may be exchanged, cancelled, or converted |
| `Delisting` | — | Removal of the security from the exchange; positions must be closed or transferred |
| `StockNameChange` | CHAN | Change to the issuer's trading name; security identifier may also change |
| `StockIdentifierChange` | CHAN | Change to the security's trading code or ISIN without a change in the underlying security |
| `RightsIssue` | RHTS | Offering of subscription rights to purchase additional shares at a discount to market price |
| `Takeover` | TEND | Acquisition of the issuer by another entity; may result in share exchange or cancellation |
| `StockReclassification` | CHAN | Reclassification of stock into a different share class |
| `BonusIssue` | BONU | Free allocation of additional shares to existing holders (capitalisation issue) |
| `ClassAction` | — | Legal proceeding for collective shareholder financial restitution |
| `EarlyRedemption` | MCAL | Redemption of the security before its scheduled maturity (typically relevant for preference shares) |
| `Liquidation` | LIQU | Dissolution of the issuer and distribution of remaining assets to shareholders |
| `BankruptcyOrInsolvency` | — | Filing for bankruptcy or insolvency by the issuer; positions typically written down to zero |
| `IssuerNationalization` | — | Government acquisition of the issuer; existing shares cancelled or converted |
| `Relisting` | — | Transfer of the security's primary listing to a different exchange or segment |
| `BespokeEvent` | — | Custom corporate action agreed separately between parties and not covered by the above types |

### Cash Dividend (DVCA)

Cash dividends are received by holders of direct equity positions. Derivative holders (e.g. equity option holders) do not receive dividends directly — the dividend is factored into derivative pricing at inception and through delta adjustments.

**Ledger treatment**: On the ex-date an `Expected` move is booked per [cash_payments.md](cash_payments.md). On the payment date the move transitions through `Instructed → Settled`.

| Move                | From                 | To                   | Asset                         | Initial State |
|---------------------|----------------------|----------------------|-------------------------------|---------------|
| Dividend receipt    | CSD                  | Exchange-Facing Book | Cash (gross dividend amount)  | `Expected`    |
| Dividend allocation | Exchange-Facing Book | Trader's Front Book  | Cash (net dividend after tax) | `Pending`     |

**Dividend tax treatment**: Withholding tax and other dividend taxes are applied at two levels:

1. **Wallet and jurisdiction level**: The applicable rate depends on the jurisdiction of incorporation of the issuing company and the legal entity status of the receiving wallet (e.g. domestic investor, non-resident, treaty-eligible entity). The net amount in the allocation move reflects the rate applicable to the receiving book.

2. **Synthetic instruments and index products**: For instruments that do not directly hold the underlying equities but carry economic dividend exposure (e.g. total return swaps, structured products referencing a price-return index), withholding tax equivalent charges may apply. For synthetic instruments above a given delta threshold, withholding taxes on dividends may be levied as if the holder were a direct holder of the underlying shares. The applicable delta threshold and the resulting tax charge are instrument-specific and determined per applicable jurisdiction rules and the instrument terms. The composition of any index referenced by the instrument must also be considered — withholding rates may vary across the constituent equities by their individual jurisdictions.

### Stock Split (SPLF), Reverse Stock Split (SPLR), and Scrip Dividend (DVSE)

These corporate actions change the number of shares in issue without changing the total monetary value of the position. The ledger adjustment is a quantity move between the CSD and the relevant books.

**2-for-1 stock split example**: The CSD delivers additional shares equal to the existing holding. Both the exchange-facing book and the trader's front book double their holdings.

| Move                     | From                 | To                   | Asset                                  | Initial State          |
|--------------------------|----------------------|----------------------|----------------------------------------|------------------------|
| Additional shares (EFB)  | CSD                  | Exchange-Facing Book | Equity units (= existing EFB holding)  | `Instructed → Settled` |
| Additional shares (book) | Exchange-Facing Book | Trader's Front Book  | Equity units (= existing book holding) | `Instructed → Settled` |

For a **reverse split** (e.g. 1-for-2), both moves reverse direction: shares are returned to the CSD, halving the quantities held in both wallets.

For a **scrip dividend**, the mechanics are identical — additional shares are moved from the CSD to the books. Any cash component of a scrip dividend is handled as a Cash Dividend per the section above.

Quantity-changing moves settle on the record date or ex-date per the exchange / CSD corporate action timetable. The price per unit adjusts proportionally so that total position value is unchanged.

**Impact on derivatives**: Quantity-changing corporate actions trigger R-value adjustments to any derivative position referencing the affected security. See [equity_options.md](equity_options.md) for the option-specific treatment.

### Spin-Off (SOFF), Merger (MRGR), and Takeover (TEND)

These events alter the nature of the underlying company and require bespoke treatment. The ledger outcome is determined on a case-by-case basis by the corporate action terms:

| Outcome          | Trigger                                                        | Ledger Treatment                                                                                   |
|------------------|----------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| Basket           | Holder receives shares in multiple entities (e.g. spin-off)   | Existing position extinguished; new positions created in each constituent security.                |
| Cash termination | Security cancelled for cash consideration (e.g. all-cash merger) | Position extinguished; cash proceeds booked per [cash_payments.md](cash_payments.md).          |
| Client election  | Corporate action terms permit holder to choose outcome         | Position suspended until election deadline; treatment applied on receipt of election instruction.  |

Where a corporate action affects a derivative position referencing the underlying equity (e.g. an equity option or structured product), the outcome for the derivative is also determined on a case-by-case basis and may be at the client's discretion. See [equity_options.md](equity_options.md).

### Rights Issue (RHTS)

A rights issue grants existing shareholders the right — but not the obligation — to subscribe for new shares at a discounted subscription price, typically in proportion to their existing holding.

**Ledger treatment**: On the ex-date, rights units are delivered from the CSD to the relevant books as a quantity move.

| Move                     | From                 | To                   | Asset                                  | Initial State          |
|--------------------------|----------------------|----------------------|----------------------------------------|------------------------|
| Rights allocation (EFB)  | CSD                  | Exchange-Facing Book | Rights units (pro-rata to equity held) | `Instructed → Settled` |
| Rights allocation (book) | Exchange-Facing Book | Trader's Front Book  | Rights units (pro-rata to equity held) | `Instructed → Settled` |

**Rights smart contract**: The rights instrument is governed by a new smart contract that accepts an exercise event. During the subscription period the holder may:

- **Exercise**: pay the subscription price and receive new shares (DvP at CSD). The exercise generates a transaction pairing a cash move (subscription price) with an equity delivery move.
- **Lapse**: allow the rights to expire; rights units are extinguished at the end of the subscription period.
- **Trade** (if the rights are listed): rights units may be traded on exchange during the subscription period, following the same execution and settlement model as cash equities.

The rights smart contract lifecycle will be documented separately.

**Impact on derivative positions**: Option holders do not receive the subscription rights directly. Instead, listed option contracts are adjusted by the exchange or clearing house, and OTC contracts by the calculation agent, so that economic value is approximately preserved after the dilution on the ex-rights date. The adjustment may take the form of a revised strike, a changed deliverable, a changed contract multiplier, or a combination; it is event-specific and determined per the clearing house or calculation agent notice. See [equity_options.md](equity_options.md).

Remaining corporate action types (Delisting, StockNameChange, StockIdentifierChange, BonusIssue, ClassAction, EarlyRedemption, Liquidation, BankruptcyOrInsolvency, IssuerNationalization, Relisting, BespokeEvent) will be specified as each type is implemented. The CDM does not yet provide complete lifecycle coverage for all the above types; deviations will be noted per type.
