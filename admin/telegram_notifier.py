import asyncio
import os
import json
import traceback
import threading
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import logging
import re

# Import telegram bot library
try:
    from telegram import Bot, Update
    from telegram.constants import ParseMode
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("Warning: python-telegram-bot not installed. Telegram notifications will be disabled.")

# Setup logging
logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Telegram Bot notifier for Monopoly game events
    Sends formatted HTML messages to specified chat/group
    """
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        
        self.bot: Optional[Bot] = None
        self.application: Optional[Application] = None
        self.enabled = False
        
        # Command handlers
        self.command_handlers: Dict[str, Callable] = {}
        
        # Store main thread info for cross-thread safety
        self.main_thread_id = threading.current_thread().ident
        try:
            self.main_event_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, will be set later
            self.main_event_loop = None
        
        # Initialize bot if credentials are available
        if TELEGRAM_AVAILABLE and self.bot_token and self.chat_id:
            try:
                # Configure bot with better connection settings to avoid pool timeouts
                from telegram.request import HTTPXRequest
                
                # Create custom request object with optimized pool settings
                request = HTTPXRequest(
                    connection_pool_size=8,  # Increase pool size
                    read_timeout=20,         # Increase read timeout
                    write_timeout=20,        # Increase write timeout
                    connect_timeout=10,      # Connection timeout
                    pool_timeout=5,          # Pool timeout
                )
                
                # Create application for handling updates
                self.application = Application.builder().token(self.bot_token).request(request).build()
                self.bot = self.application.bot
                self.enabled = True
                
                # Register message handler
                self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
                
                print(f"[OK] Telegram notifier initialized successfully with command handling")
            except Exception as e:
                print(f"[ERROR] Failed to initialize Telegram bot: {e}")
                self.enabled = False
        else:
            missing = []
            if not TELEGRAM_AVAILABLE:
                missing.append("python-telegram-bot library")
            if not self.bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self.chat_id:
                missing.append("TELEGRAM_CHAT_ID")
            print(f"[WARNING] Telegram notifier disabled. Missing: {', '.join(missing)}")
    
    def register_command_handler(self, command: str, handler: Callable):
        """Register a command handler function"""
        self.command_handlers[command] = handler
    
    async def start_listening(self):
        """Start listening for messages (should be called once during server startup)"""
        if not self.enabled or not self.application:
            return
            
        try:
            # Store the main event loop if not already stored
            if self.main_event_loop is None:
                self.main_event_loop = asyncio.get_running_loop()
                print(f"[INFO] Telegram notifier: Stored main event loop reference")
            
            # Start polling for updates
            await self.application.initialize()
            await self.application.start()
            
            # Start polling in background
            print(f"[INFO] Telegram bot started listening for commands...")
            await self.application.updater.start_polling()
            
        except Exception as e:
            print(f"[ERROR] Failed to start Telegram bot listening: {e}")
    
    async def stop_listening(self):
        """Stop listening for messages"""
        if not self.enabled or not self.application:
            return
            
        try:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            print(f"[INFO] Telegram bot stopped listening")
        except Exception as e:
            print(f"[ERROR] Error stopping Telegram bot: {e}")
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages"""
        if not update.message or not update.message.text:
            return
            
        # Only process messages from the configured chat
        if str(update.message.chat_id) != str(self.chat_id):
            return
        
        message_text = update.message.text.strip()
        print(f"[INFO] Received Telegram command: {message_text}")
        
        # Parse commands
        await self._parse_and_execute_command(message_text, update)
    
    async def _parse_and_execute_command(self, message_text: str, update: Update):
        """Parse and execute commands"""
        try:
            # Command format: "end game_id" or "end + game_id"
            end_pattern = r'^end\s*\+?\s*(.+)$'
            match = re.match(end_pattern, message_text.lower())
            
            if match:
                game_id = match.group(1).strip()
                await self._handle_end_game_command(game_id, update)
                return
            
            # Start new agents command
            start_agents_pattern = r'^start\s+new\s+agents?$'
            match = re.match(start_agents_pattern, message_text.lower())
            
            if match:
                await self._handle_start_new_agents_command(update)
                return
            
            # Help command
            if message_text.lower() in ['help', '/help']:
                await self._handle_help_command(update)
                return
            
            # Status with game ID command
            status_game_pattern = r'^status\s*\+?\s*(.+)$'
            match = re.match(status_game_pattern, message_text.lower())
            
            if match:
                game_id = match.group(1).strip()
                await self._handle_game_status_command(game_id, update)
                return
            
            # General status command
            if message_text.lower() in ['status', '/status']:
                await self._handle_status_command(update)
                return
                
        except Exception as e:
            error_msg = f"❌ Error processing command: {str(e)}"
            print(error_msg)
            await self._reply_to_message(update, error_msg)
    
    async def _handle_end_game_command(self, game_id: str, update: Update):
        """Handle end game command"""
        if 'end_game' in self.command_handlers:
            try:
                result = await self.command_handlers['end_game'](game_id)
                
                if result.get('success'):
                    agents_affected = result.get('agents_affected', 0)
                    reply_msg = f"""
🛑 <b>Game terminated successfully!</b>

🆔 Game ID: <code>{game_id}</code>
🤖 Agents deactivated: {agents_affected}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}

✅ Game has been stopped and all agents set to inactive.
                    """.strip()
                else:
                    error_reason = result.get('error', 'Unknown error')
                    reply_msg = f"""
❌ <b>Failed to end game</b>

🆔 Game ID: <code>{game_id}</code>
📝 Reason: {error_reason}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}
                    """.strip()
                    
                await self._reply_to_message(update, reply_msg)
                
            except Exception as e:
                error_msg = f"❌ Error ending game {game_id}: {str(e)}"
                await self._reply_to_message(update, error_msg)
        else:
            await self._reply_to_message(update, "❌ End game command handler not registered")
    
    async def _handle_help_command(self, update: Update):
        """Handle help command"""
        help_msg = """
🤖 <b>Monopoly Bot Commands</b>

🛑 <code>end GAME_ID</code> - End a specific game
🎯 <code>start new agents</code> - Create 4 random AI agents
📊 <code>status</code> - Show server status
📋 <code>status + GAME_ID</code> - Show specific game status
❓ <code>help</code> - Show this help message

<b>Examples:</b>
• <code>status monopoly_game_1_abc123</code>
• <code>status + monopoly_game_2_def456</code>
• <code>end monopoly_game_1_abc123</code>
• <code>end + monopoly_game_2_def456</code>
• <code>start new agents</code>

⚠️ <b>Notes:</b>
• Game status shows player money, positions, properties, and jail status
• Ending a game will immediately stop it and set all agents to inactive
• Creating agents uses GPT-4o mini to generate unique personalities
• New agents will be available for matchmaking in future games
        """.strip()
        
        await self._reply_to_message(update, help_msg)
    
    async def _handle_status_command(self, update: Update):
        """Handle status command"""
        if 'get_status' in self.command_handlers:
            try:
                status = await self.command_handlers['get_status']()
                
                active_games = status.get('active_games', 0)
                total_games = status.get('total_thread_games', 0)
                available_agents = status.get('available_agents', 0)
                
                status_msg = f"""
📊 <b>Server Status</b>

🎮 Active games: {active_games}/{total_games}
🤖 Available agents: {available_agents}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ Server is running normally.
                """.strip()
                
                await self._reply_to_message(update, status_msg)
                
            except Exception as e:
                error_msg = f"❌ Error getting status: {str(e)}"
                await self._reply_to_message(update, error_msg)
        else:
            await self._reply_to_message(update, "❌ Status command handler not registered")
    
    async def _handle_game_status_command(self, game_id: str, update: Update):
        """Handle game status command for a specific game"""
        if 'get_game_status' in self.command_handlers:
            try:
                game_status = await self.command_handlers['get_game_status'](game_id)
                
                if not game_status.get('success'):
                    error_msg = f"❌ {game_status.get('error', 'Game not found or error retrieving status')}"
                    await self._reply_to_message(update, error_msg)
                    return
                
                data = game_status.get('data', {})
                
                # Game basic info
                game_info = data.get('game_info', {})
                turn_count = game_info.get('turn_count', 0)
                game_over = game_info.get('game_over', False)
                current_player_idx = game_info.get('current_player_index', 0)
                
                # Players info
                players = data.get('players', [])
                
                # Format players information
                player_lines = []
                for i, player in enumerate(players):
                    name = player.get('name', f'Player {i}')
                    money = player.get('money', 0)
                    position = player.get('position', 0)
                    in_jail = player.get('in_jail', False)
                    is_bankrupt = player.get('is_bankrupt', False)
                    
                    # Status emoji
                    if is_bankrupt:
                        status_emoji = "💸"
                    elif in_jail:
                        status_emoji = "🏭"
                    elif i == current_player_idx:
                        status_emoji = "🎯"
                    else:
                        status_emoji = "🤖"
                    
                    # Properties owned
                    owned_properties = player.get('owned_properties', [])
                    properties_text = ""
                    if owned_properties:
                        prop_names = [prop.get('name', 'Unknown') for prop in owned_properties[:3]]
                        properties_text = f"\n   🏠 Properties: {', '.join(prop_names)}"
                        if len(owned_properties) > 3:
                            properties_text += f" (+{len(owned_properties) - 3} more)"
                    
                    # Format player line
                    player_line = f"{status_emoji} <b>{name}</b>"
                    if is_bankrupt:
                        player_line += " - <s>Bankrupt</s>"
                    else:
                        player_line += f" - 💵${money:,}"
                        if in_jail:
                            player_line += " (In Jail)"
                        else:
                            player_line += f" (Pos: {position})"
                    
                    player_line += properties_text
                    player_lines.append(player_line)
                
                players_text = "\n\n".join(player_lines) if player_lines else "<i>No players found</i>"
                
                # Game status text
                status_text = "🏁 Game Over" if game_over else "🎮 In Progress"
                
                status_msg = f"""
📋 <b>Game Status: {game_id}</b>

🎯 Status: {status_text}
🔄 Turn: {turn_count}
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

👥 <b>Players:</b>
{players_text}

💡 Use <code>status</code> for server status
                """.strip()
                
                await self._reply_to_message(update, status_msg)
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                error_msg = f"❌ Error getting game status: {str(e)}"
                await self._reply_to_message(update, error_msg)
        else:
            await self._reply_to_message(update, "❌ Game status command handler not registered")
    
    async def _handle_start_new_agents_command(self, update: Update):
        """Handle start new agents command"""
        if 'start_new_agents' in self.command_handlers:
            try:
                # Send initial response to let user know we're processing
                await self._reply_to_message(update, "🎯 <b>Starting random agent creation...</b>\n\n⏳ Generating new agents using GPT-4o mini, please wait...")
                
                # Call the command handler
                result = await self.command_handlers['start_new_agents']()
                
                # Debug: Print result structure
                print(f"[Telegram Debug] Command handler result: {result}")
                
                if result.get('success'):
                    created_agents = result.get('created_agents', [])
                    skipped_agents = result.get('skipped_agents', [])
                    successful_tpay = result.get('successful_tpay', 0)
                    
                    # Type checking to prevent errors
                    if not isinstance(created_agents, list):
                        print(f"[Telegram Warning] created_agents is not a list: {type(created_agents)} = {created_agents}")
                        created_agents = []
                    
                    if not isinstance(skipped_agents, list):
                        print(f"[Telegram Warning] skipped_agents is not a list: {type(skipped_agents)} = {skipped_agents}")
                        skipped_agents = []
                    
                    if len(created_agents) > 0:
                        # Format created agents list
                        created_list = []
                        for agent in created_agents:
                            name = agent.get('name', 'Unknown')
                            personality = agent.get('personality', 'No description')
                            tpay_status = "💰" if agent.get('tpay_account_id') else "❌"
                            
                            # Truncate personality if too long
                            if len(personality) > 60:
                                personality = personality[:57] + "..."
                            
                            created_list.append(f"🤖 <b>{name}</b> {tpay_status}\n   <i>{personality}</i>")
                        
                        created_text = "\n\n".join(created_list)
                        
                        # Format skipped agents if any
                        skipped_text = ""
                        if skipped_agents:
                            skipped_list = []
                            for agent in skipped_agents:
                                name = agent.get('name', 'Unknown')
                                reason = agent.get('reason', 'Unknown reason')
                                skipped_list.append(f"⚠️ <b>{name}</b> - {reason}")
                            skipped_text = f"\n\n<b>Skipped Agents:</b>\n" + "\n".join(skipped_list)
                        
                        # Success message with detailed info
                        reply_msg = f"""
🎯 <b>Random Agents Created Successfully!</b>

📊 <b>Summary:</b>
✅ Created: {len(created_agents)} agents
💰 With TPay: {successful_tpay} agents
⚠️ Skipped: {len(skipped_agents)} agents

🤖 <b>New Agents:</b>
{created_text}{skipped_text}

⏰ Time: {datetime.now().strftime('%H:%M:%S')}

🎮 The new agents are now available for matchmaking in games.
                        """.strip()
                    else:
                        # Format skipped agents when no agents were created
                        skipped_text = ""
                        if skipped_agents:
                            skipped_list = []
                            for agent in skipped_agents:
                                name = agent.get('name', 'Unknown')
                                reason = agent.get('reason', 'Unknown reason')
                                skipped_list.append(f"⚠️ <b>{name}</b> - {reason}")
                            skipped_text = f"\n\n<b>Skipped Agents:</b>\n" + "\n".join(skipped_list)
                        
                        # No agents created
                        reply_msg = f"""
⚠️ <b>No New Agents Created</b>

📊 <b>Summary:</b>
✅ Created: 0 agents
⚠️ Skipped: {len(skipped_agents)} agents (duplicate names){skipped_text}

💡 All generated agent names already exist in the database.
Try again later for different randomly generated names.

⏰ Time: {datetime.now().strftime('%H:%M:%S')}
                        """.strip()
                else:
                    error_reason = result.get('error', 'Unknown error')
                    reply_msg = f"""
❌ <b>Failed to create random agents</b>

📝 Reason: {error_reason}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}

🛠️ Please check server logs for more details.
                    """.strip()
                    
                await self._reply_to_message(update, reply_msg)
                
            except Exception as e:
                traceback.print_exc()
                error_msg = f"""
❌ <b>Error creating random agents</b>

🚨 Error: {str(e)}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}

🛠️ Please check server logs for more details.
                """.strip()
                await self._reply_to_message(update, error_msg)
        else:
            await self._reply_to_message(update, "❌ Start new agents command handler not registered")
    
    async def _reply_to_message(self, update: Update, message: str):
        """Reply to a message"""
        try:
            await update.message.reply_text(
                text=message,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"[ERROR] Failed to reply to message: {e}")
    
    async def send_message(self, message: str, disable_notification: bool = False) -> bool:
        """
        Send a message to the configured chat (thread-safe)
        
        Args:
            message: HTML-formatted message to send
            disable_notification: Whether to send silently
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.enabled:
            return False
        
        # Check if we're in the main thread
        current_thread_id = threading.current_thread().ident
        
        if current_thread_id != self.main_thread_id and self.main_event_loop is not None:
            # We're in a different thread, schedule the call to main thread
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._send_message_internal(message, disable_notification),
                    self.main_event_loop
                )
                # Wait for the result with a reasonable timeout
                return future.result(timeout=10.0)  # 10 seconds timeout
            except Exception as e:
                logger.error(f"Failed to send Telegram message from thread {current_thread_id}: {e}")
                return False
        else:
            # We're in the main thread, call directly
            return await self._send_message_internal(message, disable_notification)
    
    async def _send_message_internal(self, message: str, disable_notification: bool = False) -> bool:
        """Internal method to actually send the message (always runs in main thread)"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_notification=disable_notification
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def _format_player_info(self, players: List[Dict[str, Any]]) -> str:
        """Format player information for display"""
        if not players:
            return "<i>No player information</i>"
        
        player_lines = []
        for player in players:
            status = "💰" if not player.get('is_bankrupt', False) else "💸"
            name = player.get('name', f"Player {player.get('id', '?')}")
            money = player.get('money', 0)
            position = player.get('position', 0)
            
            player_line = f"{status} <b>{name}</b> - 💵${money} (Position: {position})"
            if player.get('in_jail', False):
                player_line += " 🏭"
            if player.get('is_bankrupt', False):
                player_line += " <s>Bankrupt</s>"
                
            player_lines.append(player_line)
        
        return "\n".join(player_lines)
    
    async def notify_game_start(self, game_uid: str, players: List[Dict[str, Any]], 
                              game_config: Dict[str, Any] = None) -> bool:
        """Notify when a new game starts"""
        if not self.enabled:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format player list
        player_info = self._format_player_info(players)
        
        # Format configuration info
        config_info = ""
        if game_config:
            max_turns = game_config.get('max_turns', 'unknown')
            config_info = f"\n🎯 Max turns: {max_turns}"
        
        message = f"""
🎮 <b>New game started!</b>

🆔 Game ID: <code>{game_uid}</code>
⏰ Start time: {timestamp}
👥 Player count: {len(players)}

<b>Participating players:</b>
{player_info}{config_info}

🚀 Game is starting, good luck to all players!
        """.strip()
        
        return await self.send_message(message)
    
    async def notify_turn_end(self, game_uid: str, turn_data: Dict[str, Any]) -> bool:
        """Notify when a turn ends"""
        if not self.enabled:
            return False
        
        turn_number = turn_data.get('turn_number', 0)
        # Convert 0-based turn number to 1-based for user-friendly display
        display_turn_number = turn_number + 1
        
        current_player = turn_data.get('current_player', {})
        player_name = current_player.get('name', f"Player {current_player.get('id', '?')}")
        
        # Format actions that happened this turn
        actions = turn_data.get('actions', [])
        action_summary = ""
        
        if actions:
            action_lines = []
            for action in actions:
                if action.get('type') == 'roll':
                    # Simple dice roll - just use the description directly
                    description = action.get('description', 'rolled dice')
                    action_lines.append(description)
                else:
                    # Generic action
                    desc = action.get('description', 'did something')
                    action_lines.append(f"• {desc}")
            
            if action_lines:
                action_summary = f"\n\n<b>This turn actions:</b>\n" + "\n".join(action_lines)
        
        # Player status
        money = current_player.get('money', 0)
        position = current_player.get('position', 0)
        status_emoji = "💰" if not current_player.get('is_bankrupt', False) else "💸"
        
        message = f"""
🔄 <b>Turn {display_turn_number} ended</b>

🎯 Current player: {status_emoji} <b>{player_name}</b>
💵 Money: ${money}
📍 Position: {position}{action_summary}

🎮 Game ID: <code>{game_uid}</code>
        """.strip()
        
        return await self.send_message(message, disable_notification=True)  # Silent for turn updates
    
    async def notify_game_end(self, game_uid: str, end_data: Dict[str, Any]) -> bool:
        """Notify when a game ends"""
        if not self.enabled:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Determine end reason
        end_reason = end_data.get('reason', 'unknown')
        reason_text = ""
        
        if end_reason == 'winner':
            winner = end_data.get('winner', {})
            winner_name = winner.get('name', 'unknown player')
            winner_money = winner.get('money', 0)
            reason_text = f"🏆 <b>{winner_name}</b> won! (💵${winner_money})"
        elif end_reason == 'max_turns':
            max_turns = end_data.get('max_turns_reached', '?')
            reason_text = f"⏱️ Max turns reached ({max_turns})"
        elif end_reason == 'all_bankrupt':
            reason_text = "💸 All players are bankrupt"
        else:
            reason_text = f"🔚 Game ended ({end_reason})"
        
        # Format final standings
        final_players = end_data.get('final_players', [])
        standings = ""
        if final_players:
            standings_lines = []
            for i, player in enumerate(final_players, 1):
                name = player.get('name', f"Player {player.get('id', '?')}")
                money = player.get('money', 0)
                status = "💰" if not player.get('is_bankrupt', False) else "💸"
                standings_lines.append(f"{i}. {status} <b>{name}</b> - 💵${money}")
            
            if standings_lines:
                standings = f"\n\n<b>Final standings:</b>\n" + "\n".join(standings_lines)
        
        # Game statistics
        stats = end_data.get('statistics', {})
        total_turns = stats.get('total_turns', '?')
        duration = stats.get('duration_minutes', '?')
        
        stats_text = f"\n\n📊 <b>Game statistics:</b>\n• Total turns: {total_turns}\n• Game duration: {duration} minutes"
        
        message = f"""
🏁 <b>Game ended!</b>

🆔 Game ID: <code>{game_uid}</code>
⏰ End time: {timestamp}

{reason_text}{standings}{stats_text}

Thank you for participating! 🎮
        """.strip()
        
        return await self.send_message(message)
    
    async def notify_critical_error(self, game_uid: str, error_data: Dict[str, Any]) -> bool:
        """Notify when a critical error occurs"""
        if not self.enabled:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        error_type = error_data.get('error_type', 'unknown')
        error_message = error_data.get('message', 'unknown error')
        error_context = error_data.get('context', {})
        
        context_text = ""
        if error_context:
            current_player = error_context.get('current_player')
            turn_number = error_context.get('turn_number')
            
            if current_player:
                context_text += f"\n👤 Current player: {current_player}"
            if turn_number:
                context_text += f"\n🔄 Turn number: {turn_number}"
        
        message = f"""
🚨 <b>Critical error alert!</b>

🆔 Game ID: <code>{game_uid}</code>
⏰ Error time: {timestamp}
⚠️ Error type: <code>{error_type}</code>

<b>Error details:</b>
<pre>{error_message}</pre>{context_text}

🛠️ Please check server logs for more information
        """.strip()
        
        return await self.send_message(message)
    
    async def notify_action_error(self, error_data: Dict[str, Any]) -> bool:
        """Notify when an agent action fails during gameplay with enhanced debugging information"""
        if not self.enabled:
            return False
        
        # 🔍 ENHANCED ERROR NOTIFICATION with comprehensive debugging data
        
        # Basic information
        game_uid = error_data.get('game_uid', 'unknown')
        turn_number = error_data.get('turn_number', '?')
        action_sequence = error_data.get('action_sequence', '?')
        timestamp = error_data.get('timestamp', datetime.now().strftime("%H:%M:%S"))
        
        # Player information
        player_name = error_data.get('player_name', 'unknown player')
        player_id = error_data.get('player_id', '?')
        player_money = error_data.get('player_money', '?')
        player_position = error_data.get('player_position', '?')
        player_properties_count = error_data.get('player_properties_count', '?')
        player_in_jail = error_data.get('player_in_jail', False)
        player_bankrupt = error_data.get('player_bankrupt', False)
        
        # Action information
        action_name = error_data.get('action_name', 'unknown action')
        action_parameters = error_data.get('action_parameters', 'N/A')
        available_actions = error_data.get('available_actions', 'N/A')
        error_message = error_data.get('error_message', 'unknown error')
        action_status = error_data.get('action_status', 'Unknown')
        
        # Game state information
        pending_decision = error_data.get('pending_decision', 'None')
        dice_processed = error_data.get('dice_processed', '?')
        auction_active = error_data.get('auction_active', '?')
        current_dice = error_data.get('current_dice', 'N/A')
        
        # Context information
        property_info = error_data.get('property_info', '')
        trade_info = error_data.get('trade_info', '')
        last_mortgage_error = error_data.get('last_mortgage_error', '')
        agent_thoughts = error_data.get('agent_thoughts', '')
        
        # Build the comprehensive error message
        message_parts = []
        
        # Header
        message_parts.append("🚨 <b>AGENT ACTION FAILED</b> 🚨")
        message_parts.append("")
        
        # Basic info section
        message_parts.append("📋 <b>Basic Information:</b>")
        message_parts.append(f"🎮 Game: <code>{game_uid}</code>")
        message_parts.append(f"🔄 Turn: {turn_number} (Action #{action_sequence})")
        message_parts.append(f"⏰ Time: {timestamp}")
        message_parts.append("")
        
        # Player info section
        player_status_emoji = "💸" if player_bankrupt else ("🏛️" if player_in_jail else "💰")
        message_parts.append("👤 <b>Player Information:</b>")
        message_parts.append(f"{player_status_emoji} <b>{player_name}</b> (P{player_id})")
        message_parts.append(f"💵 Money: ${player_money}")
        message_parts.append(f"📍 Position: {player_position}")
        message_parts.append(f"🏠 Properties: {player_properties_count}")
        if player_in_jail:
            message_parts.append("🏛️ Status: In Jail")
        if player_bankrupt:
            message_parts.append("💸 Status: Bankrupt")
        message_parts.append("")
        
        # Action info section
        message_parts.append("🎯 <b>Action Details:</b>")
        message_parts.append(f"🔧 Action: <code>{action_name}</code>")
        message_parts.append(f"📊 Status: <code>{action_status}</code>")
        if action_parameters and action_parameters != "N/A":
            # Format parameters for better readability
            params_display = action_parameters
            if len(params_display) > 60:
                params_display = params_display[:57] + "..."
            message_parts.append(f"⚙️ Parameters: <code>{params_display}</code>")
        message_parts.append("")
        
        # Error details section
        message_parts.append("❌ <b>Error Details:</b>")
        # Format error message with line breaks if too long
        if len(error_message) > 80:
            error_lines = []
            words = error_message.split()
            current_line = ""
            for word in words:
                if len(current_line + word + " ") <= 80:
                    current_line += word + " "
                else:
                    if current_line:
                        error_lines.append(current_line.strip())
                    current_line = word + " "
            if current_line:
                error_lines.append(current_line.strip())
            
            for line in error_lines:
                message_parts.append(f"📝 {line}")
        else:
            message_parts.append(f"📝 {error_message}")
        message_parts.append("")
        
        # Context information
        context_added = False
        if property_info:
            if not context_added:
                message_parts.append("🔍 <b>Context Information:</b>")
                context_added = True
            message_parts.append(f"🏠 Property: {property_info}")
        
        if trade_info:
            if not context_added:
                message_parts.append("🔍 <b>Context Information:</b>")
                context_added = True
            message_parts.append(f"🤝 Trade: {trade_info}")
        
        if last_mortgage_error:
            if not context_added:
                message_parts.append("🔍 <b>Context Information:</b>")
                context_added = True
            message_parts.append(f"🏛️ Mortgage: {last_mortgage_error}")
        
        if context_added:
            message_parts.append("")
        
        # Game state section
        message_parts.append("🎲 <b>Game State:</b>")
        message_parts.append(f"🎯 Pending: {pending_decision}")
        message_parts.append(f"🎲 Dice Done: {dice_processed}")
        message_parts.append(f"🎪 Auction: {auction_active}")
        if current_dice != "N/A":
            message_parts.append(f"🎲 Current Dice: {current_dice}")
        message_parts.append("")
        
        # Available actions
        if available_actions and available_actions != "None":
            message_parts.append("🛠️ <b>Available Actions:</b>")
            # Format available actions with line breaks if too long
            actions_display = available_actions
            if len(actions_display) > 60:
                # Split by comma and format nicely
                action_list = [a.strip() for a in actions_display.split(',')]
                if len(action_list) > 3:
                    actions_display = ', '.join(action_list[:3]) + f", +{len(action_list)-3} more"
                else:
                    actions_display = ', '.join(action_list)
            message_parts.append(f"⚙️ {actions_display}")
            message_parts.append("")
        
        # Agent thoughts (if available and short enough)
        if agent_thoughts and len(agent_thoughts) > 10:
            message_parts.append("🧠 <b>AI Thoughts (excerpt):</b>")
            thoughts_display = agent_thoughts
            if len(thoughts_display) > 150:
                thoughts_display = thoughts_display[:147] + "..."
            message_parts.append(f"💭 {thoughts_display}")
        
        # Join all parts together
        message = "\n".join(message_parts)
        
        # Send with silent notification to avoid spam
        return await self.send_message(message, disable_notification=True)
    
    async def notify_server_status(self, status_data: Dict[str, Any]) -> bool:
        """Notify about server status updates"""
        if not self.enabled:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        status_type = status_data.get('type', 'info')
        message_text = status_data.get('message', 'Server status update')
        
        # Choose emoji based on status type
        emoji = {
            'startup': '🚀',
            'shutdown': '🛑',
            'maintenance': '🔧',
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️'
        }.get(status_type, 'ℹ️')
        
        # Format additional details
        details = status_data.get('details', {})
        details_text = ""
        
        if details:
            active_games = details.get('active_games')
            available_agents = details.get('available_agents')
            
            if active_games is not None:
                details_text += f"\n🎮 Active games: {active_games}"
            if available_agents is not None:
                details_text += f"\n🤖 Available agents: {available_agents}"
        
        message = f"""
{emoji} <b>Server status</b>

⏰ Time: {timestamp}
📝 Info: {message_text}{details_text}
        """.strip()
        
        return await self.send_message(message, disable_notification=(status_type == 'info'))

# Global telegram notifier instance
telegram_notifier: Optional[TelegramNotifier] = None

def get_telegram_notifier() -> Optional[TelegramNotifier]:
    """Get the global telegram notifier instance"""
    return telegram_notifier

def initialize_telegram_notifier(bot_token: str = None, chat_id: str = None) -> TelegramNotifier:
    """Initialize the global telegram notifier"""
    global telegram_notifier
    telegram_notifier = TelegramNotifier(bot_token, chat_id)
    return telegram_notifier 