import asyncio
import os
import datetime
from typing import Dict, List, Any, Optional
import traceback

from .telegram_notifier import get_telegram_notifier, TelegramNotifier


class GameEventHandler:
    """
    game event handler - handle all game related events
    """
    
    def __init__(self):
        self.notifier: Optional[TelegramNotifier] = None
        self._initialize_notifier()
    
    def _initialize_notifier(self):
        """initialize Telegram notifier"""
        self.notifier = get_telegram_notifier()
    
    async def handle_server_startup(self, available_agents_count: int) -> bool:
        """handle server startup event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            await self.notifier.notify_server_status({
                'type': 'startup',
                'message': '🚀 Monopoly game server started successfully',
                'details': {
                    'active_games': 0,
                    'available_agents': available_agents_count
                }
            })
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send startup notification: {e}")
            return False
    
    async def handle_server_shutdown(self, active_games_count: int) -> bool:
        """handle server shutdown event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            await self.notifier.notify_server_status({
                'type': 'shutdown', 
                'message': '🛑 Monopoly game server is shutting down',
                'details': {
                    'active_games': active_games_count
                }
            })
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send shutdown notification: {e}")
            return False
    
    async def handle_game_start(self, game_uid: str, gc, max_turns: int) -> bool:
        """handle game start event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            # extract player information
            players_info = []
            for player in gc.players:
                players_info.append({
                    'id': player.player_id,
                    'name': player.name,
                    'money': player.money,
                    'position': player.position,
                    'is_bankrupt': player.is_bankrupt,
                    'in_jail': player.in_jail
                })
            
            game_config = {
                'max_turns': max_turns,
                'num_players': len(gc.players)
            }
            
            await self.notifier.notify_game_start(game_uid, players_info, game_config)
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send game start notification: {e}")
            return False
    
    async def handle_turn_end(self, game_uid: str, gc, turn_number: int, player_id: int, 
                            turn_actions: List[Dict[str, Any]] = None) -> bool:
        """handle turn end event"""
        if not self.notifier or not self.notifier.enabled:
            return False
        
        # only send notification on specific turns to avoid spam
        if not (turn_number % 5 == 0 or turn_number <= 5):
            return True
            
        try:
            player = gc.players[player_id]
            current_player_info = {
                'id': player.player_id,
                'name': player.name,
                'money': player.money,
                'position': player.position,
                'is_bankrupt': player.is_bankrupt,
                'in_jail': player.in_jail
            }
            
            turn_data = {
                'turn_number': turn_number,
                'current_player': current_player_info,
                'actions': turn_actions or []
            }
            
            await self.notifier.notify_turn_end(game_uid, turn_data)
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send turn end notification: {e}")
            return False
    
    async def handle_game_end(self, game_uid: str, gc, loop_turn_count: int, max_turns: int,
                            start_time: datetime.datetime = None) -> bool:
        """handle game end event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            # determine end reason
            end_reason = 'unknown'
            winner_data = {}
            
            active_players = [p for p in gc.players if not p.is_bankrupt]
            if len(active_players) == 1:
                end_reason = 'winner'
                winner = active_players[0]
                winner_data = {
                    'name': winner.name,
                    'money': winner.money,
                    'id': winner.player_id
                }
            elif loop_turn_count >= max_turns:
                end_reason = 'max_turns'
            elif not active_players:
                end_reason = 'all_bankrupt'
            
            # format final rankings
            final_players = []
            sorted_players = sorted(gc.players, key=lambda p: p.money, reverse=True)
            for player in sorted_players:
                final_players.append({
                    'id': player.player_id,
                    'name': player.name,
                    'money': player.money,
                    'is_bankrupt': player.is_bankrupt
                })
            
            # calculate game statistics
            game_duration = 0
            if start_time:
                game_duration = (datetime.datetime.now() - start_time).total_seconds() / 60
            
            end_data = {
                'reason': end_reason,
                'winner': winner_data,
                'max_turns_reached': max_turns,
                'final_players': final_players,
                'statistics': {
                    'total_turns': gc.turn_count,
                    'duration_minutes': round(game_duration, 1)
                }
            }
            
            await self.notifier.notify_game_end(game_uid, end_data)
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send game end notification: {e}")
            return False
    
    async def handle_critical_error(self, game_uid: str, error: Exception, gc=None) -> bool:
        """handle critical error event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            error_context = {}
            if gc:
                try:
                    current_player_name = 'Unknown'
                    if (hasattr(gc, 'current_player_index') and 
                        hasattr(gc, 'players') and 
                        gc.current_player_index < len(gc.players)):
                        current_player_name = gc.players[gc.current_player_index].name
                    
                    error_context = {
                        'current_player': current_player_name,
                        'turn_number': getattr(gc, 'turn_count', 'Unknown')
                    }
                except:
                    error_context = {'context_error': 'Failed to extract game context'}
            
            error_data = {
                'error_type': type(error).__name__,
                'message': str(error),
                'context': error_context
            }
            
            await self.notifier.notify_critical_error(game_uid, error_data)
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send error notification: {e}")
            return False
    
    async def handle_special_event(self, game_uid: str, event_type: str, player_name: str, 
                                 event_data: Dict[str, Any] = None) -> bool:
        """handle special game events (buy property, go to jail, trade, etc.)"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            # construct special event message
            event_info = event_data or {}
            event_info.update({
                'event_type': event_type,
                'player_name': player_name,
                'game_uid': game_uid  # Add game_uid to event_info for proper formatting
            })
            
            # send different notifications based on event type
            if event_type in ['jail', 'bankruptcy', 'property_buy', 'property_buy_failed', 'property_sell', 'trade', 'auction', 'rent_payment', 'go_salary', 'doubles_bonus_turn', 'card_drawn', 'income_tax']:
                # these important events are sent immediately
                message = self._format_special_event_message(event_info)
                if message:
                    await self.notifier.send_message(message, disable_notification=True)
                    return True
            
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send special event notification: {e}")
            return False
    
    def _format_special_event_message(self, event_info: Dict[str, Any]) -> str:
        """format special event message"""
        event_type = event_info.get('event_type', '')
        player_name = event_info.get('player_name', 'unknown player')
        game_uid = event_info.get('game_uid', '')
        
        if event_type == 'jail':
            return f"🏭 <b>{player_name}</b> went to jail!\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'bankruptcy':
            return f"💸 <b>{player_name}</b> is bankrupt!\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'property_buy':
            property_name = event_info.get('property_name', 'unknown property')
            amount = event_info.get('amount', 0)
            return f"🏠 <b>{player_name}</b> bought <i>{property_name}</i> (💵${amount})\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'property_buy_failed':
            property_name = event_info.get('property_name', 'unknown property')
            property_price = event_info.get('property_price', 0)
            player_money = event_info.get('player_money', 0)
            reason = event_info.get('reason', 'Unknown reason')
            return f"❌ <b>{player_name}</b> failed to buy <i>{property_name}</i>\n💰 Price: ${property_price} | Player money: ${player_money}\n📝 Reason: {reason}\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'trade':
            other_player = event_info.get('other_player', 'other player')
            return f"🤝 <b>{player_name}</b> and <b>{other_player}</b> completed a trade\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'auction':
            property_name = event_info.get('property_name', 'unknown property')
            amount = event_info.get('amount', 0)
            return f"🏛️ <b>{player_name}</b> won the auction for <i>{property_name}</i> at 💵${amount}\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'rent_payment':
            property_name = event_info.get('property_name', 'unknown property')
            amount = event_info.get('amount', 0)
            owner_name = event_info.get('owner_name', 'unknown owner')
            return f"🏡 <b>{player_name}</b> paid rent 💵${amount} to <b>{owner_name}</b> for <i>{property_name}</i>\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'go_salary':
            amount = event_info.get('amount', 200)
            return f"💰 <b>{player_name}</b> passed GO and collected 💵${amount} salary\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'doubles_bonus_turn':
            dice = event_info.get('dice', [0, 0])
            streak = event_info.get('streak', 1)
            return f"🎲 <b>{player_name}</b> rolled doubles ({dice[0]}, {dice[1]}) and gets bonus turn! (Streak: {streak})\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'card_drawn':
            card_type = event_info.get('card_type', 'unknown')
            card_description = event_info.get('card_description', 'unknown card')
            return f"🃏 <b>{player_name}</b> drew {card_type} card: <i>{card_description}</i>\n🎮 Game: <code>{game_uid}</code>"
        elif event_type == 'income_tax':
            amount = event_info.get('amount', 0)
            tax_type = event_info.get('tax_type', 'Income Tax')
            return f"📊 <b>{player_name}</b> paid {tax_type} 💸${amount}\n🎮 Game: <code>{game_uid}</code>"
        
        return ""
    
    async def handle_maintenance_event(self, active_games: int, available_agents: int) -> bool:
        """handle maintenance event"""
        if not self.notifier or not self.notifier.enabled:
            return False
            
        try:
            await self.notifier.notify_server_status({
                'type': 'maintenance',
                'message': '🔧 System maintenance check',
                'details': {
                    'active_games': active_games,
                    'available_agents': available_agents
                }
            })
            return True
        except Exception as e:
            print(f"[GameEventHandler] Failed to send maintenance notification: {e}")
            return False


# global game event handler instance
_game_event_handler: Optional[GameEventHandler] = None

def get_game_event_handler() -> GameEventHandler:
    """get global game event handler instance"""
    global _game_event_handler
    if _game_event_handler is None:
        _game_event_handler = GameEventHandler()
    return _game_event_handler

def initialize_game_event_handler() -> GameEventHandler:
    """initialize global game event handler"""
    global _game_event_handler
    _game_event_handler = GameEventHandler()
    return _game_event_handler 