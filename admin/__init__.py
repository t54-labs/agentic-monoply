"""
Telegram module for Monopoly Game Server

This package contains all Telegram-related functionality including:
- Bot notifications (TelegramNotifier)
- Command handlers (telegram_command_handlers)
- Game event handling (GameEventHandler)
"""

# Import main classes and functions for easy access
from .telegram_notifier import TelegramNotifier, get_telegram_notifier, initialize_telegram_notifier
from .game_event_handler import GameEventHandler, get_game_event_handler, initialize_game_event_handler
from .telegram_command_handlers import (
    telegram_end_game_command_handler,
    telegram_get_status_command_handler,
    telegram_get_game_status_command_handler,
    telegram_create_random_agents_command_handler
)

__all__ = [
    # TelegramNotifier
    'TelegramNotifier',
    'get_telegram_notifier', 
    'initialize_telegram_notifier',
    
    # GameEventHandler
    'GameEventHandler',
    'get_game_event_handler',
    'initialize_game_event_handler',
    
    # Command handlers
    'telegram_end_game_command_handler',
    'telegram_get_status_command_handler',
    'telegram_get_game_status_command_handler', 
    'telegram_create_random_agents_command_handler'
] 