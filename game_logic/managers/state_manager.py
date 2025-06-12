from typing import Dict, Any, Optional, List
from .base_manager import BaseManager
from ..player import Player


class StateManager(BaseManager):
    """
    Handles game state management including pending decisions,
    turn management, and game flow control.
    """
    
    def get_manager_name(self) -> str:
        return "StateManager" 
        
    def clear_pending_decision(self) -> None:
        """Clear the current pending decision"""
        self.gc.pending_decision_type = None
        self.gc.pending_decision_context = {}
        
    def set_pending_decision(self, decision_type: str, context: Optional[Dict[str, Any]] = None, outcome_processed: bool = False) -> None:
        """
        Set a pending decision that requires player action.
        
        Args:
            decision_type: Type of decision required
            context: Additional context for the decision
            outcome_processed: Whether the dice roll outcome has been processed
        """
        self.gc.pending_decision_type = decision_type
        self.gc.pending_decision_context = context or {}
        self.gc.dice_roll_outcome_processed = outcome_processed
        
        self.log_event(f"Pending decision set: {decision_type} with context: {context}", "debug_state")
        
    def resolve_current_action_segment(self) -> None:
        """
        Resolve the current action segment and prepare for next action.
        """
        self.gc.dice_roll_outcome_processed = True
        self.clear_pending_decision()
        self.log_event("Current action segment resolved", "debug_state")
        
    def next_turn(self) -> None:
        """
        Advance to the next player's turn.
        """
        # Skip bankrupt players
        original_index = self.current_player_index
        attempts = 0
        max_attempts = len(self.players)
        
        while attempts < max_attempts:
            self.gc.current_player_index = (self.gc.current_player_index + 1) % len(self.players)
            current_player = self.get_current_player()
            
            if not current_player.is_bankrupt:
                break
                
            attempts += 1
        
        if attempts >= max_attempts:
            self.log_event("All players are bankrupt - game should end", "error_state")
            self.gc.game_over = True
            return
            
        # Reset turn-specific state
        self.gc.doubles_streak = 0
        self.gc.dice_roll_outcome_processed = True
        self.clear_pending_decision()
        
        # Increment turn count only when returning to the first player
        if self.current_player_index <= original_index:
            self.gc.turn_count += 1
            
        new_player = self.get_current_player()
        self.log_event(f"Turn advanced to {new_player.name} (P{self.current_player_index}). Turn: {self.gc.turn_count}", "turn_advance")
        
        # Handle start-of-turn conditions
        self._handle_turn_start_conditions(new_player)
        
    def _handle_turn_start_conditions(self, player: Player) -> None:
        """
        Handle conditions that need to be checked at the start of a player's turn.
        
        Args:
            player: The player whose turn is starting
        """
        if player.in_jail:
            self.gc.jail_manager.handle_jail_turn_initiation(player)
        elif player.pending_mortgaged_properties_to_handle:
            self._handle_received_mortgaged_property_initiation(player)
        else:
            # Normal turn start - no special conditions
            self.resolve_current_action_segment()
            
    def _handle_received_mortgaged_property_initiation(self, player: Player) -> None:
        """
        Handle initiation of decisions for mortgaged properties received in trades.
        
        Args:
            player: The player who received mortgaged properties
        """
        if not player.pending_mortgaged_properties_to_handle:
            self.resolve_current_action_segment()
            return
            
        # Set pending decision for handling mortgaged properties
        self.set_pending_decision(
            "handle_received_mortgaged_properties",
            context={
                "player_id": player.player_id,
                "mortgaged_properties": player.pending_mortgaged_properties_to_handle.copy()
            },
            outcome_processed=False
        )
        
        self.log_event(f"{player.name} needs to handle {len(player.pending_mortgaged_properties_to_handle)} mortgaged properties", "state_event")
        
    def check_for_game_over_condition(self) -> None:
        """
        Check if the game should end due to bankruptcy or other conditions.
        """
        active_players = [p for p in self.players if not p.is_bankrupt]
        
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                self.log_event(f"Game Over! {winner.name} wins!", "game_over")
            else:
                self.log_event("Game Over! No players remaining.", "game_over")
                
            self.gc.game_over = True
            self.clear_pending_decision()
            self.gc.dice_roll_outcome_processed = True
            
    def get_active_player_for_decision(self) -> Optional[int]:
        """
        Get the player ID who should make the next decision.
        
        Returns:
            Optional[int]: Player ID or None if no decision pending
        """
        if self.gc.pending_decision_type and self.gc.pending_decision_context:
            return self.gc.pending_decision_context.get("player_id")
        return None
        
    def is_player_turn_complete(self, player_id: int) -> bool:
        """
        Check if a player's turn is complete.
        
        Args:
            player_id: ID of the player to check
            
        Returns:
            bool: True if the player's turn is complete
        """
        if player_id != self.current_player_index:
            return True  # Not their turn
            
        if not self.gc.dice_roll_outcome_processed:
            return False  # Still processing dice roll outcome
            
        if self.gc.pending_decision_type:
            decision_player = self.get_active_player_for_decision()
            if decision_player == player_id:
                return False  # Still has pending decision
                
        return True
        
    def can_player_act(self, player_id: int) -> bool:
        """
        Check if a player can currently take an action.
        
        Args:
            player_id: ID of the player to check
            
        Returns:
            bool: True if the player can act
        """
        if not (0 <= player_id < len(self.players)):
            return False
            
        player = self.players[player_id]
        if player.is_bankrupt:
            return False
            
        # Check if it's their turn or they have a pending decision
        if player_id == self.current_player_index:
            return True
            
        # Check if they have a pending decision (like responding to a trade)
        decision_player = self.get_active_player_for_decision()
        if decision_player == player_id:
            return True
            
        return False
        
    def get_game_phase(self) -> str:
        """
        Get the current phase of the game.
        
        Returns:
            str: Description of the current game phase
        """
        if self.gc.game_over:
            return "game_over"
            
        if self.gc.pending_decision_type:
            return f"pending_{self.gc.pending_decision_type}"
            
        if not self.gc.dice_roll_outcome_processed:
            return "processing_dice_outcome"
            
        return "normal_turn"
        
    def save_game_state_snapshot(self) -> Dict[str, Any]:
        """
        Create a snapshot of the current game state.
        
        Returns:
            Dict[str, Any]: Game state snapshot
        """
        return {
            "turn_count": self.turn_count,
            "current_player_index": self.current_player_index,
            "game_over": self.gc.game_over,
            "pending_decision_type": self.gc.pending_decision_type,
            "pending_decision_context": self.gc.pending_decision_context.copy(),
            "dice_roll_outcome_processed": self.gc.dice_roll_outcome_processed,
            "doubles_streak": self.gc.doubles_streak,
            "dice": self.gc.dice,
            "game_phase": self.get_game_phase(),
            "active_player_count": len([p for p in self.players if not p.is_bankrupt]),
            "trade_offers_count": len(self.gc.trade_offers) if hasattr(self.gc, 'trade_offers') else 0
        }
        
    def restore_game_state_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        """
        Restore game state from a snapshot.
        
        Args:
            snapshot: Game state snapshot to restore
            
        Returns:
            bool: True if restoration was successful
        """
        try:
            self.gc.turn_count = snapshot.get("turn_count", 1)
            self.gc.current_player_index = snapshot.get("current_player_index", 0)
            self.gc.game_over = snapshot.get("game_over", False)
            self.gc.pending_decision_type = snapshot.get("pending_decision_type")
            self.gc.pending_decision_context = snapshot.get("pending_decision_context", {})
            self.gc.dice_roll_outcome_processed = snapshot.get("dice_roll_outcome_processed", True)
            self.gc.doubles_streak = snapshot.get("doubles_streak", 0)
            self.gc.dice = snapshot.get("dice", (0, 0))
            
            self.log_event(f"Game state restored to turn {self.gc.turn_count}, phase: {snapshot.get('game_phase', 'unknown')}", "state_restore")
            return True
            
        except Exception as e:
            self.log_event(f"Failed to restore game state: {str(e)}", "error_state")
            return False 