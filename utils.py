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
    
    