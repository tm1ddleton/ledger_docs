# Futures Smart Contract

## Overview

A futures contract is a standardised, exchange-traded agreement to buy or sell an underlying asset at a specified price on a future delivery date. Unlike OTC derivatives, futures are centrally cleared through a Central Counterparty (CCP): the CCP novates to become the counterparty to all positions and guarantees settlement.

The defining feature of futures is **daily mark-to-market settlement**: rather than accruing unrealised P&L, the CCP crystallises daily gains and losses as actual cash transfers (variation margin, VM). This crystallisation is captured in the ledger model through the **Position cost basis** (see [state.md](../state.md)): a scalar per (Futures Desk Book, futures Unit, CCP) that equals `Σ (price × quantity × multiplier)` across all trades contributing to the position. At EOD, VM is the difference between today's mark and the cost basis, and the cost basis is then reset to today's settlement mark. The next day's VM therefore measures only the day-on-day change in settlement price.

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

## State Model

Futures state follows the framework defined in [state.md](../state.md): Unit state (Product + liveness) is global to the contract; Position state is per (wallet, unit, counterparty).

### Unit State

The Product of a futures Unit is the contract specification published by the exchange: underlying, contract size / multiplier, expiry date, last trading date, settlement convention (cash or physical), and final-settlement-price methodology. The Product is set at contract listing and is immutable through the Unit's life.

Unit liveness uses the canonical three-state model:

| Liveness  | Meaning                                                                                                                       |
|-----------|-------------------------------------------------------------------------------------------------------------------------------|
| `Active`  | Contract is live; trading is permitted; daily settlement is ongoing.                                                          |
| `Matured` | Contract expiry reached; the final settlement transaction has been created but not all moves have reached `Settled`.          |
| `Expired` | All final settlement moves are `Settled`; the Unit is closed. CDM `closedState` is set at this point.                         |

`Active → Matured` on contract expiry when the final settlement transaction is created. `Matured → Expired` once all moves in that transaction have reached `Settled` (see [equity_options.md](equity_options.md) CDM Extension 3 for the general `Matured` state pattern).

### Position State

A futures Position is keyed by (Futures Desk Book, futures Unit, CCP). It carries two scalars and no bucket vector:

| Element            | Value                                                                                                                                                                                  |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `quantity`         | Net number of futures units held. Signed: long positive, short negative.                                                                                                               |
| `totalCostBasis`   | `Σ (price_i × quantity_i × multiplier)` over all trades contributing to the current position. Reset every EOD to `settlement_price × quantity × multiplier` once VM has been computed. |

The settlement-cycle bucket vector defined in [state.md](../state.md) is degenerate for futures: every futures unit move is written `Settled` at execution per the [Exchange Trade Booking Model](../invariants.md#exchange-trade-booking-model). All quantity sits in `SettledPrior` from the moment of execution. The economic exposure is captured entirely by the cost basis and the running settlement-price reference.

The Position state evolves through three drivers:

1. **Trade execution**: a new trade adds `(n_i, trade_price_i × n_i × multiplier)` to `(quantity, totalCostBasis)`. The trade may be in either direction; signs are preserved.
2. **EOD settlement**: `Daily VM = settlement_price × quantity × multiplier − totalCostBasis` is computed and paid; `totalCostBasis` is reset to `settlement_price × quantity × multiplier`.
3. **Expiry**: the final settlement price is treated as the EOD price on the last trading day; the final VM is computed and paid, the units are extinguished, and (for physical contracts) delivery moves are created.

This single mechanism subsumes the trade-date and post-trade-date VM cases under one formula. There is no separate per-move state distinguishing newly executed trades from carried positions; the running cost basis carries everything required to compute the next VM.

---

## Daily Settlement Mechanics

The CCP calculates and calls VM at EOD each business day based on the official settlement price published by the exchange. The VM formula is uniform across trade-day and subsequent-day positions:

```
Daily VM = (Settlement_D × quantity × multiplier) − totalCostBasis
```

After VM is paid:

```
totalCostBasis ← Settlement_D × quantity × multiplier
```

For a position carried from the prior day with no new trades, `totalCostBasis` was set yesterday to `Settlement_{D−1} × quantity × multiplier`, so the formula reduces to the familiar `(Settlement_D − Settlement_{D−1}) × quantity × multiplier`. For a position established by new trades during the day, `totalCostBasis` equals `Σ (trade_price_i × n_i × multiplier)`, so the formula reduces to `Σ (Settlement_D − trade_price_i) × n_i × multiplier`. The mixed-day case (a carried position plus new trades) is handled by the same formula without special casing — the cost basis additions accumulate during the day and the single EOD computation yields the correct VM.

---

## VM Granularity and Settlement Netting

The daily settlement cycle must simultaneously satisfy two requirements that operate at different levels of granularity.

**Position-level P&L**: VM must be computed at the level of each (Futures Desk Book, futures Unit) Position so that daily P&L can be attributed to individual books and traders. Without this granularity, desk-level risk and return cannot be derived from the ledger.

**Single exchange payment**: The CCP faces the Exchange-Facing Book only. It calculates a single net VM amount per contract against the EFB's net position and calls or pays that as one cash flow. There is no mechanism for the CCP to direct VM to individual desk books.

The ledger satisfies both requirements through a **two-tier VM structure** created atomically within each `DailySettlementEvent`:

| Tier | Move                    | Granularity                   | Initial State | Settlement Path            |
|------|-------------------------|-------------------------------|---------------|----------------------------|
| 1    | Futures Desk Book ↔ EFB | Per (desk book, futures Unit) | `Settled`     | Internal entry; immediate  |
| 2    | EFB ↔ CCP               | Single net per futures Unit   | `Expected`    | External payment lifecycle |

The EFB is flat on VM: the sum of all Tier 1 allocation moves across all desk books equals the Tier 2 external move in the opposite direction, satisfying the double-entry invariant. The EFB's net cash position from VM is zero after both tiers complete.

**Key design implication**: VM calculation granularity and VM settlement granularity are decoupled. If they were collapsed into a single move per desk book directly to the CCP, this would either require the CCP to be aware of internal desk allocation (which it is not) or would lose position-level P&L visibility. The two-tier structure is the minimum required to preserve both.

---

## Lifecycle Events

### 1. Trade Execution

**Trigger**: Futures order filled on the exchange. Execution notification delivered to the smart contract.

The smart contract creates a transaction recording the futures unit move. For a long trade the units move from the CCP to the desk; for a short trade the direction is reversed.

| Move                 | From                         | To                           | Asset                                                            | State     |
|----------------------|------------------------------|------------------------------|------------------------------------------------------------------|-----------|
| Long trade: units    | Exchange / CCP (virtual)     | Futures Desk Book (real)     | N futures units (contract, expiry month, trade price, trade ref) | `Settled` |
| Short trade: units   | Futures Desk Book (real)     | Exchange / CCP (virtual)     | N futures units (contract, expiry month, trade price, trade ref) | `Settled` |

Futures unit moves are recorded as `Settled` immediately — the position is live from execution. The Position state is updated:

```
quantity        ← quantity + n         (signed; long positive, short negative)
totalCostBasis  ← totalCostBasis + trade_price × n × multiplier
```

Multiple trades in the same Unit on the same day each contribute their own `(n_i, trade_price_i × n_i × multiplier)` term. The Position requires no per-trade state record beyond what is already recorded on the ledger move itself.

No premium or upfront cash payment is created at execution. All P&L exposure is carried through the daily VM cycle.

### 2. EOD Settlement

**Trigger**: Exchange publishes the official settlement price at EOD.

For each (Futures Desk Book, futures Unit) Position with non-zero quantity or non-zero cost basis, the smart contract:

1. Computes Daily VM:
   ```
   Daily VM = Settlement_D × quantity × multiplier − totalCostBasis
   ```
2. Creates the two-tier VM moves (see [VM Granularity and Settlement Netting](#vm-granularity-and-settlement-netting)).

   **Tier 1 — Internal VM allocation** (one move per desk book, per futures Unit):

   | Move                            | From                 | To                   | Asset                      | Initial State |
   |---------------------------------|----------------------|----------------------|----------------------------|---------------|
   | Allocation (desk book receives) | Exchange-Facing Book | Futures Desk Book    | Cash (settlement currency) | `Settled`     |
   | Allocation (desk book pays)     | Futures Desk Book    | Exchange-Facing Book | Cash (settlement currency) | `Settled`     |

   Each desk book's allocation equals the Daily VM for its Position in the Unit. One direction applies per desk book. Internal moves settle immediately as accounting entries.

   **Tier 2 — External settlement** (one move per futures Unit at EFB level):

   | Move                            | From                 | To                   | Asset                      | Initial State |
   |---------------------------------|----------------------|----------------------|----------------------------|---------------|
   | VM settlement (EFB receives)    | CCP (virtual)        | Exchange-Facing Book | Cash (settlement currency) | `Expected`    |
   | VM settlement (EFB pays)        | Exchange-Facing Book | CCP (virtual)        | Cash (settlement currency) | `Expected`    |

   The Tier 2 amount equals the sum of all Tier 1 allocations across all desk books for the Unit. One direction applies.

3. Resets the cost basis on each affected Position:
   ```
   totalCostBasis ← Settlement_D × quantity × multiplier
   ```

The Tier 2 external VM move follows the standard payment state flow:
```
Expected → Pending → Instructed → Settled
```

After this event, every Position in the Unit is marked at `Settlement_D` and ready for the next day's cycle. Whether the Position contains trades executed today, a position carried from yesterday, or a mixture of both is immaterial — the single formula and the cost-basis reset handle all cases.

### 3. Position Close / Partial Close

**Trigger**: Desk executes an offsetting trade in the same futures Unit.

A closing trade is a new trade in the opposite direction. The smart contract creates the offsetting futures unit move at `Settled` and updates the Position per [Trade Execution](#1-trade-execution): `quantity` moves toward zero, `totalCostBasis` is reduced by `closing_price × n_close × multiplier` (signs preserved).

At EOD the standard mechanism applies: a single Daily VM is computed against the updated cost basis and the cost basis is reset.

If the position reaches `quantity = 0` after a full close and the position is closed before expiry, the Unit's liveness state is unaffected for other holders — the desk simply has zero exposure to the Unit. The cost basis at EOD will be `0` once the close trade is included (mark of zero quantity is zero) and the Daily VM will reflect the realised P&L.

If the position is non-zero after a partial close, the remaining position continues with the updated `(quantity, totalCostBasis)`.

### 4. Expiry — Cash Settlement

**Trigger**: Contract expiry. The exchange publishes the final settlement price (e.g. special opening quotation for equity index futures). No further trading is permitted.

The final VM is computed against the Position using the final settlement price as today's mark:

```
Final VM = Final Settlement Price × quantity × multiplier − totalCostBasis
```

The futures units are extinguished and the final VM move is created:

| Move                       | From                     | To                           | Asset                      | Initial State |
|----------------------------|--------------------------|------------------------------|----------------------------|---------------|
| Futures extinguishment     | Futures Desk Book        | Exchange / CCP (virtual)     | N futures units            | `Pending`     |
| Final VM (desk receives)   | Exchange / CCP (virtual) | Futures Desk Book            | Cash (settlement currency) | `Expected`    |
| Final VM (desk pays)       | Futures Desk Book        | Exchange / CCP (virtual)     | Cash (settlement currency) | `Expected`    |

After extinguishment, `quantity = 0` and `totalCostBasis = 0` on the Position.

Unit liveness: `Active → Matured` when the final settlement transaction is created. `Matured → Expired` once all moves — extinguishment and final VM — have reached `Settled`.

### 5. Expiry — Physical Delivery

For physically deliverable futures (e.g. single-stock futures, bond futures), expiry triggers delivery of the underlying rather than a cash-only final settlement.

At expiry:

- The futures unit is extinguished as in the cash settlement path.
- Additional delivery moves are created representing the exchange of the underlying and the delivery price cash payment, following the settlement model of the applicable underlying smart contract (see [equities.md](equities.md), [bonds.md](bonds.md)). These delivery moves run through the standard settlement-bucket cycle defined in [state.md](../state.md).
- Final VM on the last trading day is computed and settled as in the cash settlement path.

Unit liveness follows the same `Active → Matured → Expired` path: `Matured` when the final settlement transaction (including delivery moves) is created; `Expired` when all moves have settled.

---

## QRL Schedule Generation

QRL generates the following for futures contracts:

| QRL Output              | Description                                                                                                       |
|-------------------------|-------------------------------------------------------------------------------------------------------------------|
| Contract expiry date    | The final settlement date; the date on which the final settlement price is applied and positions are extinguished |
| Last trading date       | For contracts where the last trading day precedes the final settlement date (e.g. most interest rate futures)     |
| Settlement price basis  | The method by which the final settlement price is determined (e.g. special opening quotation, closing auction)    |
| EOD settlement calendar | The exchange business day calendar governing which days generate VM calculations and settlement price observations |

QRL outputs are consumed at execution and stored as part of the trade record. Changes to scheduled dates constitute an amendment per [invariant 7](../invariants.md#core-ledger-invariants).

---

## CDM Event Representation

| Lifecycle Event                             | CDM Business Event Qualification             | CDM Transfer State              | Notes                                                                               |
|---------------------------------------------|----------------------------------------------|---------------------------------|-------------------------------------------------------------------------------------|
| Trade execution (long)                      | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move CCP → Desk; Position `(quantity, totalCostBasis)` updated         |
| Trade execution (short)                     | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move Desk → CCP; Position `(quantity, totalCostBasis)` updated         |
| EOD settlement — Tier 1 internal allocation | CDM extension: `DailySettlementEvent`        | `TransferStatusEnum.Settled`    | Internal VM move per desk book (Desk ↔ EFB); position-level P&L recorded            |
| EOD settlement — Tier 2 external VM         | CDM extension: `DailySettlementEvent`        | `TransferStatusEnum.Expected`   | Net VM move at EFB level (EFB ↔ CCP); equals sum of Tier 1 allocations              |
| EOD settlement — cost basis reset           | CDM extension: `DailySettlementEvent`        | — (Position state update)       | `totalCostBasis ← Settlement_D × quantity × multiplier` on every affected Position  |
| VM payment instructed                       | — (state transition only)                    | `TransferStatusEnum.Instructed` | Tier 2 external move only; standard payment lifecycle                               |
| VM payment confirmed                        | — (state transition only)                    | `TransferStatusEnum.Settled`    | Tier 2 external move settles                                                        |
| Position close — offsetting trade           | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Offsetting futures unit move; Position updated as a normal trade                    |
| Expiry — final settlement created           | `EventQualificationEnum.ContractTermination` | `TransferStatusEnum.Pending`    | Extinguishment + final VM moves; Unit liveness: `Active → Matured`                  |
| Expiry — fully settled                      | — (state transition only)                    | `TransferStatusEnum.Settled`    | All final moves settled; Unit liveness: `Matured → Expired`; CDM `closedState` set  |

---

## CDM Extensions

CDM covers exchange-traded futures via `FuturesPayout` within a `TradeState`. However, CDM has no native representation of the Position cost-basis state or the EOD settlement cycle as a first-class lifecycle event. The following extensions are required.

### Extension 1: `FuturesPositionState`

CDM has no concept of a Position-level cost basis. This extension carries the per-(desk book, futures Unit, CCP) Position state used to drive VM calculation.

```
FuturesPositionState:
  deskBook            -- the Futures Desk Book (real wallet)
  futuresUnit         -- the futures Unit (contract, expiry month)
  counterparty        -- the CCP (fixed for cleared futures)
  quantity            -- signed net number of futures units held
  totalCostBasis      -- Σ (price × quantity × multiplier) over contributing trades
```

The Position state is derived from the ledger: `quantity` from the net of all `Settled` futures unit moves into and out of the desk book for the Unit; `totalCostBasis` from the prices recorded on those moves combined with the EOD reset events. The extension provides an explicit representation of this derived state for consumption by VM calculation logic.

### Extension 2: `DailySettlementEvent`

CDM's `EventQualificationEnum` has no entry for the futures EOD settlement cycle. This extension represents the daily P&L crystallisation event that drives the central state transition of this model.

```
DailySettlementEvent:
  contractReference       -- exchange, instrument, and expiry month identifying the futures Unit
  settlementDate          -- business day to which the settlement price applies
  settlementPrice         -- official settlement price published by the exchange

  -- Tier 1: internal allocation (one entry per desk book holding Positions in this Unit)
  internalAllocations[]:
    deskBook              -- the desk book being allocated
    priorCostBasis        -- totalCostBasis on the Position immediately before this event
    quantity              -- signed net quantity on the Position
    dailyVm               -- settlementPrice × quantity × multiplier − priorCostBasis
    allocationMove        -- the Settled internal cash move (Desk Book ↔ EFB)
    resetCostBasis        -- settlementPrice × quantity × multiplier (new totalCostBasis after reset)

  -- Tier 2: external settlement (single move at EFB level)
  externalVmMove          -- net of all dailyVm amounts; the Expected cash move (EFB ↔ CCP)
```

The `DailySettlementEvent` records both the VM cash structure and the cost-basis reset applied to each affected Position. It is triggered by the exchange's publication of the official settlement price.
