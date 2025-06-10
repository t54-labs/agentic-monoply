import asyncio
import json
import random  # Added for random turn delays
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any, Optional
import datetime
import os
import uuid
from contextlib import asynccontextmanager

import tpay
from tpay.tools import taudit_verifier

from game_logic.player import Player
from game_logic.game_controller import GameController 
from ai_agent.agent import OpenAIAgent
from main import TOOL_REGISTRY, NUM_PLAYERS, PLAYER_NAMES, MAX_TURNS, ACTION_DELAY_SECONDS, MAX_ACTIONS_PER_SEGMENT, execute_agent_action, print_game_summary, _setup_tool_placeholders
from colorama import init, Fore as ColoramaFore, Style as ColoramaStyle

# Import utils for tpay operations
import utils

# 2. Database and SQLAlchemy imports
from database import create_db_and_tables, engine, games_table, players_table, game_turns_table, agent_actions_table, agents_table
from sqlalchemy import insert, update, select, func
from sqlalchemy.orm import Session 

# Game simulation configuration
CONCURRENT_GAMES_COUNT = 1  # Number of games to run simultaneously
AUTO_RESTART_GAMES = True  # Whether to start new games when current ones finish
GAME_COUNTER = 0  # Global counter for unique game numbering
MAINTENANCE_INTERVAL = 30  # Seconds between game count maintenance checks

# Agent management configuration
AGENTS_PER_GAME = NUM_PLAYERS     # Number of agents per game (should match NUM_PLAYERS)
AGENT_INITIAL_BALANCE = 1500  # Starting balance for each game

# 1. Colorama setup & Global placeholders
class Fore: CYAN=YELLOW=GREEN=RED=MAGENTA=WHITE=BLACK=BLUE=""; LIGHTBLACK_EX=LIGHTBLUE_EX=LIGHTCYAN_EX=LIGHTGREEN_EX=LIGHTMAGENTA_EX=LIGHTRED_EX=LIGHTWHITE_EX=LIGHTYELLOW_EX=""
class Style: RESET_ALL=BRIGHT=DIM=NORMAL="";
COLORAMA_OK = False
try: 
    init()
    Fore = ColoramaFore; Style = ColoramaStyle; COLORAMA_OK = True
    if os.getenv("RUN_CONTEXT") != "test" and __name__ == "__main__": print(f"{Fore.GREEN}Colorama initialized.{Style.RESET_ALL}")
except ImportError: 
    if os.getenv("RUN_CONTEXT") != "test" and __name__ == "__main__": print("Colorama not found.")
    pass 

load_dotenv()

TLEDGER_API_KEY = os.getenv("TLEDGER_API_KEY")
TLEDGER_API_SECRET = os.getenv("TLEDGER_API_SECRET")
TLEDGER_PROJECT_ID = os.getenv("TLEDGER_PROJECT_ID")
TLEDGER_BASE_URL = os.getenv("TLEDGER_BASE_URL")

# 3. ConnectionManager class definition
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.lobby_connections: List[WebSocket] = [] # Added for lobby
    async def connect(self, websocket: WebSocket, game_id: str):
        await websocket.accept()
        if game_id not in self.active_connections: self.active_connections[game_id] = []
        self.active_connections[game_id].append(websocket)
        print(f"Client connected to G:{game_id}. Total: {len(self.active_connections[game_id])}")
    def disconnect(self, websocket: WebSocket, game_id: str):
        if game_id in self.active_connections and websocket in self.active_connections[game_id]:
            self.active_connections[game_id].remove(websocket)
            if not self.active_connections[game_id]: del self.active_connections[game_id]
        print(f"Client disconnected from G:{game_id}. Remaining: {len(self.active_connections.get(game_id, []))}")
    async def broadcast_to_game(self, game_id: str, message_data: Dict[str, Any]):
        if game_id in self.active_connections and self.active_connections[game_id]:
            message_str = json.dumps(message_data)
            results = await asyncio.gather(*[con.send_text(message_str) for con in self.active_connections[game_id]], return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, Exception): print(f"[WS Broadcast E for client {i} in G:{game_id}]: {res}")

    async def connect_to_lobby(self, websocket: WebSocket):
        await websocket.accept()
        self.lobby_connections.append(websocket)
        print(f"Client connected to Lobby. Total lobby connections: {len(self.lobby_connections)}")

    def disconnect_from_lobby(self, websocket: WebSocket):
        if websocket in self.lobby_connections:
            self.lobby_connections.remove(websocket)
        print(f"Client disconnected from Lobby. Remaining lobby connections: {len(self.lobby_connections)}")

    async def broadcast_to_lobby(self, message_data: Dict[str, Any]):
        if self.lobby_connections:
            message_str = json.dumps(message_data)
            # Create a list of tasks for sending messages to all lobby connections
            tasks = [conn.send_text(message_str) for conn in self.lobby_connections]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    # Attempt to identify the failing connection if possible (more complex, requires tracking connections)
                    # For now, generic error message.
                    print(f"[WS Lobby Broadcast Error for client {i}]: {res}")

# 4. Create instance of ConnectionManager
manager = ConnectionManager()

# 4.5. Agent Management System
class AgentManager:
    def __init__(self):
        self.available_agents: List[Dict[str, Any]] = []  # Available agents for matchmaking
        self.agents_in_game: Dict[str, str] = {}  # agent_uid -> game_uid mapping
        self.agent_instances: Dict[str, OpenAIAgent] = {}  # agent_uid -> OpenAIAgent instance
        
    async def initialize_agents_from_database(self):
        """Load all active agents from database and create their instances"""
        try:
            with Session(engine) as session:
                # Get all active agents from database
                stmt = select(agents_table).where(agents_table.c.status == 'active')
                result = session.execute(stmt)
                agents_data = result.fetchall()
                
                print(f"{Fore.GREEN}[Agent Manager] Found {len(agents_data)} active agents in database{Style.RESET_ALL}")
                
                for agent_row in agents_data:
                    agent_dict = {
                        'id': agent_row.id,
                        'agent_uid': agent_row.agent_uid,
                        'name': agent_row.name,
                        'personality_prompt': agent_row.personality_prompt,
                        'memory_data': agent_row.memory_data or {},
                        'preferences': agent_row.preferences or {},
                        'total_games_played': agent_row.total_games_played,
                        'total_wins': agent_row.total_wins,
                        'tpay_account_id': agent_row.tpay_account_id,
                        'status': agent_row.status
                    }
                    
                    # Create OpenAI agent instance
                    agent_instance = OpenAIAgent(
                        player_id=-1,  # Will be set when joining a game
                        name=agent_dict['name']
                    )
                    
                    # Store agent instance
                    self.agent_instances[agent_dict['agent_uid']] = agent_instance
                    
                    # Add to available agents if not in game
                    if agent_dict['status'] == 'active':
                        self.available_agents.append(agent_dict)
                
                print(f"{Fore.GREEN}[Agent Manager] Initialized {len(self.available_agents)} available agents{Style.RESET_ALL}")
                
        except Exception as e:
            print(f"{Fore.RED}[Agent Manager] Error initializing agents: {e}{Style.RESET_ALL}")
    
    def get_available_agents_for_game(self, num_needed: int) -> List[Dict[str, Any]]:
        """Get available agents for a new game"""
        if len(self.available_agents) < num_needed:
            print(f"{Fore.YELLOW}[Agent Manager] Not enough available agents. Need {num_needed}, have {len(self.available_agents)}{Style.RESET_ALL}")
            return []
        
        # Select agents (for now, just take first N available)
        selected_agents = self.available_agents[:num_needed]
        
        # Remove selected agents from available pool
        for agent in selected_agents:
            self.available_agents.remove(agent)
            # Mark as in_game in memory (will update DB when game starts)
            
        return selected_agents
    
    def assign_agents_to_game(self, agents: List[Dict[str, Any]], game_uid: str):
        """Assign agents to a specific game"""
        for agent in agents:
            self.agents_in_game[agent['agent_uid']] = game_uid
            # Update status in database
            self._update_agent_status(agent['agent_uid'], 'in_game')
    
    def release_agents_from_game(self, game_uid: str):
        """Release agents back to available pool when game ends"""
        agents_to_release = [agent_uid for agent_uid, g_uid in self.agents_in_game.items() if g_uid == game_uid]
        
        for agent_uid in agents_to_release:
            # Remove from in_game mapping
            del self.agents_in_game[agent_uid]
            
            # Find agent data and add back to available pool
            try:
                with Session(engine) as session:
                    stmt = select(agents_table).where(agents_table.c.agent_uid == agent_uid)
                    result = session.execute(stmt)
                    agent_row = result.fetchone()
                    
                    if agent_row:
                        agent_dict = {
                            'id': agent_row.id,
                            'agent_uid': agent_row.agent_uid,
                            'name': agent_row.name,
                            'personality_prompt': agent_row.personality_prompt,
                            'memory_data': agent_row.memory_data or {},
                            'preferences': agent_row.preferences or {},
                            'total_games_played': agent_row.total_games_played,
                            'total_wins': agent_row.total_wins,
                            'tpay_account_id': agent_row.tpay_account_id,
                            'status': 'active'
                        }
                        self.available_agents.append(agent_dict)
                        
                        # Update status in database
                        self._update_agent_status(agent_uid, 'active')
                        
                        print(f"{Fore.GREEN}[Agent Manager] Released agent {agent_dict['name']} back to available pool{Style.RESET_ALL}")
                        
            except Exception as e:
                print(f"{Fore.RED}[Agent Manager] Error releasing agent {agent_uid}: {e}{Style.RESET_ALL}")
    
    def _update_agent_status(self, agent_uid: str, status: str):
        """Update agent status in database"""
        try:
            with Session(engine) as session:
                stmt = update(agents_table).where(
                    agents_table.c.agent_uid == agent_uid
                ).values(
                    status=status,
                    last_active=func.now()
                )
                session.execute(stmt)
                session.commit()
        except Exception as e:
            print(f"{Fore.RED}[Agent Manager] Error updating agent status: {e}{Style.RESET_ALL}")
    
    def get_agent_instance(self, agent_uid: str) -> Optional[OpenAIAgent]:
        """Get the OpenAI agent instance for a given agent_uid"""
        return self.agent_instances.get(agent_uid)

# Global agent manager instance
agent_manager = AgentManager()

async def initialize_agent_tpay_balances(available_agents: List[Dict[str, Any]], game_uid: str):
    """Initialize game token accounts for agents at game start"""
    # Extract tpay account IDs from available agents
    agent_tpay_ids = []
    agent_names = []
    
    for agent_data in available_agents:
        tpay_account_id = agent_data.get('tpay_account_id')
        if not tpay_account_id:
            print(f"{Fore.YELLOW}[TPay] Agent {agent_data['name']} has no tpay account, skipping game token setup{Style.RESET_ALL}")
            continue
        
        agent_tpay_ids.append(tpay_account_id)
        agent_names.append(agent_data['name'])
    
    print(f"{Fore.CYAN}[TPay] Resetting {utils.GAME_TOKEN_SYMBOL} accounts for {len(agent_tpay_ids)} agents in game {game_uid}{Style.RESET_ALL}")
    
    try:
        # reset game token accounts for all agents
        for agent_id in agent_tpay_ids:
            result = utils.reset_agent_game_balance(
                agent_id=agent_id,
            )
            if result:
                print(f"{Fore.GREEN}[TPay] Successfully reset {utils.GAME_TOKEN_SYMBOL} balance for agent {agent_id}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[TPay] Failed to reset {utils.GAME_TOKEN_SYMBOL} balance for agent {agent_id}{Style.RESET_ALL}")        
    except Exception as e:
        print(f"{Fore.RED}[TPay] Error initializing game token accounts for {game_uid}: {e}{Style.RESET_ALL}")

async def update_agent_game_statistics(available_agents: List[Dict[str, Any]], gc: GameController, 
                                      game_db_id: int):
    """Update agent statistics after a game ends"""
    try:
        # Determine winner and rankings
        active_players = [p for p in gc.players if not p.is_bankrupt]
        winner_agent_id = None
        
        if len(active_players) == 1:
            # Single winner
            winner_player_idx = active_players[0].player_id
            winner_agent_id = available_agents[winner_player_idx]['id']
        
        # Update each agent's statistics
        with Session(engine) as session:
            for i, agent_data in enumerate(available_agents):
                player = gc.players[i]
                is_winner = (agent_data['id'] == winner_agent_id)
                
                # Calculate final ranking (1st = winner, others based on money/assets)
                final_ranking = 1 if is_winner else (len(available_agents) if player.is_bankrupt else 2)
                
                # Update agents table
                agent_update = update(agents_table).where(
                    agents_table.c.id == agent_data['id']
                ).values(
                    total_games_played=agents_table.c.total_games_played + 1,
                    total_wins=agents_table.c.total_wins + (1 if is_winner else 0),
                    last_active=func.now()
                )
                session.execute(agent_update)
                
                # Update players table with final game data
                player_update = update(players_table).where(
                    players_table.c.id == available_agents[i]['db_id']
                ).values(
                    final_balance=player.money,
                    final_ranking=final_ranking
                )
                session.execute(player_update)
                
                print(f"{Fore.CYAN}[Stats] Agent {agent_data['name']}: Ranking {final_ranking}, Final Balance: ${player.money}{Style.RESET_ALL}")
            
            session.commit()
            
    except Exception as e:
        print(f"{Fore.RED}[Agent Stats] Error updating agent statistics: {e}{Style.RESET_ALL}")
        raise

# 5. Game management functions
async def create_new_game_instance(app_instance: FastAPI) -> str:
    """Create and start a new game instance"""
    global GAME_COUNTER
    
    # Check if we have enough available agents
    available_agents = agent_manager.get_available_agents_for_game(AGENTS_PER_GAME)
    if not available_agents:
        print(f"{Fore.YELLOW}[Game Manager] Cannot create new game - not enough available agents (need {AGENTS_PER_GAME}){Style.RESET_ALL}")
        return None
    
    GAME_COUNTER += 1
    game_uid = f"monopoly_game_{GAME_COUNTER}_{uuid.uuid4().hex[:6]}"
    print(f"{Fore.GREEN}[Game Manager] Creating new game instance: {game_uid} with agents: {[a['name'] for a in available_agents]}{Style.RESET_ALL}")
    
    # Assign agents to this game
    agent_manager.assign_agents_to_game(available_agents, game_uid)
    
    game_task = asyncio.create_task(start_monopoly_game_instance_with_restart(game_uid, manager, app_instance, available_agents))
    app_instance.state.game_tasks[game_uid] = game_task
    
    print(f"{Fore.GREEN}[Game Manager] Game {game_uid} task created and started{Style.RESET_ALL}")
    return game_uid

async def maintain_game_count(app_instance: FastAPI):
    """Ensure we maintain the desired number of concurrent games"""
    if not hasattr(app_instance.state, 'game_tasks'):
        return
        
    # Count active (not done) game tasks
    active_games = {uid: task for uid, task in app_instance.state.game_tasks.items() 
                   if not task.done()}
    
    # Remove completed tasks from the registry
    completed_games = [uid for uid, task in app_instance.state.game_tasks.items() if task.done()]
    for completed_uid in completed_games:
        print(f"{Fore.YELLOW}[Game Manager] Removing completed game {completed_uid} from registry{Style.RESET_ALL}")
        del app_instance.state.game_tasks[completed_uid]
    
    # Start new games if needed
    games_needed = CONCURRENT_GAMES_COUNT - len(active_games)
    if games_needed > 0 and AUTO_RESTART_GAMES:
        print(f"{Fore.CYAN}[Game Manager] Need to start {games_needed} new games (active: {len(active_games)}/{CONCURRENT_GAMES_COUNT}){Style.RESET_ALL}")
        
        # Check if we have enough available agents
        available_agent_count = len(agent_manager.available_agents)
        max_possible_games = available_agent_count // AGENTS_PER_GAME
        
        if max_possible_games < games_needed:
            print(f"{Fore.YELLOW}[Game Manager] Not enough agents for all requested games. Available agents: {available_agent_count}, can start {max_possible_games} games{Style.RESET_ALL}")
            games_needed = max_possible_games
        
        for _ in range(games_needed):
            created_game_uid = await create_new_game_instance(app_instance)
            if created_game_uid is None:
                print(f"{Fore.YELLOW}[Game Manager] Could not create more games - no available agents{Style.RESET_ALL}")
                break

async def start_monopoly_game_instance_with_restart(game_uid: str, connection_manager_param: ConnectionManager, app_instance: FastAPI, available_agents: List[Dict[str, Any]]):
    """Wrapper for game instance that handles auto-restart"""
    try:
        await start_monopoly_game_instance(game_uid, connection_manager_param, app_instance, available_agents)
    except Exception as e:
        print(f"{Fore.RED}[Game Manager] Game {game_uid} ended with error: {e}{Style.RESET_ALL}")
    finally:
        print(f"{Fore.CYAN}[Game Manager] Game {game_uid} has finished. Checking if new game should be started...{Style.RESET_ALL}")
        
        # Always release agents back to available pool
        try:
            agent_manager.release_agents_from_game(game_uid)
            print(f"{Fore.GREEN}[Game Manager] Released agents from {game_uid} back to available pool{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[Game Manager] Error releasing agents from {game_uid}: {e}{Style.RESET_ALL}")
        
        # Schedule a new game to maintain the count (will be handled by periodic maintenance)
        if AUTO_RESTART_GAMES:
            # Use asyncio.create_task to avoid blocking this cleanup
            asyncio.create_task(maintain_game_count(app_instance))

async def periodic_game_maintenance(app_instance: FastAPI):
    """Periodically check and maintain the desired number of games"""
    while True:
        try:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            await maintain_game_count(app_instance)
        except asyncio.CancelledError:
            print(f"{Fore.YELLOW}[Game Manager] Periodic maintenance task cancelled{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"{Fore.RED}[Game Manager] Error in periodic maintenance: {e}{Style.RESET_ALL}")

def get_game_status(app_instance: FastAPI) -> Dict[str, Any]:
    """Get current status of all games"""
    if not hasattr(app_instance.state, 'game_tasks'):
        return {"active_games": 0, "total_games": 0, "games": []}
    
    active_games = []
    completed_count = 0
    
    for uid, task in app_instance.state.game_tasks.items():
        if task.done():
            completed_count += 1
        else:
            game_info = {
                "game_uid": uid,
                "status": "running",
                "task_done": False
            }
            # Try to get more details from active_games if available
            if hasattr(app_instance.state, 'active_games') and uid in app_instance.state.active_games:
                gc = app_instance.state.active_games[uid]
                game_info.update({
                    "turn_count": getattr(gc, 'turn_count', 0),
                    "game_over": getattr(gc, 'game_over', False),
                    "current_player": getattr(gc, 'current_player_index', 0),
                    "player_count": len(getattr(gc, 'players', []))
                })
            active_games.append(game_info)
    
    return {
        "active_games": len(active_games),
        "completed_games": completed_count,
        "total_games": len(app_instance.state.game_tasks),
        "concurrent_games_target": CONCURRENT_GAMES_COUNT,
        "auto_restart_enabled": AUTO_RESTART_GAMES,
        "games": active_games
    }

# 6. Helper function definitions (_log_agent_action_to_db, start_monopoly_game_instance)
def _log_agent_action_to_db(gc_ref: Any, player_id: int, agent_ref: Any, action_result: Dict[str, Any]):
    if gc_ref.game_db_id is None: print("[DB Log] No game_db_id for agent action log."); return
    player_db_id = gc_ref.players[player_id].db_id
    if player_db_id is None: gc_ref.log_event(f"[DB E] P{player_id} ({gc_ref.players[player_id].name}) no db_id.", "error_log"); return
    if not hasattr(agent_ref, 'get_last_decision_details_for_db'): gc_ref.log_event(f"[DB E] Agent P{player_id} no get_last_decision_details.", "error_log"); return
    decision_details = agent_ref.get_last_decision_details_for_db()
    # ---- START DEBUG ----
    print(f"[DEBUG DB LOG] Agent gc_turn_number from decision_details: {decision_details.get('gc_turn_number')} for player {player_id}. GC.turn_count: {gc_ref.turn_count}")
    # ---- END DEBUG ----
    action_data = {
        "game_id": gc_ref.game_db_id, "game_turn_id": gc_ref.current_game_turn_db_id,
        "player_db_id": player_db_id, "player_game_index": player_id,
        "gc_turn_number": decision_details.get("gc_turn_number"),
        "action_sequence_in_gc_turn": decision_details.get("action_sequence_in_gc_turn"),
        "pending_decision_type_before": decision_details.get("pending_decision_type_before"),
        "pending_decision_context_json_before": decision_details.get("pending_decision_context_json_before"),
        "available_actions_json_before": decision_details.get("available_actions_json_before"),
        "agent_thoughts_text": decision_details.get("agent_thoughts_text"),
        "llm_raw_response_text": decision_details.get("llm_raw_response_text"),
        "parsed_action_json_str": decision_details.get("parsed_action_json_str"),
        "chosen_tool_name": decision_details.get("chosen_tool_name"),
        "tool_parameters_json": decision_details.get("tool_parameters_json"),
        "action_result_status": action_result.get("status"),
        "action_result_message": action_result.get("message"),
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
    }
    try:
        with Session(engine) as session:
            stmt = insert(agent_actions_table).values(action_data); session.execute(stmt); session.commit()
    except Exception as e: print(f"[DB Error] Log agent action P{player_id} G_DB_ID {gc_ref.game_db_id}: {e}")

async def start_monopoly_game_instance(game_uid: str, connection_manager_param: ConnectionManager, app_instance: FastAPI, available_agents: List[Dict[str, Any]]):
    print(f"Attempting to start G_UID: {game_uid}")
    game_db_id: Optional[int] = None; 
    gc: Optional[GameController] = None 

    try:
        with Session(engine) as session:
            game_values = {"game_uid": game_uid, "status": "initializing", "num_players": len(available_agents), "max_turns": MAX_TURNS}
            game_db_id = session.execute(insert(games_table).values(game_values).returning(games_table.c.id)).scalar_one_or_none()
            if game_db_id is None: raise Exception("Failed to get game_db_id.")
            
            # Create player records linked to persistent agents
            for i, agent_data in enumerate(available_agents):
                p_values = {
                    "game_id": game_db_id, 
                    "agent_id": agent_data['id'],  # Link to persistent agent
                    "player_index_in_game": i, 
                    "agent_name": agent_data['name'], 
                    "agent_type": "OpenAIAgent_gpt-4",
                    "game_starting_balance": AGENT_INITIAL_BALANCE
                }
                p_db_id = session.execute(insert(players_table).values(p_values).returning(players_table.c.id)).scalar_one_or_none()
                if p_db_id is None: raise Exception(f"Failed to get player_db_id for P_idx {i}.")
                available_agents[i]['db_id'] = p_db_id
        
            session.commit()
            print(f"{Fore.GREEN}DB init G_UID:{game_uid} (DBID:{game_db_id}) with persistent agents. {Style.RESET_ALL}")
    except Exception as db_init_e: 
        print(f"{Fore.RED}[FATAL DB ERROR] for {game_uid}: {db_init_e}{Style.RESET_ALL}")
        # Optionally broadcast a lobby update about failed game creation if desired
        # await connection_manager_param.broadcast_to_lobby({"type": "game_creation_failed", "game_uid": game_uid, "error": str(db_init_e)})
        return 

    try:
        gc = GameController(game_uid=game_uid, ws_manager=connection_manager_param, 
                            game_db_id=game_db_id, participants=available_agents, treasury_agent_id="agnt_d755a309-682b-49b7-b997-956efef2b591")
        
        if hasattr(app_instance.state, 'active_games'):
            app_instance.state.active_games[game_uid] = gc
            print(f"{Fore.GREEN}GameController for G_UID:{game_uid} stored in app.state.active_games.{Style.RESET_ALL}")
        
        _setup_tool_placeholders(gc)
        
        # Use persistent agent instances instead of creating new ones
        agents = []
        for i, agent_data in enumerate(available_agents):
            agent_instance = agent_manager.get_agent_instance(agent_data['agent_uid'])
            if agent_instance:
                # Update the agent's player_id for this game
                agent_instance.player_id = i
                agents.append(agent_instance)
                print(f"{Fore.CYAN}[Agent] Using persistent agent {agent_data['name']} (UID: {agent_data['agent_uid']}) as Player {i}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[Agent Error] Could not find agent instance for {agent_data['agent_uid']}{Style.RESET_ALL}")
                # Fallback: create new agent instance
                agent_instance = OpenAIAgent(player_id=i, name=agent_data['name'])
                agents.append(agent_instance)
        
        await gc.send_event_to_frontend({"type": "init_log", "message": f"Initialized {len(agents)} persistent agents for G:{game_uid}."})
        
        # Initialize game token accounts for all agents before game starts
        print(f"{Fore.CYAN}[TPay] Creating {utils.GAME_TOKEN_SYMBOL} token accounts for game {game_uid}...{Style.RESET_ALL}")
        await initialize_agent_tpay_balances(available_agents, game_uid)
        
        # ----- Broadcast New Game to Lobby ----- START
        initial_players_info_for_lobby = []
        for p in gc.players: # gc.players should be populated by GameController.__init__
            initial_players_info_for_lobby.append({
                "id": p.player_id,
                "name": p.name,
                "is_ai": p.is_ai,
                "is_bankrupt": p.is_bankrupt # Should be False at start
            })
        
        new_game_lobby_data = {
            "game_uid": gc.game_uid,
            "status": "initializing", # Or gc.status if GC has a more detailed status attribute
            "current_players_count": len(gc.players),
            "max_players": NUM_PLAYERS, # Assuming NUM_PLAYERS is the max for the game
            "players": initial_players_info_for_lobby,
            "turn_count": gc.turn_count # Will be 0 before gc.start_game()
        }
        await connection_manager_param.broadcast_to_lobby({
            "type": "game_added", # Using a more descriptive type
            "data": new_game_lobby_data
        })
        print(f"{Fore.CYAN}[Lobby Broadcast] Sent game_added event for G_UID: {game_uid}{Style.RESET_ALL}")
        # ----- Broadcast New Game to Lobby ----- END

        # trade_details_for_test = {
        #     "proposer_id": 0,
        #     "recipient_id": 1,
        #     "offered_property_ids": [1],  # Mediterranean Avenue
        #     "offered_money": 50,
        #     "offered_gooj_cards": 0,
        #     "requested_property_ids": [3], # Baltic Avenue
        #     "requested_money": 0,
        #     "requested_gooj_cards": 0,
        #     "message": "Hey Player B, let's make a deal for Baltic Avenue!" # Example message
        # }
        # property_id_for_auction_test = 11 # St. Charles Place (ensure it's a valid, unowned purchasable property ID from your board setup)
        # gc.start_game(test_mode_trade_details=trade_details_for_test)

        gc.start_game() # This sets turn_count to 1 and determines starting player
        
        # Update lobby again after gc.start_game() to reflect "in_progress" and correct turn 1 info if needed
        # Or rely on the first player_state_update from the game loop to trigger a more general game_update to lobby
        # For simplicity now, we could send a game_status_update here.
        game_started_lobby_data = {
            "game_uid": gc.game_uid,
            "status": "in_progress", # Game is now truly in progress
            "turn_count": gc.turn_count, # Should be 1
            "current_player_index": gc.current_player_index # Who is starting
        }
        await connection_manager_param.broadcast_to_lobby({
            "type": "game_status_update", 
            "data": game_started_lobby_data
        })
        print(f"{Fore.CYAN}[Lobby Broadcast] Sent game_status_update (in_progress) for G_UID: {game_uid}{Style.RESET_ALL}")

        # Send initial state for all players after game starts (will reflect jail status)
        for p_idx in range(len(available_agents)):
            if not gc.players[p_idx].is_bankrupt: # Should not be bankrupt at start
                player_state_data = gc.get_game_state_for_agent(p_idx)
                await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data})
        print(f"Sent initial player states for G_UID: {game_uid}")
                
        loop_turn_count = 0 
        action_sequence_this_gc_turn = 0 
        last_gc_turn_for_action_seq = gc.turn_count
        if last_gc_turn_for_action_seq == 0: last_gc_turn_for_action_seq = 1

        print(f"{Fore.CYAN}Starting main game loop for G_UID: {game_uid}...{Style.RESET_ALL}")
        while not gc.game_over and loop_turn_count < MAX_TURNS:
            loop_turn_count += 1 # This is outer loop/safety counter, not gc.turn_count
            # gc.turn_count is advanced by gc.next_turn()
            print(f"{Fore.BLUE}Main Loop Iter: {loop_turn_count}, GC Turn: {gc.turn_count}, Current Main Player Index: {gc.current_player_index}{Style.RESET_ALL}")
            
            active_player_id: Optional[int]; current_acting_player: Optional[Player]; 
            roll_action_taken_this_main_turn_segment = False 
            current_main_turn_player_id = gc.current_player_index

            if gc.turn_count != last_gc_turn_for_action_seq: # If GC turn has advanced
                action_sequence_this_gc_turn = 0
                last_gc_turn_for_action_seq = gc.turn_count
            
            # Determine active player for this segment (main turn, auction, trade response, etc.)
            if gc.auction_in_progress and gc.pending_decision_type == "auction_bid":
                active_player_id = gc.pending_decision_context.get("player_to_bid_id")
                if active_player_id is None: 
                    await gc.send_event_to_frontend({"type":"error_log", "message": f"[E] GameLoop G{game_uid}: Auction but no bidder."})
                    gc._conclude_auction(no_winner=True); 
                    active_player_id = current_main_turn_player_id # Fallback to current main player 
                current_acting_player = gc.players[active_player_id]
            elif gc.pending_decision_type in ["respond_to_trade_offer", "handle_received_mortgaged_property", "propose_new_trade_after_rejection"]:
                active_player_id = gc.pending_decision_context.get("player_id")
                if active_player_id is None: 
                    await gc.send_event_to_frontend({"type":"error_log", "message": f"[E] GameLoop G{game_uid}: Pending '{gc.pending_decision_type}' but no P_ID."})
                    gc._clear_pending_decision(); 
                    active_player_id = current_main_turn_player_id # Fallback
                current_acting_player = gc.players[active_player_id]
            else: # Default to the main player for the current game controller turn
                active_player_id = current_main_turn_player_id
                current_acting_player = gc.players[active_player_id]
            
            print(f"{Fore.BLUE}  Active Player ID for this segment: {active_player_id}, Name: {current_acting_player.name if current_acting_player else 'N/A'}{Style.RESET_ALL}")
            agent_to_act = agents[active_player_id]
            await gc.send_event_to_frontend({"type": "turn_info", "data": f"--- Loop {loop_turn_count} (GC_Turn {gc.turn_count}) for P{active_player_id} ({current_acting_player.name}) --- PendDec: {gc.pending_decision_type}"}) 
            
            if not current_acting_player.is_bankrupt: 
                player_state_data_before_segment = gc.get_game_state_for_agent(current_acting_player.player_id)
                await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data_before_segment})
            
            if current_acting_player.is_bankrupt:
                if gc.game_over: break 
                # If a player involved in an auction/trade response becomes bankrupt mid-decision, GC needs to handle it.
                # For now, if bankrupt, skip their segment and let next_turn logic or auction logic handle removal.
                if gc.auction_in_progress and current_acting_player in gc.auction_active_bidders:
                    gc._handle_auction_pass(current_acting_player) # Treat as pass if bankrupt during auction turn
                # If it was main turn player, next_turn will handle it. If other, specific logic might be needed.
                # This continue might need to be smarter based on context.
                print(f"{Fore.YELLOW}Player P{active_player_id} ({current_acting_player.name}) is bankrupt. Skipping their action segment.{Style.RESET_ALL}")
                # The crucial part is to ensure gc.next_turn() is called if this was the main turn player.
                # This will be handled by the logic at the end of the outer while loop.
                if active_player_id == current_main_turn_player_id and not gc.auction_in_progress: # If it was their main turn and they are bankrupt
                    gc.log_event(f"Bankrupt main player P{active_player_id} detected at start of segment. Calling next_turn.", "debug_next_turn")
                    gc.next_turn() 
                if gc.game_over: break
                continue 
            
            player_turn_segment_active = True; action_this_segment_count = 0
            # Reset roll_action_taken flag if it's the start of a main turn player's segment and no decision is pending (meaning they can roll)
            if active_player_id == current_main_turn_player_id and gc.pending_decision_type is None:
                 roll_action_taken_this_main_turn_segment = False
            
            while player_turn_segment_active and not current_acting_player.is_bankrupt and not gc.game_over and action_this_segment_count < MAX_ACTIONS_PER_SEGMENT:
                action_this_segment_count += 1
                action_sequence_this_gc_turn += 1
                gc.log_event(f"Loop {loop_turn_count}, SegAct {action_this_segment_count}, P{active_player_id} ({current_acting_player.name}) Turn. GC.Pend: {gc.pending_decision_type}, GC.DiceDone: {gc.dice_roll_outcome_processed}", "debug_loop")
                available_actions = gc.get_available_actions(active_player_id)
                gc.log_event(f"P{active_player_id} AvailActions: {available_actions}", "debug_loop")
                if not available_actions: 
                    await gc.send_event_to_frontend({"type":"warning_log", "message":f"[W] No actions for P{active_player_id} ({current_acting_player.name}). Pend:'{gc.pending_decision_type}', SegEnd."})
                    player_turn_segment_active = False; break 
                game_state_for_agent = gc.get_game_state_for_agent(active_player_id)
                await gc.send_event_to_frontend({"type": "agent_thinking_start", "player_id": active_player_id, "available_actions": available_actions, "context": gc.pending_decision_context, "turn": gc.turn_count, "seq": action_sequence_this_gc_turn})
                print(f"[DEBUG SERVER LOOP] Passing gc.turn_count: {gc.turn_count} to agent {active_player_id} (Name: {agent_to_act.name}) for decide_action")
                chosen_tool_name, params = await asyncio.to_thread(agent_to_act.decide_action, game_state_for_agent, available_actions, gc.turn_count, action_sequence_this_gc_turn)
                thoughts = agent_to_act.get_player_thought_process()
                await gc.send_event_to_frontend({"type": "agent_decision", "player_id": active_player_id, "tool_name": chosen_tool_name, "params": params, "thoughts": thoughts})
                action_result = await asyncio.to_thread(execute_agent_action, gc, active_player_id, chosen_tool_name, params)
                await asyncio.to_thread(_log_agent_action_to_db, gc, active_player_id, agent_to_act, action_result)
                await gc.send_event_to_frontend({"type": "action_result", "player_id": active_player_id, "tool_name": chosen_tool_name, "result_status": action_result.get('status'), "result_message": action_result.get('message')})
                if not current_acting_player.is_bankrupt: 
                    player_state_data_after_action = gc.get_game_state_for_agent(current_acting_player.player_id)
                    await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data_after_action})

                if action_result.get("status") == "error" or current_acting_player.is_bankrupt : player_turn_segment_active = False; break 
                
                # --- Player action segment termination logic --- 
                if chosen_tool_name == "tool_roll_dice":
                    if action_result.get("status") == "success":
                        if active_player_id == current_main_turn_player_id: roll_action_taken_this_main_turn_segment = True
                        if not action_result.get("went_to_jail", False):
                            dice_val = action_result.get("dice_roll", gc.dice)
                            if dice_val and sum(dice_val) > 0 : gc._move_player(current_acting_player, sum(dice_val))
                            else: 
                                gc.log_event(f"[E] Invalid dice {dice_val} from roll_dice tool for P{active_player_id}. Ending segment.", "error_log")
                                gc._resolve_current_action_segment() # Resolve to avoid stuck state
                                player_turn_segment_active = False # End segment due to error with dice
                    # After roll & move, GC state (pending_decision, dice_roll_outcome_processed) is updated by land_on_square.
                    # If a new decision is pending for *this* player (e.g., buy), loop continues.
                    # If landing is resolved and no new decision for this player, then segment ends.
                    if gc.pending_decision_type is None and gc.dice_roll_outcome_processed: player_turn_segment_active = False
                
                elif chosen_tool_name == "tool_buy_property":
                     # If buy succeeds, GC resolves the segment. If fails (funds), GC keeps pending_decision.
                    if action_result.get("status") == "success" and gc.pending_decision_type is None and gc.dice_roll_outcome_processed:
                        player_turn_segment_active = False 
                
                elif chosen_tool_name == "tool_pass_on_buying_property":
                    # GC._initiate_auction sets pending_decision for next auction bidder. Current player's segment is done.
                    player_turn_segment_active = False 
                
                elif chosen_tool_name == "tool_end_turn" or chosen_tool_name == "tool_resign_game": 
                    player_turn_segment_active = False
                
                elif gc.pending_decision_type == "jail_options":
                    # If a jail action was taken (roll, pay, card) and player is still in jail (or got out and moved),
                    # the GC state (pending_decision_type, dice_roll_outcome_processed) will determine if more actions are needed from this player.
                    # If tool_end_turn was chosen from jail, player_turn_segment_active will be false.
                    # If player got out and moved, pending_decision_type will be None and dice_roll_outcome_processed true IF landing is simple.
                    # If a new decision arose from landing after getting out, loop continues.
                    if gc.pending_decision_type is None and gc.dice_roll_outcome_processed: # e.g. got out and landed on unowned or simple square
                        player_turn_segment_active = False
                    elif gc.pending_decision_type == "jail_options" and chosen_tool_name != "tool_end_turn": # Still in jail, but made an attempt (e.g. failed roll)
                        pass # Loop continues to re-evaluate available jail options for THIS player.
                    # else: if chose tool_end_turn, already handled. If another decision arose, loop continues.

                elif gc.pending_decision_type == "asset_liquidation_for_debt":
                    if chosen_tool_name == "tool_confirm_asset_liquidation_actions_done" or current_acting_player.money >=0:
                         player_turn_segment_active = False 
                
                elif gc.pending_decision_type == "handle_received_mortgaged_property":
                    # If all mortgaged props handled, GC clears pending_decision & sets dice_roll_outcome_processed=True.
                    if gc.pending_decision_type != "handle_received_mortgaged_property": 
                        player_turn_segment_active = False
                
                elif gc.auction_in_progress and gc.pending_decision_type == "auction_bid": 
                    # After a bid/pass, GC sets pending_decision for the *next* bidder. Current player's segment is done.
                    player_turn_segment_active = False 
                
                # --- Trade negotiation handling ---
                elif chosen_tool_name in ["tool_accept_trade", "tool_reject_trade", "tool_propose_counter_offer"]:
                    # After responding to a trade offer, the segment for the responder is done
                    # If trade is accepted, it's resolved. If rejected, control goes to original proposer
                    # If counter-offered, control goes to original proposer to respond to new offer
                    player_turn_segment_active = False 
                
                elif chosen_tool_name == "tool_propose_trade":
                    # After any trade proposal (new or during negotiation), the segment for the proposer is done
                    # Control should transfer to the recipient
                    if action_result.get("status") == "success":
                        player_turn_segment_active = False
                
                elif chosen_tool_name == "tool_end_trade_negotiation":
                    # After ending trade negotiation, current player's segment is done
                    player_turn_segment_active = False
                
                elif gc.pending_decision_type is None and gc.dice_roll_outcome_processed: # General actions phase after a roll or other resolved decision
                    current_av_actions = gc.get_available_actions(active_player_id)
                    # If only end_turn or wait is left, or no actions, segment usually ends. Agent can choose end_turn.
                    if not current_av_actions or all(act in ["tool_end_turn", "tool_wait"] for act in current_av_actions):
                         player_turn_segment_active = False
                
                if action_this_segment_count >= MAX_ACTIONS_PER_SEGMENT: 
                    await gc.send_event_to_frontend({"type":"warning_log", "message":f"[W] Max actions for P{active_player_id}. SegEnd."})
                    player_turn_segment_active = False
                
                if player_turn_segment_active and not gc.game_over and ACTION_DELAY_SECONDS > 0: await asyncio.sleep(ACTION_DELAY_SECONDS)
            
            # --- End of inner while loop (player_turn_segment_active) ---
            if gc.game_over: break # Break outer while loop if game over
        
            # --- Outer while loop: Max turns check & Game Over check ---
            if loop_turn_count >= MAX_TURNS and not gc.game_over: 
                print(f"{Fore.YELLOW}G_UID:{game_uid} - Max turns ({MAX_TURNS}) reached.{Style.RESET_ALL}")
                gc.game_over = True 
            if gc.game_over: 
                print(f"{Fore.RED}G_UID:{game_uid} - Game over flag is true. Exiting main loop.{Style.RESET_ALL}")
                break 

            # --- Determine if next turn should be called --- 
            main_turn_player_for_next_step = gc.players[gc.current_player_index]
            call_next_turn_flag = False

            # Don't advance turn if we're in the middle of trade negotiations or other cross-player decisions
            if gc.pending_decision_type in ["respond_to_trade_offer", "propose_new_trade_after_rejection"]:
                # Trade negotiations are happening - don't advance main turn yet
                gc.log_event(f"Trade negotiation in progress ({gc.pending_decision_type}). Not advancing main turn.", "debug_next_turn")
                call_next_turn_flag = False
            elif not gc.auction_in_progress: 
                if main_turn_player_for_next_step.is_bankrupt: 
                    gc.log_event(f"Main turn P{main_turn_player_for_next_step.player_id} ({main_turn_player_for_next_step.name}) is bankrupt. Advancing turn.", "debug_next_turn")
                    call_next_turn_flag = True
                elif active_player_id == main_turn_player_for_next_step.player_id: 
                    is_in_jail_at_segment_end = main_turn_player_for_next_step.in_jail
                    rolled_doubles_for_bonus = (roll_action_taken_this_main_turn_segment and 
                                              gc.dice[0] == gc.dice[1] and gc.dice[0] != 0 and 
                                              not is_in_jail_at_segment_end and 
                                              gc.doubles_streak < 3 and gc.doubles_streak > 0)
                    if rolled_doubles_for_bonus:
                        await gc.send_event_to_frontend({"type": "bonus_turn", "player_id": main_turn_player_for_next_step.player_id, "streak": gc.doubles_streak})
                        gc._clear_pending_decision(); gc.dice_roll_outcome_processed = True; 
                        roll_action_taken_this_main_turn_segment = False 
                        if main_turn_player_for_next_step.pending_mortgaged_properties_to_handle: 
                            gc._handle_received_mortgaged_property_initiation(main_turn_player_for_next_step)
                        gc.log_event(f"Player {main_turn_player_for_next_step.name} gets a bonus turn segment due to doubles.", "debug_next_turn")
                    else:
                        gc.log_event(f"End of segment for main turn player {main_turn_player_for_next_step.name} (P{active_player_id}). In jail: {is_in_jail_at_segment_end}. Proceeding to next logical turn decision.", "debug_next_turn")
                        call_next_turn_flag = True
            
            if call_next_turn_flag:
                gc.log_event(f"Calling gc.next_turn() for G_UID:{game_uid}. Previous GC turn: {gc.turn_count}, Previous Main PIdx: {current_main_turn_player_id}", "debug_next_turn")
                gc.next_turn() # This will increment gc.turn_count and set new current_player_index
                gc.log_event(f"gc.next_turn() called. New GC turn: {gc.turn_count}, New Main PIdx: {gc.current_player_index}", "debug_next_turn")
            elif gc.auction_in_progress: 
                await gc.send_event_to_frontend({"type":"auction_log", "message":f"Auction for propId {gc.auction_property_id if gc.auction_property_id is not None else 'N/A'} continues..."})
        
            # After potential turn change or auction continuation, send updates for all players
            if not gc.game_over: 
                print(f"{Fore.MAGENTA}End of loop iter {loop_turn_count} for G_UID:{game_uid}. Sending all player state updates.{Style.RESET_ALL}")
                for p_idx_update in range(len(available_agents)):
                    if not gc.players[p_idx_update].is_bankrupt:
                        player_state_data_periodic = gc.get_game_state_for_agent(p_idx_update) 
                        await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data_periodic})

            if gc.game_over: 
                print(f"{Fore.RED}G_UID:{game_uid} - Game over flag is true post next_turn/auction logic. Exiting main loop.{Style.RESET_ALL}")
                break 
            
            # Add random delay between turns (5-10 seconds)
            turn_delay = random.uniform(5.0, 10.0)
            print(f"{Fore.CYAN}[Turn Delay] Waiting {turn_delay:.1f} seconds before next turn for G_UID:{game_uid}...{Style.RESET_ALL}")
            await asyncio.sleep(turn_delay)
        
        # --- End of main while loop ---
        print(f"{Fore.CYAN}Main game loop for G_UID: {game_uid} has ended. Game Over: {gc.game_over if gc else 'N/A'}, Loop Turns: {loop_turn_count}{Style.RESET_ALL}")
        if gc:
            final_summary_str = await asyncio.to_thread(print_game_summary, gc, True)
            await gc.send_event_to_frontend({"type": "game_summary_data", "summary": final_summary_str})
            await gc.send_event_to_frontend({"type": "game_end_log", "message":f"Monopoly Game Instance {game_uid} Finished."})
            print(f"Game instance {game_uid} final summary sent.")
            
            # Update agent statistics and release them back to available pool
            try:
                await update_agent_game_statistics(available_agents, gc, game_db_id)
                agent_manager.release_agents_from_game(game_uid)
                print(f"{Fore.GREEN}[Agent Manager] Released {len(available_agents)} agents back to available pool{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[Agent Manager] Error updating agent statistics: {e}{Style.RESET_ALL}")
            
            if game_db_id:
                try:
                    with Session(engine) as session:
                        current_status_query = select(games_table.c.status).where(games_table.c.id == game_db_id)
                        current_status_res = session.execute(current_status_query).scalar_one_or_none()
                        if current_status_res != "crashed_logic_error": 
                            winner_player_db_id = None
                            active_p_list = [p for p in gc.players if not p.is_bankrupt]
                            if len(active_p_list) == 1: winner_player_db_id = available_agents[active_p_list[0].player_id]['db_id']
                            final_status = "completed"
                            if loop_turn_count >= MAX_TURNS: final_status = "max_turns_reached"
                            elif not active_p_list and len(active_p_list) !=1 : final_status = "aborted_no_winner" 
                            elif len(active_p_list) == 1 : final_status = "completed"
                            else: final_status = "unknown_end" # Should ideally not happen
                            stmt = games_table.update().where(games_table.c.id == game_db_id).values(
                                status=final_status, 
                                end_time=datetime.datetime.now(datetime.timezone.utc),
                                winner_player_id=winner_player_db_id
                            )
                            session.execute(stmt); session.commit()
                            print(f"G_UID {game_uid} (DBID:{game_db_id}) status updated to {final_status}.")
                except Exception as e: print(f"[DB E] Update game end status for G_DB_ID {game_db_id}: {e}")
    
    except Exception as game_logic_e:
        print(f"{Fore.RED}[FATAL GAME LOGIC ERROR] for G_UID:{game_uid}: {game_logic_e}{Style.RESET_ALL}")
        if game_db_id: 
            try:
                with Session(engine) as session:
                    stmt_crash = update(games_table).where(games_table.c.id == game_db_id).values(
                        status="crashed_logic_error",
                        end_time=datetime.datetime.now(datetime.timezone.utc)
                    )
                    session.execute(stmt_crash)
                    session.commit()
                    print(f"G_UID {game_uid} (DBID:{game_db_id}) status updated to crashed_logic_error due to: {game_logic_e}")
            except Exception as db_e_crash:
                print(f"[DB E] while updating status to crashed_logic_error for G_DB_ID {game_db_id}: {db_e_crash}")
        if gc: 
             try:
                 await gc.send_event_to_frontend({"type": "critical_error", "message": f"Game {game_uid} encountered a critical error: {str(game_logic_e)}. Please check server logs."})
             except Exception as send_err_e:
                  print(f"{Fore.RED}[E] Failed to send critical_error to frontend for G_UID {game_uid} after game logic error: {send_err_e}{Style.RESET_ALL}")
        # Consider re-raising if the surrounding task management needs to know: raise game_logic_e

    finally:
        if hasattr(app_instance.state, 'active_games') and game_uid in app_instance.state.active_games:
            del app_instance.state.active_games[game_uid]
            print(f"{Fore.YELLOW}GameController for G_UID:{game_uid} removed from app.state.active_games.{Style.RESET_ALL}")
        
    print(f"start_monopoly_game_instance for {game_uid} fully concluded (or terminated due to error/cancellation).")

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    print("FastAPI server starting up (via lifespan)...")
    create_db_and_tables()
    print("DB tables checked/created (via lifespan).")
    
    app_instance.state.active_games = {} 
    app_instance.state.game_tasks = {}   
    
    # Initialize tpay sdk
    print(f"Initializing tpay sdk with api_key: {TLEDGER_API_KEY}, api_secret: {TLEDGER_API_SECRET}, project_id: {TLEDGER_PROJECT_ID}, base_url: {TLEDGER_BASE_URL}, timeout: 1000")
    tpay.tpay_initialize(api_key=TLEDGER_API_KEY, api_secret=TLEDGER_API_SECRET, project_id=TLEDGER_PROJECT_ID, base_url=TLEDGER_BASE_URL, timeout=1000)

    # Initialize agent manager and load agents from database
    print("Initializing Agent Manager...")
    await agent_manager.initialize_agents_from_database()
    
    # Check if we have enough agents to start games
    if len(agent_manager.available_agents) < AGENTS_PER_GAME:
        print(f"{Fore.YELLOW}[Warning] Not enough agents in database to start games. Need at least {AGENTS_PER_GAME}, have {len(agent_manager.available_agents)}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[Warning] Consider creating agents in the database or reducing AGENTS_PER_GAME{Style.RESET_ALL}")

    print(f"Initializing {CONCURRENT_GAMES_COUNT} game instance(s) simultaneously (via lifespan)...")
    # Start the configured number of games
    for i in range(CONCURRENT_GAMES_COUNT):
        await create_new_game_instance(app_instance)
    
    print(f"{CONCURRENT_GAMES_COUNT} game instances are now running concurrently.")
    print(f"Auto-restart games: {'Enabled' if AUTO_RESTART_GAMES else 'Disabled'}")
    
    # Start periodic maintenance task
    maintenance_task = None
    if AUTO_RESTART_GAMES:
        maintenance_task = asyncio.create_task(periodic_game_maintenance(app_instance))
        print(f"Periodic game maintenance started (interval: {MAINTENANCE_INTERVAL}s)")
    
    yield # Server is running
    
    print("FastAPI server shutting down (via lifespan)...")
    
    # Cancel maintenance task first
    if maintenance_task and not maintenance_task.done():
        print("Cancelling periodic maintenance task...")
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            print("Maintenance task cancelled successfully.")
        except Exception as e:
            print(f"Error during maintenance task cancellation: {e}")
    
    if hasattr(app_instance.state, 'game_tasks') and app_instance.state.game_tasks:
        tasks_to_cancel = list(app_instance.state.game_tasks.items()) # Iterate over a copy
        print(f"Found {len(tasks_to_cancel)} game tasks to potentially cancel.")
        
        for game_uid_to_cancel, task_to_cancel in tasks_to_cancel:
            if task_to_cancel and not task_to_cancel.done():
                print(f"Cancelling game task for G_UID:{game_uid_to_cancel}...")
                task_to_cancel.cancel()
                try:
                    await task_to_cancel
                except asyncio.CancelledError:
                    print(f"Game task for G_UID:{game_uid_to_cancel} successfully cancelled.")
                except Exception as e:
                    # Log error that occurred during task cancellation/awaiting, 
                    # e.g., if the task raised an exception other than CancelledError on being cancelled.
                    print(f"{Fore.RED}Error during game task G_UID:{game_uid_to_cancel} cancellation/shutdown: {e}{Style.RESET_ALL}")
            elif task_to_cancel and task_to_cancel.done():
                print(f"Game task for G_UID:{game_uid_to_cancel} was already done.")
                # Optionally, check task_to_cancel.exception() if it was done with an error.
                if task_to_cancel.exception():
                    print(f"{Fore.YELLOW}  Task G_UID:{game_uid_to_cancel} had an exception: {task_to_cancel.exception()}{Style.RESET_ALL}")

    # Ensure active_games is cleaned up, though start_monopoly_game_instance's finally should handle most.
    if hasattr(app_instance.state, 'active_games'):
        active_game_keys = list(app_instance.state.active_games.keys())
        if active_game_keys:
            print(f"{Fore.YELLOW}Force cleaning up {len(active_game_keys)} GCs from app.state.active_games during shutdown: {active_game_keys}{Style.RESET_ALL}")
            for game_uid_cleanup in active_game_keys:
                # Game instance's finally block should have removed it. This is a fallback.
                if game_uid_cleanup in app_instance.state.active_games:
                     del app_instance.state.active_games[game_uid_cleanup]
                     print(f"{Fore.YELLOW}  Force removed game controller for {game_uid_cleanup} from app state.{Style.RESET_ALL}")
        app_instance.state.active_games.clear()

    print("Server shutdown complete.")

# 8. Instantiate FastAPI app
app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:3001", 
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        "null"  # For file:// origins
    ], 
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# 9. Define routes
@app.get("/api/lobby/games")
async def get_lobby_games_api(request: Request):
    active_games_info = []
    if not hasattr(request.app.state, 'active_games'):
        print(f"{Fore.RED}[API E] active_games not found in app.state for lobby. Server not initialized correctly?{Style.RESET_ALL}")
        # Return empty list or error, an empty list might be better for frontend resilience
        return [] 
        # raise HTTPException(status_code=500, detail="Server error: Game state not available.")

    # Accessing NUM_PLAYERS from main, ensure it's available or pass to GC and store there
    try:
        from main import NUM_PLAYERS as MAX_PLAYERS_CONST # Assuming this is the max players per game
    except ImportError:
        MAX_PLAYERS_CONST = 4 # Default fallback
        print(f"{Fore.YELLOW}[API W] Could not import NUM_PLAYERS from main for lobby, defaulting to {MAX_PLAYERS_CONST}{Style.RESET_ALL}")


    active_game_controllers = list(request.app.state.active_games.values()) # Get a list of current GC instances

    for gc_instance in active_game_controllers:
        if gc_instance: # Ensure instance is not None
            game_status = "in_progress"
            if gc_instance.game_over:
                game_status = "completed"
            # Add more sophisticated status if available, e.g. gc_instance.status if it exists
            # For "initializing" or "waiting_for_players", that state might be in DB before GC is fully ready or if GC has such a state.
            # This simple version assumes active_games only holds fully started or completed games from GC perspective.

            players_info = []
            for p in gc_instance.players:
                players_info.append({
                    "id": p.player_id,
                    "name": p.name,
                    "is_ai": p.is_ai, # Assuming Player object has is_ai attribute
                    "is_bankrupt": p.is_bankrupt
                })
            
            game_info = {
                "game_uid": gc_instance.game_uid,
                "status": game_status,
                "current_players_count": len(gc_instance.players), # Or count non-bankrupt if that's more relevant
                "max_players": gc_instance.num_players if hasattr(gc_instance, 'num_players') else MAX_PLAYERS_CONST, # Get from GC if stored, else constant
                "players": players_info,
                "turn_count": gc_instance.turn_count if hasattr(gc_instance, 'turn_count') else 0
            }
            active_games_info.append(game_info)
    
    return active_games_info

@app.get("/api/game/{game_id}/board_layout")
async def get_board_layout_api(game_id: str, request: Request):
    if not hasattr(request.app.state, 'active_games'):
        print(f"{Fore.RED}[API E] active_games not found in app.state. Server not initialized correctly?{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Server error: Game state not available.")

    gc_instance = request.app.state.active_games.get(game_id)
    
    if not gc_instance:
        not_found_msg = f"Game {game_id} not found or not active."
        print(f"{Fore.YELLOW}[API W] {not_found_msg}{Style.RESET_ALL}")
        raise HTTPException(status_code=404, detail=not_found_msg)
        
    if not hasattr(gc_instance, 'get_board_layout_for_frontend'):
        method_missing_msg = f"Game controller for {game_id} is missing 'get_board_layout_for_frontend' method."
        print(f"{Fore.RED}[API E] {method_missing_msg}{Style.RESET_ALL}")
        raise HTTPException(status_code=501, detail="Server error: Feature not implemented on game controller.")
        
    try:
        board_layout = gc_instance.get_board_layout_for_frontend() 
        return {"game_id": game_id, "board_layout": board_layout, "status": "success"}
    except Exception as e:
        error_msg = f"Failed to retrieve board layout for game {game_id} due to an internal error."
        print(f"{Fore.RED}[API E] Error in get_board_layout_for_frontend for {game_id}: {e}{Style.RESET_ALL}")
        # Log the full exception `e` for server-side debugging.
        raise HTTPException(status_code=500, detail=error_msg)

@app.websocket("/ws/lobby")
async def websocket_lobby_endpoint(websocket: WebSocket):
    await manager.connect_to_lobby(websocket)
    try:
        while True:
            data = await websocket.receive_text() # Lobby WS can be mostly for receiving broadcasts
            print(f"Message from lobby client (should be rare, mostly broadcasts from server): {data}")
            # Optionally, handle incoming messages from lobby clients if needed (e.g., refresh request)
    except WebSocketDisconnect:
        print(f"Lobby WS Explicitly Disconnected by client.")
    except Exception as e:
        print(f"Error in Lobby WS connection: {e}")
    finally:
        manager.disconnect_from_lobby(websocket)

@app.websocket("/ws/game/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    await manager.connect(websocket, game_id)
    try:
        while True: data = await websocket.receive_text(); print(f"Msg from client (G:{game_id}): {data}")
    except WebSocketDisconnect: print(f"WS Explicitly Disconnected by client for G:{game_id}.")
    except Exception as e: print(f"Error in WS connection for G:{game_id}: {e}")
    finally: manager.disconnect(websocket, game_id)

@app.get("/api/admin/games/status")
async def get_games_status_api(request: Request):
    """Get detailed status of all games"""
    try:
        status = get_game_status(request.app)
        return status
    except Exception as e:
        print(f"{Fore.RED}[API E] Error getting games status: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to get games status")

@app.post("/api/admin/games/create")
async def create_game_api(request: Request):
    """Manually create a new game instance"""
    try:
        game_uid = await create_new_game_instance(request.app)
        return {"success": True, "game_uid": game_uid, "message": f"Game {game_uid} created successfully"}
    except Exception as e:
        print(f"{Fore.RED}[API E] Error creating new game: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to create new game")

@app.post("/api/admin/games/maintain")
async def trigger_maintenance_api(request: Request):
    """Manually trigger game count maintenance"""
    try:
        await maintain_game_count(request.app)
        status = get_game_status(request.app)
        return {"success": True, "message": "Maintenance completed", "status": status}
    except Exception as e:
        print(f"{Fore.RED}[API E] Error during manual maintenance: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to perform maintenance")

@app.get("/api/admin/config")
async def get_config_api():
    """Get current configuration"""
    return {
        "concurrent_games_count": CONCURRENT_GAMES_COUNT,
        "auto_restart_games": AUTO_RESTART_GAMES,
        "maintenance_interval": MAINTENANCE_INTERVAL,
        "game_counter": GAME_COUNTER
    }

@app.post("/api/admin/config")
async def update_config_api(request: Request):
    """Update configuration (supports concurrent_games_count and auto_restart_games)"""
    global CONCURRENT_GAMES_COUNT, AUTO_RESTART_GAMES
    
    try:
        data = await request.json()
        
        if "concurrent_games_count" in data:
            new_count = int(data["concurrent_games_count"])
            if new_count < 0 or new_count > 10:  # Reasonable limits
                raise HTTPException(status_code=400, detail="concurrent_games_count must be between 0 and 10")
            
            old_count = CONCURRENT_GAMES_COUNT
            CONCURRENT_GAMES_COUNT = new_count
            print(f"{Fore.GREEN}[Config] Updated concurrent_games_count from {old_count} to {new_count}{Style.RESET_ALL}")
            
            # Trigger maintenance to adjust game count immediately
            await maintain_game_count(request.app)
        
        if "auto_restart_games" in data:
            AUTO_RESTART_GAMES = bool(data["auto_restart_games"])
            print(f"{Fore.GREEN}[Config] Updated auto_restart_games to {AUTO_RESTART_GAMES}{Style.RESET_ALL}")
        
        return {
            "success": True, 
            "message": "Configuration updated successfully",
            "new_config": {
                "concurrent_games_count": CONCURRENT_GAMES_COUNT,
                "auto_restart_games": AUTO_RESTART_GAMES,
                "maintenance_interval": MAINTENANCE_INTERVAL,
                "game_counter": GAME_COUNTER
            }
        }
    
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid value: {e}")
    except Exception as e:
        print(f"{Fore.RED}[API E] Error updating config: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to update configuration")

@app.post("/api/admin/agents/create_defaults")
async def create_default_agents_api():
    """Create default agents for testing"""
    try:
        default_agents = [
            {"name": "Wall Street Wolf", "personality": "Aggressive trader focused on quick profits and hostile takeovers"},
            {"name": "Warren Wisdom", "personality": "Conservative long-term strategist who thinks decades ahead"},
            {"name": "Smooth Talker Sally", "personality": "Charismatic negotiator who can convince anyone of anything"},
            {"name": "Casino Charlie", "personality": "High-risk high-reward gambler who lives for the thrill"},
            # {"name": "Professor Numbers", "personality": "Data-driven analytical genius who calculates every probability"},
            # {"name": "Vulture Victor", "personality": "Opportunistic scavenger who swoops in on distressed assets"},
            # {"name": "Friendship Frank", "personality": "Collaborative deal-maker who believes everyone can win"},
            # {"name": "Zen Master Min", "personality": "Minimalist philosopher focused only on essential moves"}
        ]
        
        created_agents = []
        with Session(engine) as session:
            for agent_data in default_agents:
                agent_uid = f"agent_{agent_data['name'].lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
                
                # Create tpay account for this agent
                tpay_account_id = None
                try:
                    print(f"{Fore.CYAN}[TPay] Creating account for agent: {agent_data['name']}{Style.RESET_ALL}")
                    
                    tpay_agent_data = tpay.create_agent(
                        name=agent_data['name'],
                        description=f"Monopoly AI agent: {agent_data['personality']}",
                        agent_daily_limit=10000.0,  # High limit for monopoly transactions
                        agent_type="autonomous_agent"
                    )
                    
                    if tpay_agent_data and 'id' in tpay_agent_data:
                        tpay_account_id = tpay_agent_data['id']
                        print(f"{Fore.GREEN}[TPay] Successfully created account for {agent_data['name']} with ID: {tpay_account_id}{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.RED}[TPay] Failed to create account for {agent_data['name']} - no ID returned{Style.RESET_ALL}")
                        
                except Exception as tpay_error:
                    print(f"{Fore.RED}[TPay] Error creating account for {agent_data['name']}: {tpay_error}{Style.RESET_ALL}")
                
                # Create agent record in database (even if tpay failed)
                agent_values = {
                    "agent_uid": agent_uid,
                    "name": agent_data['name'],
                    "personality_prompt": agent_data['personality'],
                    "memory_data": {},
                    "preferences": {},
                    "total_games_played": 0,
                    "total_wins": 0,
                    "tpay_account_id": tpay_account_id,  # Will be None if tpay creation failed
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
                        "personality": agent_data['personality'],
                        "tpay_account_id": tpay_account_id,
                        "tpay_status": "created" if tpay_account_id else "failed"
                    })
            
            session.commit()
        
        # Reload agents in agent manager
        await agent_manager.initialize_agents_from_database()
        
        successful_tpay = len([a for a in created_agents if a['tpay_account_id']])
        
        return {
            "success": True,
            "message": f"Created {len(created_agents)} agents ({successful_tpay} with tpay accounts)",
            "agents": created_agents,
            "tpay_success_count": successful_tpay,
            "tpay_total_count": len(created_agents)
        }
    
    except Exception as e:
        print(f"{Fore.RED}[API E] Error creating default agents: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to create default agents")

@app.get("/api/admin/agents")
async def get_agents_api():
    """Get all agents and their status"""
    try:
        # Get detailed info from database
        with Session(engine) as session:
            stmt = select(agents_table)
            result = session.execute(stmt)
            all_agents = result.fetchall()
            
            agents_with_tpay = len([a for a in all_agents if a.tpay_account_id])
            agents_without_tpay = len(all_agents) - agents_with_tpay
        
        agents_info = {
            "available_agents": len(agent_manager.available_agents),
            "agents_in_game": len(agent_manager.agents_in_game),
            "total_agent_instances": len(agent_manager.agent_instances),
            "total_agents_in_db": len(all_agents),
            "agents_with_tpay": agents_with_tpay,
            "agents_without_tpay": agents_without_tpay,
            "available_agents_list": agent_manager.available_agents,
            "agents_in_game_mapping": agent_manager.agents_in_game
        }
        return agents_info
    except Exception as e:
        print(f"{Fore.RED}[API E] Error getting agents info: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to get agents information")

@app.post("/api/admin/agents/create_game_tokens")
async def create_game_token_accounts_api(request: Request):
    """Create game token accounts for all agents"""
    try:
        data = await request.json() if hasattr(request, 'json') else {}
        game_token = data.get('game_token', utils.GAME_TOKEN_SYMBOL)
        initial_balance = data.get('initial_balance', utils.GAME_INITIAL_BALANCE)
        
        # Get all agents with tpay accounts
        with Session(engine) as session:
            stmt = select(agents_table).where(agents_table.c.tpay_account_id.is_not(None))
            result = session.execute(stmt)
            agents_with_tpay = result.fetchall()
        
        if not agents_with_tpay:
            raise HTTPException(status_code=400, detail="No agents with tpay accounts found")
        
        agent_tpay_ids = [agent.tpay_account_id for agent in agents_with_tpay]
        agent_names = [agent.name for agent in agents_with_tpay]
        
        print(f"{Fore.CYAN}[API] Creating {game_token} accounts for {len(agent_tpay_ids)} agents{Style.RESET_ALL}")
        
        # Create game token accounts
        results = utils.create_game_token_accounts_for_agents(
            agent_tpay_ids=agent_tpay_ids,
            game_token=game_token,
            initial_balance=initial_balance,
            network="solana"
        )
        
        return {
            "success": True,
            "message": f"Created {game_token} accounts for agents",
            "game_token": game_token,
            "initial_balance": initial_balance,
            "results": results,
            "successful_accounts": len(results['success']),
            "failed_accounts": len(results['failed']),
            "total_processed": results['total_processed']
        }
    
    except Exception as e:
        print(f"{Fore.RED}[API E] Error creating game token accounts: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to create game token accounts")

@app.post("/api/admin/agents/{agent_id}/reset_game_balance")
async def reset_agent_game_balance_api(agent_id: int, request: Request):
    """Reset a specific agent's game token balance"""
    try:
        data = await request.json() if hasattr(request, 'json') else {}
        game_token = data.get('game_token', utils.GAME_TOKEN_SYMBOL)
        new_balance = data.get('new_balance', utils.GAME_INITIAL_BALANCE)
        
        # Get agent's tpay account ID
        with Session(engine) as session:
            stmt = select(agents_table).where(agents_table.c.id == agent_id)
            result = session.execute(stmt)
            agent_row = result.fetchone()
        
        if not agent_row:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        if not agent_row.tpay_account_id:
            raise HTTPException(status_code=400, detail="Agent has no tpay account")
        
        print(f"{Fore.CYAN}[API] Resetting {game_token} balance for agent {agent_row.name} to ${new_balance}{Style.RESET_ALL}")
        
        success = utils.reset_agent_game_balance(
            agent_id=agent_row.tpay_account_id,
            game_token=game_token,
            new_balance=new_balance
        )
        
        if success:
            return {
                "success": True,
                "message": f"Successfully reset {game_token} balance for {agent_row.name}",
                "agent_name": agent_row.name,
                "agent_id": agent_id,
                "tpay_account_id": agent_row.tpay_account_id,
                "game_token": game_token,
                "new_balance": new_balance
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to reset agent balance")
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"{Fore.RED}[API E] Error resetting agent balance: {e}{Style.RESET_ALL}")
        raise HTTPException(status_code=500, detail="Failed to reset agent balance")

if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server for Monopoly...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False) 