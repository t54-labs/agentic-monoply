from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Avoid circular imports by using TYPE_CHECKING
if TYPE_CHECKING:
    from ..game_controller_v2 import GameControllerV2


class BaseManager(ABC):
    """
    Base class for all game logic managers.
    Each manager handles a specific aspect of the game logic to reduce
    the complexity of the main GameController class.
    """
    
    def __init__(self, game_controller: 'GameControllerV2'):
        """
        Initialize the manager with a reference to the main game controller.
        
        Args:
            game_controller: The main GameController instance
        """
        self.gc = game_controller
        
    @property
    def players(self):
        """Convenience property to access players"""
        return self.gc.players
        
    @property
    def board(self):
        """Convenience property to access board"""
        return self.gc.board
        
    @property
    def current_player_index(self):
        """Convenience property to access current player index"""
        return self.gc.current_player_index
        
    @property
    def turn_count(self):
        """Convenience property to access turn count"""
        return self.gc.turn_count
        
    def get_current_player(self):
        """Convenience method to get current player"""
        return self.gc.get_current_player()
        
    def log_event(self, message: str, event_type: str = "game_log_event"):
        """Convenience method to log events through the game controller"""
        self.gc.log_event(message, event_type)
        
    @abstractmethod
    def get_manager_name(self) -> str:
        """
        Return the name of this manager for logging and debugging purposes.
        
        Returns:
            str: The name of this manager
        """
        pass
        
    def initialize(self) -> None:
        """
        Optional initialization method called after all managers are created.
        Override this if the manager needs to perform setup after all managers exist.
        """
        pass 