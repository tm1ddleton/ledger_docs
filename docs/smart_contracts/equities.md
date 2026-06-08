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
| Internal Wallet | Real wallet | Individual trader or desk book to which the position is allocated |
| CSD | Virtual wallet | Represents the Central Securities Depository; the exchange-facing book's settlement agent |

---

## Settlement State

Settlement state is held on the **position**, not on individual moves, per the [State Model](../state.md). Moves within a `(unit, wallet, counterparty wallet)` position are treated as fungible; the canonical record of where quantity sits in the settlement cycle is the position-state bucket. CDM `TransferStatusEnum` values remain useful event vocabulary for inbound and outbound feeds but are not stamped on individual moves.

For equities in most markets the cycle is T+1: on trade date T the affected quantity sits in `Pending(T+1)` of the relevant position and transitions to `Settled` on the value date.

---

## Trade Execution Flow

### 1. Trade Notification (T+0)

When a trade is executed at the exchange (or reported to it), a trade notification is delivered to the smart contract. This notification is the triggering event.

The smart contract creates a single **Transaction** containing two simultaneous, balanced legs.

#### Leg 1 — External: Exchange ↔ Exchange-Facing Book

| Move            | From                      | To                    | Asset                                          |
|-----------------|---------------------------|-----------------------|------------------------------------------------|
| Equity delivery | Exchange (virtual wallet) | Exchange-Facing Book  | Equity units (quantity × security identifier)  |
| Cash payment    | Exchange-Facing Book      | Exchange (virtual)    | Cash (trade consideration: price × quantity)    |

#### Leg 2 — Internal: Exchange-Facing Book ↔ Internal Wallet

| Move              | From                  | To                   | Asset                       |
|-------------------|-----------------------|----------------------|-----------------------------|
| Equity allocation | Exchange-Facing Book  | Internal Wallet      | Equity units                |
| Cash allocation   | Internal Wallet       | Exchange-Facing Book | Cash (trade consideration)  |

Both legs are part of the same atomic transaction (see [Transaction atomicity invariant](../invariants.md#core-ledger-invariants)) and are recorded simultaneously. The exchange-facing book nets to flat immediately upon transaction recording.

**Position-state impact**: each affected position has its quantity recorded into the `Pending(T+1)` bucket. The exchange's CSD settlement instruction is generated automatically by the exchange execution mechanism in parallel with this booking; the smart contract does not separately model the instruction.

### 2. Settlement Notification (value date)

On the contractual value date the smart contract optimistically transitions the relevant quantity `Pending(value-date) → Settled` on each position involved. Where a settlement-system feed is available, it confirms or contradicts that optimistic transition; where it is not, the optimistic transition stands.

A **settlement failure does not extinguish the legal obligation** between the parties — the trade still exists, only the settlement attempt has failed. Failures are therefore recorded at the position-state level by rotating the relevant quantity into the next business day's `Pending` bucket. The terminal `Failed` bucket is reserved for definitive resolutions: bilateral cancellation, mandatory buy-in, and similar end states.

#### Position-State Transitions on Settlement Outcomes

| Outcome                            | Position-state transition                                         | Meaning                                                                                         |
|------------------------------------|-------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Settlement confirmed               | `Pending(D) → Settled`                                            | DvP completed at the CSD; obligation extinguished. Terminal.                                    |
| Settlement attempt failed (retry)  | `Pending(D) → Pending(D+1)`                                       | CSD retries the next business day. Obligation persists. Non-terminal.                           |
| Bilateral cancellation             | `Pending(D) → Failed`                                             | Trade cancelled by mutual agreement; obligation extinguished. Terminal.                         |
| Buy-in triggered                   | `Pending(D) → Failed`; new trade transaction created              | Mandatory buy-in initiated; original instruction cancelled. Terminal — new trade compensates.   |

All transitions apply atomically to every affected position in the original transaction (the two-leg external and internal legs move in lockstep).

#### Post-Failure Resolution Paths

There are three distinct resolution paths once a settlement attempt has failed.

**Path 1 — Retry and settle (most common)**

The CSD retries each business day. No new ledger transaction is created. Quantity rotates `Pending(D) → Pending(D+1) → ...` until DvP succeeds (`Pending → Settled`) or the instruction is terminally cancelled.

**Path 2 — Bilateral cancellation**

Both parties agree to cancel the trade. The smart contract moves quantity to the `Failed` bucket on every affected position. Because `Failed` quantities are excluded from all wallet balance views (per [invariant 9](../invariants.md#core-ledger-invariants)), balances auto-correct — **no reversal transaction is required or created**. The [Cancellation by reversal invariant](../invariants.md#core-ledger-invariants) does not apply because the quantity never reached `Settled` and never affected any balance.

**Path 3 — Mandatory buy-in (CSDR / equivalent)**

After a defined number of failed settlement days (typically 4 business days for equities under EU CSDR), a mandatory buy-in is triggered. A buy-in agent purchases the securities in the open market and delivers them to the receiving party; the cost difference is charged back to the failing party. The original trade's quantity is moved into the `Failed` bucket on all affected positions; the buy-in is a **new trade** with its own transaction and settlement lifecycle, plus a separate cash compensation move for any price differential.

---

## CDM Event Representation

CDM `TransferStatusEnum` values are used here as the event vocabulary — i.e. the labels for inbound feed messages and outbound notifications. They are **not** stamped on individual moves; canonical settlement state lives in the position-state bucket per the [State Model](../state.md).

| Lifecycle Event                   | CDM Business Event Qualification    | Event Vocabulary (CDM)            | Position-state effect                                              |
|-----------------------------------|-------------------------------------|-----------------------------------|--------------------------------------------------------------------|
| Trade notification received       | `EventQualificationEnum.Execution`  | —                                 | New quantity added to `Pending(T+1)` on every affected position    |
| Settlement confirmed              | — (state transition only)           | `TransferStatusEnum.Settled`      | `Pending(D) → Settled`. Terminal.                                  |
| Settlement attempt failed         | — (state transition only)           | `TransferStatusEnum.Pending`      | `Pending(D) → Pending(D+1)`. Non-terminal.                         |
| Bilateral cancellation confirmed  | — (state transition only)           | `TransferStatusEnum.Failed`       | `Pending(D) → Failed`. Terminal. No reversal needed.               |
| Buy-in triggered                  | — (state transition only)           | `TransferStatusEnum.Failed`       | `Pending(D) → Failed`. Terminal. Triggers buy-in trade.            |
| Buy-in trade                      | `EventQualificationEnum.Execution`  | —                                 | New trade transaction; quantity into `Pending(T+1)`.               |
| Buy-in cash compensation          | —                                   | —                                 | Single cash move for buy-in price differential; settles with the buy-in trade. |

CDM reference: [Event Model](https://cdm.finos.org/docs/event-model/) · [FINOS CDM GitHub](https://github.com/finos/common-domain-model)

---

## Corporate Actions

Application of corporate actions across all subscribed positions follows the [Corporate Action Orchestration](../invariants.md#corporate-action-orchestration) model in `invariants.md`: subscriptions are recorded at product creation; CA records are defined per listing; application is atomic across an ISIN per [invariant 12](../invariants.md#core-ledger-invariants); position-level overrides resolve per the Modes order before the ex-date, with a cancel/correct path post-ex-date. This section covers the equity-specific mechanics for each CA type.

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

**Eligibility**: Dividend eligibility is determined per position state (see [state.md](../state.md)). Only quantities in the `Settled` bucket of the relevant `(unit, wallet, counterparty)` position on the record date are eligible. Quantities still in `Pending(D)` on the record date — e.g. shares purchased intraday on T but with anticipated settlement on T+2 falling after record date — do **not** receive the dividend; the seller, whose `Settled` balance has not yet been reduced, retains eligibility for those shares.

**Ledger treatment**: On the ex-date the dividend cash moves are created and the receiving positions record the cash quantity in `Pending(payment-date)`. On the payment date the optimistic transition `Pending(payment-date) → Settled` applies to both positions.

| Move                | From                 | To                   | Asset                         | Position-state on creation  |
|---------------------|----------------------|----------------------|-------------------------------|-----------------------------|
| Dividend receipt    | CSD                  | Exchange-Facing Book | Cash (gross dividend amount)  | `Pending(payment-date)`     |
| Dividend allocation | Exchange-Facing Book | Internal Wallet      | Cash (net dividend after tax) | `Pending(payment-date)`     |

**Dividend tax treatment**: The applicable withholding tax rate is resolved per dividend recipient at application time. The rate function is:

```
rate = productInstanceOverride
       ?? lookup(counterparty, issuerJurisdiction, counterpartyJurisdiction)
```

| Dimension                   | Description                                                                                      | Source                                  |
|-----------------------------|--------------------------------------------------------------------------------------------------|-----------------------------------------|
| `counterparty`              | The entity receiving the dividend (or whose synthetic exposure is being credited)                | Counterparty static data                |
| `issuerJurisdiction`        | Jurisdiction of incorporation of the issuing company                                              | Issuer static data on the listing       |
| `counterpartyJurisdiction`  | Tax residence of the counterparty (drives treaty status, domestic vs non-resident treatment)     | Counterparty static data                |
| `productInstanceOverride`   | Optional per-product-instance override of the matrix-derived rate (e.g. a structured note with non-standard withholding terms) | Product state |

The lookup is performed independently for each `(unit, wallet, counterparty wallet)` position eligible to receive the dividend; a single cash dividend on a single equity may therefore produce different net amounts for different counterparty wallets in the same orchestrated transaction. Each counterparty's allocation move uses its own resolved rate; gross dividend × (1 − rate) is the net amount paid to that counterparty.

**Synthetic instruments and index products**: For instruments that do not directly hold the underlying equities but carry economic dividend exposure (e.g. total return swaps, structured products referencing a price-return index), withholding-tax equivalent charges may apply. For synthetic instruments above a given delta threshold, withholding may be levied as if the holder were a direct holder of the underlying shares. The applicable delta threshold and the resulting charge are instrument-specific and may be expressed as a `productInstanceOverride` on the synthetic product's state. For index-referencing instruments, the rate function is applied per constituent and aggregated, since withholding rates may vary across constituents by their individual issuer jurisdictions.

### Stock Split (SPLF), Reverse Stock Split (SPLR), and Scrip Dividend (DVSE)

These corporate actions change the number of shares in issue without changing the total monetary value of the position. The ledger adjustment is a quantity move between the CSD and the relevant books.

**2-for-1 stock split example**: The CSD delivers additional shares equal to the existing holding. Both the exchange-facing book and the internal wallet double their holdings.

| Move                     | From                 | To                   | Asset                                  | Position-state on creation |
|--------------------------|----------------------|----------------------|----------------------------------------|----------------------------|
| Additional shares (EFB)  | CSD                  | Exchange-Facing Book | Equity units (= existing EFB holding)  | `Settled`                  |
| Additional shares (book) | Exchange-Facing Book | Internal Wallet      | Equity units (= existing book holding) | `Settled`                  |

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

| Move                     | From                 | To                   | Asset                                  | Position-state on creation |
|--------------------------|----------------------|----------------------|----------------------------------------|----------------------------|
| Rights allocation (EFB)  | CSD                  | Exchange-Facing Book | Rights units (pro-rata to equity held) | `Settled`                  |
| Rights allocation (book) | Exchange-Facing Book | Internal Wallet      | Rights units (pro-rata to equity held) | `Settled`                  |

**Rights smart contract**: The rights instrument is governed by a new smart contract that accepts an exercise event. During the subscription period the holder may:

- **Exercise**: pay the subscription price and receive new shares (DvP at CSD). The exercise generates a transaction pairing a cash move (subscription price) with an equity delivery move.
- **Lapse**: allow the rights to expire; rights units are extinguished at the end of the subscription period.
- **Trade** (if the rights are listed): rights units may be traded on exchange during the subscription period, following the same execution and settlement model as cash equities.

The rights smart contract lifecycle will be documented separately.

**Impact on derivative positions**: Option holders do not receive the subscription rights directly. Instead, listed option contracts are adjusted by the exchange or clearing house, and OTC contracts by the calculation agent, so that economic value is approximately preserved after the dilution on the ex-rights date. The adjustment may take the form of a revised strike, a changed deliverable, a changed contract multiplier, or a combination; it is event-specific and determined per the clearing house or calculation agent notice. See [equity_options.md](equity_options.md).

Remaining corporate action types (Delisting, StockNameChange, StockIdentifierChange, BonusIssue, ClassAction, EarlyRedemption, Liquidation, BankruptcyOrInsolvency, IssuerNationalization, Relisting, BespokeEvent) will be specified as each type is implemented. The CDM does not yet provide complete lifecycle coverage for all the above types; deviations will be noted per type.

---

## Implementation

This section binds the cash-equities contract to the [External Message Interface](../implementation.md). It lists the concrete inbound messages the contract subscribes to and the outbound messages it emits.

### Inbound

| Family                  | Concrete message(s)                                                               | Window       | Triggers                                                                                                   |
|-------------------------|-----------------------------------------------------------------------------------|--------------|------------------------------------------------------------------------------------------------------------|
| `MarketObservation`     | `Close` — official closing price of the listing                                   | Point (date) | Valuation / live-balance marking; not itself a lifecycle trigger.                                          |
| `DateEvent`             | `ScheduledDate` — value-date arrival; dividend ex-date, record date, payment date | —            | Optimistic `Pending(value-date) → Settled`; dividend booking.                                              |
| `CorporateAction`       | Full `CorporateActionTypeEnum` set (see Corporate Actions above)                  | —            | Orchestrated application across subscribed positions ([inv. 12](../invariants.md#core-ledger-invariants)). |
| `TradeNotification`     | Exchange fill or reported/negotiated trade                                        | —            | Two-leg execution transaction; quantity into `Pending(T+1)`.                                               |
| `SettlementFeedback`    | DvP confirmed / failed / bilateral cancellation / buy-in trigger                  | —            | Position-state bucket transition.                                                                          |
| `OverrideConfiguration` | Pre-ex-date position-level CA override                                            | —            | Stored against `(position, ISIN, ex-date, action-type)`.                                                   |

### Outbound

| Family               | Concrete message(s)                                                                                            | CDM projection                                     |
|----------------------|----------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| `Payment`            | Dividend cash (gross/net per withholding); buy-in cash compensation                                            | `CashDividend` / `CashTransfer`                    |
| `ProductStateChange` | Position-state bucket transitions; CA applied (product-state version bump, R-value propagation to derivatives) | `TransferStatusEnum` vocabulary; `StockSplit` etc. |
| `NewProductTemplate` | Rights instrument (on `RightsIssue`); basket constituents (on `SpinOff` / `Merger` / `Takeover`)               | `Execution` / `Transfer`                           |

Ordinary equity trades create no new product template — they open positions in an existing listing. Templates are emitted only where a corporate action brings a new instrument into existence.
