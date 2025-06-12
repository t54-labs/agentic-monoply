import os
import json
import requests
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

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
        new_balance = int(new_balance * 10 ** 6)
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
    
    