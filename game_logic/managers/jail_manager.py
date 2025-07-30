from typing import Dict, Any, Optional
from .base_manager import BaseManager
from ..player import Player


class JailManager(BaseManager):
    """
    Handles jail mechanics including getting out of jail,
    paying bail, using cards, and rolling for release.
    """
    
    def get_manager_name(self) -> str:
        return "JailManager"
    
    def handle_jail_turn_initiation(self, player: Player) -> None:
        """
        Handle the initiation of a jail turn for a player.
        
        Args:
            player: The player who is in jail
        """
        if not player.in_jail:
            self.log_event(f"{player.name} is not in jail", "error_jail")
            return
            
        self.log_event(f"{player.name} is in jail. Turns remaining: {getattr(player, 'jail_turns_remaining', 0)}", "jail_event")
        
        # Set pending decision for jail options
        self.gc._set_pending_decision(
            "jail_options",
            context={
                "player_id": player.player_id,
                "jail_turns_remaining": getattr(player, 'jail_turns_remaining', 0),
                "can_use_gooj_card": self._can_use_gooj_card_internal(player),
                "can_pay_bail": player.money >= 50  # Standard bail amount
            },
            outcome_processed=False
        )
        
    async def attempt_roll_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempt to roll doubles to get out of jail.
        
        Args:
            player_id: ID of the player attempting to roll out
            params: Additional parameters
            
        Returns:
            Dict[str, Any]: Result of the roll attempt
        """
        if not (0 <= player_id < len(self.players)):
            return {"success": False, "message": "Invalid player ID"}
            
        player = self.players[player_id]
        
        if not player.in_jail:
            return {"success": False, "message": f"{player.name} is not in jail"}
            
        # Roll dice
        dice1, dice2 = self.gc.roll_dice()
        is_doubles = dice1 == dice2
        
        if is_doubles:
            # Got doubles - free from jail
            player.leave_jail()
            self.log_event(f"{player.name} rolled doubles ({dice1}, {dice2}) and is released from jail!", "jail_event")
            
            # Move player based on dice roll
            await self.gc._move_player(player, dice1 + dice2)
            
            # 🎯 CRITICAL FIX: After movement, resolve the action segment
            # This ensures the game state is properly updated and prevents agents from thinking they need to roll dice again
            self.gc._resolve_current_action_segment()
            
            return {
                "success": True, 
                "message": f"{player.name} rolled doubles and is free!",
                "dice": [dice1, dice2],
                "released": True
            }
        else:
            # No doubles - stay in jail
            jail_turns_remaining = getattr(player, 'jail_turns_remaining', 3) - 1
            player.jail_turns_remaining = max(0, jail_turns_remaining)
            
            self.log_event(f"{player.name} rolled ({dice1}, {dice2}) - no doubles. Jail turns remaining: {player.jail_turns_remaining}", "jail_event")
            
            if player.jail_turns_remaining <= 0:
                # Must pay to get out after 3 turns
                self.log_event(f"{player.name} has served maximum jail time and must pay $50 to get out", "jail_event")
                return await self.pay_to_get_out_of_jail(player_id, {"forced": True})
            else:
                # End turn in jail
                self.gc._resolve_current_action_segment()
                return {
                    "success": True,
                    "message": f"{player.name} stays in jail",
                    "dice": [dice1, dice2],
                    "released": False,
                    "turns_remaining": player.jail_turns_remaining
                }
    
    async def pay_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pay bail to get out of jail.
        
        Args:
            player_id: ID of the player paying bail
            params: Additional parameters (may include "forced" for mandatory payment)
            
        Returns:
            Dict[str, Any]: Result of the payment
        """
        if not (0 <= player_id < len(self.players)):
            return {"success": False, "message": "Invalid player ID"}
            
        player = self.players[player_id]
        
        if not player.in_jail:
            return {"success": False, "message": f"{player.name} is not in jail"}
            
        bail_amount = 50  # Standard bail amount
        forced = params.get("forced", False)
        
        if player.money < bail_amount:
            if forced:
                # Must pay but can't afford - handle bankruptcy
                self.log_event(f"{player.name} cannot afford ${bail_amount} bail and will be bankrupted", "error_jail")
                self.gc.bankruptcy_manager.check_and_handle_bankruptcy(player, debt_to_creditor=bail_amount, creditor=None)
                return {"success": False, "message": f"{player.name} cannot afford bail - bankruptcy initiated"}
            else:
                return {"success": False, "message": f"{player.name} cannot afford ${bail_amount} bail"}
        
        # Execute TPay payment for bail
        payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_system(
            payer=player,
            amount=float(bail_amount),
            reason="jail bail",
            event_description=f"{player.name} paid ${bail_amount} bail to get out of jail"
        )
        
        if payment_success:
            # Release from jail
            player.leave_jail()
            self.log_event(f"{player.name} paid ${bail_amount} bail and is released from jail", "jail_event")
            
            # 🎲 IMPORTANT: After paying bail, player must immediately roll dice and move
            # This is a core Monopoly rule - no optional actions after getting out of jail
            self.log_event(f"{player.name} must now roll dice and move immediately after paying bail", "jail_event")
            
            # Roll dice for the player
            dice1, dice2 = self.gc.roll_dice()
            
            # Move player based on dice roll
            await self.gc._move_player(player, dice1 + dice2)
            
            # 🎯 CRITICAL FIX: After movement, resolve the action segment
            # This ensures the game state is properly updated and prevents agents from thinking they need to roll dice again
            self.gc._resolve_current_action_segment()
            
            return {
                "success": True,
                "message": f"{player.name} paid bail, rolled ({dice1}, {dice2}), and moved!",
                "amount_paid": bail_amount,
                "released": True,
                "dice": [dice1, dice2],
                "moved": True
            }
        else:
            self.log_event(f"{player.name} bail payment failed", "error_jail")
            return {"success": False, "message": "Bail payment failed"}
    
    async def use_card_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use a Get Out of Jail Free card.
        
        Args:
            player_id: ID of the player using the card
            params: Additional parameters
            
        Returns:
            Dict[str, Any]: Result of using the card
        """
        if not (0 <= player_id < len(self.players)):
            return {"success": False, "message": "Invalid player ID"}
            
        player = self.players[player_id]
        
        if not player.in_jail:
            return {"success": False, "message": f"{player.name} is not in jail"}
            
        if not self._can_use_gooj_card_internal(player):
            return {"success": False, "message": f"{player.name} has no Get Out of Jail Free cards"}
        
        # Use the card
        if hasattr(player, 'has_chance_gooj_card') and player.has_chance_gooj_card:
            player.has_chance_gooj_card = False
            card_type = "Chance"
        elif hasattr(player, 'has_community_gooj_card') and player.has_community_gooj_card:
            player.has_community_gooj_card = False
            card_type = "Community Chest"
        else:
            # Use generic GOOJ card count if available
            if player.get_out_of_jail_free_cards > 0:
                player.get_out_of_jail_free_cards -= 1
                card_type = "Generic"
            else:
                return {"success": False, "message": f"{player.name} has no Get Out of Jail Free cards"}
        
        # Release from jail
        player.leave_jail()
        self.log_event(f"{player.name} used {card_type} Get Out of Jail Free card and is released", "jail_event")
        
        # 🎲 IMPORTANT: After using GOOJ card, player must immediately roll dice and move
        # This is a core Monopoly rule - no optional actions after getting out of jail
        self.log_event(f"{player.name} must now roll dice and move immediately after using GOOJ card", "jail_event")
        
        # Roll dice for the player
        dice1, dice2 = self.gc.roll_dice()
        
        # Move player based on dice roll - now properly await the async call
        await self.gc._move_player(player, dice1 + dice2)
        
        # 🎯 CRITICAL FIX: After movement, resolve the action segment
        # This ensures the game state is properly updated and prevents agents from thinking they need to roll dice again
        self.gc._resolve_current_action_segment()
        
        return {
            "success": True,
            "message": f"{player.name} used GOOJ card, rolled ({dice1}, {dice2}), and moved!",
            "card_type": card_type,
            "released": True,
            "dice": [dice1, dice2],
            "moved": True
        }
    
    def _can_use_gooj_card_internal(self, player: Player) -> bool:
        """
        Check if player can use a Get Out of Jail Free card.
        
        Args:
            player: The player to check
            
        Returns:
            bool: True if player has a GOOJ card to use
        """
        if player.has_chance_gooj_card:
            return True
        if player.has_community_gooj_card:
            return True
        if player.get_out_of_jail_free_cards > 0:
            return True
        return False 