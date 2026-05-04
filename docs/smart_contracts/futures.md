# Futures Smart Contract

## Overview

A futures contract is a standardised, exchange-traded agreement to buy or sell an underlying asset at a specified price on a future delivery date. Unlike OTC derivatives, futures are centrally cleared through a Central Counterparty (CCP): the CCP novates to become the counterparty to all positions and guarantees settlement.

The defining feature of futures is **daily mark-to-market settlement**: rather than accruing unrealised P&L, the CCP crystallises daily gains and losses as actual cash transfers (variation margin, VM). This creates the primary modelling challenge: on trade date T, VM is calculated using each trade's individual trade price as the reference; from T+1 onwards, VM is calculated using the previous day's official settlement price. Positions in the pre-settlement state cannot be aggregated and must be tracked individually; positions that have passed through at least one EOD settlement cycle can be collapsed into a single net position at a single reference price.

This is the futures analogue of the `Pending`/`Settled` move distinction in the general ledger model: a trade that has not yet been through an EOD settlement cycle is like a `Pending` move that must be processed individually; once settled, it becomes part of the aggregated `Settled` position that is processed uniformly.

Initial margin is out of scope (see [invariants.md](../invariants.md)).

---

## Instrument Scope

| Instrument              | Underlying                              | Settlement at Expiry                 |
|-------------------------|-----------------------------------------|--------------------------------------|
| Equity index futures    | Stock index (e.g. S&P 500, EURO STOXX)  | Cash settlement                      |
| Single-stock futures    | Individual equity                       | Physical or cash (contract-specific) |
| Interest rate futures   | Government bond or rate index           | Physical or cash (contract-specific) |
| FX futures              | Currency pair                           | Physical delivery                    |

Commodity futures with physical delivery are out of scope.

---

## Parties and Wallets

Futures are exchange-traded and follow the exchange trade booking model (see [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model)).

| Party                | Wallet Type     | Description                                                                                                        |
|----------------------|-----------------|--------------------------------------------------------------------------------------------------------------------|
| Exchange / CCP       | Virtual wallet  | The CCP (e.g. CME, Eurex, ICE) acting as central counterparty to all positions post-clearing                       |
| Exchange-Facing Book | Real wallet     | Single book per legal entity per exchange; holds the cleared net position as seen by the CCP                       |
| Futures Desk Book    | Real wallet     | Individual desk or strategy book; holds allocated futures unit positions and associated VM cash flows              |
| Clearing Broker      | Virtual wallet  | Where the desk clears through a broker (FCM) rather than directly, the broker intermediates between EFB and CCP    |

For directly cleared members, the Exchange-Facing Book faces the CCP. For non-clearing members, the clearing broker's virtual wallet sits between the Exchange-Facing Book and the CCP. The economics are identical in both cases; only the settlement chain differs.

---

## Instrument State Model

Futures positions carry two independent layers of state.

### Contract Lifecycle State

| State         | Meaning                                                                                                                    |
|---------------|----------------------------------------------------------------------------------------------------------------------------|
| `Active`      | Position is live; daily settlement is ongoing; the desk holds a non-zero net futures unit balance                          |
| `Matured`     | Contract expiry date reached; final settlement transaction created but not yet fully settled                               |
| `Terminated`  | All obligations discharged; futures units extinguished, final VM settled, and (for physical contracts) delivery completed  |

`Active → Matured` on contract expiry when the final settlement transaction is created. `Matured → Terminated` when all moves in the final settlement transaction have reached `Settled`. CDM `closedState` is set only at `Terminated` (see [equity_options.md](equity_options.md) CDM Extension 3 for the general `Matured` state pattern).

### Daily Settlement State

This state governs VM calculation and position aggregation. It is independent of the contract lifecycle state and applies only while the contract lifecycle state is `Active`.

| State             | VM Reference Price        | Aggregation                                          |
|-------------------|---------------------------|------------------------------------------------------|
| `NewTrade`        | Individual trade price    | Must be tracked per trade; not aggregable            |
| `RunningPosition` | Last official settlement price | Fully aggregable into a single net position at the settlement price |

The transition `NewTrade → RunningPosition` occurs at the EOD settlement event on trade date T. After this transition, the original trade price is no longer referenced in daily VM calculations: the settlement price becomes the sole reference. All `RunningPosition` units in the same contract can be treated as a single net position at the settlement price.

---

## Daily Settlement Mechanics

The CCP calculates and calls VM at EOD each business day based on the official settlement price published by the exchange. The VM formula depends on the daily settlement state of the position:

| Position State    | VM Formula                                                                           |
|-------------------|--------------------------------------------------------------------------------------|
| `NewTrade`        | `VM = (Settlement_T − Trade_Price) × Contract_Size × N_contracts`                   |
| `RunningPosition` | `VM = (Settlement_D − Settlement_{D−1}) × Contract_Size × N_net`                    |

For a mixed day (new trades and a carried position co-exist), both calculations are performed independently and the results netted into a single VM cash move. After EOD:

- All `NewTrade` units transition to `RunningPosition`.
- All `RunningPosition` units in the same contract can be treated as a single net position at the day's settlement price.

This prevents trade-price information from propagating into subsequent days: once in `RunningPosition` state, all carried positions share a common reference and are treated uniformly.

---

## VM Granularity and Settlement Netting

The daily settlement cycle must simultaneously satisfy two requirements that operate at different levels of granularity.

**Position-level P&L**: VM must be computed at the level of each (Futures Desk Book, futures contract) combination, and within that at `NewTrade` vs. `RunningPosition` position granularity. This is the basis on which daily P&L is attributed to individual books and traders. Without this granularity, desk-level risk and return cannot be derived from the ledger.

**Single exchange payment**: The CCP faces the Exchange-Facing Book only. It calculates a single net VM amount per contract against the EFB's net position and calls or pays that as one cash flow. There is no mechanism for the CCP to direct VM to individual desk books.

The ledger satisfies both requirements through a **two-tier VM structure** created atomically within each `DailySettlementEvent`:

| Tier | Move                   | Granularity                                   | Initial State | Settlement Path           |
|------|------------------------|-----------------------------------------------|---------------|---------------------------|
| 1    | Futures Desk Book ↔ EFB | Per (desk book, contract, NewTrade/Running)  | `Settled`     | Internal entry; immediate |
| 2    | EFB ↔ CCP              | Single net per contract                       | `Expected`    | External payment lifecycle |

The EFB is flat on VM: the sum of all Tier 1 allocation moves across all desk books equals the Tier 2 external move in the opposite direction, satisfying the double-entry invariant. The EFB's net cash position from VM is zero after both tiers complete.

**Key design implication**: VM calculation granularity and VM settlement granularity are decoupled. If they were collapsed into a single move per desk book directly to the CCP, this would either require the CCP to be aware of internal desk allocation (which it is not) or would lose position-level P&L visibility. The two-tier structure is the minimum required to preserve both.

---

## Lifecycle Events

### 1. Trade Execution

**Trigger**: Futures order filled on the exchange. Execution notification delivered to the smart contract.

The smart contract creates a transaction recording the futures unit position. For a long trade the units move from the CCP to the desk; for a short trade the direction is reversed.

| Move                 | From                         | To                           | Asset                                                         | State     |
|----------------------|------------------------------|------------------------------|---------------------------------------------------------------|-----------|
| Long trade: units    | Exchange / CCP (virtual)     | Futures Desk Book (real)     | N futures units (contract, expiry month, trade price, trade reference) | `Settled` |
| Short trade: units   | Futures Desk Book (real)     | Exchange / CCP (virtual)     | N futures units (contract, expiry month, trade price, trade reference) | `Settled` |

Futures unit moves are recorded as `Settled` immediately — the position is live from execution. The daily settlement state of the newly created units is `NewTrade`: they carry their individual trade price and are not yet part of the settled position aggregate.

Multiple trades in the same contract on the same day each create separate futures unit moves with their own trade prices. They remain individually identified in `NewTrade` state until the EOD settlement cycle.

No premium or upfront cash payment is created at execution. All P&L exposure is carried through daily VM.

### 2. EOD Settlement — First Cycle (Trade Date T)

**Trigger**: Exchange publishes the official settlement price at EOD on trade date T.

For all futures unit moves in `NewTrade` state, the smart contract:

1. Calculates VM for each `NewTrade` position:
   ```
   VM_i = (Settlement_T − Trade_Price_i) × Contract_Size × N_i
   ```
2. Creates VM moves in two tiers (see [VM Granularity and Settlement Netting](#vm-granularity-and-settlement-netting)):

   **Tier 1 — Internal VM allocation** (one move per desk book, per contract):

   | Move                           | From                 | To                   | Asset                      | Initial State |
   |--------------------------------|----------------------|----------------------|----------------------------|---------------|
   | Allocation (desk book receives) | Exchange-Facing Book | Futures Desk Book    | Cash (settlement currency) | `Settled`     |
   | Allocation (desk book pays)    | Futures Desk Book    | Exchange-Facing Book | Cash (settlement currency) | `Settled`     |

   Each desk book's allocation is the net VM across all its `NewTrade` positions for the contract: `Σ (Settlement_T − Trade_Price_i) × Contract_Size × N_i`. One direction applies per desk book. Internal moves settle immediately as accounting entries.

   **Tier 2 — External settlement** (one move for the contract at EFB level):

   | Move                           | From                 | To                   | Asset                      | Initial State |
   |--------------------------------|----------------------|----------------------|----------------------------|---------------|
   | VM settlement (EFB receives)   | CCP (virtual)        | Exchange-Facing Book | Cash (settlement currency) | `Expected`    |
   | VM settlement (EFB pays)       | Exchange-Facing Book | CCP (virtual)        | Cash (settlement currency) | `Expected`    |

   The Tier 2 amount equals the sum of all Tier 1 allocations across all desk books. One direction applies.

3. Transitions all `NewTrade` units to `RunningPosition` state, with `Settlement_T` as the new reference price.
4. All `RunningPosition` units in the same contract can be treated as a single net position at reference price `Settlement_T`.

The Tier 2 external VM move follows the standard payment state flow:
```
Expected → Pending → Instructed → Settled
```

After this event, no `NewTrade` units remain for trade date T. Each desk book's position can be expressed as a net of `N_net` contracts at reference price `Settlement_T`.

### 3. Daily Variation Margin (T+1 Onwards)

**Trigger**: Exchange publishes the official settlement price at EOD on each subsequent business day.

For positions in `RunningPosition` state, VM is uniform across the entire net position:

```
VM = (Settlement_D − Settlement_{D−1}) × Contract_Size × N_net
```

**Tier 1 — Internal VM allocation** (one move per desk book):

| Move                           | From                 | To                   | Asset                      | Initial State |
|--------------------------------|----------------------|----------------------|----------------------------|---------------|
| Allocation (desk book receives) | Exchange-Facing Book | Futures Desk Book    | Cash (settlement currency) | `Settled`     |
| Allocation (desk book pays)    | Futures Desk Book    | Exchange-Facing Book | Cash (settlement currency) | `Settled`     |

**Tier 2 — External settlement** (one move at EFB level):

| Move                           | From                 | To                   | Asset                      | Initial State |
|--------------------------------|----------------------|----------------------|----------------------------|---------------|
| VM settlement (EFB receives)   | CCP (virtual)        | Exchange-Facing Book | Cash (settlement currency) | `Expected`    |
| VM settlement (EFB pays)       | Exchange-Facing Book | CCP (virtual)        | Cash (settlement currency) | `Expected`    |

The reference price is updated to `Settlement_D` after each daily settlement event. The cycle repeats each business day until the position is closed or the contract expires.

### 4. Mixed Day (New Trades and Running Position)

If the desk executes new trades on a day when it already holds a `RunningPosition`:

- **Existing position** (`RunningPosition`): VM referenced to `Settlement_{D−1}`.
- **New trades** (`NewTrade`): VM referenced to individual trade prices.

Both VM components are calculated independently per desk book. The two-tier VM structure applies as in section 2: one Tier 1 internal allocation per desk book (covering both components) and one Tier 2 external settlement at the EFB level. After EOD, new trades transition `NewTrade → RunningPosition` and the net position can be re-aggregated at today's settlement price.

### 5. Position Close / Partial Close

**Trigger**: Desk executes an offsetting trade in the same futures contract.

A closing trade is a new trade in the opposite direction. The smart contract creates the offsetting futures unit move in `NewTrade` state with its own closing trade price.

At EOD:

- The closing `NewTrade` units and the existing `RunningPosition` are processed together per section 4.
- VM is calculated on both components separately and netted.
- After EOD the net position can be treated as a single net position in `RunningPosition` state.

If the net position reaches zero after the closing trade settles through EOD:
- Contract lifecycle state: `Active → Matured` once the final VM move is created.
- `Matured → Terminated` once the final VM move reaches `Settled`.

If the net position is non-zero after a partial close, the remaining position continues in `RunningPosition` state.

### 6. Expiry — Cash Settlement

**Trigger**: Contract expiry. The exchange publishes the final settlement price (e.g. special opening quotation for equity index futures). No further trading is permitted.

The final VM is calculated against the carried `RunningPosition` using the final settlement price as the closing reference:

```
Final VM = (Final Settlement Price − Settlement_{last trading day}) × Contract_Size × N_net
```

The futures units are extinguished and the final VM move is created:

| Move                       | From                     | To                           | Asset                      | Initial State |
|----------------------------|--------------------------|------------------------------|----------------------------|---------------|
| Futures extinguishment     | Futures Desk Book        | Exchange / CCP (virtual)     | N futures units            | `Pending`     |
| Final VM (desk receives)   | Exchange / CCP (virtual) | Futures Desk Book            | Cash (settlement currency) | `Expected`    |
| Final VM (desk pays)       | Futures Desk Book        | Exchange / CCP (virtual)     | Cash (settlement currency) | `Expected`    |

Contract lifecycle state: `Active → Matured` when the final settlement transaction is created. `Matured → Terminated` once all moves — extinguishment and final VM — have reached `Settled`.

### 7. Expiry — Physical Delivery

For physically deliverable futures (e.g. single-stock futures, bond futures), expiry triggers delivery of the underlying rather than a cash-only final settlement.

At expiry:

- The futures unit is extinguished as in the cash settlement path.
- Additional delivery moves are created representing the exchange of the underlying and the delivery price cash payment, following the settlement model of the applicable underlying smart contract (see [equities.md](equities.md), [bonds.md](bonds.md)).
- Final VM on the last trading day is calculated and settled as in the cash settlement path.

Contract lifecycle state follows the same `Active → Matured → Terminated` path: `Matured` when the final settlement transaction (including delivery moves) is created; `Terminated` when all moves have settled.

---

## QRL Schedule Generation

QRL generates the following for futures contracts:

| QRL Output              | Description                                                                                                       |
|-------------------------|-------------------------------------------------------------------------------------------------------------------|
| Contract expiry date    | The final settlement date; the date on which the final settlement price is applied and positions are extinguished  |
| Last trading date       | For contracts where the last trading day precedes the final settlement date (e.g. most interest rate futures)      |
| Settlement price basis  | The method by which the final settlement price is determined (e.g. special opening quotation, closing auction)    |
| EOD settlement calendar | The exchange business day calendar governing which days generate VM calculations and settlement price observations |

QRL outputs are consumed at execution and stored as part of the trade record. Changes to scheduled dates constitute an amendment per [invariant 7](../invariants.md#core-ledger-invariants).

---

## CDM Event Representation

| Lifecycle Event                   | CDM Business Event Qualification             | CDM Transfer State              | Notes                                                                               |
|-----------------------------------|----------------------------------------------|---------------------------------|-------------------------------------------------------------------------------------|
| Trade execution (long)            | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move CCP → Desk; daily settlement state: `NewTrade`                    |
| Trade execution (short)           | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move Desk → CCP; daily settlement state: `NewTrade`                    |
| EOD settlement — Tier 1 internal allocation | CDM extension: `DailySettlementEvent` | `TransferStatusEnum.Settled`    | Internal VM move per desk book (Desk ↔ EFB); settles immediately; position-level P&L recorded; `NewTrade → RunningPosition` |
| EOD settlement — Tier 2 external VM         | CDM extension: `DailySettlementEvent` | `TransferStatusEnum.Expected`   | Net VM move at EFB level (EFB ↔ CCP); single amount per contract; equals sum of Tier 1 allocations |
| VM payment instructed             | — (state transition only)                    | `TransferStatusEnum.Instructed` | Tier 2 external move only; standard payment lifecycle                               |
| VM payment confirmed              | — (state transition only)                    | `TransferStatusEnum.Settled`    | Tier 2 external move settles                                                        |
| Position close — offsetting trade | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Offsetting futures unit move; `NewTrade` state until EOD; net collapses at EOD      |
| Expiry — final settlement created | `EventQualificationEnum.ContractTermination` | `TransferStatusEnum.Pending`    | Extinguishment + final VM moves; lifecycle state: `Active → Matured`                |
| Expiry — fully settled            | — (state transition only)                    | `TransferStatusEnum.Settled`    | All final moves settled; lifecycle state: `Matured → Terminated`; CDM `closedState` set |

---

## CDM Extensions

CDM covers exchange-traded futures via `FuturesPayout` within a `TradeState`. However, CDM has no native representation of the T vs. post-T settlement state distinction or the EOD settlement cycle as a first-class lifecycle event. The following extensions are required.

### Extension 1: `FuturesDailySettlementStateEnum`

CDM has no concept of whether a futures unit has been through its first EOD settlement cycle. This extension carries that state.

```
FuturesDailySettlementStateEnum:
  NewTrade          -- opened on the current settlement day; VM reference is trade price; not yet aggregable
  RunningPosition   -- through at least one EOD settlement cycle; VM reference is last settlement price; fully aggregable
```

Carried as a bespoke field on the `TradeState` of each futures position move. Transitions from `NewTrade` to `RunningPosition` atomically within the `DailySettlementEvent`.

### Extension 2: `DailySettlementEvent`

CDM's `EventQualificationEnum` has no entry for the futures EOD settlement cycle. This extension represents the daily P&L crystallisation event that drives the central state transition of this model.

```
DailySettlementEvent:
  contractReference       -- exchange, instrument, and expiry month identifying the futures contract
  settlementDate          -- business day to which the settlement price applies
  settlementPrice         -- official settlement price published by the exchange

  -- Tier 1: internal allocation (one entry per desk book holding positions in this contract)
  internalAllocations[]:
    deskBook              -- the desk book being allocated
    newTradeVm            -- VM on NewTrade positions for this desk book (reference: trade prices)
    runningPositionVm     -- VM on RunningPosition for this desk book (reference: prior settlement price)
    netAllocation         -- total VM attributed to this desk book (newTradeVm + runningPositionVm)
    allocationMove        -- the Settled internal cash move (Desk Book ↔ EFB)

  -- Tier 2: external settlement (single move at EFB level)
  externalVmMove          -- net of all netAllocation amounts; the Expected cash move (EFB ↔ CCP)

  referenceTransition     -- records the NewTrade → RunningPosition transition for all positions processed
  updatedReferencePrice   -- new reference price for subsequent daily VM calculations
```

The `DailySettlementEvent` records the daily settlement state transitions and the two-tier VM cash structure. It is triggered by the exchange's publication of the official settlement price.
