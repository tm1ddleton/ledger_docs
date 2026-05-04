## Summary

- This repository is purely for the building of a document tree in markdown that describes the business logic for a ledger to record and lifecycle the products an hedges traded by a structured products business in an investment bank.
- You are a business analyst responsible for taking high level business requirements and converting them into markdown documents that describe the lifecycle events that will affect each product  
- The goal is to track as closely as possible to the common domain model (https://github.com/finos/common-domain-model), but it is accepted that this may not be adequate to describe all the business and lifecycle events that may happen.
- The project borrows language from blockchain but does not use a blockchain

## Definitions

- Wallet: a collection of asset holdings that belong to a particular party.  In the conventional sense, all books are wallets but not all wallets are books.
- Move: the transfer of one asset from one wallet to another
- Ledger: the sequence of immutable, ordered moves that together represent the current state, and is an input for other systems (e.g. risk, valuation, operations ...)
- Transaction: a set of moves that must be executed simultaneously to be valid (and thus are transactions in both financial and database senses)
- Smart Contract: an encoded set of rules that represent the a legal agreement between parties (e.g. the term sheet for an OTC exotic option)
- Trade: a transaction that is generated externally to the smart contract (e.g. by a trade on an exchange)
- Real wallet: represents a real set of holdings that are held by an entity internal to the business (e.g. a trader's front book)
- Virtual wallet: represents a set of holdings of an external entity that face the structured products business (e.g. a CSD)
- Simulated wallet: represents simulated holdings (e.g. an index)
- Unit: the representation of a given asset.  These can also be compound, based on other wallets (e.g. a total return swap could be written on a wallet in a simulated wallet that represents the constituents of an index).

## Repo structure

docs/ => all the documents in this repo
docs/invariants.md => invariants that are true for all smart contracts
docs/events.md => a list of events, their representation in CDM, and the a cross reference of the smart contracts that they apply to
docs/smart_contracts/ => a document per smart contract that describes the lifecycle events that apply to each smart contract
docs/smart_contracts/equities.md => cash equities
docs/smart_contracts/futures.md => futures
docs/smart_contracts/funding.md => funding
docs/smart_contracts/equity_options.md => options
docs/smart_contracts/bonds.md => bonds
docs/smart_contracts/fx.md => FX (spot, forward, swap, NDF)
docs/smart_contracts/irs.md => interest rate swaps
docs/smart_contracts/structured_products.md => structured products
docs/smart_contracts/qis.md => quantitative investment strategies
docs/smart_contracts/cash_payments.md => standalone cash payments
docs/smart_contracts/stock_borrow_loan.md => stock borrow / loan (SBL)

## DO

- Use whitespace to make sure that all table columns have a fixed width and the pipes align
