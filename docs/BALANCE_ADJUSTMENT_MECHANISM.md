# Game Balance Adjustment Mechanism

## Overview

The new game balance adjustment mechanism uses real TPay payments to ensure that each player starts the game with exactly **1500 AMN tokens**, replacing the previous forced balance reset method.

## How It Works

### 1. Balance Query

* The system queries each agent’s current AMN token balance.
* `tpay.get_agent_asset_balance()` is used to fetch real‑time balances.

### 2. Balance Decision

The system compares the current balance with the target balance (1500 AMN) and makes decisions:

#### Case A: Excess Balance

* **Condition:** current balance > 1500 AMN
* **Action:** agent pays the excess to the Treasury
* **Direction:** Player Agent → Treasury Agent

#### Case B: Deficit Balance

* **Condition:** current balance < 1500 AMN
* **Action:** Treasury pays the difference to the agent
* **Direction:** Treasury Agent → Player Agent

#### Case C: Correct Balance

* **Condition:** current balance ≈ 1500 AMN (tolerance < 0.01)
* **Action:** no adjustment needed

### 3. Payment Execution

* Uses real TPay payment system
* Includes detailed `trace_context` for auditing
* Settlement on the Solana blockchain
* **🚨 Important:** considered successful only after payment is confirmed

### Payment Completion Verification

Two‑phase verification ensures a payment truly completes:

1. **Payment Creation:** `tpay_agent.create_payment()`
2. **Completion Wait:** `_wait_for_payment_completion()` waits until done

```python
payment_result = await tpay_agent.create_payment(...)

if payment_result:
    payment_success = await _wait_for_payment_completion(payment_result)
    if payment_success:
        return {"success": True, ...}
    else:
        return {"success": False, "error": "Payment failed to complete", ...}
```

**Status polling:** every 2s, timeout after 60s.

* ✅ Success states: `success`, `completed`
* ❌ Fail states: `failed`, `rejected`, `cancelled`
* ⏳ In‑progress states: `pending`, `processing`, `initiated`, `created`, `submitted`, `approved`, `pending_confirmation`
* ❓ Unknown states: logged for review

**Flow:**

```
created/initiated → pending → processing → approved → submitted → pending_confirmation → success ✅
                                        ↘ failed/rejected ❌
```

`approved` means cleared for submission to Solana.
`pending_confirmation` means submitted and awaiting network confirmation.
Only `success` means truly completed.

## Technical Implementation

### Core Functions

#### `balance_agent_game_balance_via_payments()` (in `utils.py`)

```python
async def balance_agent_game_balance_via_payments(
    agent_id: str,
    treasury_agent_id: str,
    target_balance: float = 1500.0,
    game_token: str = "AMN",
    game_uid: str = "unknown",
    agent_name: str = "Unknown Agent"
) -> dict:
```

**Return:**

```json
{
  "success": true,
  "action": "excess_paid_to_treasury",
  "amount_paid/received": 250.0,
  "from_balance": 1750.0,
  "to_balance": 1500.0,
  "payment_id": "pay_xyz789",
  "agent_id": "agent_xxx",
  "agent_name": "Player Name",
  "message": "..."
}
```

#### `initialize_agent_tpay_balances()` (in `server.py`)

Calls the new adjustment logic with detailed logs.

## Trace Context Example

**Excess Payment**

```json
{
  "payment_type": "game_initialization_excess_balance",
  "game_context": {
    "game_uid": "game_xxx",
    "initialization_phase": "pre_game_balance_adjustment",
    "target_balance": 1500.0,
    "current_balance": 1750.0,
    "balance_difference": 250.0,
    "action_required": "excess_payment_to_treasury"
  },
  "agent_context": {
    "agent_id": "agent_xxx",
    "agent_name": "Player Name",
    "role": "player_agent",
    "balance_status": "excess"
  },
  "treasury_context": {
    "treasury_agent_id": "treasury_xxx",
    "role": "system_treasury",
    "purpose": "collect_excess_player_balance"
  },
  "transaction": {
    "reason": "game_initialization_balance_adjustment",
    "description": "Player X paying excess balance to treasury before game start",
    "amount": 250.0,
    "currency": "AMN",
    "timestamp": "2024-01-01T00:00:00",
    "network": "solana"
  },
  "regulatory_context": {
    "transaction_type": "balance_normalization",
    "compliance_note": "Pre-game balance adjustment to ensure fair gameplay",
    "audit_trail": "Agent had 1750.0 AMN, required 1500.0",
    "business_logic": "All players must start with equal balance of 1500 AMN tokens"
  },
  "operational_metadata": {
    "system_component": "game_initialization",
    "process_step": "balance_equalization",
    "automated": true,
    "requires_approval": false
  }
}
```

(Deficit payment uses a similar structure with adjusted fields.)

## Logging Output Example

```
[TPay] Balancing AMN accounts for 4 agents in game monopoly_game_123 via real payments
[TPay] Processing balance adjustment for Player1 (agent_abc123)
[Utils] Waiting for payment pay_xyz789 to complete...
[Utils] Payment pay_xyz789 status changed: unknown -> pending
[Utils] Payment pay_xyz789 status changed: pending -> processing
[Utils] Payment pay_xyz789 status changed: processing -> approved
[Utils] Payment pay_xyz789 status changed: approved -> submitted
[Utils] Payment pay_xyz789 status changed: submitted -> pending_confirmation
[Utils] Payment pay_xyz789 status changed: pending_confirmation -> success
[Utils] ✅ Payment pay_xyz789 completed successfully (status: success)
[TPay] ✓ Player1: Paid 250.00 excess to treasury (Payment ID: pay_xyz789) - COMPLETED
...
========== BALANCE ADJUSTMENT SUMMARY FOR GAME monopoly_game_123 ==========
✓ Successful adjustments: 2
≈ No action needed: 1
✗ Failed adjustments: 1
💰 Total excess collected by treasury: 250.00 AMN
💸 Total deficit provided by treasury: 100.00 AMN
🏦 Net treasury change: gained 150.00 AMN
================================================================
```

## API Endpoint

**Test Adjustment**

```
POST /api/admin/balance/test_adjustment
```

Returns detailed adjustment results.

## Configuration Requirements

* Env var: `TREASURY_AGENT_ID`
* TPay service running
* Solana network accessible
* Valid TPay accounts

## Error Handling

* Skips agents if balance query fails
* Logs payment creation failures
* Retries handled by TPay library
* Clear error messages for missing configs

## Audit & Compliance

* Every payment carries full `trace_context`
* Payments are on-chain and auditable
* Detailed logs retained

## Migration Notes

* Old `utils.reset_agent_game_balance()` replaced by `utils.balance_agent_game_balance_via_payments()`
* `initialize_agent_tpay_balances()` updated
* Old method kept for backward compatibility

## Performance

* Each agent requires 1–2 network calls
* Payments asynchronous, wait for confirmation
* Max wait per payment: 60s, polling every 2s
* Typical adjustment time for 4 agents: 30–240s if adjustments needed

## Security

* Uses TPay’s security
* Authenticated agents
* Treasury must hold sufficient funds
* Reasonable payment limits enforced

## Troubleshooting

* Missing `TREASURY_AGENT_ID`: set env var
* Agent has no TPay account: check creation
* Payment fails: check network and balance
* Timeout: check TPay status and Solana congestion
* `approved` ≠ success; wait until `success`
* Use `/api/admin/balance/test_adjustment` for debugging and view logs

---

**✅ This new mechanism ensures fair gameplay by equalizing all players’ starting balances through auditable, real on‑chain payments.**
