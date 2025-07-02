"""
Telegram Bot Command Handlers for Monopoly Game Server

This module contains all command handlers for the Telegram bot admin interface.
Separated from server.py for better code organization and maintainability.
"""

import asyncio
import datetime
import uuid
from typing import Dict, Any, List
from sqlalchemy import insert, update, select, func
from sqlalchemy.orm import Session

# Import necessary modules from the main application
import tpay
import utils
from database import engine, agents_table


async def telegram_end_game_command_handler(game_id: str) -> Dict[str, Any]:
    """Handle Telegram end game command"""
    from .telegram_notifier import get_telegram_notifier
    
    # Import here to avoid circular imports
    from server import game_instances, agent_manager
    
    try:
        print(f"[Telegram Command] Received end game command for: {game_id}")
        
        # Find the game instance
        game_instance = game_instances.get(game_id)
        if not game_instance:
            return {
                'success': False,
                'error': f'Game {game_id} not found or not active'
            }
        
        # Get game controller to access agents
        game_controller = game_instance.game_controller
        if not game_controller:
            return {
                'success': False,
                'error': f'Game {game_id} has no active controller'
            }
        
        # Get the agents for this game
        agents_in_game = []
        for agent_uid, g_uid in agent_manager.agents_in_game.items():
            if g_uid == game_id:
                agents_in_game.append(agent_uid)
        
        # Set game_over flag to end the game gracefully
        game_controller.game_over = True
        print(f"[Telegram Command] Set game_over flag for {game_id}")
        
        # Set all agents in this game to inactive
        agents_affected = 0
        try:
            with Session(engine) as session:
                for agent_uid in agents_in_game:
                    stmt = update(agents_table).where(
                        agents_table.c.agent_uid == agent_uid
                    ).values(
                        status='inactive',
                        last_active=func.now()
                    )
                    session.execute(stmt)
                    agents_affected += 1
                    print(f"[Telegram Command] Set agent {agent_uid} to inactive")
                
                session.commit()
                
        except Exception as db_error:
            print(f"[Telegram Command] Database error updating agents: {db_error}")
        
        # Send game termination notification
        try:
            telegram_notifier = get_telegram_notifier()
            if telegram_notifier and telegram_notifier.enabled:
                await telegram_notifier.send_message(
                    f"🛑 <b>Game manually terminated</b>\n\n"
                    f"🆔 Game ID: <code>{game_id}</code>\n"
                    f"🤖 Agents affected: {agents_affected}\n"
                    f"⏰ Time: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
                    f"✅ Game terminated by admin command"
                )
        except Exception as notify_error:
            print(f"[Telegram Command] Failed to send termination notification: {notify_error}")
        
        return {
            'success': True,
            'agents_affected': agents_affected,
            'message': f'Game {game_id} terminated successfully'
        }
        
    except Exception as e:
        print(f"[Telegram Command] Error ending game {game_id}: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def telegram_get_status_command_handler() -> Dict[str, Any]:
    """Handle Telegram status command"""
    # Import here to avoid circular imports
    from server import global_app_instance, get_game_status, agent_manager, CONCURRENT_GAMES_COUNT, AUTO_RESTART_GAMES
    
    try:
        if not global_app_instance:
            return {
                'active_games': 0,
                'total_thread_games': 0,
                'available_agents': 0,
                'error': 'App instance not available'
            }
        
        # Get current game status
        status = get_game_status(global_app_instance)
        
        # Get agent status
        agent_status = agent_manager.get_status()
        
        return {
            'active_games': status.get('active_games', 0),
            'total_thread_games': status.get('total_thread_games', 0),
            'available_agents': agent_status.get('available_agents_count', 0),
            'agents_in_game': agent_status.get('agents_in_game_count', 0),
            'concurrent_games_target': CONCURRENT_GAMES_COUNT,
            'auto_restart_enabled': AUTO_RESTART_GAMES
        }
        
    except Exception as e:
        print(f"[Telegram Command] Error getting status: {e}")
        return {
            'active_games': 0,
            'total_thread_games': 0,
            'available_agents': 0,
            'error': str(e)
        }


async def telegram_get_game_status_command_handler(game_id: str) -> Dict[str, Any]:
    """Handle Telegram get game status command"""
    # Import here to avoid circular imports
    from server import game_instances
    
    try:
        print(f"[Telegram Command] Received get game status command for: {game_id}")
        
        # Find the game instance
        game_instance = game_instances.get(game_id)
        if not game_instance:
            return {
                'success': False,
                'error': f'Game {game_id} not found or not active'
            }
        
        if not game_instance.is_running():
            return {
                'success': False,
                'error': f'Game {game_id} is not currently running'
            }
        
        # Get game controller
        game_controller = game_instance.game_controller
        if not game_controller:
            return {
                'success': False,
                'error': f'Game {game_id} has no active controller'
            }
        
        # Get detailed game information
        game_info = {
            'turn_count': game_controller.turn_count,
            'game_over': game_controller.game_over,
            'current_player_index': game_controller.current_player_index
        }
        
        # Get detailed player information
        players_info = []
        for i, player in enumerate(game_controller.players):
            player_info = {
                'name': player.name,
                'money': player.money,
                'position': player.position,
                'in_jail': player.in_jail,
                'is_bankrupt': player.is_bankrupt,
                'owned_properties': []
            }
            
            # Get owned properties with details
            for prop_id in player.properties_owned_ids:
                try:
                    prop = game_controller.board.squares[prop_id]
                    if hasattr(prop, 'name'):
                        prop_info = {
                            'id': prop_id,
                            'name': prop.name,
                            'color': getattr(prop, 'color', 'unknown'),
                            'rent': getattr(prop, 'rent', 0),
                            'is_mortgaged': getattr(prop, 'is_mortgaged', False),
                            'houses': getattr(prop, 'num_houses', 0),
                            'hotels': 1 if getattr(prop, 'num_houses', 0) == 5 else 0
                        }
                        player_info['owned_properties'].append(prop_info)
                except (IndexError, AttributeError):
                    continue
            
            players_info.append(player_info)
        
        return {
            'success': True,
            'data': {
                'game_info': game_info,
                'players': players_info
            }
        }
        
    except Exception as e:
        print(f"[Telegram Command] Error getting game status for {game_id}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }


async def telegram_create_random_agents_command_handler() -> Dict[str, Any]:
    """Handle Telegram create random agents command"""
    from .telegram_notifier import get_telegram_notifier
    
    # Import here to avoid circular imports
    from server import agent_manager
    
    try:
        print(f"[Telegram Command] Received create random agents command")
        
        agent_count = 4
        print(f"[Telegram Command] Generating {agent_count} random agents using GPT-4o mini...")
        
        # Use the same logic as the API endpoint
        random_agents = utils.generate_random_agents(agent_count)
        
        created_agents = []
        skipped_agents = []
        
        with Session(engine) as session:
            for agent_data in random_agents:
                # Check if agent with the same name already exists
                existing_agent_stmt = select(agents_table).where(agents_table.c.name == agent_data['name'])
                existing_agent = session.execute(existing_agent_stmt).fetchone()
                
                if existing_agent:
                    print(f"[Telegram Command] Skipping '{agent_data['name']}' - agent with this name already exists")
                    skipped_agents.append({
                        "name": agent_data['name'],
                        "reason": "Agent with this name already exists",
                        "existing_id": existing_agent.id,
                        "existing_status": existing_agent.status
                    })
                    continue
                
                agent_uid = f"agent_{agent_data['name'].lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
                
                # Create tpay account for this agent
                tpay_account_id = None
                try:
                    print(f"[Telegram Command] Creating TPay account for agent: {agent_data['name']}")
                    
                    tpay_agent_data = tpay.create_agent(
                        name=agent_data['name'],
                        description=f"Monopoly AI agent: {agent_data['personality']}",
                        agent_daily_limit=10000.0,  # High limit for monopoly transactions
                        agent_type="autonomous_agent"
                    )
                    
                    if tpay_agent_data and 'id' in tpay_agent_data:
                        tpay_account_id = tpay_agent_data['id']
                        print(f"[Telegram Command] Successfully created TPay account for {agent_data['name']} with ID: {tpay_account_id}")
                    else:
                        print(f"[Telegram Command] Failed to create TPay account for {agent_data['name']} - no ID returned")
                        
                except Exception as tpay_error:
                    print(f"[Telegram Command] Error creating TPay account for {agent_data['name']}: {tpay_error}")
                
                if tpay_account_id:
                    # Create agent record in database
                    agent_values = {
                        "agent_uid": agent_uid,
                        "name": agent_data['name'],
                        "personality_prompt": agent_data['personality'],
                        "memory_data": {},
                        "preferences": {},
                        "total_games_played": 0,
                        "total_wins": 0,
                        "tpay_account_id": tpay_account_id,
                        "status": "active"
                    }
                    
                    stmt = insert(agents_table).values(agent_values).returning(agents_table.c.id)
                    result = session.execute(stmt)
                    agent_id = result.scalar_one_or_none()
                    
                    if agent_id:
                        created_agents.append({
                            "id": agent_id,
                            "agent_uid": agent_uid,
                            "name": agent_data['name'],
                            "personality": agent_data['personality'][:50] + "..." if len(agent_data['personality']) > 50 else agent_data['personality'],
                            "tpay_account_id": tpay_account_id,
                            "tpay_status": "created" if tpay_account_id else "failed"
                        })
            
            session.commit()
        
        # Reload agents in agent manager
        await agent_manager.initialize_agents_from_database()
        
        successful_tpay = len([a for a in created_agents if a['tpay_account_id']])
        
        # Note: Telegram message sending is handled by the telegram_notifier's _handle_start_new_agents_command
        
        return {
            'success': True,
            'created_agents': created_agents,
            'skipped_agents': skipped_agents,
            'successful_tpay': successful_tpay,
            'message': f'Created {len(created_agents)} random agents ({successful_tpay} with TPay accounts), skipped {len(skipped_agents)} existing agents'
        }
        
    except Exception as e:
        print(f"[Telegram Command] Error creating random agents: {e}")
        
        # Note: Error notification is handled by the telegram_notifier's _handle_start_new_agents_command
        return {
            'success': False,
            'error': str(e)
        }


# Export all handlers for easy import
__all__ = [
    'telegram_end_game_command_handler',
    'telegram_get_status_command_handler', 
    'telegram_get_game_status_command_handler',
    'telegram_create_random_agents_command_handler'
] 