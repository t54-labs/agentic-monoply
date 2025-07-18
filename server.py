import asyncio
import json
import random  # Added for random turn delays
import threading
from concurrent.futures import ThreadPoolExecutor
from queue import Queue as SyncQueue, Empty
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any, Optional
import datetime
import os
import uuid
from contextlib import asynccontextmanager

# Log system import
import logging
import sys
from pathlib import Path

import tpay
from tpay.tools import taudit_verifier

from game_logic.player import Player
from game_logic.game_controller_v2 import GameControllerV2
from ai_agent.agent import OpenAIAgent
from main import TOOL_REGISTRY, NUM_PLAYERS, PLAYER_NAMES, MAX_TURNS, ACTION_DELAY_SECONDS, MAX_ACTIONS_PER_SEGMENT, execute_agent_action, print_game_summary, _setup_tool_placeholders
from colorama import init, Fore as ColoramaFore, Style as ColoramaStyle

# Import utils for tpay operations
import utils

# Import game event handler for notifications
from admin.game_event_handler import initialize_game_event_handler, get_game_event_handler

# 2. Database and SQLAlchemy imports
from database import create_db_and_tables, engine, games_table, players_table, game_turns_table, agent_actions_table, agents_table
from sqlalchemy import insert, update, select, func
from sqlalchemy.orm import Session 

# === log system ===
class LogFileManager:
    """Class for managing log file output"""
    def __init__(self):
        self.log_file = None
        self.setup_logging()
    
    def setup_logging(self):
        """Set up log file system"""
        try:
            # Create logs directory
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            
            # Generate timestamped log file name
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"monopoly_server_{timestamp}.log"
            log_path = logs_dir / log_filename
            
            # Create log file
            self.log_file = open(log_path, 'w', encoding='utf-8')
            
            # Use original print function to avoid recursion
            import builtins
            builtins.print(f"📝 Log file created successfully: {log_path}")
            self.log_to_file(f"📝 Log file creation time: {datetime.datetime.now().isoformat()}")
            self.log_to_file(f"📝 Server startup log started")
            self.log_to_file("=" * 80)
            
        except Exception as e:
            import builtins
            builtins.print(f"❌ Failed to create log file: {e}")
            self.log_file = None
    
    def log_to_file(self, message: str):
        """Write message to log file"""
        if self.log_file:
            try:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                self.log_file.write(f"[{timestamp}] {message}\n")
                self.log_file.flush()  # Write immediately to file
            except Exception as e:
                # If log writing fails, only output error to console to avoid infinite loop
                import builtins
                builtins.print(f"❌ 日志写入失败: {e}", file=sys.__stderr__)
    
    def close(self):
        """Close log file"""
        if self.log_file:
            try:
                self.log_to_file("=" * 80)
                self.log_to_file(f"📝 Server shutdown time: {datetime.datetime.now().isoformat()}")
                self.log_to_file(f"📝 Log file ended")
                self.log_file.close()
                import builtins
                builtins.print("📝 Log file closed")
            except Exception as e:
                import builtins
                builtins.print(f"❌ Failed to close log file: {e}")

# Create global log manager instance
log_manager = LogFileManager()

# Override print function to output to console and log file
original_print = print
def enhanced_print(*args, **kwargs):
    """Enhanced print function that outputs to console and log file"""
    # First call original print function to output to console
    original_print(*args, **kwargs)
    
    # Then write to log file
    try:
        # Get printed content
        if args:
            # Convert all arguments to strings and join
            sep = kwargs.get('sep', ' ')
            message = sep.join(str(arg) for arg in args)
            
            # Write to log file
            log_manager.log_to_file(message)
    except Exception as e:
        # If log writing fails, only output error to stderr to avoid recursion
        original_print(f"❌ Log writing failed: {e}", file=sys.__stderr__)

# Replace global print function
print = enhanced_print

# Signal handler to ensure log file is closed when program exits
import signal
import atexit

def cleanup_logs():
    """Function to clean up log file"""
    try:
        log_manager.close()
    except Exception as e:
        original_print(f"❌ Error cleaning up log file: {e}", file=sys.__stderr__)

def signal_handler(signum, frame):
    """Signal handler"""
    original_print(f"\n📝 Received signal {signum}, closing log file...")
    cleanup_logs()
    sys.exit(0)

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

# Register cleanup function when program exits
atexit.register(cleanup_logs)

# Game simulation configuration
CONCURRENT_GAMES_COUNT = 10  # Number of games to run simultaneously
AUTO_RESTART_GAMES = True  # Whether to start new games when current ones finish
GAME_COUNTER = 0  # Global counter for unique game numbering
MAINTENANCE_INTERVAL = 30  # Seconds between game count maintenance checks

# Agent management configuration
AGENTS_PER_GAME = NUM_PLAYERS     # Number of agents per game (should match NUM_PLAYERS)
AGENT_INITIAL_BALANCE = 1500  # Starting balance for each game

def print_startup_config():
    """Print startup configuration for debugging"""
    print(f"{Fore.CYAN}=== MONOPOLY GAME SERVER CONFIGURATION ==={Style.RESET_ALL}")
    print(f"{Fore.GREEN}Concurrent Games: {CONCURRENT_GAMES_COUNT}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Auto Restart: {AUTO_RESTART_GAMES}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Agents Per Game: {AGENTS_PER_GAME}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Maintenance Interval: {MAINTENANCE_INTERVAL}s{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Max Turns: {MAX_TURNS}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Action Delay: {ACTION_DELAY_SECONDS}s{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Treasury Agent ID: {TREASURY_AGENT_ID}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}============================================{Style.RESET_ALL}")

# 1. Colorama setup & Global placeholders
class Fore: CYAN=YELLOW=GREEN=RED=MAGENTA=WHITE=BLACK=BLUE=""; LIGHTBLACK_EX=LIGHTBLUE_EX=LIGHTCYAN_EX=LIGHTGREEN_EX=LIGHTMAGENTA_EX=LIGHTRED_EX=LIGHTWHITE_EX=LIGHTYELLOW_EX=""
class Style: RESET_ALL=BRIGHT=DIM=NORMAL="";
COLORAMA_OK = False
try: 
    init()
    Fore = ColoramaFore; Style = ColoramaStyle; COLORAMA_OK = True
    if os.getenv("RUN_CONTEXT") != "test" and __name__ == "__main__": 
        print(f"{Fore.GREEN}Colorama initialized.{Style.RESET_ALL}")
except ImportError: 
    if os.getenv("RUN_CONTEXT") != "test" and __name__ == "__main__": print("Colorama not found.")
    pass 

load_dotenv()

TLEDGER_API_KEY = os.getenv("TLEDGER_API_KEY")
TLEDGER_API_SECRET = os.getenv("TLEDGER_API_SECRET")
TLEDGER_PROJECT_ID = os.getenv("TLEDGER_PROJECT_ID")
TLEDGER_BASE_URL = os.getenv("TLEDGER_BASE_URL")
TREASURY_AGENT_ID = os.getenv("TREASURY_AGENT_ID")

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
        self._lock = threading.RLock()  # Thread-safe lock for agent operations
        
    async def initialize_agents_from_database(self):
        """Load all active agents from database and create their instances (safe for repeated calls)"""
        try:
            with Session(engine) as session:
                # Get all active agents from database
                stmt = select(agents_table).where(agents_table.c.status == 'active')
                result = session.execute(stmt)
                agents_data = result.fetchall()
                
                print(f"{Fore.GREEN}[Agent Manager] Found {len(agents_data)} active agents in database{Style.RESET_ALL}")
                
                new_agents_count = 0
                updated_agents_count = 0
                
                with self._lock:  # Thread-safe initialization
                    for agent_row in agents_data:
                        agent_uid = agent_row.agent_uid
                        
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
                        
                        # Create agent instance only if it doesn't exist
                        if agent_uid not in self.agent_instances:
                            agent_instance = OpenAIAgent(
                                agent_uid=agent_dict['agent_uid'],
                                player_id=-1,  # Will be set when joining a game
                                name=agent_dict['name'],
                                personality=agent_dict.get('personality_prompt', '')
                            )
                            self.agent_instances[agent_uid] = agent_instance
                            new_agents_count += 1
                        
                        # Check if agent is already in available pool or in game
                        agent_already_available = any(a['agent_uid'] == agent_uid for a in self.available_agents)
                        agent_in_game = agent_uid in self.agents_in_game
                        
                        # Only add to available pool if:
                        # 1. Agent is active in database
                        # 2. Agent is not already in available pool 
                        # 3. Agent is not currently in a game
                        if (agent_dict['status'] == 'active' and 
                            not agent_already_available and 
                            not agent_in_game):
                            self.available_agents.append(agent_dict)
                            updated_agents_count += 1
                        elif agent_in_game:
                            print(f"{Fore.CYAN}[Agent Manager] Agent {agent_dict['name']} is in game {self.agents_in_game[agent_uid]} - not adding to available pool{Style.RESET_ALL}")
                        elif agent_already_available:
                            print(f"{Fore.CYAN}[Agent Manager] Agent {agent_dict['name']} already in available pool - skipping{Style.RESET_ALL}")
                
                print(f"{Fore.GREEN}[Agent Manager] Initialization complete: {new_agents_count} new instances, {updated_agents_count} added to available pool, {len(self.available_agents)} total available{Style.RESET_ALL}")
                
        except Exception as e:
            print(f"{Fore.RED}[Agent Manager] Error initializing agents: {e}{Style.RESET_ALL}")
    
    def get_available_agents_for_game(self, num_needed: int) -> List[Dict[str, Any]]:
        """Thread-safely get and reserve available agents for a new game"""
        with self._lock:
            if len(self.available_agents) < num_needed:
                print(f"{Fore.YELLOW}[Agent Manager] Not enough available agents. Need {num_needed}, have {len(self.available_agents)}{Style.RESET_ALL}")
                return []
            
            # Select agents (for now, just take first N available)
            selected_agents = self.available_agents[:num_needed]
            
            # Remove selected agents from available pool IMMEDIATELY to prevent double allocation
            for agent in selected_agents:
                if agent in self.available_agents:
                    self.available_agents.remove(agent)
                    # print(f"{Fore.CYAN}[Agent Manager] Reserved agent {agent['name']} for new game{Style.RESET_ALL}")
            
            return selected_agents
    
    def assign_agents_to_game(self, agents: List[Dict[str, Any]], game_uid: str):
        """Assign agents to a specific game (agents should already be removed from available pool)"""
        with self._lock:
            for agent in agents:
                # Double-check agent status before assigning to game
                try:
                    with Session(engine) as session:
                        stmt = select(agents_table.c.status).where(agents_table.c.agent_uid == agent['agent_uid'])
                        current_status = session.execute(stmt).scalar_one_or_none()
                        
                        if current_status == 'inactive':
                            print(f"{Fore.YELLOW}[Agent Manager] Agent {agent['name']} is inactive - skipping assignment to game {game_uid}{Style.RESET_ALL}")
                            continue
                            
                except Exception as e:
                    print(f"{Fore.RED}[Agent Manager] Error checking agent status for {agent['agent_uid']}: {e}{Style.RESET_ALL}")
                    # Continue with assignment if we can't check status
                
                self.agents_in_game[agent['agent_uid']] = game_uid
                # Update status in database
                self._update_agent_status(agent['agent_uid'], 'in_game')
                print(f"{Fore.GREEN}[AGENT STATE] 🎮 Agent {agent['name']} ({agent['agent_uid']}) assigned to game {game_uid}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}[AGENT STATE]    📊 Status: active → in_game, Total in game: {len(self.agents_in_game)}{Style.RESET_ALL}")
    
    def release_agents_from_game(self, game_uid: str):
        """Release agents back to available pool when game ends"""
        with self._lock:
            agents_to_release = [agent_uid for agent_uid, g_uid in self.agents_in_game.items() if g_uid == game_uid]
            
            for agent_uid in agents_to_release:
                # Remove from in_game mapping
                del self.agents_in_game[agent_uid]
                
                # Get agent's information from database and reset status to active
                try:
                    with Session(engine) as session:
                        stmt = select(agents_table).where(agents_table.c.agent_uid == agent_uid)
                        result = session.execute(stmt)
                        agent_row = result.fetchone()
                        
                        if agent_row:
                            # First, update agent status back to 'active'
                            if agent_row.status in ['in_game', 'active']:
                                # Update status to active if currently in_game or already active
                                update_stmt = update(agents_table).where(
                                    agents_table.c.agent_uid == agent_uid
                                ).values(
                                    status='active',
                                    last_active=func.now()
                                )
                                session.execute(update_stmt)
                                session.commit()
                                
                                # Now add back to available pool
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
                                    'status': 'active'  # Set to active since we just updated it
                                }
                                self.available_agents.append(agent_dict)
                                print(f"{Fore.BLUE}[AGENT STATE] 🔄 Agent {agent_dict['name']} released from game {game_uid}{Style.RESET_ALL}")
                                print(f"{Fore.BLUE}[AGENT STATE]    📊 Status: {agent_row.status} → active, Available pool: {len(self.available_agents)}{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.YELLOW}[Agent Manager] Agent {agent_row.name} has status '{agent_row.status}' - not adding back to available pool{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}[Agent Manager] Agent {agent_uid} not found in database{Style.RESET_ALL}")
                            
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
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent manager status for debugging"""
        with self._lock:
            return {
                "available_agents_count": len(self.available_agents),
                "available_agents": [a['name'] for a in self.available_agents],
                "agents_in_game_count": len(self.agents_in_game),
                "agents_in_game": list(self.agents_in_game.items()),
                "total_agent_instances": len(self.agent_instances)
            }

# Global agent manager instance
agent_manager = AgentManager()

# 4.6. Thread-Safe Game Instance Manager
class ThreadSafeGameInstance:
    """
    Thread-safe game instance management class that runs game logic in separate threads
    Prevents TPay and other async operations from blocking the main server event loop
    """
    def __init__(self, game_uid: str, connection_manager: ConnectionManager, 
                 app_instance: FastAPI, available_agents: List[Dict[str, Any]]):
        self.game_uid = game_uid
        self.connection_manager = connection_manager
        self.app_instance = app_instance
        self.available_agents = available_agents
        
        # Thread-related attributes
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False
        self.game_controller: Optional[GameControllerV2] = None
        
        # Thread-safe state access
        self._state_lock = threading.RLock()
        self._cached_state = {}
        self._state_update_time = 0
        
        # Thread-safe message queue for WebSocket communication
        self._message_queue = asyncio.Queue()
        self._queue_processor_task = None
        self._main_loop = asyncio.get_event_loop()  # Save reference to main thread's event loop
        
    def start(self):
        """Start game in a separate thread"""
        if self.running:
            print(f"{Fore.YELLOW}[Game Thread] Game {self.game_uid} is already running{Style.RESET_ALL}")
            return
        
        # Set running flag BEFORE starting threads to avoid race condition
        self.running = True
            
        # Start message queue processor in main thread
        self._start_message_queue_processor()
            
        self.thread = threading.Thread(target=self._run_game_thread, daemon=True)
        self.thread.start()
        print(f"{Fore.GREEN}[Game Thread] Started game {self.game_uid} in thread {self.thread.ident}{Style.RESET_ALL}")
        
    def _run_game_thread(self):
        """Main game thread function - runs complete game logic in separate thread"""
        # Create new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # running is already set to True in start() method
        
        try:
            print(f"{Fore.CYAN}[Game Thread] Running game {self.game_uid} in thread {threading.current_thread().ident}{Style.RESET_ALL}")
            # Run game in this thread's event loop
            self.loop.run_until_complete(self._run_game_async())
            print(f"{Fore.GREEN}[Game Thread] Game {self.game_uid} completed successfully{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[Game Thread] Game {self.game_uid} error: {e}{Style.RESET_ALL}")
            import traceback
            print(f"{Fore.RED}[Game Thread] Full traceback for {self.game_uid}:{Style.RESET_ALL}")
            traceback.print_exc()
            
            # Additional debugging info
            print(f"{Fore.YELLOW}[Game Thread] Error details for {self.game_uid}:{Style.RESET_ALL}")
            print(f"  - Error type: {type(e).__name__}")
            print(f"  - Error message: {str(e)}")
            print(f"  - Thread ID: {threading.current_thread().ident}")
            print(f"  - Loop running: {self.loop and not self.loop.is_closed() if self.loop else 'No loop'}")
        finally:
            self.running = False  # Set to False when game truly ends
            
            print(f"{Fore.YELLOW}[Game Thread] Cleaning up game {self.game_uid}...{Style.RESET_ALL}")
            
            # Stop message queue processor
            if self._queue_processor_task and not self._queue_processor_task.done():
                self._queue_processor_task.cancel()
                print(f"{Fore.YELLOW}[Game Thread] Cancelled message queue processor for {self.game_uid}{Style.RESET_ALL}")
            
            if self.loop:
                try:
                    # Close any remaining tasks
                    pending_tasks = [task for task in asyncio.all_tasks(self.loop) if not task.done()]
                    if pending_tasks:
                        print(f"{Fore.YELLOW}[Game Thread] Cancelling {len(pending_tasks)} pending tasks for {self.game_uid}{Style.RESET_ALL}")
                        for task in pending_tasks:
                            task.cancel()
                    
                    self.loop.close()
                    print(f"{Fore.GREEN}[Game Thread] Loop closed successfully for {self.game_uid}{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}[Game Thread] Error closing loop for {self.game_uid}: {e}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[Game Thread] Game {self.game_uid} thread finished{Style.RESET_ALL}")
    
    async def _run_game_async(self):
        """Run game logic asynchronously in separate thread's event loop"""
        # Run the original start_monopoly_game_instance logic here
        # but in separate thread and event loop, won't block main server
        await start_monopoly_game_instance(
            self.game_uid, 
            self.connection_manager, 
            self.app_instance, 
            self.available_agents
        )
    
    def get_state_safely(self, player_id: int) -> Optional[Dict[str, Any]]:
        """Thread-safely get game state"""
        with self._state_lock:
            try:
                if not self.running or not self.game_controller:
                    return None
                    
                # Caching mechanism to avoid frequent cross-thread access
                import time
                current_time = time.time()
                cache_key = f"player_{player_id}"
                
                if (cache_key in self._cached_state and 
                    current_time - self._state_update_time < 1.0):  # 1 second cache
                    return self._cached_state[cache_key]
                
                # Get latest state
                state = self.game_controller.get_game_state_for_agent(player_id)
                self._cached_state[cache_key] = state
                self._state_update_time = current_time
                
                return state
            except Exception as e:
                print(f"{Fore.RED}[Game Thread] Error getting state for {self.game_uid}: {e}{Style.RESET_ALL}")
                return None
    
    def get_board_layout_safely(self) -> Optional[List[Dict[str, Any]]]:
        """Thread-safely get board layout"""
        with self._state_lock:
            try:
                if not self.running or not self.game_controller:
                    return None
                    
                # Check cache
                import time
                current_time = time.time()
                cache_key = "board_layout"
                
                if (cache_key in self._cached_state and 
                    current_time - self._state_update_time < 5.0):  # 5 second cache (board changes less frequently)
                    return self._cached_state[cache_key]
                
                # Get latest board layout
                layout = self.game_controller.get_board_layout_for_frontend()
                self._cached_state[cache_key] = layout
                self._state_update_time = current_time
                
                return layout
            except Exception as e:
                print(f"{Fore.RED}[Game Thread] Error getting board layout for {self.game_uid}: {e}{Style.RESET_ALL}")
                return None
    
    def is_running(self) -> bool:
        """Check if game is currently running"""
        return self.running and self.thread and self.thread.is_alive()
    
    def get_basic_info(self) -> Dict[str, Any]:
        """Get basic game info (no locks needed)"""
        info = {
            "game_uid": self.game_uid,
            "running": self.is_running(),
            "thread_id": self.thread.ident if self.thread else None,
            "has_controller": self.game_controller is not None
        }
        
        # Try to get basic state info
        try:
            if self.game_controller:
                info.update({
                    "turn_count": getattr(self.game_controller, 'turn_count', 0),
                    "game_over": getattr(self.game_controller, 'game_over', False),
                    "current_player": getattr(self.game_controller, 'current_player_index', 0),
                    "player_count": len(getattr(self.game_controller, 'players', []))
                })
        except Exception:
            pass  # Ignore errors when getting state
            
        return info
    
    def _start_message_queue_processor(self):
        """Start message queue processor in main thread"""
        if self._queue_processor_task is None or self._queue_processor_task.done():
            self._queue_processor_task = asyncio.create_task(self._process_message_queue())
            print(f"{Fore.CYAN}[Game Thread] Started message queue processor for {self.game_uid}{Style.RESET_ALL}")
    
    async def _process_message_queue(self):
        """Process messages from game thread and send to frontend (runs in main thread)"""
        try:
            while self.is_running():
                try:
                    # Get message from async queue with timeout
                    message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                    
                    # Check if this is a special event notification
                    if message.get('type') == 'special_event_notification':
                        # Handle special event notification
                        event_handler = get_game_event_handler()
                        if event_handler:
                            await event_handler.handle_special_event(
                                message.get('game_uid', self.game_uid),
                                message.get('event_type', ''),
                                message.get('player_name', ''),
                                message.get('event_data', {})
                            )
                    elif message.get('type') == 'action_error_notification':
                        # Handle action error notification for Telegram
                        try:
                            from admin import get_telegram_notifier
                            telegram_notifier = get_telegram_notifier()
                            if telegram_notifier and telegram_notifier.enabled:
                                error_data = message.get('data', {})
                                await telegram_notifier.notify_action_error(error_data)
                        except Exception as e:
                            print(f"{Fore.RED}[Game Thread] Error sending action error notification: {e}{Style.RESET_ALL}")
                    elif message.get('type') == 'property_landing_notification':
                        # Handle property landing notification for Telegram
                        try:
                            from admin import get_telegram_notifier
                            telegram_notifier = get_telegram_notifier()
                            if telegram_notifier and telegram_notifier.enabled:
                                landing_message = message.get('message', '')
                                if landing_message:
                                    await telegram_notifier.send_message(landing_message)
                                    print(f"{Fore.GREEN}📱 [Property Landing] Telegram notification sent successfully{Style.RESET_ALL}")
                        except Exception as e:
                            print(f"{Fore.RED}[Game Thread] Error sending property landing notification: {e}{Style.RESET_ALL}")
                    else:
                        # Send regular message via connection manager in main thread
                        await self.connection_manager.broadcast_to_game(self.game_uid, message)
                    
                    # Mark task as done
                    self._message_queue.task_done()
                    
                except asyncio.TimeoutError:
                    # No messages in queue, continue polling
                    continue
                except Exception as e:
                    print(f"{Fore.RED}[Game Thread] Error processing message for {self.game_uid}: {e}{Style.RESET_ALL}")
                    continue
                    
        except Exception as e:
            print(f"{Fore.RED}[Game Thread] Message queue processor error for {self.game_uid}: {e}{Style.RESET_ALL}")
        finally:
            print(f"{Fore.YELLOW}[Game Thread] Message queue processor stopped for {self.game_uid}{Style.RESET_ALL}")
    
    def send_message_safely(self, message: Dict[str, Any]):
        """Thread-safely queue a message for sending to frontend"""
        try:
            # Schedule the put operation in the main thread's event loop
            asyncio.run_coroutine_threadsafe(self._message_queue.put(message), self._main_loop)
        except Exception as e:
            print(f"{Fore.RED}[Game Thread] Failed to queue message for {self.game_uid}: {e}{Style.RESET_ALL}")

# Global game instance manager
game_instances: Dict[str, ThreadSafeGameInstance] = {}

# Global app instance reference (for cross-thread access)
global_app_instance: Optional[FastAPI] = None

# Global lock for game count maintenance
_game_maintenance_lock = threading.RLock()

async def initialize_agent_tpay_balances(available_agents: List[Dict[str, Any]], game_uid: str):
    """Initialize game token accounts for agents at game start via real TPay payments"""
    
    print(f"{Fore.CYAN}[TPay] Balancing {utils.GAME_TOKEN_SYMBOL} accounts for {len(available_agents)} agents in game {game_uid} via real payments{Style.RESET_ALL}")
    
    # Extract tpay account IDs and names from available agents
    agent_data_list = []
    
    for agent_data in available_agents:
        tpay_account_id = agent_data.get('tpay_account_id')
        if not tpay_account_id:
            print(f"{Fore.YELLOW}[TPay] Agent {agent_data['name']} has no tpay account, skipping balance adjustment{Style.RESET_ALL}")
            continue
        
        agent_data_list.append({
            'tpay_id': tpay_account_id,
            'name': agent_data['name'],
            'db_id': agent_data.get('id', None)
        })
    
    if not agent_data_list:
        print(f"{Fore.RED}[TPay] No agents with valid TPay accounts found for game {game_uid}{Style.RESET_ALL}")
        return
    
    try:
        # Get treasury agent ID
        treasury_agent_id = os.getenv('TREASURY_AGENT_ID')
        if not treasury_agent_id:
            print(f"{Fore.RED}[TPay] No TREASURY_AGENT_ID configured, cannot balance agent accounts{Style.RESET_ALL}")
            return
        
        # Track results for summary reporting
        success_count = 0
        failure_count = 0
        no_action_count = 0
        total_excess_collected = 0.0
        total_deficit_provided = 0.0
        detailed_results = []
        
        # Process each agent's balance adjustment
        for agent_info in agent_data_list:
            agent_id = agent_info['tpay_id']
            agent_name = agent_info['name']
            
            print(f"{Fore.BLUE}[TPay] Processing balance adjustment for {agent_name} ({agent_id}){Style.RESET_ALL}")
            
            # Call the new balance adjustment function
            result = await utils.balance_agent_game_balance_via_payments(
                agent_id=agent_id,
                treasury_agent_id=treasury_agent_id,
                target_balance=utils.GAME_INITIAL_BALANCE,
                game_token=utils.GAME_TOKEN_SYMBOL,
                game_uid=game_uid,
                agent_name=agent_name
            )
            
            detailed_results.append(result)
            
            if result['success']:
                action = result.get('action', 'unknown')
                
                if action == 'no_action_needed':
                    no_action_count += 1
                    print(f"{Fore.GREEN}[TPay] ✓ {agent_name}: {result['message']}{Style.RESET_ALL}")
                    
                elif action == 'excess_paid_to_treasury':
                    success_count += 1
                    amount = result.get('amount_paid', 0)
                    total_excess_collected += amount
                    payment_id = result.get('payment_id', 'N/A')
                    print(f"{Fore.GREEN}[TPay] ✓ {agent_name}: Paid {amount:.2f} excess to treasury (Payment ID: {payment_id}) - COMPLETED{Style.RESET_ALL}")
                    
                elif action == 'deficit_paid_by_treasury':
                    success_count += 1
                    amount = result.get('amount_received', 0)
                    total_deficit_provided += amount
                    payment_id = result.get('payment_id', 'N/A')
                    print(f"{Fore.GREEN}[TPay] ✓ {agent_name}: Received {amount:.2f} from treasury (Payment ID: {payment_id}) - COMPLETED{Style.RESET_ALL}")
                    
                else:
                    success_count += 1
                    print(f"{Fore.GREEN}[TPay] ✓ {agent_name}: Balance adjusted successfully{Style.RESET_ALL}")
                    
            else:
                failure_count += 1
                error_msg = result.get('error', 'Unknown error')
                payment_id = result.get('payment_id')
                
                if payment_id:
                    print(f"{Fore.RED}[TPay] ✗ {agent_name}: {error_msg} (Payment ID: {payment_id}){Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}[TPay] ✗ {agent_name}: {error_msg}{Style.RESET_ALL}")
                
                # Log additional details for payment failures
                amount_attempted = result.get('amount_attempted')
                if amount_attempted:
                    print(f"{Fore.YELLOW}[TPay]   → Amount attempted: ${amount_attempted:.2f} {utils.GAME_TOKEN_SYMBOL}{Style.RESET_ALL}")
        
        # Print comprehensive summary
        print(f"{Fore.CYAN}[TPay] ========== BALANCE ADJUSTMENT SUMMARY FOR GAME {game_uid} =========={Style.RESET_ALL}")
        print(f"{Fore.GREEN}[TPay] ✓ Successful adjustments: {success_count}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}[TPay] ≈ No action needed: {no_action_count}{Style.RESET_ALL}")
        print(f"{Fore.RED}[TPay] ✗ Failed adjustments: {failure_count}{Style.RESET_ALL}")
        
        if total_excess_collected > 0:
            print(f"{Fore.YELLOW}[TPay] 💰 Total excess collected by treasury: {total_excess_collected:.2f} {utils.GAME_TOKEN_SYMBOL}{Style.RESET_ALL}")
            
        if total_deficit_provided > 0:
            print(f"{Fore.YELLOW}[TPay] 💸 Total deficit provided by treasury: {total_deficit_provided:.2f} {utils.GAME_TOKEN_SYMBOL}{Style.RESET_ALL}")
            
        net_treasury_change = total_excess_collected - total_deficit_provided
        if net_treasury_change != 0:
            direction = "gained" if net_treasury_change > 0 else "spent"
            print(f"{Fore.MAGENTA}[TPay] 🏦 Net treasury change: {direction} {abs(net_treasury_change):.2f} {utils.GAME_TOKEN_SYMBOL}{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}[TPay] ================================================================{Style.RESET_ALL}")
        
        # Store detailed results for potential debugging or auditing
        if hasattr(utils, 'last_balance_adjustment_results'):
            utils.last_balance_adjustment_results[game_uid] = detailed_results
        else:
            utils.last_balance_adjustment_results = {game_uid: detailed_results}
            
    except Exception as e:
        print(f"{Fore.RED}[TPay] Critical error during balance adjustment for game {game_uid}: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()

async def update_agent_game_statistics(available_agents: List[Dict[str, Any]], gc: GameControllerV2, 
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
                
                # Update game count
                total_games = agent_data.get('total_games_played', 0) + 1
                total_wins = agent_data.get('total_wins', 0)
                
                # Update win count if this agent won
                if winner_agent_id and agent_data['id'] == winner_agent_id:
                    total_wins += 1
                
                # Update agent statistics in database
                stmt = update(agents_table).where(
                    agents_table.c.id == agent_data['id']
                ).values(
                    total_games_played=total_games,
                    total_wins=total_wins,
                    last_active=func.now()
                )
                session.execute(stmt)
            
            session.commit()
            print(f"{Fore.GREEN}[Agent Manager] Updated game statistics for {len(available_agents)} agents{Style.RESET_ALL}")
            
    except Exception as e:
        print(f"{Fore.RED}[Agent Manager] Error updating agent statistics: {e}{Style.RESET_ALL}")

async def create_new_game_instance(app_instance: FastAPI) -> str:
    """Create and start a new game instance in a separate thread"""
    global GAME_COUNTER
    
    # Double check with lock to prevent race conditions
    with _game_maintenance_lock:
        # Count active threaded games again
        active_thread_games = {uid: instance for uid, instance in game_instances.items() 
                              if instance.is_running()}
        
        # If we already have enough games, don't create new one
        if len(active_thread_games) >= CONCURRENT_GAMES_COUNT:
            print(f"{Fore.YELLOW}[Game Manager] Already have {len(active_thread_games)}/{CONCURRENT_GAMES_COUNT} games running. Not creating new game.{Style.RESET_ALL}")
            return None
        
        # Check if we have enough available agents
        available_agents = agent_manager.get_available_agents_for_game(AGENTS_PER_GAME)
        if not available_agents:
            print(f"{Fore.YELLOW}[Game Manager] Cannot create new game - not enough available agents (need {AGENTS_PER_GAME}){Style.RESET_ALL}")
            return None
    
        GAME_COUNTER += 1
        game_uid = f"monopoly_game_{GAME_COUNTER}_{uuid.uuid4().hex[:6]}"
        print(f"{Fore.GREEN}[Game Manager] Creating new threaded game instance: {game_uid} with agents: {[a['name'] for a in available_agents]}{Style.RESET_ALL}")
        
        # Assign agents to this game
        agent_manager.assign_agents_to_game(available_agents, game_uid)
        
        # Create threaded game instance instead of async task
        game_instance = ThreadSafeGameInstance(game_uid, manager, app_instance, available_agents)
        game_instances[game_uid] = game_instance
        
        # Start the game in its own thread
        game_instance.start()
        
        # Create a monitoring task to clean up when the game finishes
        monitoring_task = asyncio.create_task(monitor_threaded_game(game_uid, game_instance))
        app_instance.state.game_tasks[game_uid] = monitoring_task
        
        print(f"{Fore.GREEN}[Game Manager] Threaded game {game_uid} started and monitoring task created{Style.RESET_ALL}")
        return game_uid

async def monitor_threaded_game(game_uid: str, game_instance: ThreadSafeGameInstance):
    """Monitor a threaded game and handle cleanup when it finishes"""
    try:
        # Wait for game thread to complete
        while game_instance.is_running():
            await asyncio.sleep(5)  # Check every 5 seconds
            
        print(f"{Fore.YELLOW}[Game Monitor] Game {game_uid} thread has finished{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}[Game Monitor] Error monitoring game {game_uid}: {e}{Style.RESET_ALL}")
    finally:
        # Clean up game instance
        if game_uid in game_instances:
            del game_instances[game_uid]
            print(f"{Fore.YELLOW}[Game Monitor] Cleaned up game instance {game_uid}{Style.RESET_ALL}")
        
        # Release agents
        try:
            agent_manager.release_agents_from_game(game_uid)
            print(f"{Fore.GREEN}[Game Monitor] Released agents from {game_uid} back to available pool{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[Game Monitor] Error releasing agents from {game_uid}: {e}{Style.RESET_ALL}")
        
        # If auto-restart is enabled, trigger new game creation (with delay to prevent rapid cycling)
        if AUTO_RESTART_GAMES and global_app_instance:
            await asyncio.sleep(2)  # 2 second delay to prevent rapid game cycling
            asyncio.create_task(maintain_game_count(global_app_instance))

async def maintain_game_count(app_instance: Optional[FastAPI] = None):
    """Ensure we maintain the desired number of concurrent games (thread-safe)"""
    # Use lock to prevent concurrent execution
    with _game_maintenance_lock:
        # Get app instance
        if app_instance is None:
            app_instance = global_app_instance
            
        if app_instance is None:
            print(f"{Fore.RED}[Game Manager] No app instance available for maintenance{Style.RESET_ALL}")
            return
            
        if not hasattr(app_instance.state, 'game_tasks'):
            return
            
        # Count active threaded games
        active_thread_games = {uid: instance for uid, instance in game_instances.items() 
                              if instance.is_running()}
        
        # Count active monitoring tasks
        active_tasks = {uid: task for uid, task in app_instance.state.game_tasks.items() 
                       if not task.done()}
        
        # Remove completed tasks from the registry
        completed_games = [uid for uid, task in app_instance.state.game_tasks.items() if task.done()]
        for completed_uid in completed_games:
            print(f"{Fore.YELLOW}[Game Manager] Removing completed monitoring task {completed_uid} from registry{Style.RESET_ALL}")
            del app_instance.state.game_tasks[completed_uid]
        
        # Start new games if needed (based on actual running games, not tasks)
        games_needed = CONCURRENT_GAMES_COUNT - len(active_thread_games)
        if games_needed > 0 and AUTO_RESTART_GAMES:
            # print(f"{Fore.CYAN}[Game Manager] Need to start {games_needed} new games (active: {len(active_thread_games)}/{CONCURRENT_GAMES_COUNT}){Style.RESET_ALL}")
            
            # Check if we have enough available agents
            available_agent_count = len(agent_manager.available_agents)
            max_possible_games = available_agent_count // AGENTS_PER_GAME
            
            if max_possible_games < games_needed:
                print(f"{Fore.YELLOW}[Game Manager] Not enough agents for all requested games. Available agents: {available_agent_count}, can start {max_possible_games} games{Style.RESET_ALL}")
                games_needed = max_possible_games
            
            for i in range(games_needed):
                created_game_uid = await create_new_game_instance(app_instance)
                if created_game_uid is None:
                    print(f"{Fore.YELLOW}[Game Manager] Could not create more games - no available agents or limit reached{Style.RESET_ALL}")
                    break
                
                # Add a small delay between game creations to prevent overwhelming the system
                if i < games_needed - 1:  # Don't delay after the last game
                    await asyncio.sleep(1)

async def start_monopoly_game_instance_with_restart(game_uid: str, connection_manager_param: ConnectionManager, app_instance: FastAPI, available_agents: List[Dict[str, Any]]):
    """Wrapper for game instance that handles auto-restart"""
    try:
        await start_monopoly_game_instance(game_uid, connection_manager_param, app_instance, available_agents)
    except Exception as e:
        print(f"{Fore.RED}[Game Manager] Game {game_uid} ended with error: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"{Fore.CYAN}[Game Manager] Game {game_uid} has finished{Style.RESET_ALL}")
        # Note: Agent cleanup and game restart is handled by monitor_threaded_game
        # to avoid double cleanup and maintain proper timing

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
    """Get current status of all games using thread-safe instances"""
    active_games = []
    completed_count = 0
    
    # Check monitoring tasks if available
    monitoring_tasks_count = 0
    if hasattr(app_instance.state, 'game_tasks'):
        monitoring_tasks_count = len(app_instance.state.game_tasks)
        for uid, task in app_instance.state.game_tasks.items():
            if task.done():
                completed_count += 1
    
    # Get info from thread-safe game instances
    for game_uid, game_instance in game_instances.items():
        try:
            basic_info = game_instance.get_basic_info()
            
            game_info = {
                "game_uid": game_uid,
                "status": "running" if basic_info['running'] else "finished",
                "task_done": False,  # Thread-based, so different concept
                "thread_id": basic_info.get('thread_id'),
                "has_controller": basic_info.get('has_controller', False)
            }
            
            # Add detailed info if available
            if basic_info.get('has_controller'):
                game_info.update({
                    "turn_count": basic_info.get('turn_count', 0),
                    "game_over": basic_info.get('game_over', False),
                    "current_player": basic_info.get('current_player', 0),
                    "player_count": basic_info.get('player_count', 0)
                })
            
            active_games.append(game_info)
            
        except Exception as e:
            # Add error info for debugging
            error_info = {
                "game_uid": game_uid,
                "status": "error",
                "error": str(e),
                "running": False
            }
            active_games.append(error_info)
    
    # Count actually running games
    running_games = len([g for g in active_games if g.get('status') == 'running'])
    
    return {
        "active_games": running_games,
        "total_thread_games": len(game_instances),
        "completed_monitoring_tasks": completed_count,
        "total_monitoring_tasks": monitoring_tasks_count,
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
    gc: Optional[GameControllerV2] = None 

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
        gc = GameControllerV2(game_uid=game_uid, ws_manager=connection_manager_param, 
                            game_db_id=game_db_id, participants=available_agents, treasury_agent_id=TREASURY_AGENT_ID)
        
        # Set the game controller reference in the thread-safe instance if available
        if game_uid in game_instances:
            game_instances[game_uid].game_controller = gc
            # Set reverse reference for thread-safe communication
            gc._threaded_game_instance = game_instances[game_uid]
            print(f"{Fore.GREEN}GameController for G_UID:{game_uid} linked to thread-safe instance.{Style.RESET_ALL}")
        
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
                agent_instance = OpenAIAgent(
                    player_id=i, 
                    name=agent_data['name'], 
                    agent_uid=agent_data['agent_uid'],
                    personality=agent_data.get('personality_prompt', '')
                )
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
        
        # Send game start notification
        event_handler = get_game_event_handler()
        await event_handler.handle_game_start(gc.game_uid, gc, MAX_TURNS)
        
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
        
        # Track turn actions for the ENTIRE turn (not just segments)
        current_turn_actions = []

        print(f"{Fore.CYAN}Starting main game loop for G_UID: {game_uid}...{Style.RESET_ALL}")
        print(f"{Fore.CYAN}🎯 [GAME START] Initial turn: {gc.turn_count}, Player: {gc.players[gc.current_player_index].name} (P{gc.current_player_index}){Style.RESET_ALL}")
        
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
                # Reset turn actions when a new turn starts (new player)
                current_turn_actions = []
                print(f"{Fore.CYAN}🔄 [NEW TURN] Turn {gc.turn_count} started, reset actions for player {gc.current_player_index}{Style.RESET_ALL}")
                if gc.turn_count % 10 == 0:
                    print(f"{Fore.MAGENTA}🏁 [MILESTONE] Turn {gc.turn_count} reached! Game progress milestone{Style.RESET_ALL}")
                if gc.turn_count >= 100:
                    print(f"{Fore.RED}🎯 [TARGET REACHED] Turn 100+ achieved! Current turn: {gc.turn_count}{Style.RESET_ALL}")
                    print(f"{Fore.RED}🎯 [GAME STATUS] Players status check at turn {gc.turn_count}:{Style.RESET_ALL}")
                    for i, p in enumerate(gc.players):
                        print(f"{Fore.RED}   Player {i}: {p.name}, Money: ${p.money}, Properties: {len(p.properties)}, Bankrupt: {p.is_bankrupt}{Style.RESET_ALL}")
            
            print(f"{Fore.CYAN}[DEBUG] About to determine active player...{Style.RESET_ALL}")
            
            # Determine active player for this segment (main turn, auction, trade response, etc.)
            if gc.auction_in_progress and gc.pending_decision_type == "auction_bid":
                print(f"{Fore.CYAN}[DEBUG] Auction in progress, determining bidder...{Style.RESET_ALL}")
                active_player_id = gc.pending_decision_context.get("player_to_bid_id")
                if active_player_id is None: 
                    await gc.send_event_to_frontend({"type":"error_log", "message": f"[E] GameLoop G{game_uid}: Auction but no bidder."})
                    await gc._conclude_auction(no_winner=True); 
                    active_player_id = current_main_turn_player_id # Fallback to current main player 
                current_acting_player = gc.players[active_player_id]
            elif gc.pending_decision_type in ["respond_to_trade_offer", "handle_received_mortgaged_property", "propose_new_trade_after_rejection"]:
                print(f"{Fore.CYAN}[DEBUG] Pending decision: {gc.pending_decision_type}{Style.RESET_ALL}")
                active_player_id = gc.pending_decision_context.get("player_id")
                if active_player_id is None: 
                    await gc.send_event_to_frontend({"type":"error_log", "message": f"[E] GameLoop G{game_uid}: Pending '{gc.pending_decision_type}' but no P_ID."})
                    gc._clear_pending_decision(); 
                    active_player_id = current_main_turn_player_id # Fallback
                current_acting_player = gc.players[active_player_id]
            else: # Default to the main player for the current game controller turn
                print(f"{Fore.CYAN}[DEBUG] Using main player for turn{Style.RESET_ALL}")
                active_player_id = current_main_turn_player_id
                current_acting_player = gc.players[active_player_id]
            
            print(f"{Fore.BLUE}  Active Player ID for this segment: {active_player_id}, Name: {current_acting_player.name if current_acting_player else 'N/A'}{Style.RESET_ALL}")
            
            try:
                print(f"{Fore.CYAN}[DEBUG] Getting agent for player {active_player_id}...{Style.RESET_ALL}")
                agent_to_act = agents[active_player_id]
                print(f"{Fore.CYAN}[DEBUG] Agent obtained: {agent_to_act.name}{Style.RESET_ALL}")
                
                await gc.send_event_to_frontend({"type": "turn_info", "data": f"--- Loop {loop_turn_count} (GC_Turn {gc.turn_count}) for P{active_player_id} ({current_acting_player.name}) --- PendDec: {gc.pending_decision_type}"}) 
            
                print(f"{Fore.CYAN}[DEBUG] About to get player state for agent...{Style.RESET_ALL}")
                if not current_acting_player.is_bankrupt: 
                    player_state_data_before_segment = gc.get_game_state_for_agent(current_acting_player.player_id)
                    await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data_before_segment})
                    print(f"{Fore.CYAN}[DEBUG] Player state updated successfully{Style.RESET_ALL}")
                
            except Exception as debug_e:
                print(f"{Fore.RED}[DEBUG ERROR] Error in agent setup: {debug_e}{Style.RESET_ALL}")
                import traceback
                traceback.print_exc()
                raise  # Re-raise to trigger main exception handler
            
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
            
            # DEBUG: Add detailed state logging before entering inner loop
            print(f"{Fore.CYAN}[DEBUG] Player segment state: active={player_turn_segment_active}, bankrupt={current_acting_player.is_bankrupt}, game_over={gc.game_over}, action_count={action_this_segment_count}, max_actions={MAX_ACTIONS_PER_SEGMENT}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[DEBUG] Game state: pending_decision={gc.pending_decision_type}, dice_processed={gc.dice_roll_outcome_processed}, auction={gc.auction_in_progress}{Style.RESET_ALL}")
            
            while player_turn_segment_active and not current_acting_player.is_bankrupt and not gc.game_over and action_this_segment_count < MAX_ACTIONS_PER_SEGMENT:
                action_this_segment_count += 1
                action_sequence_this_gc_turn += 1
                gc.log_event(f"Loop {loop_turn_count}, SegAct {action_this_segment_count}, P{active_player_id} ({current_acting_player.name}) Turn. GC.Pend: {gc.pending_decision_type}, GC.DiceDone: {gc.dice_roll_outcome_processed}", "debug_loop")
                
                # 🎯 CRITICAL: Send Landing Analysis for ALL movements
                # This ensures every dice roll movement gets a Telegram notification
                
                # 🎯 CRITICAL: Handle async landing processing if needed
                # This handles players who moved synchronously but need async landing effects
                is_trade_negotiation = gc.pending_decision_type in ["respond_to_trade_offer", "propose_new_trade_after_rejection"]
                is_action_card_draw = gc.pending_decision_type == "action_card_draw"
                
                should_process_normal_async = (not gc.dice_roll_outcome_processed and 
                                             getattr(gc, 'turn_phase', None) == "post_roll" and 
                                             active_player_id == current_main_turn_player_id and
                                             not is_trade_negotiation)
                                             
                should_process_action_card = (is_action_card_draw and 
                                            gc.pending_decision_context.get("player_id") == current_main_turn_player_id)
                
                if should_process_normal_async or should_process_action_card:
                    
                    print(f"{Fore.CYAN}[ASYNC LANDING] Processing deferred landing effects for {current_acting_player.name} at position {current_acting_player.position}{Style.RESET_ALL}")
                    
                    # Handle GO salary if needed
                    if hasattr(current_acting_player, '_needs_go_salary'):
                        print(f"{Fore.CYAN}[ASYNC LANDING] Processing deferred GO salary for {current_acting_player.name}{Style.RESET_ALL}")
                        try:
                            await gc._handle_go_passed(current_acting_player)
                            delattr(current_acting_player, '_needs_go_salary')
                            print(f"{Fore.GREEN}[ASYNC LANDING] GO salary processed for {current_acting_player.name}{Style.RESET_ALL}")
                        except Exception as e:
                            print(f"{Fore.RED}[ASYNC LANDING] Error processing GO salary for {current_acting_player.name}: {e}{Style.RESET_ALL}")
                            if hasattr(current_acting_player, '_needs_go_salary'):
                                delattr(current_acting_player, '_needs_go_salary')
                    
                    # Process landing on the square
                    try:
                        await gc.land_on_square(current_acting_player)
                        print(f"{Fore.GREEN}[ASYNC LANDING] Landing effects processed for {current_acting_player.name}{Style.RESET_ALL}")
                        
                        # 🎯 PROCESSING FLAG MANAGEMENT:
                        # Check if this is a Chance/Community Chest card that still needs processing
                        current_square = gc.board.get_square(current_acting_player.position)
                        from game_logic.property import ActionSquare
                        
                        if isinstance(current_square, ActionSquare):
                            print(f"{Fore.CYAN}[ASYNC LANDING] 🎴 Action square (Chance/Community Chest) processed{Style.RESET_ALL}")
                            # Action squares should be fully processed by land_on_square
                            # If dice_roll_outcome_processed is still False, it means a movement card was drawn
                            if not gc.dice_roll_outcome_processed:
                                print(f"{Fore.CYAN}[ASYNC LANDING] 🎴 Movement card detected - will need additional processing{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.GREEN}[ASYNC LANDING] 🎴 Card effect completed successfully{Style.RESET_ALL}")
                        else:
                            # Non-action squares should be marked as processed to prevent loops
                            if not gc.dice_roll_outcome_processed:
                                gc.dice_roll_outcome_processed = True
                                print(f"{Fore.GREEN}[ASYNC LANDING] ✅ Non-action square: marked dice outcome as processed{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.GREEN}[ASYNC LANDING] ✅ Landing processing completed: dice_roll_outcome_processed = True{Style.RESET_ALL}")
                        
                        # Mark async processing as complete for this turn segment
                        print(f"{Fore.GREEN}[ASYNC LANDING] Landing effects completed{Style.RESET_ALL}")
                        
                    except Exception as e:
                        print(f"{Fore.RED}[ASYNC LANDING] Error processing landing effects for {current_acting_player.name}: {e}{Style.RESET_ALL}")
                        # Set processed to true to avoid infinite loop
                        gc.dice_roll_outcome_processed = True

                available_actions = gc.get_available_actions(active_player_id)
                gc.log_event(f"P{active_player_id} AvailActions: {available_actions}", "debug_loop")
                print(f"{Fore.CYAN}[DEBUG] Available actions for P{active_player_id}: {available_actions}{Style.RESET_ALL}")
                
                # Clear any pending landing notifications if they exist
                if hasattr(current_acting_player, '_pending_landing_notification'):
                    delattr(current_acting_player, '_pending_landing_notification')
                
                # 🎯 Check for pending trade notifications and send to Telegram
                if hasattr(gc, '_pending_trade_notifications') and gc._pending_trade_notifications:
                    trade_notifications = gc._pending_trade_notifications
                    gc._pending_trade_notifications = []  # Clear the list
                    
                    print(f"{Fore.GREEN}📱 [TELEGRAM] Processing {len(trade_notifications)} trade notifications{Style.RESET_ALL}")
                    
                    for notification in trade_notifications:
                        try:
                            notification_type = notification["type"]
                            data = notification["data"]
                            
                            from admin import get_telegram_notifier
                            telegram_notifier = get_telegram_notifier()
                            
                            if telegram_notifier and telegram_notifier.enabled:
                                if notification_type == "trade_proposal":
                                    # Format trade proposal message
                                    message = f"🔄 **Trade Proposal** 🔄\n\n"
                                    message += f"📋 Trade ID: {data['trade_id']}\n"
                                    message += f"👤 From: {data['proposer_name']}\n"
                                    message += f"👤 To: {data['recipient_name']}\n"
                                    message += f"🎮 Game: {data['game_uid']}\n"
                                    message += f"🎲 Turn: {data['turn_count']}\n\n"
                                    
                                    # Offering section
                                    message += f"💰 **{data['proposer_name']} Offers:**\n"
                                    if data['offered_properties']:
                                        message += f"🏠 Properties: {', '.join(data['offered_properties'])}\n"
                                    if data['offered_money'] > 0:
                                        message += f"💵 Money: ${data['offered_money']}\n"
                                    if data['offered_gooj_cards'] > 0:
                                        message += f"🎫 Get Out of Jail Cards: {data['offered_gooj_cards']}\n"
                                    if not data['offered_properties'] and data['offered_money'] == 0 and data['offered_gooj_cards'] == 0:
                                        message += "🚫 Nothing\n"
                                    
                                    # Requesting section
                                    message += f"\n🎯 **{data['proposer_name']} Wants:**\n"
                                    if data['requested_properties']:
                                        message += f"🏠 Properties: {', '.join(data['requested_properties'])}\n"
                                    if data['requested_money'] > 0:
                                        message += f"💵 Money: ${data['requested_money']}\n"
                                    if data['requested_gooj_cards'] > 0:
                                        message += f"🎫 Get Out of Jail Cards: {data['requested_gooj_cards']}\n"
                                    if not data['requested_properties'] and data['requested_money'] == 0 and data['requested_gooj_cards'] == 0:
                                        message += "🚫 Nothing\n"
                                    
                                    if data['message']:
                                        message += f"\n💬 Message: {data['message']}\n"
                                    
                                    # Send to both Telegram and WebSocket (frontend)
                                    if telegram_notifier and telegram_notifier.enabled:
                                        await telegram_notifier.send_message(message)
                                    
                                    # Also send to frontend via WebSocket
                                    if game_uid in game_instances:
                                        game_instances[game_uid].send_message_safely({
                                            'type': 'trade_proposal_notification',
                                            'game_uid': game_uid,
                                            'trade_id': data['trade_id'],
                                            'proposer_name': data['proposer_name'],
                                            'recipient_name': data['recipient_name'],
                                            'message': message
                                        })
                                    
                                    print(f"{Fore.MAGENTA}📱 [TELEGRAM SENT] Trade proposal {data['trade_id']}: {data['proposer_name']} → {data['recipient_name']}{Style.RESET_ALL}")
                                    print(f"{Fore.GREEN}🌐 [WEBSOCKET SENT] Trade proposal to frontend for {game_uid}{Style.RESET_ALL}")
                                    
                                elif notification_type == "trade_acceptance":
                                    message = f"✅ **Trade Accepted** ✅\n\n"
                                    message += f"📋 Trade ID: {data['trade_id']}\n"
                                    message += f"👤 {data['recipient_name']} accepted the trade from {data['proposer_name']}\n"
                                    message += f"🎮 Game: {data['game_uid']}\n"
                                    message += f"🎲 Turn: {data['turn_count']}\n\n"
                                    message += f"🎉 Trade executed successfully!"
                                    
                                    # Send to both Telegram and WebSocket (frontend)
                                    if telegram_notifier and telegram_notifier.enabled:
                                        await telegram_notifier.send_message(message)
                                    
                                    # Also send to frontend via WebSocket
                                    if game_uid in game_instances:
                                        game_instances[game_uid].send_message_safely({
                                            'type': 'trade_acceptance_notification',
                                            'game_uid': game_uid,
                                            'trade_id': data['trade_id'],
                                            'proposer_name': data['proposer_name'],
                                            'recipient_name': data['recipient_name'],
                                            'message': message
                                        })
                                    
                                    print(f"{Fore.MAGENTA}📱 [TELEGRAM SENT] Trade acceptance {data['trade_id']}: {data['recipient_name']} accepted{Style.RESET_ALL}")
                                    print(f"{Fore.GREEN}🌐 [WEBSOCKET SENT] Trade acceptance to frontend for {game_uid}{Style.RESET_ALL}")
                                    
                                elif notification_type == "trade_rejection":
                                    message = f"❌ **Trade Rejected** ❌\n\n"
                                    message += f"📋 Trade ID: {data['trade_id']}\n"
                                    message += f"👤 {data['recipient_name']} rejected the trade from {data['proposer_name']}\n"
                                    message += f"🎮 Game: {data['game_uid']}\n"
                                    message += f"🎲 Turn: {data['turn_count']}\n\n"
                                    message += f"📊 Rejection count: {data['rejection_count']}/{data['max_rejections']}\n"
                                    
                                    if data['rejection_count'] >= data['max_rejections']:
                                        message += f"🚫 Maximum rejections reached - trade negotiation ended"
                                    else:
                                        message += f"🔄 {data['proposer_name']} can propose a new trade"
                                    
                                    # Send to both Telegram and WebSocket (frontend)
                                    if telegram_notifier and telegram_notifier.enabled:
                                        await telegram_notifier.send_message(message)
                                    
                                    # Also send to frontend via WebSocket
                                    if game_uid in game_instances:
                                        game_instances[game_uid].send_message_safely({
                                            'type': 'trade_rejection_notification',
                                            'game_uid': game_uid,
                                            'trade_id': data['trade_id'],
                                            'proposer_name': data['proposer_name'],
                                            'recipient_name': data['recipient_name'],
                                            'rejection_count': data['rejection_count'],
                                            'max_rejections': data['max_rejections'],
                                            'message': message
                                        })
                                    
                                    print(f"{Fore.MAGENTA}📱 [TELEGRAM SENT] Trade rejection {data['trade_id']}: {data['recipient_name']} rejected{Style.RESET_ALL}")
                                    print(f"{Fore.GREEN}🌐 [WEBSOCKET SENT] Trade rejection to frontend for {game_uid}{Style.RESET_ALL}")
                                    
                                elif notification_type == "trade_counter":
                                    message = f"🔄 **Trade Counter-Offer** 🔄\n\n"
                                    message += f"📋 Original Trade ID: {data['original_trade_id']}\n"
                                    message += f"📋 Counter Trade ID: {data['counter_trade_id']}\n"
                                    message += f"👤 {data['recipient_name']} countered {data['proposer_name']}'s trade\n"
                                    message += f"🎮 Game: {data['game_uid']}\n"
                                    message += f"🎲 Turn: {data['turn_count']}\n\n"
                                    
                                    # Counter offer details
                                    message += f"💰 **{data['recipient_name']} Counter-Offers:**\n"
                                    if data['counter_offered_properties']:
                                        message += f"🏠 Properties: {', '.join(data['counter_offered_properties'])}\n"
                                    if data['counter_offered_money'] > 0:
                                        message += f"💵 Money: ${data['counter_offered_money']}\n"
                                    if data['counter_offered_gooj_cards'] > 0:
                                        message += f"🎫 Get Out of Jail Cards: {data['counter_offered_gooj_cards']}\n"
                                    if not data['counter_offered_properties'] and data['counter_offered_money'] == 0 and data['counter_offered_gooj_cards'] == 0:
                                        message += "🚫 Nothing\n"
                                    
                                    message += f"\n🎯 **{data['recipient_name']} Wants:**\n"
                                    if data['counter_requested_properties']:
                                        message += f"🏠 Properties: {', '.join(data['counter_requested_properties'])}\n"
                                    if data['counter_requested_money'] > 0:
                                        message += f"💵 Money: ${data['counter_requested_money']}\n"
                                    if data['counter_requested_gooj_cards'] > 0:
                                        message += f"🎫 Get Out of Jail Cards: {data['counter_requested_gooj_cards']}\n"
                                    if not data['counter_requested_properties'] and data['counter_requested_money'] == 0 and data['counter_requested_gooj_cards'] == 0:
                                        message += "🚫 Nothing\n"
                                    
                                    if data['counter_message']:
                                        message += f"\n💬 Message: {data['counter_message']}\n"
                                    
                                    # Send to both Telegram and WebSocket (frontend)
                                    if telegram_notifier and telegram_notifier.enabled:
                                        await telegram_notifier.send_message(message)
                                    
                                    # Also send to frontend via WebSocket
                                    if game_uid in game_instances:
                                        game_instances[game_uid].send_message_safely({
                                            'type': 'trade_counter_notification',
                                            'game_uid': game_uid,
                                            'original_trade_id': data['original_trade_id'],
                                            'counter_trade_id': data['counter_trade_id'],
                                            'proposer_name': data['proposer_name'],
                                            'recipient_name': data['recipient_name'],
                                            'message': message
                                        })
                                    
                                    print(f"{Fore.MAGENTA}📱 [TELEGRAM SENT] Trade counter {data['counter_trade_id']}: {data['recipient_name']} countered{Style.RESET_ALL}")
                                    print(f"{Fore.GREEN}🌐 [WEBSOCKET SENT] Trade counter to frontend for {game_uid}{Style.RESET_ALL}")
                                    
                                elif notification_type == "trade_completion":
                                    message = f"🎉 **Trade Completed** 🎉\n\n"
                                    message += f"📋 Trade ID: {data['trade_id']}\n"
                                    message += f"👥 Players: {data['proposer_name']} ↔ {data['recipient_name']}\n"
                                    message += f"🎮 Game: {data['game_uid']}\n"
                                    message += f"🎲 Turn: {data['turn_count']}\n\n"
                                    
                                    # Items transferred
                                    prop_to_recip = data['items_transferred']['proposer_to_recipient']
                                    recip_to_prop = data['items_transferred']['recipient_to_proposer']
                                    
                                    message += f"📦 **Items Transferred:**\n"
                                    message += f"🔄 {data['proposer_name']} → {data['recipient_name']}:\n"
                                    if prop_to_recip['properties']:
                                        message += f"  🏠 Properties: {', '.join(prop_to_recip['properties'])}\n"
                                    if prop_to_recip['money'] > 0:
                                        message += f"  💵 Money: ${prop_to_recip['money']}\n"
                                    if prop_to_recip['gooj_cards'] > 0:
                                        message += f"  🎫 Get Out of Jail Cards: {prop_to_recip['gooj_cards']}\n"
                                    
                                    message += f"\n🔄 {data['recipient_name']} → {data['proposer_name']}:\n"
                                    if recip_to_prop['properties']:
                                        message += f"  🏠 Properties: {', '.join(recip_to_prop['properties'])}\n"
                                    if recip_to_prop['money'] > 0:
                                        message += f"  💵 Money: ${recip_to_prop['money']}\n"
                                    if recip_to_prop['gooj_cards'] > 0:
                                        message += f"  🎫 Get Out of Jail Cards: {recip_to_prop['gooj_cards']}\n"
                                    
                                    # Mortgaged properties warning
                                    if data['mortgaged_properties']['received_by_recipient'] or data['mortgaged_properties']['received_by_proposer']:
                                        message += f"\n⚠️ **Mortgaged Properties:**\n"
                                        if data['mortgaged_properties']['received_by_recipient']:
                                            message += f"  📍 {data['recipient_name']} received mortgaged properties\n"
                                        if data['mortgaged_properties']['received_by_proposer']:
                                            message += f"  📍 {data['proposer_name']} received mortgaged properties\n"
                                    
                                    # Send to both Telegram and WebSocket (frontend)
                                    if telegram_notifier and telegram_notifier.enabled:
                                        await telegram_notifier.send_message(message)
                                    
                                    # Also send to frontend via WebSocket
                                    if game_uid in game_instances:
                                        game_instances[game_uid].send_message_safely({
                                            'type': 'trade_completion_notification',
                                            'game_uid': game_uid,
                                            'trade_id': data['trade_id'],
                                            'proposer_name': data['proposer_name'],
                                            'recipient_name': data['recipient_name'],
                                            'items_transferred': data['items_transferred'],
                                            'mortgaged_properties': data['mortgaged_properties'],
                                            'message': message
                                        })
                                    
                                    print(f"{Fore.MAGENTA}📱 [TELEGRAM SENT] Trade completion {data['trade_id']}: {data['proposer_name']} ↔ {data['recipient_name']}{Style.RESET_ALL}")
                                    print(f"{Fore.GREEN}🌐 [WEBSOCKET SENT] Trade completion to frontend for {game_uid}{Style.RESET_ALL}")
                                    
                        except Exception as e:
                            print(f"{Fore.RED}❌ [TELEGRAM ERROR] Failed to send trade notification {notification_type}: {e}{Style.RESET_ALL}")
                            logger.error(f"Failed to send trade notification {notification_type}: {e}")
                            import traceback
                            traceback.print_exc()
                
                if not available_actions: 
                    print(f"{Fore.YELLOW}[DEBUG] No actions available - ending segment{Style.RESET_ALL}")
                    await gc.send_event_to_frontend({"type":"warning_log", "message":f"[W] No actions for P{active_player_id} ({current_acting_player.name}). Pend:'{gc.pending_decision_type}', SegEnd."})
                    player_turn_segment_active = False; break 
                game_state_for_agent = gc.get_game_state_for_agent(active_player_id)
                await gc.send_event_to_frontend({"type": "agent_thinking_start", "player_id": active_player_id, "available_actions": available_actions, "context": gc.pending_decision_context, "turn": gc.turn_count, "seq": action_sequence_this_gc_turn})
                print(f"[DEBUG SERVER LOOP] Passing gc.turn_count: {gc.turn_count} to agent {active_player_id} (Name: {agent_to_act.name}) for decide_action")
                
                try:
                    print(f"{Fore.CYAN}[AI DECISION] 🤖 Agent {agent_to_act.name} starting decision process...{Style.RESET_ALL}")
                    print(f"{Fore.CYAN}[AI DECISION]    📊 Turn: {gc.turn_count}, Action #{action_sequence_this_gc_turn}{Style.RESET_ALL}")
                    print(f"{Fore.CYAN}[AI DECISION]    🎯 Available actions: {available_actions}{Style.RESET_ALL}")
                    
                    import time
                    decision_start_time = time.time()
                    
                    # Add timeout wrapper for AI decision
                    chosen_tool_name, params = await asyncio.wait_for(
                        asyncio.to_thread(agent_to_act.decide_action, game_state_for_agent, available_actions, gc.turn_count, action_sequence_this_gc_turn),
                        timeout=30.0  # 30 second timeout
                    )
                    
                    decision_time = time.time() - decision_start_time
                    print(f"{Fore.GREEN}[AI DECISION] ✅ Decision completed in {decision_time:.2f}s: {chosen_tool_name}{Style.RESET_ALL}")
                    if decision_time > 10.0:
                        print(f"{Fore.YELLOW}[AI DECISION] ⚠️  SLOW DECISION WARNING: {decision_time:.2f}s > 10s{Style.RESET_ALL}")
                    
                except asyncio.TimeoutError:
                    print(f"{Fore.RED}[AI DECISION] ⏰ TIMEOUT: Agent {agent_to_act.name} decision took >30s{Style.RESET_ALL}")
                    print(f"{Fore.RED}[AI DECISION] 🔄 Falling back to default action{Style.RESET_ALL}")
                    # Fallback to first available action
                    chosen_tool_name = available_actions[0] if available_actions else "tool_end_turn"
                    params = {}
                except Exception as agent_decision_error:
                    print(f"{Fore.RED}[AI DECISION] ❌ Decision failed: {type(agent_decision_error).__name__}: {agent_decision_error}{Style.RESET_ALL}")
                    import traceback
                    traceback.print_exc()
                    raise  # Re-raise to trigger main exception handler
                    
                thoughts = agent_to_act.get_player_thought_process()
                await gc.send_event_to_frontend({"type": "agent_decision", "player_id": active_player_id, "tool_name": chosen_tool_name, "params": params, "thoughts": thoughts})
                
                try:
                    print(f"{Fore.CYAN}[DEBUG] About to execute agent action: {chosen_tool_name}{Style.RESET_ALL}")
                    action_result = await asyncio.to_thread(execute_agent_action, gc, active_player_id, chosen_tool_name, params)
                    print(f"{Fore.GREEN}[DEBUG] Action executed successfully: {action_result.get('status', 'N/A')}{Style.RESET_ALL}")
                    
                except Exception as action_execution_error:
                    print(f"{Fore.RED}[DEBUG ERROR] Action execution failed: {action_execution_error}{Style.RESET_ALL}")
                    import traceback
                    traceback.print_exc()
                    raise  # Re-raise to trigger main exception handler
                await asyncio.to_thread(_log_agent_action_to_db, gc, active_player_id, agent_to_act, action_result)
                await gc.send_event_to_frontend({"type": "action_result", "player_id": active_player_id, "tool_name": chosen_tool_name, "result_status": action_result.get('status'), "result_message": action_result.get('message')})
                if not current_acting_player.is_bankrupt: 
                    player_state_data_after_action = gc.get_game_state_for_agent(current_acting_player.player_id)
                    await gc.send_event_to_frontend({"type": "player_state_update", "data": player_state_data_after_action})

                # Print detailed error information and send Telegram notification for action errors
                if action_result.get("status") in ["error", "failure"]:
                    # Print detailed error information to console
                    print(f"{Fore.RED}╭{'─' * 80}╮{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🚨 ACTION EXECUTION FAILED {' ' * 49}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}├{'─' * 80}┤{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🎮 Game ID:      {game_uid:<61}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🔄 Turn:         {gc.turn_count:<61}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🤖 Player:       {current_acting_player.name} (P{active_player_id}){' ' * (61 - len(current_acting_player.name) - len(str(active_player_id)) - 4)}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 💰 Player Money: ${current_acting_player.money:<60}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 📍 Position:     {current_acting_player.position:<61}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🎯 Action:       {chosen_tool_name:<61}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}├{'─' * 80}┤{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 📋 Parameters:                                                                │{Style.RESET_ALL}")
                    
                    # Format parameters nicely
                    params_str = str(params) if params else "{}"
                    if len(params_str) > 74:
                        params_str = params_str[:71] + "..."
                    print(f"{Fore.RED}│   {params_str:<75}│{Style.RESET_ALL}")
                    
                    print(f"{Fore.RED}├{'─' * 80}┤{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ ❌ Error Message:                                                            │{Style.RESET_ALL}")
                    
                    # Format error message with word wrapping
                    error_message = action_result.get('message', 'Unknown error')
                    error_lines = []
                    words = error_message.split()
                    current_line = ""
                    
                    for word in words:
                        if len(current_line + word + " ") <= 75:
                            current_line += word + " "
                        else:
                            if current_line:
                                error_lines.append(current_line.strip())
                            current_line = word + " "
                    
                    if current_line:
                        error_lines.append(current_line.strip())
                    
                    for line in error_lines:
                        print(f"{Fore.RED}│   {line:<75}│{Style.RESET_ALL}")
                    
                    # Add game state information if available
                    print(f"{Fore.RED}├{'─' * 80}┤{Style.RESET_ALL}")
                    print(f"{Fore.RED}│ 🎲 Game State:                                                               │{Style.RESET_ALL}")
                    print(f"{Fore.RED}│   Pending Decision: {gc.pending_decision_type or 'None':<51}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│   Dice Processed:   {str(gc.dice_roll_outcome_processed):<51}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│   In Jail:          {str(current_acting_player.in_jail):<51}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}│   Auction Active:   {str(gc.auction_in_progress):<51}│{Style.RESET_ALL}")
                    print(f"{Fore.RED}╰{'─' * 80}╯{Style.RESET_ALL}")
                    
                    # Also log to the game controller for frontend visibility
                    gc.log_event(f"[ACTION ERROR] P{active_player_id} ({current_acting_player.name}) - {chosen_tool_name}: {error_message}", "error_log")
                    
                    try:
                        from admin import get_telegram_notifier
                        telegram_notifier = get_telegram_notifier()
                        if telegram_notifier and telegram_notifier.enabled:
                            error_data = {
                                'game_uid': game_uid,
                                'player_name': current_acting_player.name,
                                'action_name': chosen_tool_name,
                                'error_message': action_result.get('message', 'Unknown error'),
                                'turn_number': gc.turn_count
                            }
                            # Use the threaded game instance to send message safely
                            if game_uid in game_instances:
                                game_instances[game_uid].send_message_safely({
                                    'type': 'action_error_notification',
                                    'data': error_data
                                })
                    except Exception as notify_error:
                        print(f"{Fore.YELLOW}[Telegram] Failed to send action error notification: {notify_error}{Style.RESET_ALL}")

                if action_result.get("status") == "error" or current_acting_player.is_bankrupt : player_turn_segment_active = False; break 
                
                # --- Player action segment termination logic --- 
                if chosen_tool_name == "tool_roll_dice":
                    print(f"{Fore.YELLOW}🎲 [ROLL DEBUG] Processing tool_roll_dice for {current_acting_player.name} (P{active_player_id}){Style.RESET_ALL}")
                    print(f"{Fore.YELLOW}  Status: {action_result.get('status')}, Active={active_player_id}, Main={current_main_turn_player_id}, Turn={gc.turn_count}{Style.RESET_ALL}")
                    
                    if action_result.get("status") == "success":
                        dice_val = action_result.get("dice_roll")
                        print(f"{Fore.YELLOW}  Dice result: {dice_val}{Style.RESET_ALL}")
                        
                        if active_player_id == current_main_turn_player_id: 
                            roll_action_taken_this_main_turn_segment = True
                            
                            # Record dice roll action for turn summary
                            if dice_val:
                                current_turn_actions.append({
                                    'type': 'roll',
                                    'player_name': current_acting_player.name,
                                    'dice': dice_val,
                                    'description': f"🎲 {current_acting_player.name} rolled ({dice_val[0]}, {dice_val[1]})"
                                })
                                print(f"{Fore.BLUE}✅ [DICE ROLL] Recorded dice action for player {current_acting_player.name} (P{active_player_id}) in turn {gc.turn_count}: {dice_val}{Style.RESET_ALL}")
                                print(f"{Fore.BLUE}📊 [DICE ROLL] Total actions in current turn: {len(current_turn_actions)}{Style.RESET_ALL}")
                            else:
                                print(f"{Fore.RED}❌ [DICE ROLL] No dice_val in action_result for {current_acting_player.name}{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.YELLOW}⚠️ [DICE ROLL] Not recording - not main player (active={active_player_id}, main={current_main_turn_player_id}){Style.RESET_ALL}")
                    else:
                        print(f"{Fore.RED}❌ [DICE ROLL] Action failed with status: {action_result.get('status')}{Style.RESET_ALL}")
                        
                    if not action_result.get("went_to_jail", False):
                            dice_val = action_result.get("dice_roll")
                            if dice_val and sum(dice_val) > 0 : 
                                await gc._move_player(current_acting_player, sum(dice_val))
                                print(f"{Fore.CYAN}[DEBUG MOVE] {current_acting_player.name} moved {sum(dice_val)} steps from dice {dice_val} to position {current_acting_player.position}{Style.RESET_ALL}")
                                
                                # Landing position info already sent in ASYNC LANDING section above
                                print(f"{Fore.CYAN}📍 [LANDING] {current_acting_player.name} moved to {current_acting_player.position}{Style.RESET_ALL}")
                                    
                            elif not dice_val:
                                gc.log_event(f"[E] No dice_roll in action_result for P{active_player_id}. Ending segment.", "error_log")
                                gc._resolve_current_action_segment()
                                player_turn_segment_active = False
                            else: 
                                gc.log_event(f"[E] Invalid dice {dice_val} from roll_dice tool for P{active_player_id}. Ending segment.", "error_log")
                                gc._resolve_current_action_segment() # Resolve to avoid stuck state
                                player_turn_segment_active = False # End segment due to error with dice
                    # After roll & move, GC state (pending_decision, dice_roll_outcome_processed) is updated by land_on_square.
                    # If a new decision is pending for *this* player (e.g., buy), loop continues.
                    # If landing is resolved and no new decision for this player, then segment ends.
                    # 🎯 IMPORTANT: Check turn_phase to determine if segment should continue
                    if gc.pending_decision_type is None and gc.dice_roll_outcome_processed:
                        # Check if we should continue to post-roll phase for property management
                        current_turn_phase = getattr(gc, 'turn_phase', 'unknown')
                        if current_turn_phase == "post_roll" and active_player_id == current_main_turn_player_id:
                            # Player landed on own property or entered post-roll phase - continue for property management
                            gc.log_event(f"Continuing to post-roll phase for {current_acting_player.name} - property management available", "debug_turn_phase")
                            # Don't end segment - let player choose property management actions
                        else:
                            # Normal end of segment (e.g., paid rent, bought property, etc.)
                            player_turn_segment_active = False
                
                elif chosen_tool_name == "tool_buy_property":
                     # If buy succeeds, GC resolves the segment. If fails (funds), GC keeps pending_decision.
                    if action_result.get("status") == "success" and gc.pending_decision_type is None and gc.dice_roll_outcome_processed:
                        player_turn_segment_active = False 
                
                elif chosen_tool_name == "tool_pass_on_buying_property":
                    # Pass on buying property should initiate auction. Check if action succeeded.
                    if action_result.get("status") == "success":
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
                
                elif gc.pending_decision_type == "handle_received_mortgaged_properties":
                    # If all mortgaged props handled, GC clears pending_decision & sets dice_roll_outcome_processed=True.
                    if gc.pending_decision_type != "handle_received_mortgaged_properties": 
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
            # DEBUG: Log why the inner loop ended
            print(f"{Fore.YELLOW}[DEBUG] Inner loop ended. Reasons: segment_active={player_turn_segment_active}, bankrupt={current_acting_player.is_bankrupt}, game_over={gc.game_over}, action_count={action_this_segment_count}, max_actions={MAX_ACTIONS_PER_SEGMENT}{Style.RESET_ALL}")
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

            # DEBUG: Log the decision logic for advancing turns
            print(f"{Fore.MAGENTA}🔍 [TURN LOGIC] Turn advance analysis for G:{game_uid} Loop:{loop_turn_count} GC_Turn:{gc.turn_count}{Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}    📊 State: pending_decision='{gc.pending_decision_type}', auction={gc.auction_in_progress}, dice_processed={gc.dice_roll_outcome_processed}{Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}    👤 Players: active_player={active_player_id}, main_player={main_turn_player_for_next_step.player_id}, main_bankrupt={main_turn_player_for_next_step.is_bankrupt}{Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}    🎲 Dice: rolled_in_segment={roll_action_taken_this_main_turn_segment}, dice={gc.dice}, doubles_streak={gc.doubles_streak}{Style.RESET_ALL}")

            # Don't advance turn if we're in the middle of trade negotiations or other cross-player decisions
            if gc.pending_decision_type in ["respond_to_trade_offer", "propose_new_trade_after_rejection"]:
                # Trade negotiations are happening - don't advance main turn yet
                gc.log_event(f"Trade negotiation in progress ({gc.pending_decision_type}). Not advancing main turn.", "debug_next_turn")
                print(f"{Fore.MAGENTA}🔄 [TURN LOGIC] Trade negotiation in progress - not advancing turn{Style.RESET_ALL}")
                call_next_turn_flag = False
            elif not gc.auction_in_progress: 
                if main_turn_player_for_next_step.is_bankrupt: 
                    gc.log_event(f"Main turn P{main_turn_player_for_next_step.player_id} ({main_turn_player_for_next_step.name}) is bankrupt. Advancing turn.", "debug_next_turn")
                    print(f"{Fore.MAGENTA}💀 [TURN LOGIC] Main player is bankrupt - advancing turn{Style.RESET_ALL}")
                    call_next_turn_flag = True
                elif active_player_id == main_turn_player_for_next_step.player_id: 
                    is_in_jail_at_segment_end = main_turn_player_for_next_step.in_jail
                    # 🎯 CRITICAL FIX: Don't rely on roll_action_taken_this_main_turn_segment
                    # Instead, check if current dice are doubles and player has valid streak
                    rolled_doubles_for_bonus = (gc.dice[0] == gc.dice[1] and gc.dice[0] != 0 and 
                                              not is_in_jail_at_segment_end and 
                                              gc.doubles_streak > 0 and gc.doubles_streak < 3)
                    print(f"{Fore.MAGENTA}    🎯 [DOUBLES DEBUG] Player {main_turn_player_for_next_step.name} dice analysis:{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       📊 Current dice: ({gc.dice[0]}, {gc.dice[1]}), streak: {gc.doubles_streak}{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       ✓ Dice are equal: {gc.dice[0] == gc.dice[1]}{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       ✓ Dice not zero: {gc.dice[0] != 0}{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       ✓ Not in jail: {not is_in_jail_at_segment_end}{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       ✓ Streak valid (0 < {gc.doubles_streak} < 3): {gc.doubles_streak > 0 and gc.doubles_streak < 3}{Style.RESET_ALL}")
                    print(f"{Fore.MAGENTA}       🎯 FINAL DOUBLES BONUS: {rolled_doubles_for_bonus}{Style.RESET_ALL}")
                    
                    if rolled_doubles_for_bonus:
                        await gc.send_event_to_frontend({"type": "bonus_turn", "player_id": main_turn_player_for_next_step.player_id, "streak": gc.doubles_streak})
                        
                        # Send doubles bonus turn notification
                        if game_uid in game_instances:
                            game_instances[game_uid].send_message_safely({
                                'type': 'special_event_notification',
                                'game_uid': game_uid,
                                'event_type': 'doubles_bonus_turn',
                                'player_name': main_turn_player_for_next_step.name,
                                'event_data': {
                                    'dice': list(gc.dice),
                                    'streak': gc.doubles_streak
                                }
                            })
                        
                        # Send bonus turn continuation notification to admin
                        try:
                            event_handler = get_game_event_handler()
                            if event_handler:
                                print(f"{Fore.BLUE}🎲 [BONUS TURN] Sending bonus turn continuation notification for player {main_turn_player_for_next_step.name}{Style.RESET_ALL}")
                                await event_handler.handle_bonus_turn_continuation(
                                    gc.game_uid, 
                                    gc, 
                                    gc.turn_count, 
                                    main_turn_player_for_next_step.player_id,
                                    gc.dice,
                                    gc.doubles_streak
                                )
                                print(f"{Fore.GREEN}✅ [BONUS TURN] Bonus turn notification sent successfully{Style.RESET_ALL}")
                        except Exception as bonus_turn_error:
                            print(f"{Fore.RED}❌ [BONUS TURN] Error sending bonus turn notification: {bonus_turn_error}{Style.RESET_ALL}")
                        
                        gc._clear_pending_decision(); gc.dice_roll_outcome_processed = True; 
                        
                        # 🎯 For bonus turn: DON'T reset turn_phase immediately
                        # Let player go through normal post_roll phase for property management
                        # The bonus turn will be handled when they choose to end their turn or after property management
                        # We just don't call next_turn() to keep them as the active player
                        
                        roll_action_taken_this_main_turn_segment = False 
                        if main_turn_player_for_next_step.pending_mortgaged_properties_to_handle: 
                            gc._handle_received_mortgaged_property_initiation(main_turn_player_for_next_step)
                        gc.log_event(f"Player {main_turn_player_for_next_step.name} gets a bonus turn segment due to doubles - will continue to property management phase first.", "debug_next_turn")
                        print(f"{Fore.MAGENTA}🎲 [TURN LOGIC] Player gets bonus turn - will complete post-roll phase first, then get another turn{Style.RESET_ALL}")
                        call_next_turn_flag = False
                    else:
                        gc.log_event(f"End of segment for main turn player {main_turn_player_for_next_step.name} (P{active_player_id}). In jail: {is_in_jail_at_segment_end}. Proceeding to next logical turn decision.", "debug_next_turn")
                        print(f"{Fore.MAGENTA}✅ [TURN LOGIC] Normal end of turn - advancing turn{Style.RESET_ALL}")
                        call_next_turn_flag = True
                else:
                    print(f"{Fore.MAGENTA}❌ [TURN LOGIC] Active player ({active_player_id}) != main player ({main_turn_player_for_next_step.player_id}) - not advancing turn{Style.RESET_ALL}")
                    call_next_turn_flag = False
            else:
                print(f"{Fore.MAGENTA}🏛️ [TURN LOGIC] Auction in progress - not advancing turn{Style.RESET_ALL}")
                call_next_turn_flag = False
            
            print(f"{Fore.MAGENTA}🎯 [TURN LOGIC] FINAL DECISION: call_next_turn_flag = {call_next_turn_flag}{Style.RESET_ALL}")
            
            if call_next_turn_flag:
                print(f"{Fore.GREEN}🔄 [TURN ADVANCE] Beginning turn advancement for {game_uid}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}[TURN ADVANCE]    📊 BEFORE: Turn {gc.turn_count}, Player {current_main_turn_player_id} ({gc.players[current_main_turn_player_id].name}){Style.RESET_ALL}")
                print(f"{Fore.GREEN}[TURN ADVANCE]    🎯 Actions taken this turn: {len(current_turn_actions)}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}[TURN ADVANCE]    🎲 Dice state: {gc.dice}, streak: {gc.doubles_streak}{Style.RESET_ALL}")
                
                # Store the previous turn number for notification
                previous_turn_number = gc.turn_count
                previous_player_name = gc.players[current_main_turn_player_id].name
                
                gc.log_event(f"Calling gc.next_turn() for G_UID:{game_uid}. Previous GC turn: {gc.turn_count}, Previous Main PIdx: {current_main_turn_player_id}", "debug_next_turn")
                gc.next_turn() # This will increment gc.turn_count and set new current_player_index
                gc.log_event(f"gc.next_turn() called. New GC turn: {gc.turn_count}, New Main PIdx: {gc.current_player_index}", "debug_next_turn")
                
                print(f"{Fore.GREEN}[TURN ADVANCE]    📊 AFTER: Turn {gc.turn_count}, Player {gc.current_player_index} ({gc.players[gc.current_player_index].name}){Style.RESET_ALL}")
                print(f"{Fore.GREEN}✅ [TURN ADVANCE] Turn advancement complete: {previous_player_name} → {gc.players[gc.current_player_index].name}{Style.RESET_ALL}")
                
                # Send turn end notification (each turn now has unique turn_count)
                print(f"{Fore.BLUE}📢 [TURN END] Preparing turn end notification for player {current_main_turn_player_id}, turn {previous_turn_number}{Style.RESET_ALL}")
                print(f"{Fore.BLUE}📊 [TURN END] Current turn actions: {len(current_turn_actions)} actions{Style.RESET_ALL}")
                try:
                    event_handler = get_game_event_handler()
                    if event_handler is None:
                        print(f"{Fore.RED}❌ [TURN END] Event handler is None - cannot send turn end notification{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.BLUE}✅ [TURN END] Event handler obtained successfully{Style.RESET_ALL}")
                        
                        print(f"{Fore.BLUE}📤 [TURN END] Sending turn end notification: Turn {previous_turn_number}, Player {gc.players[current_main_turn_player_id].name} (P{current_main_turn_player_id}), Actions: {len(current_turn_actions)}{Style.RESET_ALL}")
                        
                        # Debug: Show all actions being sent
                        for i, action in enumerate(current_turn_actions):
                            print(f"{Fore.BLUE}  Action {i+1}: {action.get('description', 'Unknown action')}{Style.RESET_ALL}")
                        
                        # Note: current_turn_actions is now populated throughout the turn, not just at the end
                        # All dice rolls and important actions are already recorded
                        
                        await event_handler.handle_turn_end(gc.game_uid, gc, previous_turn_number, current_main_turn_player_id, current_turn_actions)
                        print(f"{Fore.GREEN}🎉 [TURN END] Turn end notification sent successfully{Style.RESET_ALL}")
                        
                except Exception as turn_end_error:
                    print(f"{Fore.RED}❌ [TURN END] Error sending turn end notification: {turn_end_error}{Style.RESET_ALL}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"{Fore.YELLOW}⏭️ [TURN SKIP] Not advancing turn (call_next_turn_flag=False){Style.RESET_ALL}")
            
            if gc.auction_in_progress: 
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
            # turn_delay = random.uniform(5.0, 10.0)
            # print(f"{Fore.CYAN}[Turn Delay] Waiting {turn_delay:.1f} seconds before next turn for G_UID:{game_uid}...{Style.RESET_ALL}")
            # await asyncio.sleep(turn_delay)
        
        # --- End of main while loop ---
        print(f"{Fore.CYAN}Main game loop for G_UID: {game_uid} has ended. Game Over: {gc.game_over if gc else 'N/A'}, Loop Turns: {loop_turn_count}{Style.RESET_ALL}")
        if gc:
            final_summary_str = await asyncio.to_thread(print_game_summary, gc, True)
            await gc.send_event_to_frontend({"type": "game_summary_data", "summary": final_summary_str})
            await gc.send_event_to_frontend({"type": "game_end_log", "message":f"Monopoly Game Instance {game_uid} Finished."})
            print(f"Game instance {game_uid} final summary sent.")
            
            # Send game end notification
            event_handler = get_game_event_handler()
            start_time = getattr(gc, 'start_time', datetime.datetime.now()) if hasattr(gc, 'start_time') else datetime.datetime.now()
            await event_handler.handle_game_end(gc.game_uid, gc, loop_turn_count, MAX_TURNS, start_time)
            
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
        traceback.print_exc()
        print(f"{Fore.RED}[FATAL GAME LOGIC ERROR] for G_UID:{game_uid}: {game_logic_e}{Style.RESET_ALL}")
        
        # Send critical error notification
        event_handler = get_game_event_handler()
        await event_handler.handle_critical_error(game_uid, game_logic_e, gc)
        
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
    global global_app_instance
    print("FastAPI server starting up (via lifespan)...")
    
    # Print startup configuration
    print_startup_config()
    
    create_db_and_tables()
    print("DB tables checked/created (via lifespan).")
    
    # Set global app instance reference for cross-thread access
    global_app_instance = app_instance
    
    app_instance.state.active_games = {} 
    app_instance.state.game_tasks = {}   
    
    # Initialize tpay sdk
    print(f"Initializing tpay sdk with api_key: {TLEDGER_API_KEY}, api_secret: {TLEDGER_API_SECRET}, project_id: {TLEDGER_PROJECT_ID}, base_url: {TLEDGER_BASE_URL}, timeout: 10000000")
    tpay.tpay_initialize(api_key=TLEDGER_API_KEY, api_secret=TLEDGER_API_SECRET, project_id=TLEDGER_PROJECT_ID, base_url=TLEDGER_BASE_URL, timeout=1000000)

    # Initialize treasury agent
    # print(f"Initializing treasury agent with agent_id: {TREASURY_AGENT_ID}")
    # result = utils.reset_agent_game_balance(agent_id=TREASURY_AGENT_ID, new_balance=10000000000000)
    # print(f"Treasury agent initialized: {result}")

    # Initialize agent manager and load agents from database
    print("Initializing Agent Manager...")
    await agent_manager.initialize_agents_from_database()
    
    # Initialize game event handler and Telegram notifications
    print("Initializing Game Event Handler...")
    from admin import initialize_telegram_notifier, get_telegram_notifier
    initialize_telegram_notifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    event_handler = initialize_game_event_handler()
    
    # Register Telegram command handlers
    telegram_notifier = get_telegram_notifier()
    if telegram_notifier and telegram_notifier.enabled:
        print("Registering Telegram command handlers...")
        telegram_notifier.register_command_handler('end_game', telegram_end_game_command_handler)
        telegram_notifier.register_command_handler('get_status', telegram_get_status_command_handler)
        telegram_notifier.register_command_handler('get_game_status', telegram_get_game_status_command_handler)
        telegram_notifier.register_command_handler('start_new_agents', telegram_create_random_agents_command_handler)
        
        # Start Telegram bot listening for commands
        print("Starting Telegram bot command listening...")
        try:
            asyncio.create_task(telegram_notifier.start_listening())
            print(f"{Fore.GREEN}✅ Telegram bot is now listening for admin commands{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️ Failed to start Telegram bot listening: {e}{Style.RESET_ALL}")
    
    # Send server startup notification
    await event_handler.handle_server_startup(len(agent_manager.available_agents))
    
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
    
    # Send server shutdown notification BEFORE stopping Telegram bot
    try:
        event_handler = get_game_event_handler()
        active_games_count = len([g for g in game_instances.values() if g.is_running()]) if game_instances else 0
        # Add timeout to prevent blocking shutdown
        await asyncio.wait_for(
            event_handler.handle_server_shutdown(active_games_count),
            timeout=5.0  # 5 seconds timeout
        )
        print(f"{Fore.GREEN}✅ Server shutdown notification sent{Style.RESET_ALL}")
    except asyncio.TimeoutError:
        print(f"{Fore.YELLOW}⚠️ Server shutdown notification timeout after 5 seconds{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}⚠️ Error sending server shutdown notification: {e}{Style.RESET_ALL}")
    
    # Stop Telegram bot listening AFTER sending shutdown notification
    telegram_notifier = get_telegram_notifier()
    if telegram_notifier and telegram_notifier.enabled:
        print("Stopping Telegram bot listening...")
        try:
            await telegram_notifier.stop_listening()
            print(f"{Fore.GREEN}✅ Telegram bot stopped listening{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️ Error stopping Telegram bot: {e}{Style.RESET_ALL}")
    
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
    
    # Close log file
    try:
        log_manager.close()
    except Exception as e:
        print(f"❌ Error closing log file: {e}", file=sys.__stderr__)

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
        "http://monopoly.t54.ai",
        "https://monopoly.t54.ai",
        "*"  # For file:// origins
    ], 
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# 9. Define routes

@app.get("/")
async def root():
    """Health check and basic API info"""
    return {
        "status": "healthy",
        "service": "Monopoly Game Server",
        "version": "2.0",
        "endpoints": {
            "health": "/",
            "docs": "/docs",
            "lobby": "/api/lobby/games",
            "admin": "/api/admin/"
        }
    }

@app.get("/health")
async def health_check():
    """Simple health check endpoint for Heroku"""
    return {"status": "ok", "timestamp": datetime.datetime.now().isoformat()}

@app.get("/api/lobby/games")
async def get_lobby_games_api(request: Request):
    """Get lobby games using thread-safe game instances"""
    active_games_info = []
    
    # Use global game_instances instead of app.state.active_games
    if not game_instances:
        return []  # Return empty list if no games are running

    # Get max players constant
    try:
        from main import NUM_PLAYERS as MAX_PLAYERS_CONST
    except ImportError:
        MAX_PLAYERS_CONST = 4
        print(f"{Fore.YELLOW}[API W] Could not import NUM_PLAYERS from main for lobby, defaulting to {MAX_PLAYERS_CONST}{Style.RESET_ALL}")

    # Iterate through thread-safe game instances
    for game_uid, game_instance in game_instances.items():
        try:
            # Get basic info (doesn't require locks)
            basic_info = game_instance.get_basic_info()
            
            if basic_info['running'] and basic_info['has_controller']:
                # Try to get more detailed info safely
                game_status = "in_progress"
            if basic_info.get('game_over', False):
                game_status = "completed"
                
                # Build game info with available data
            game_info = {
                    "game_uid": game_uid,
                    "status": game_status,
                    "current_players_count": basic_info.get('player_count', 0),
                    "max_players": MAX_PLAYERS_CONST,
                    "players": [],  # Simplified for lobby view to avoid thread issues
                    "turn_count": basic_info.get('turn_count', 0)
                }
                
            # Try to get player info safely (optional, may be empty if access fails)
            try:
                if basic_info.get('player_count', 0) > 0:
                    # For lobby, we just need basic player count, not detailed info
                    game_info["players"] = [
                        {"id": i, "name": f"Player {i+1}", "is_ai": True, "is_bankrupt": False}
                        for i in range(basic_info.get('player_count', 0))
                    ]
            except Exception:
                pass  # Ignore player info errors for lobby view
                
            active_games_info.append(game_info)
                
        except Exception as e:
            print(f"{Fore.YELLOW}[API W] Error getting info for game {game_uid}: {e}{Style.RESET_ALL}")
            continue  # Skip this game and continue with others
    
    return active_games_info

@app.get("/api/game/{game_id}/board_layout")
async def get_board_layout_api(game_id: str, request: Request):
    """Get board layout using thread-safe game instances"""
    # Check if game exists in thread-safe instances
    game_instance = game_instances.get(game_id)
    
    if not game_instance:
        not_found_msg = f"Game {game_id} not found or not active."
        print(f"{Fore.YELLOW}[API W] {not_found_msg}{Style.RESET_ALL}")
        raise HTTPException(status_code=404, detail=not_found_msg)
        
    # Check if game is running
    if not game_instance.is_running():
        inactive_msg = f"Game {game_id} is not currently running."
        print(f"{Fore.YELLOW}[API W] {inactive_msg}{Style.RESET_ALL}")
        raise HTTPException(status_code=410, detail=inactive_msg)  # 410 Gone
        
    try:
        # Use thread-safe method to get board layout
        board_layout = game_instance.get_board_layout_safely()
        
        if board_layout is None:
            error_msg = f"Could not retrieve board layout for game {game_id} - game state not available."
            print(f"{Fore.YELLOW}[API W] {error_msg}{Style.RESET_ALL}")
            raise HTTPException(status_code=503, detail=error_msg)  # 503 Service Unavailable
        
        return {"game_id": game_id, "board_layout": board_layout, "status": "success"}
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        error_msg = f"Failed to retrieve board layout for game {game_id} due to an internal error."
        print(f"{Fore.RED}[API E] Error in get_board_layout_safely for {game_id}: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
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
    """Get current status of all running games"""
    if not global_app_instance:
        raise HTTPException(status_code=500, detail="App instance not available")
    
    status = get_game_status(global_app_instance)
    return {"status": "success", "data": status}

@app.get("/api/admin/agents/status")
async def get_agent_manager_status_api(request: Request):
    """Get current status of the agent manager"""
    try:
        status = agent_manager.get_status()
        return {"status": "success", "data": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting agent status: {str(e)}")

@app.post("/api/admin/games/create")
async def create_game_api(request: Request):
    """Manually create a new game instance"""
    if not global_app_instance:
        raise HTTPException(status_code=500, detail="App instance not available")
    
    try:
        game_uid = await create_new_game_instance(global_app_instance)
        if game_uid:
            return {"status": "success", "game_uid": game_uid}
        else:
            return {"status": "error", "message": "Could not create game - not enough agents or limit reached"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating game: {str(e)}")

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

@app.post("/api/admin/agents/create_random")
async def create_random_agents_api():
    """Create 4 new random agents using OpenAI GPT-4o mini"""
    try:
        new_agents = utils.generate_random_agents(count=4)
        
        if new_agents:
            # Create TPay accounts for the new agents
            utils.create_game_token_accounts_for_agents(new_agents)
            
            return {"success": True, "agents": new_agents, "count": len(new_agents)}
        else:
            return {"success": False, "error": "Failed to generate random agents", "agents": [], "count": 0}
    except Exception as e:
        return {"success": False, "error": str(e), "agents": [], "count": 0}

@app.post("/api/admin/balance/test_adjustment")
async def test_balance_adjustment_api():
    """Test the new balance adjustment mechanism for a sample set of agents"""
    try:
        import time
        
        # Get all available agents for testing
        from database import engine, agents_table
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        
        with Session(engine) as session:
            stmt = select(agents_table).limit(5)  # Test with up to 5 agents
            result = session.execute(stmt)
            agents = [dict(row._mapping) for row in result]
        
        if not agents:
            return {
                "success": False,
                "error": "No agents found in database for testing",
                "details": []
            }
        
        # Test the balance adjustment function
        test_game_uid = f"balance_test_{int(time.time())}"
        
        print(f"{Fore.YELLOW}[Admin API] Testing balance adjustment for {len(agents)} agents{Style.RESET_ALL}")
        
        # Call our new balance adjustment function
        await initialize_agent_tpay_balances(agents, test_game_uid)
        
        # Return the results
        test_results = utils.last_balance_adjustment_results.get(test_game_uid, []) if hasattr(utils, 'last_balance_adjustment_results') else []
        
        successful_adjustments = [r for r in test_results if r.get('success', False)]
        failed_adjustments = [r for r in test_results if not r.get('success', False)]
        
        return {
            "success": True,
            "test_game_uid": test_game_uid,
            "total_agents_tested": len(agents),
            "successful_adjustments": len(successful_adjustments),
            "failed_adjustments": len(failed_adjustments),
            "details": test_results,
            "summary": {
                "excess_payments": [r for r in successful_adjustments if r.get('action') == 'excess_paid_to_treasury'],
                "deficit_payments": [r for r in successful_adjustments if r.get('action') == 'deficit_paid_by_treasury'],
                "no_action_needed": [r for r in successful_adjustments if r.get('action') == 'no_action_needed'],
                "failures": failed_adjustments
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Exception during balance adjustment test: {str(e)}",
            "details": []
        }

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

# Import Telegram command handlers from separate module
from admin import (
    telegram_end_game_command_handler,
    telegram_get_status_command_handler,
    telegram_get_game_status_command_handler,
    telegram_create_random_agents_command_handler
)

if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server for Monopoly...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False) 
