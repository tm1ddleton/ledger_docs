# Futures Smart Contract

## Overview

A futures contract is a standardised, exchange-traded agreement to buy or sell an underlying asset at a specified price on a future delivery date. Unlike OTC derivatives, futures are centrally cleared through a Central Counterparty (CCP): the CCP novates to become the counterparty to all positions and guarantees settlement.

The defining feature of futures is **daily mark-to-market settlement**: rather than accruing unrealised P&L, the CCP crystallises daily gains and losses as actual cash transfers (variation margin, VM). The smart contract maintains a running **cost basis** per position; daily VM is the difference between the position's value at today's settlement price and its current cost basis. The cost basis is reset to `settlement price × position size` at each EOD, so the same arithmetic applies uniformly to new intraday trades and to running positions carried from prior days — there is no need to track per-trade reference prices once an EOD has passed.

Initial margin is out of scope (see [invariants.md](../invariants.md)).

---

## Instrument Scope

| Instrument              | Underlying                              | Settlement at Expiry                 |
|-------------------------|-----------------------------------------|--------------------------------------|
| Equity index futures    | Stock index (e.g. S&P 500, EURO STOXX)  | Cash settlement                      |
| Single-stock futures    | Individual equity                       | Physical or cash (contract-specific) |
| Interest rate futures   | Government bond or rate index           | Physical or cash (contract-specific) |
| FX futures              | Currency pair                           | Physical delivery                    |

Commodity futures with physical delivery are out of scope. Physical delivery for the instruments listed above may also be out of scope for v1; cash settlement is the primary path.

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

## State

The futures smart contract is stateless. Each invocation receives Product state, Unit state, and Position state per the global [State Model](../invariants.md#state-model).

### Product State

| Field            | Description                                                                       |
|------------------|-----------------------------------------------------------------------------------|
| `expiry`         | Contract expiry date (the final settlement date)                                  |
| `settlementType` | `Cash` or `Physical` (physical may be out of scope; see Instrument Scope)         |
| `underlying`     | Reference asset (index, single equity, bond, currency pair, etc.)                 |
| `multiplier`     | Contract size / point value (notional per unit per point of underlying)           |
| `ccp`            | Central counterparty (e.g. CME, Eurex, ICE)                                       |

### Unit State

| State      | Meaning                                                                                                            |
|------------|--------------------------------------------------------------------------------------------------------------------|
| `Active`   | Trading open; daily settlement ongoing                                                                              |
| `Matured`  | Contract expiry reached; final settlement transaction created but not yet fully settled                             |
| `Expired`  | All final settlement obligations discharged; futures units extinguished and (for cash settlement) final VM paid     |

`Active → Matured` on contract expiry. `Matured → Expired` once all moves in the final settlement transaction reach `Settled`. CDM `closedState` is set at `Expired`.

### Position State

In addition to the global bucketed counters (per [State Model](../invariants.md#state-model)), the futures position state for each `(unit, wallet, counterparty wallet)` tuple carries one extra scalar:

| Field        | Description                                                                                              |
|--------------|----------------------------------------------------------------------------------------------------------|
| `costBasis`  | Running scalar: signed sum of `price × multiplier × quantity` for the current position, reset daily at EOD |

Cost basis evolves under two events:

- **On trade execution** at price `p`, signed quantity `q` (positive long, negative short):
  ```
  costBasis += p × multiplier × q
  N         += q
  ```
- **On EOD daily settlement** at price `S`:
  ```
  VM         = S × multiplier × N − costBasis      // the daily P&L cash flow
  costBasis  = S × multiplier × N                  // reset
  ```

This single mechanic subsumes the previous distinction between "new trades referenced to trade price" and "running positions referenced to prior settlement price". After each EOD reset, cost basis equals `multiplier × N × today's settlement price`, so the next day's VM calculation needs no knowledge of how today's position was assembled.

### Data Requirements

| Input                                       | Cadence                  | Source     |
|---------------------------------------------|--------------------------|------------|
| Daily settlement price                      | Each business day at EOD | Exchange   |
| Exchange Delivery Settlement Price (EDSP)   | At expiry                | Exchange   |

---

## VM Granularity and Settlement Netting

The daily settlement cycle must simultaneously satisfy two requirements that operate at different levels of granularity.

**Position-level P&L**: VM must be computed at the level of each (Futures Desk Book, futures contract) combination. This is the basis on which daily P&L is attributed to individual books and traders. Without this granularity, desk-level risk and return cannot be derived from the ledger.

**Single exchange payment**: The CCP faces the Exchange-Facing Book only. It calculates a single net VM amount per contract against the EFB's net position and calls or pays that as one cash flow. There is no mechanism for the CCP to direct VM to individual desk books.

The ledger satisfies both requirements through a **two-tier VM structure** created atomically within each `DailySettlementEvent`:

| Tier | Move                    | Granularity                  | Initial State | Settlement Path           |
|------|-------------------------|------------------------------|---------------|---------------------------|
| 1    | Futures Desk Book ↔ EFB | Per (desk book, contract)    | `Settled`     | Internal entry; immediate |
| 2    | EFB ↔ CCP               | Single net per contract      | `Expected`    | External payment lifecycle |

The EFB is flat on VM: the sum of all Tier 1 allocation moves across all desk books equals the Tier 2 external move in the opposite direction, satisfying the double-entry invariant. The EFB's net cash position from VM is zero after both tiers complete.

**Key design implication**: VM calculation granularity and VM settlement granularity are decoupled. If they were collapsed into a single move per desk book directly to the CCP, this would either require the CCP to be aware of internal desk allocation (which it is not) or would lose position-level P&L visibility. The two-tier structure is the minimum required to preserve both.

---

## Lifecycle Events

### 1. Trade Execution

**Trigger**: Futures order filled on the exchange. Execution notification delivered to the smart contract.

The smart contract creates a transaction recording the futures unit position. For a long trade the units move from the CCP to the desk; for a short trade the direction is reversed.

| Move                 | From                         | To                           | Asset                                                   | State     |
|----------------------|------------------------------|------------------------------|---------------------------------------------------------|-----------|
| Long trade: units    | Exchange / CCP (virtual)     | Futures Desk Book (real)     | N futures units (contract, expiry month, trade reference) | `Settled` |
| Short trade: units   | Futures Desk Book (real)     | Exchange / CCP (virtual)     | N futures units (contract, expiry month, trade reference) | `Settled` |

Futures unit moves are recorded as `Settled` immediately — the position is live from execution. The position state is updated:

```
costBasis += trade_price × multiplier × q
N         += q                                  // q signed by direction
```

Multiple trades in the same contract on the same day each contribute their own price × quantity to the running `costBasis`; the smart contract no longer needs to track them individually. No premium or upfront cash payment is created at execution. All P&L exposure is carried through daily VM.

### 2. Daily Settlement

**Trigger**: Exchange publishes the official settlement price `S` at EOD.

For each `(desk book, contract, CCP)` position with current `costBasis` and signed quantity `N`, the smart contract:

1. Computes the daily VM:
   ```
   VM = S × multiplier × N − costBasis
   ```
2. Creates VM moves in two tiers (see [VM Granularity and Settlement Netting](#vm-granularity-and-settlement-netting)):

   **Tier 1 — Internal VM allocation** (one move per desk book, per contract):

   | Move                            | From                 | To                   | Asset                      | Initial State |
   |---------------------------------|----------------------|----------------------|----------------------------|---------------|
   | Allocation (desk book receives) | Exchange-Facing Book | Futures Desk Book    | Cash (settlement currency) | `Settled`     |
   | Allocation (desk book pays)     | Futures Desk Book    | Exchange-Facing Book | Cash (settlement currency) | `Settled`     |

   One direction applies per desk book, sized to that desk's `VM`. Internal moves settle immediately as accounting entries.

   **Tier 2 — External settlement** (one move for the contract at EFB level):

   | Move                            | From                 | To                   | Asset                      | Initial State |
   |---------------------------------|----------------------|----------------------|----------------------------|---------------|
   | VM settlement (EFB receives)    | CCP (virtual)        | Exchange-Facing Book | Cash (settlement currency) | `Expected`    |
   | VM settlement (EFB pays)        | Exchange-Facing Book | CCP (virtual)        | Cash (settlement currency) | `Expected`    |

   The Tier 2 amount equals the sum of all Tier 1 allocations across all desk books for the contract. One direction applies.

3. Resets `costBasis ← S × multiplier × N` for each desk book's position.

The Tier 2 external VM move follows the standard payment state flow:
```
Expected → Pending → Instructed → Settled
```

This single mechanic handles trade-date EOD, every subsequent business day, and any mix of new trades and running positions: the cost basis carries all the information needed.

### 3. Position Close / Partial Close

**Trigger**: Desk executes an offsetting trade in the same futures contract.

A closing trade is processed identically to any other trade: it adjusts `N` and `costBasis` per Trade Execution. At the next EOD, the Daily Settlement mechanic produces VM = `S × multiplier × N − costBasis`, which automatically incorporates the realised P&L on the closed leg.

If `N` reaches zero and remains zero through EOD:
- The EOD reset leaves `costBasis = S × multiplier × 0 = 0`.
- The position is flat. Unit state remains `Active` until contract expiry; the desk simply has no exposure.

If `N` is non-zero after a partial close, the remaining position carries a `costBasis` that reflects today's settlement price after the next EOD reset.

### 4. Expiry — Cash Settlement

**Trigger**: Contract expiry. The exchange publishes the EDSP (Exchange Delivery Settlement Price). No further trading is permitted.

The final VM is calculated against the carried position using the EDSP as the closing settlement price:

```
Final VM = EDSP × multiplier × N − costBasis
```

The futures units are extinguished and the final VM move is created:

| Move                       | From                     | To                           | Asset                      | Initial State |
|----------------------------|--------------------------|------------------------------|----------------------------|---------------|
| Futures extinguishment     | Futures Desk Book        | Exchange / CCP (virtual)     | N futures units            | `Pending`     |
| Final VM (desk receives)   | Exchange / CCP (virtual) | Futures Desk Book            | Cash (settlement currency) | `Expected`    |
| Final VM (desk pays)       | Futures Desk Book        | Exchange / CCP (virtual)     | Cash (settlement currency) | `Expected`    |

Unit state: `Active → Matured` when the final settlement transaction is created. `Matured → Expired` once all moves — extinguishment and final VM — have reached `Settled`.

### 5. Expiry — Physical Delivery

For physically deliverable futures (e.g. single-stock futures, bond futures), expiry triggers delivery of the underlying rather than a cash-only final settlement. This path may be out of scope for v1.

At expiry:

- The futures unit is extinguished as in the cash settlement path.
- Additional delivery moves are created representing the exchange of the underlying and the delivery price cash payment, following the settlement model of the applicable underlying smart contract (see [equities.md](equities.md), [bonds.md](bonds.md)).
- Final VM on the last trading day is calculated and settled as in the cash settlement path.

Unit state follows the same `Active → Matured → Expired` path: `Matured` when the final settlement transaction (including delivery moves) is created; `Expired` when all moves have settled.

---

## QRL Schedule Generation

QRL generates the following for futures contracts:

| QRL Output              | Description                                                                                                       |
|-------------------------|-------------------------------------------------------------------------------------------------------------------|
| Contract expiry date    | The final settlement date; the date on which the EDSP is applied and positions are extinguished                    |
| Last trading date       | For contracts where the last trading day precedes the final settlement date (e.g. most interest rate futures)      |
| Settlement price basis  | The method by which the EDSP is determined (e.g. special opening quotation, closing auction)                       |
| EOD settlement calendar | The exchange business day calendar governing which days generate VM calculations and settlement price observations |

QRL outputs are consumed at execution and stored as part of the trade record. Changes to scheduled dates constitute an amendment per [invariant 7](../invariants.md#core-ledger-invariants).

---

## CDM Event Representation

| Lifecycle Event                             | CDM Business Event Qualification             | CDM Transfer State              | Notes                                                                                  |
|---------------------------------------------|----------------------------------------------|---------------------------------|----------------------------------------------------------------------------------------|
| Trade execution (long)                      | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move CCP → Desk; updates `costBasis` and `N`                              |
| Trade execution (short)                     | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Futures unit move Desk → CCP; updates `costBasis` and `N`                              |
| EOD settlement — Tier 1 internal allocation | CDM extension: `DailySettlementEvent`        | `TransferStatusEnum.Settled`    | Internal VM move per desk book (Desk ↔ EFB); settles immediately; position-level P&L recorded; `costBasis` reset |
| EOD settlement — Tier 2 external VM         | CDM extension: `DailySettlementEvent`        | `TransferStatusEnum.Expected`   | Net VM move at EFB level (EFB ↔ CCP); single amount per contract; equals sum of Tier 1 allocations |
| VM payment instructed                       | — (state transition only)                    | `TransferStatusEnum.Instructed` | Tier 2 external move only; standard payment lifecycle                                  |
| VM payment confirmed                        | — (state transition only)                    | `TransferStatusEnum.Settled`    | Tier 2 external move settles                                                           |
| Position close — offsetting trade           | `EventQualificationEnum.Execution`           | `TransferStatusEnum.Settled`    | Offsetting trade; processed by the same Trade Execution mechanic                       |
| Expiry — final settlement created           | `EventQualificationEnum.ContractTermination` | `TransferStatusEnum.Pending`    | Extinguishment + final VM moves; unit state: `Active → Matured`                        |
| Expiry — fully settled                      | — (state transition only)                    | `TransferStatusEnum.Settled`    | All final moves settled; unit state: `Matured → Expired`; CDM `closedState` set        |

---

## CDM Extensions

CDM covers exchange-traded futures via `FuturesPayout` within a `TradeState`. However, CDM has no native representation of the EOD daily-settlement cycle as a first-class lifecycle event, nor of the running cost basis that drives it. The following extension is required.

### Extension: `DailySettlementEvent`

CDM's `EventQualificationEnum` has no entry for the futures EOD settlement cycle. This extension represents the daily P&L crystallisation event.

```
DailySettlementEvent:
  contractReference       -- exchange, instrument, and expiry month identifying the futures contract
  settlementDate          -- business day to which the settlement price applies
  settlementPrice         -- official settlement price published by the exchange (or EDSP at expiry)

  -- Tier 1: internal allocation (one entry per desk book holding positions in this contract)
  internalAllocations[]:
    deskBook              -- the desk book being allocated
    priorCostBasis        -- the desk book's costBasis prior to this event
    quantity              -- the desk book's signed position size N
    vm                    -- S × multiplier × N − priorCostBasis
    newCostBasis          -- S × multiplier × N (the post-event reset value)
    allocationMove        -- the Settled internal cash move (Desk Book ↔ EFB)

  -- Tier 2: external settlement (single move at EFB level)
  externalVmMove          -- net of all internalAllocations[].vm; the Expected cash move (EFB ↔ CCP)
```

The `DailySettlementEvent` records the daily VM crystallisation, the cost-basis reset, and the two-tier cash structure. It is triggered by the exchange's publication of the official settlement price (or the EDSP on the expiry event).
