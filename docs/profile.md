# CDM Profile

## Purpose

This document is the single, consolidated record of how this ledger maps onto the FINOS Common Domain Model (CDM 6.x). It exists so that every place the implementation specialises, extends, or diverges from CDM is documented in one place rather than discovered by reading eleven smart-contract documents.

The distinction that governs every entry below:

- **Profile** = adoption-aligned specialisation. A choice made where CDM is thin, ambiguous, or offers more than one valid representation, recorded as a deliberate mapping. The intent is to remain interoperable with CDM-native systems.
- **Fork** = divergence. A place where the ledger's canonical model cannot be expressed in CDM at all and a bespoke extension is required (marked `†` throughout this repository).

Where CDM is adopted unchanged, there is nothing to record here; the per-contract documents cite the relevant CDM types directly. This document records only specialisations, extensions, and the resolutions of CDM ambiguities. The per-contract `smart_contracts/*.md` files remain the detailed source; this document is the index and the rationale.

---

## 1. Global State-Model Profile

These decisions are made once, in [state.md](state.md), and apply to every smart contract.

| # | Decision | CDM baseline | Profile / fork | Source |
|---|----------|--------------|----------------|--------|
| 1 | **Settlement state on the position, not the move.** Moves are fungible within a `(unit, wallet, counterparty wallet)` position; the canonical settlement state is the position-state bucket (`Settled` / `Pending(date)` / `Failed`). | CDM carries a `TransferStatusEnum` per `Transfer`. | **Profile.** `TransferStatusEnum` values are retained as event *vocabulary* for inbound feeds and outbound notifications, but are not stamped on individual moves. The per-move model is fictional under settlement netting (see rationale in source). | [state.md §Moves Are Fungible](state.md#moves-are-fungible-a-deliberate-departure-from-cdm) |
| 2 | **`Expected` pre-instruction state.** Anticipated future receipts (coupons, dividends, notional exchanges) are promoted to first-class ledger moves in `Expected` state from position acquisition. | `TransferStatusEnum` has no pre-instruction state. Closest concept is `ScheduledTransfer` within the payout framework, but that is a contract term, not a live ledger entry. | **Fork** (bespoke state). Provides a complete forward income schedule to risk and treasury from day one; visible in the live balance, excluded from the settled balance (invariant 9). | [bonds.md](smart_contracts/bonds.md), [cash_payments.md](smart_contracts/cash_payments.md) |
| 3 | **Compound unit state** — `liveliness \| last-lifecycle-event marker \| corporate-actions-applied list`, uniform across all holders. | CDM `TradeState` has no native compound liveliness + last-event marker. | **Fork.** Carries idempotency (invariant 10), audit, and CA-history monotonicity in one structure. | [state.md §Unit State](state.md#unit-state) |
| 4 | **`Matured` interstitial liveliness.** A state between live and closed: the final lifecycle event has fired but final settlement is still open. | CDM has `closedState` (set/unset) but no interstitial. | **Profile.** `Matured` is carried as a bespoke field on `TradeState` *without* setting `closedState`; `closedState` is set only at `Expired` / `Terminated`. | [state.md §Liveliness](state.md#liveliness), [irs.md](smart_contracts/irs.md), [fx.md](smart_contracts/fx.md) |
| 5 | **Exercise sub-bucket on position state** — the `Live` / `Exercised(date)` / `Assigned(date)` partition layered onto the settlement buckets. | CDM models exercise as an event, not as a standing position partition. | **Fork** (position-state extension). Required for American/Bermudan; degenerate (always `Live`) for European. | [equity_options.md §Position State](smart_contracts/equity_options.md#position-state) |
| 6 | **Futures `costBasis` scalar** on position state, reset at each EOD. | CDM has no running cost basis for the daily-settlement cycle. | **Fork** (position-state extension). Materialised derived state, re-derivable from the trade ledger and the recorded daily settlement events (invariant 4). | [state.md §Position-Specific State Extensions](state.md#product-specific-state-extensions), [futures.md](smart_contracts/futures.md) |

---

## 2. Product, Registry, and Grain

| # | Decision | Profile / fork | Source |
|---|----------|----------------|--------|
| 7 | **Product is a pre-existing registry entry** keyed by `(productId, version)` at the payout layer; trades reference the product. | **Profile.** Aligns with CDM's product/event separation. Listed-vs-OTC is metadata on the registry entry, not a structural fork of the payoff template. | [state.md §Product Registry](state.md#product-registry) |
| 8 | **`lifecyclingGrain` flag** (`trade` / `position`) declared on the registry entry. | **Profile** (no CDM equivalent flag). Grain is a consequence of fungibility surfaced explicitly; `trade`-grained is the degenerate single-trade case of `position`-grained. | [state.md §Lifecycling Grain](state.md#lifecycling-grain) |
| 9 | **Down-allocation as the interop bridge.** Position-level events are projected losslessly to per-trade CDM events at the boundary. | **Profile.** Internal canonical record is position-level; CDM-native per-trade events are a re-derivable projection. | [events.md §Projection and Down-Allocation](events.md#projection-and-down-allocation) |

---

## 3. Resolved CDM Ambiguities

CDM admits more than one valid representation in each of the following; this section records the choice this ledger makes. Each is a **profile** decision, open to challenge.

### 3.1 `quantity.value` vs `quantity.multiplier` on listed contracts

CDM allows the size of a listed position to be expressed either as a contract count in `quantity.value` or with the per-contract point value folded into a `multiplier`.

**Decision.** Position size `N` is the **number of contracts**, carried in `quantity.value`. The per-contract point value / lot size is carried **once** as `multiplier` on the product registry entry (product state), never duplicated into the quantity. Economic notional is always reconstructed as `quantity.value × product.multiplier × price`. This keeps `N` (the thing that nets across trades into a position) a clean integer contract count and localises the point-value to the product template, where corporate-action R-value adjustments apply (see [equity_options.md](smart_contracts/equity_options.md#quantity-changing-actions-r-value-adjustments)).

### 3.2 Reset vs Observation

CDM distinguishes `Observation` (a raw market datum) from `Reset` (the application of an observation to crystallise an amount on a payout).

**Decision.** Both are recorded, with a clear canonical/derived split per invariant 4:

- The **`Observation`** (the fixing value, barrier reference level, settlement price) is the **canonical, immutable source** — recorded once, re-fed idempotently.
- The **`Reset`** (the crystallised amount written onto the `Expected` move, the VM figure, the cost-basis reset) is a **derived view** computed from the observation and the product terms. If a `Reset` and its source `Observation` ever disagree, the observation wins and the reset is recomputed.

This is why rate fixing (IRS, FRN) and barrier observation are state-only events that update an existing move rather than create one: the observation is the source, the reset is the materialisation.

### 3.3 Asset vs payout for listed options

A listed option can be modelled either as a tradeable **asset** (an `AssetPayout` / security reference to the listing) or at the **payout layer** as an `OptionPayout` within a contractual product, the same as an OTC option.

**Decision.** Listed options are modelled at the **payout layer** (`OptionPayout`), identically to OTC options; the exchange/clearing listing is metadata on the registry entry (decision 7). This is the direct consequence of Principle 1 — listed-vs-OTC is not a structural fork — and it means one option lifecycle engine ([equity_options.md](smart_contracts/equity_options.md)) serves both, with the CCP appearing only as the counterparty wallet and the booking topology differing per the [Exchange Trade Booking Model](invariants.md#exchange-trade-booking-model).

### 3.4 STM vs CTM for margin

Variation margin can be modelled as **settled-to-market (STM)** — a title-transfer settlement of the day's P&L that extinguishes it — or **collateralised-to-market (CTM)** — collateral pledged against a still-accruing exposure.

**Decision.**

| Flow | Model | Rationale |
|------|-------|-----------|
| Cleared VM (CCP) | **STM** | The CCP crystallises daily P&L as an actual cash transfer; the futures `costBasis` reset (futures.md) is precisely the STM mechanic — VM settles the day's P&L and the basis resets to today's mark. No residual collateral position. |
| Bilateral VM under a title-transfer CSA | **STM** | Title passes; modelled as a settlement, same as cleared VM. |
| Bilateral VM under a security-interest CSA | **CTM** | Collateral is pledged, not settled; modelled as a collateral position (a pledge), not a P&L settlement. |
| Initial margin (all) | Out of scope / collateral | IM is a segregated collateral obligation, not a cash asset of the desk; excluded per the [IM exclusion](invariants.md#initial-margin--out-of-scope). It never resets cost basis and never creates a funding position. |

---

## 4. Bespoke Event Extensions (Forks)

Every event qualification or type marked `†` in [events.md](events.md) is a fork — a place where no standard CDM equivalent exists. Consolidated here by smart contract; the detailed shape of each is in the cited document's *CDM Extensions* section.

| Smart contract | Bespoke extension | Nature | Source |
|----------------|-------------------|--------|--------|
| Futures | `DailySettlementEvent` | EOD VM crystallisation + cost-basis reset + two-tier cash structure | [futures.md §CDM Extensions](smart_contracts/futures.md#cdm-extensions) |
| Equity options | `BarrierObservationEvent` | First-class barrier observation (breach and non-breach) | [equity_options.md §CDM Extensions](smart_contracts/equity_options.md#cdm-extensions) |
| Equity options | `ClosedStateEnum.BarrierKnockOut` | Distinguishes KO termination from `Lapsed` / `Exercised` | [equity_options.md §CDM Extensions](smart_contracts/equity_options.md#cdm-extensions) |
| Equity options | `BarrierKnockIn` | KI breach state event | [events.md](events.md) |
| Structured products | `StructuredProductCreationPrimitive` | Wraps three simultaneous `ExecutionPrimitive`s | [events.md](events.md) |
| Structured products | `BarrierPropagationEvent` | Option → note barrier-breach propagation | [events.md](events.md) |
| Structured products | `NotePhysicalRedemptionEvent` | Physical share redemption at maturity | [events.md](events.md) |
| Funding | `MtMLinkedLoan` (product type) | Loan whose notional resets to externally-computed portfolio MtM | [funding.md §CDM Extension Points](smart_contracts/funding.md#cdm-extension-points) |
| Funding | `MtMResetEvent` | Compound `Reset` + `QuantityChangePrimitive` + `Transfer` | [funding.md §CDM Extension Points](smart_contracts/funding.md#cdm-extension-points) |
| Funding | `InternalFundingRate` (observable) | Proprietary Treasury rate, not a published index | [funding.md §CDM Extension Points](smart_contracts/funding.md#cdm-extension-points) |
| Funding | `IFRUpdateEvent` | Discretionary rate change on an existing loan | [funding.md §CDM Extension Points](smart_contracts/funding.md#cdm-extension-points) |
| SBL | `MarkToMarketCollateralCall` | GMSLA collateral margin call / return | [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md) |
| SBL | `RecallEvent` | Lender-initiated recall | [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md) |
| SBL | `ManufacturedPaymentEvent` | Income on loaned stock | [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md) |
| SBL | `CollateralSubstitutionEvent` | Atomic DvD collateral swap | [stock_borrow_loan.md](smart_contracts/stock_borrow_loan.md) |
| QIS | `ReturnStreamConstituent` | `BasketConstituent` with a monetary (not unit-count) quantity | [qis.md §CDM Extension Points](smart_contracts/qis.md#cdm-extension-points) |
| QIS | `BasketUnderlier.portfolio → SimulatedWalletId` | Links composite unit to its simulated wallet | [qis.md §CDM Extension Points](smart_contracts/qis.md#cdm-extension-points) |
| QIS | `Rebalancing` (qualification) | Distinguishes a strategy rebalance from other quantity changes | [qis.md §CDM Extension Points](smart_contracts/qis.md#cdm-extension-points) |
| QIS | `IndexDivisor` (field on `PortfolioState`) | Index-continuity divisor | [qis.md §CDM Extension Points](smart_contracts/qis.md#cdm-extension-points) |
| FX | CLS bilateral netting event | Cancel-gross / create-net as a lifecycle event | [fx.md](smart_contracts/fx.md) |

These extensions should be reviewed against future CDM releases as coverage advances (the ISLA CDM Working Group is actively developing GMSLA coverage; see [events.md §SBL CDM Coverage](events.md#2-sbl-cdm-coverage--partial)).

---

## 5. Open Items

The following are not yet resolved and remain on the profile backlog:

- **Unspecified corporate-action types.** `Delisting`, `StockNameChange`, `StockIdentifierChange`, `BonusIssue`, `ClassAction`, `EarlyRedemption`, `Liquidation`, `BankruptcyOrInsolvency`, `IssuerNationalization`, `Relisting`, and `BespokeEvent` are enumerated in [equities.md](smart_contracts/equities.md) but not yet given full lifecycle treatment.
- **Rights instrument smart contract.** The rights unit's own exercise lifecycle is referenced but documented separately (see [equities.md §Rights Issue](smart_contracts/equities.md#rights-issue-rhts)).
- **Provenance schema.** Invariant 13 establishes that provenance distinguishes events; the concrete schema (which fields, carried per-move or per-transaction) is not yet pinned down.
