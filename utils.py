import os
import json
import requests
import logging
import random
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from openai import OpenAI

# Setup logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# TPay configuration
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
TLEDGER_BASE_URL = os.getenv("TLEDGER_BASE_URL")

# Game-specific utilities
GAME_TOKEN_SYMBOL = "AMN"  # Default game token
GAME_INITIAL_BALANCE = 1500.0   # Default starting balance 

def admin_create_asset_account(
    agent_id: str,
    asset: str = GAME_TOKEN_SYMBOL,
    balance: float = GAME_INITIAL_BALANCE,
    network: str = "solana",
    wallet_address: str = "",
    private_key: str = "",
    account_metadata: str = "{}"
) -> Optional[Dict[str, Any]]:
    """
    Admin endpoint to force create or update an asset account for an agent
    
    Args:
        admin_key: Admin secret key for authentication
        agent_id: ID of the agent to create asset account for
        asset: Asset type (e.g., USDC, XRP, SOL)
        balance: Initial balance to set
        network: Network (e.g., solana, xrpl)
        wallet_address: Wallet address (optional)
        private_key: Private key (optional)
        account_metadata: JSON metadata for the account
        
    Returns:
        Dictionary containing asset account response, or None if creation fails
    """
    logger.info(f"Creating asset account for agent {agent_id}")
    
    url = f"{TLEDGER_BASE_URL}/admin/agents/{agent_id}/asset-accounts"
    headers = {
        "X-Admin-Key": ADMIN_SECRET_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "asset": asset,
        "balance": balance,
        "network": network,
        "wallet_address": wallet_address,
        "private_key": private_key,
        "account_metadata": account_metadata
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        account_data = response.json()
        return account_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Asset account creation failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Error details: {error_detail}")
            except:
                print(f"Error status code: {e.response.status_code}")
                print(f"Error text: {e.response.text}")
        return None

def reset_agent_game_balance(agent_id: str, 
                           game_token: str = GAME_TOKEN_SYMBOL,
                           new_balance: float = GAME_INITIAL_BALANCE) -> bool:
    """
    Reset a specific agent's game token balance
    
    Args:
        agent_id: TPay agent ID
        game_token: Game token symbol
        new_balance: New balance to set
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # new_balance = int(new_balance * 10 ** 6)
        result = admin_create_asset_account(
            agent_id=agent_id,
            asset=game_token,
            balance=new_balance,
            network="solana",
            account_metadata='{"decimals": 6}'
        )
        
        return result is not None
        
    except Exception as e:
        print(f"[Utils] Error resetting balance for agent {agent_id}: {e}")
        return False

async def _wait_for_payment_completion(payment_result: dict, timeout_seconds: int = 60) -> bool:
    """
    Wait for a TPay payment to complete.
    
    Args:
        payment_result: The payment result from create_payment
        timeout_seconds: Maximum time to wait for completion
        
    Returns:
        bool: True if payment completed successfully, False otherwise
    """
    if not payment_result or not payment_result.get('id'):
        print(f"[Utils] No payment ID to wait for")
        return False
        
    payment_id = payment_result['id']
    print(f"[Utils] Waiting for payment {payment_id} to complete...")
    
    import time
    import asyncio
    import tpay
    
    # Create TPay agent instance for status checking
    tpay_agent = tpay.agent.AsyncTPayAgent()
    
    start_time = time.time()
    poll_interval = 2.0  # poll every 2 seconds
    last_status = "unknown"
    
    while time.time() - start_time < timeout_seconds:
        try:
            # async query payment status
            status_result = await tpay_agent.get_payment_status(payment_id)
            
            if status_result and 'status' in status_result:
                status = status_result['status']
                if status != last_status:
                    print(f"[Utils] Payment {payment_id} status changed: {last_status} -> {status}")
                    last_status = status
                
                if status in ['success', 'completed']:
                    print(f"[Utils] ✅ Payment {payment_id} completed successfully (status: {status})")
                    return True
                elif status in ['failed', 'rejected', 'cancelled']:
                    print(f"[Utils] ❌ Payment {payment_id} failed (status: {status})")
                    return False
                elif status in ['pending', 'processing', 'initiated', 'created', 'submitted', 'approved', 'pending_confirmation']:
                    # async wait - approved means approved for blockchain submission, still in progress
                    # pending_confirmation means waiting for blockchain confirmation
                    await asyncio.sleep(poll_interval)
                    continue
                else:
                    print(f"[Utils] ❓ Unknown payment status: {status}")
                    print(f"[Utils] 🔍 Please check if '{status}' should be treated as success, failure, or in-progress")
                    return False
            else:
                print(f"[Utils] ⚠️ Failed to get payment status for {payment_id}")
                await asyncio.sleep(poll_interval)
                
        except Exception as e:
            print(f"[Utils] 💥 Error checking payment status: {e}")
            await asyncio.sleep(poll_interval)
    
    print(f"[Utils] ⏰ Payment {payment_id} TIMED OUT after {timeout_seconds}s. Last status: {last_status}")
    print(f"[Utils] 🚨 CRITICAL: Payment may have succeeded but status check failed. Manual verification needed.")
    return False

async def balance_agent_game_balance_via_payments(agent_id: str, 
                                                treasury_agent_id: str,
                                                target_balance: float = GAME_INITIAL_BALANCE,
                                                game_token: str = GAME_TOKEN_SYMBOL,
                                                game_uid: str = "unknown",
                                                agent_name: str = "Unknown Agent") -> dict:
    """
    Balance an agent's game token balance to target amount via real TPay payments
    
    Args:
        agent_id: TPay agent ID of the player
        treasury_agent_id: TPay agent ID of the treasury
        target_balance: Target balance to achieve (default 1500)
        game_token: Game token symbol
        game_uid: Game unique identifier
        agent_name: Human-readable agent name
        
    Returns:
        Dict with status, action taken, amounts, and details
    """
    try:
        import tpay
        import datetime
        
        # Query current balance
        current_balance = tpay.get_agent_asset_balance(
            agent_id=agent_id, 
            network="solana", 
            asset=game_token
        )
        
        if current_balance is None:
            return {
                "success": False,
                "error": f"Failed to query balance for agent {agent_id}",
                "agent_id": agent_id,
                "agent_name": agent_name
            }
        
        balance_difference = current_balance - target_balance
        
        # Create TPay agent instance
        tpay_agent = tpay.agent.AsyncTPayAgent()
        
        if abs(balance_difference) < 0.01:  # Already balanced (within 1 cent)
            return {
                "success": True,
                "action": "no_action_needed",
                "current_balance": current_balance,
                "target_balance": target_balance,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "message": f"{agent_name} already has correct balance ({current_balance})"
            }
        
        elif balance_difference > 0:  # Agent has excess, needs to pay treasury
            amount_to_pay = balance_difference
            
            # Build comprehensive trace context for excess payment
            trace_context = {
                "payment_type": "game_initialization_excess_balance",
                "game_context": {
                    "game_uid": game_uid,
                    "initialization_phase": "pre_game_balance_adjustment",
                    "target_balance": target_balance,
                    "current_balance": current_balance,
                    "balance_difference": balance_difference,
                    "action_required": "excess_payment_to_treasury"
                },
                "agent_context": {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "role": "player_agent",
                    "balance_status": "excess"
                },
                "treasury_context": {
                    "treasury_agent_id": treasury_agent_id,
                    "role": "system_treasury",
                    "purpose": "collect_excess_player_balance"
                },
                "transaction": {
                    "reason": "game_initialization_balance_adjustment",
                    "description": f"Player {agent_name} paying excess balance to treasury before game start",
                    "amount": float(amount_to_pay),
                    "currency": game_token,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "network": "solana"
                },
                "regulatory_context": {
                    "transaction_type": "balance_normalization",
                    "compliance_note": "Pre-game balance adjustment to ensure fair gameplay",
                    "audit_trail": f"Agent {agent_id} had {current_balance} {game_token}, required {target_balance}",
                    "business_logic": "All players must start with equal balance of 1500 AMN tokens"
                },
                "operational_metadata": {
                    "system_component": "game_initialization",
                    "process_step": "balance_equalization",
                    "automated": True,
                    "requires_approval": False
                }
            }
            
            # Execute payment from agent to treasury
            payment_result = await tpay_agent.create_payment(
                agent_id=agent_id,
                receiving_agent_id=treasury_agent_id,
                amount=amount_to_pay,
                currency=game_token,
                settlement_network="solana",
                func_stack_hashes=tpay.tools.get_current_stack_function_hashes(),
                debug_mode=False,
                trace_context=trace_context
            )
            
            if payment_result:
                # 🚨 CRITICAL FIX: Wait for payment completion
                payment_success = await _wait_for_payment_completion(payment_result)
                
                if payment_success:
                    return {
                        "success": True,
                        "action": "excess_paid_to_treasury",
                        "amount_paid": amount_to_pay,
                        "from_balance": current_balance,
                        "to_balance": target_balance,
                        "payment_id": payment_result.get('id'),
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": f"{agent_name} paid {amount_to_pay} excess to treasury"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Payment from {agent_name} to treasury failed to complete",
                        "amount_attempted": amount_to_pay,
                        "payment_id": payment_result.get('id'),
                        "agent_id": agent_id,
                        "agent_name": agent_name
                    }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create payment from {agent_name} to treasury",
                    "amount_attempted": amount_to_pay,
                    "agent_id": agent_id,
                    "agent_name": agent_name
                }
                
        else:  # Agent has deficit, treasury needs to pay agent
            amount_to_receive = -balance_difference
            
            # Build comprehensive trace context for deficit payment
            trace_context = {
                "payment_type": "game_initialization_deficit_balance",
                "game_context": {
                    "game_uid": game_uid,
                    "initialization_phase": "pre_game_balance_adjustment",
                    "target_balance": target_balance,
                    "current_balance": current_balance,
                    "balance_difference": balance_difference,
                    "action_required": "deficit_payment_from_treasury"
                },
                "agent_context": {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "role": "player_agent",
                    "balance_status": "deficit"
                },
                "treasury_context": {
                    "treasury_agent_id": treasury_agent_id,
                    "role": "system_treasury",
                    "purpose": "provide_deficit_player_balance"
                },
                "transaction": {
                    "reason": "game_initialization_balance_adjustment",
                    "description": f"Treasury providing deficit balance to player {agent_name} before game start",
                    "amount": float(amount_to_receive),
                    "currency": game_token,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "network": "solana"
                },
                "regulatory_context": {
                    "transaction_type": "balance_normalization",
                    "compliance_note": "Pre-game balance adjustment to ensure fair gameplay",
                    "audit_trail": f"Agent {agent_id} had {current_balance} {game_token}, required {target_balance}",
                    "business_logic": "All players must start with equal balance of 1500 AMN tokens"
                },
                "operational_metadata": {
                    "system_component": "game_initialization",
                    "process_step": "balance_equalization",
                    "automated": True,
                    "requires_approval": False
                }
            }
            
            # Execute payment from treasury to agent
            payment_result = await tpay_agent.create_payment(
                agent_id=treasury_agent_id,
                receiving_agent_id=agent_id,
                amount=amount_to_receive,
                currency=game_token,
                settlement_network="solana",
                func_stack_hashes=tpay.tools.get_current_stack_function_hashes(),
                debug_mode=False,
                trace_context=trace_context
            )
            
            if payment_result:
                # 🚨 CRITICAL FIX: Wait for payment completion
                payment_success = await _wait_for_payment_completion(payment_result)
                
                if payment_success:
                    return {
                        "success": True,
                        "action": "deficit_paid_by_treasury",
                        "amount_received": amount_to_receive,
                        "from_balance": current_balance,
                        "to_balance": target_balance,
                        "payment_id": payment_result.get('id'),
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": f"Treasury paid {amount_to_receive} deficit to {agent_name}"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Payment from treasury to {agent_name} failed to complete",
                        "amount_attempted": amount_to_receive,
                        "payment_id": payment_result.get('id'),
                        "agent_id": agent_id,
                        "agent_name": agent_name
                    }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create payment from treasury to {agent_name}",
                    "amount_attempted": amount_to_receive,
                    "agent_id": agent_id,
                    "agent_name": agent_name
                }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Exception during balance adjustment for agent {agent_id}: {str(e)}",
            "agent_id": agent_id,
            "agent_name": agent_name
        }

def generate_random_agents(count: int = 4) -> List[Dict[str, str]]:
    """
    Generate random agent data using GPT-4o mini
    
    Args:
        count: Number of agents to generate, defaults to 4
        
    Returns:
        List containing agent information, each agent has name and personality fields
    """
    try:
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            logger.error("OPENAI_API_KEY not found in environment variables")
            return _get_fallback_agents(count)
        
        client = OpenAI(api_key=openai_api_key)
        
        # Build prompt for GPT
        prompt = f"""Generate {count} AI player characters for a Monopoly game. Each character should have a unique name and personality description.

Requirements:
1. Names should be fun and memorable
2. Personality descriptions should be 50-80 words in English, reflecting their strategy style in Monopoly
3. Ensure each character has different game strategies and personality traits
4. Personalities can include: aggressive, conservative, negotiator, risk-taker, analyst, opportunist, etc.

Return in JSON format as follows:
[
  {{"name": "Character Name", "personality": "English personality description"}},
  {{"name": "Character Name", "personality": "English personality description"}}
]

Please ensure the returned JSON format is correct and can be parsed directly."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a creative assistant specialized in creating interesting game characters. Generate JSON-formatted character data according to user requirements."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,  # Increase creativity
            max_tokens=1000
        )
        
        # Parse response
        content = response.choices[0].message.content.strip()
        
        # Try to extract JSON (if wrapped in code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        agents_data = json.loads(content)
        
        # Validate data format
        if not isinstance(agents_data, list):
            raise ValueError("Response is not a list")
        
        validated_agents = []
        for agent in agents_data:
            if isinstance(agent, dict) and "name" in agent and "personality" in agent:
                validated_agents.append({
                    "name": str(agent["name"]).strip(),
                    "personality": str(agent["personality"]).strip()
                })
        
        if len(validated_agents) >= count:
            return validated_agents[:count]
        else:
            logger.warning(f"Generated only {len(validated_agents)} agents, expected {count}")
            # If not enough agents generated, supplement with fallback data
            fallback_agents = _get_fallback_agents(count - len(validated_agents))
            return validated_agents + fallback_agents
            
    except Exception as e:
        logger.error(f"Error generating random agents with OpenAI: {e}")
        return _get_fallback_agents(count)

def _get_fallback_agents(count: int) -> List[Dict[str, str]]:
    """
    Fallback agent generator when OpenAI API is not available
    
    Args:
        count: Number of agents to generate
        
    Returns:
        List of fallback agent data
    """
    # Fallback name pool
    names = [
        "Market Maverick", "Fortune Hunter", "Deal Wizard", "Risk Taker Ruby", 
        "Strategy Sam", "Lucky Lucy", "Profit Pete", "Shrewd Sarah",
        "Monopoly Mike", "Clever Clara", "Bold Bobby", "Wise William",
        "Cunning Cathy", "Daring Dave", "Smart Steve", "Tactical Tina",
        "Business Baron", "Property Pirate", "Real Estate Rex", "Investment Ivy",
        "Cash Collector", "Asset Annie", "Revenue Rob", "Dividend Dan"
    ]
    
    # Fallback personality pool
    personalities = [
        "Aggressive property collector who believes in monopolizing entire color groups",
        "Conservative investor who prefers safe, steady income from railroads and utilities",
        "Master negotiator who can talk their way out of any difficult situation",
        "High-risk gambler who makes bold moves and big bets on expensive properties",
        "Analytical strategist who calculates probabilities before every decision",
        "Opportunistic trader who swoops in on distressed properties and bankruptcies",
        "Social player who builds alliances and makes mutually beneficial deals",
        "Minimalist player who focuses only on essential properties and cash flow",
        "Ruthless capitalist who shows no mercy in bankrupting opponents",
        "Adaptive player who changes strategy based on the current game state",
        "Patient investor who waits for the perfect moment to strike big",
        "Charismatic leader who influences other players' decisions through persuasion"
    ]
    
    # Randomly select and combine
    selected_agents = []
    used_names = set()
    used_personalities = set()
    
    for i in range(count):
        # Select unused names
        available_names = [name for name in names if name not in used_names]
        if not available_names:
            available_names = names  # If exhausted, restart
            used_names.clear()
        
        name = random.choice(available_names)
        used_names.add(name)
        
        # Select unused personalities
        available_personalities = [p for p in personalities if p not in used_personalities]
        if not available_personalities:
            available_personalities = personalities  # If exhausted, restart
            used_personalities.clear()
        
        personality = random.choice(available_personalities)
        used_personalities.add(personality)
        
        selected_agents.append({
            "name": name,
            "personality": personality
        })
    
    return selected_agents

def create_game_token_accounts_for_agents(
    agent_tpay_ids: List[str],
    game_token: str = GAME_TOKEN_SYMBOL,
    initial_balance: float = GAME_INITIAL_BALANCE,
    network: str = "solana"
) -> Dict[str, Any]:
    """
    Create game token accounts for multiple agents
    
    Args:
        agent_tpay_ids: List of agent tpay IDs
        game_token: Game token symbol
        initial_balance: Initial balance
        network: Network type
        
    Returns:
        Dictionary containing success and failure results
    """
    results = {
        "success": [],
        "failed": [],
        "total_processed": len(agent_tpay_ids)
    }
    
    for agent_id in agent_tpay_ids:
        try:
            success = reset_agent_game_balance(
                agent_id=agent_id,
                game_token=game_token,
                new_balance=initial_balance
            )
            
            if success:
                results["success"].append(agent_id)
                logger.info(f"Successfully created {game_token} account for agent {agent_id}")
            else:
                results["failed"].append({"agent_id": agent_id, "error": "Reset balance failed"})
                logger.error(f"Failed to create {game_token} account for agent {agent_id}")
                
        except Exception as e:
            results["failed"].append({"agent_id": agent_id, "error": str(e)})
            logger.error(f"Error creating {game_token} account for agent {agent_id}: {e}")
    
    return results
    
    