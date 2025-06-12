import asyncio
import datetime
from typing import Dict, Any, Optional, List
import tpay
import utils
from .base_manager import BaseManager
from ..player import Player


class PaymentManager(BaseManager):
    """
    Handles all payment operations including TPay integration,
    player-to-player payments, system payments, and payment validation.
    """
    
    def get_manager_name(self) -> str:
        return "PaymentManager"
        
    def initialize(self) -> None:
        """Initialize TPay agent if not already done"""
        if not hasattr(self.gc, 'tpay_agent') or self.gc.tpay_agent is None:
            self.gc.tpay_agent = tpay.agent.AsyncTPayAgent()
            self.log_event("TPay agent initialized by PaymentManager", "debug_payment")
    
    async def create_tpay_payment_player_to_player(self, payer: Player, recipient: Player, amount: float, reason: str, 
                                                  agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Create a TPay payment from one player to another.
        
        Args:
            payer: The player making the payment
            recipient: The player receiving the payment
            amount: The payment amount
            reason: The reason for the payment
            agent_decision_context: Additional context for the payment
            
        Returns:
            bool: True if payment was successful, False otherwise
        """
        self.log_event(f"Initiating TPay payment: {payer.name} -> {recipient.name} ${amount} ({reason})", "debug_payment")
        
        # Build comprehensive payment context matching original GameController format exactly
        trace_context = {
            "payment_type": "player_to_player",
            "game_context": {
                "game_uid": self.gc.game_uid,
                "turn_count": self.turn_count,
                "current_player": payer.player_id,
                "game_phase": self.gc.pending_decision_type or "normal_play",
                "dice_roll": list(self.gc.dice) if self.gc.dice != (0, 0) else None,
                "dice_roll_outcome_processed": self.gc.dice_roll_outcome_processed,
                "game_over": self.gc.game_over,
                "max_turns": getattr(self.gc, 'max_turns', None)
            },
            "board_state": {
                "total_squares": len(self.board.squares),
                "payer_square": {
                    "position": payer.position,
                    "name": self.board.get_square(payer.position).name if 0 <= payer.position < len(self.board.squares) else "Unknown",
                    "type": self.board.get_square(payer.position).square_type.value if 0 <= payer.position < len(self.board.squares) else "Unknown"
                },
                "recipient_square": {
                    "position": recipient.position,
                    "name": self.board.get_square(recipient.position).name if 0 <= recipient.position < len(self.board.squares) else "Unknown",
                    "type": self.board.get_square(recipient.position).square_type.value if 0 <= recipient.position < len(self.board.squares) else "Unknown"
                }
            },
            "players": {
                "payer": {
                    "id": payer.player_id,
                    "name": payer.name,
                    "position": payer.position,
                    "balance_before": float(payer.money),
                    "properties_owned": list(payer.properties_owned_ids),
                    "properties_count": len(payer.properties_owned_ids),
                    "is_in_jail": payer.in_jail,
                    "jail_turns_remaining": getattr(payer, 'jail_turns_remaining', 0),
                    "is_bankrupt": payer.is_bankrupt,
                    "has_gooj_cards": {
                        "chance": getattr(payer, 'has_chance_gooj_card', False),
                        "community_chest": getattr(payer, 'has_community_gooj_card', False)
                    }
                },
                "recipient": {
                    "id": recipient.player_id, 
                    "name": recipient.name,
                    "position": recipient.position,
                    "balance_before": float(recipient.money),
                    "properties_owned": list(recipient.properties_owned_ids),
                    "properties_count": len(recipient.properties_owned_ids),
                    "is_in_jail": recipient.in_jail,
                    "jail_turns_remaining": getattr(recipient, 'jail_turns_remaining', 0),
                    "is_bankrupt": recipient.is_bankrupt,
                    "has_gooj_cards": {
                        "chance": getattr(recipient, 'has_chance_gooj_card', False),
                        "community_chest": getattr(recipient, 'has_community_gooj_card', False)
                    }
                }
            },
            "all_players_summary": [
                {
                    "id": p.player_id,
                    "name": p.name,
                    "position": p.position,
                    "balance": float(p.money),
                    "properties_count": len(p.properties_owned_ids),
                    "is_bankrupt": p.is_bankrupt,
                    "is_in_jail": p.in_jail
                } for p in self.players
            ],
            "transaction": {
                "reason": reason,
                "amount": float(amount),
                "timestamp": datetime.datetime.now().isoformat()
            },
            "game_history": {
                "recent_events": self.gc.game_log[-10:] if hasattr(self.gc, 'game_log') and self.gc.game_log else [],
                "current_turn_events": [event for event in (self.gc.game_log[-20:] if hasattr(self.gc, 'game_log') and self.gc.game_log else []) if f"Turn {self.turn_count}" in event or f"T:{self.turn_count}" in event]
            }
        }
        
        # Add agent decision context if provided
        if agent_decision_context:
            trace_context["agent_decision"] = agent_decision_context
            
        # Check if payer has sufficient funds
        if payer.money < amount:
            self.log_event(f"{payer.name} has insufficient funds for ${amount} payment to {recipient.name}", "error_payment")
            return False
            
        try:
            # Get function stack hashes
            func_stack_hashes = tpay.tools.get_current_stack_function_hashes()
            
            # Create TPay payment using correct original parameters
            payment_result = await self.gc.tpay_agent.create_payment(
                agent_id=payer.agent_tpay_id,
                receiving_agent_id=recipient.agent_tpay_id,
                amount=int(amount * 10 ** 6),
                currency=utils.GAME_TOKEN_SYMBOL,
                settlement_network="solana",
                func_stack_hashes=func_stack_hashes,
                debug_mode=True,
                trace_context=trace_context
            )
            
            if payment_result:
                # Wait for payment completion
                payment_success = await self._wait_for_payment_completion(payment_result)
                
                if payment_success:
                    # Update player balances
                    
                    self.log_event(f"TPay payment successful: {payer.name} paid ${amount} to {recipient.name}", "success_payment")
                    return True
                else:
                    self.log_event(f"TPay payment failed: {payer.name} -> {recipient.name} ${amount}", "error_payment")
                    return False
            else:
                self.log_event(f"TPay payment creation failed: {payer.name} -> {recipient.name} ${amount}", "error_payment")
                return False
                
        except Exception as e:
            self.log_event(f"TPay payment exception: {payer.name} -> {recipient.name} ${amount} - {str(e)}", "error_payment")
            return False
    
    async def create_tpay_payment_player_to_system(self, payer: Player, amount: float, reason: str, 
                                                  event_description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a TPay payment from a player to the system/treasury.
        
        Args:
            payer: The player making the payment
            amount: The payment amount
            reason: The reason for the payment
            event_description: Optional description of the event
            
        Returns:
            Optional[Dict[str, Any]]: Payment result or None if failed
        """
        self.log_event(f"Initiating system payment: {payer.name} -> Treasury ${amount} ({reason})", "debug_payment")
        
        # Build payment context matching original GameController format exactly
        trace_context = {
            "payment_type": "player_to_system",
            "game_context": {
                "game_uid": self.gc.game_uid,
                "turn_count": self.turn_count,
                "current_player": payer.player_id,
                "game_phase": self.gc.pending_decision_type or "normal_play",
                "dice_roll": list(self.gc.dice) if self.gc.dice != (0, 0) else None,
                "dice_roll_outcome_processed": self.gc.dice_roll_outcome_processed,
                "game_over": self.gc.game_over,
                "max_turns": getattr(self.gc, 'max_turns', None)
            },
            "board_state": {
                "total_squares": len(self.board.squares),
                "current_square": {
                    "position": payer.position,
                    "name": self.board.get_square(payer.position).name if 0 <= payer.position < len(self.board.squares) else "Unknown",
                    "type": self.board.get_square(payer.position).square_type.value if 0 <= payer.position < len(self.board.squares) else "Unknown"
                }
            },
            "player": {
                "id": payer.player_id,
                "name": payer.name,
                "position": payer.position,
                "balance_before": float(payer.money),
                "properties_owned": list(payer.properties_owned_ids),
                "properties_count": len(payer.properties_owned_ids),
                "is_in_jail": payer.in_jail,
                "jail_turns_remaining": getattr(payer, 'jail_turns_remaining', 0),
                "is_bankrupt": payer.is_bankrupt,
                "has_gooj_cards": {
                    "chance": getattr(payer, 'has_chance_gooj_card', False),
                    "community_chest": getattr(payer, 'has_community_gooj_card', False)
                }
            },
            "all_players_summary": [
                {
                    "id": p.player_id,
                    "name": p.name,
                    "position": p.position,
                    "balance": float(p.money),
                    "properties_count": len(p.properties_owned_ids),
                    "is_bankrupt": p.is_bankrupt,
                    "is_in_jail": p.in_jail
                } for p in self.players
            ],
            "transaction": {
                "reason": reason,
                "amount": float(amount),
                "timestamp": datetime.datetime.now().isoformat()
            },
            "event": {
                "description": event_description or reason,
                "square_name": self.board.get_square(payer.position).name if 0 <= payer.position < len(self.board.squares) else "Unknown",
                "why_player_here": self._get_position_explanation(payer)
            },
            "game_history": {
                "recent_events": self.gc.game_log[-10:] if hasattr(self.gc, 'game_log') and self.gc.game_log else [],
                "current_turn_events": [event for event in (self.gc.game_log[-20:] if hasattr(self.gc, 'game_log') and self.gc.game_log else []) if f"Turn {self.turn_count}" in event or f"T:{self.turn_count}" in event],
                "movement_context": self._get_movement_context(payer)
            }
        }
        
        # Check if payer has sufficient funds
        if payer.money < amount:
            self.log_event(f"{payer.name} has insufficient funds for ${amount} system payment", "error_payment")
            return None
            
        try:
            # Get function stack hashes
            func_stack_hashes = tpay.tools.get_current_stack_function_hashes()
            
            # Create TPay payment to treasury using correct original parameters
            payment_result = await self.gc.tpay_agent.create_payment(
                agent_id=payer.agent_tpay_id,
                receiving_agent_id=self.gc.treasury_agent_id,
                amount=int(amount * 10 ** 6),
                currency=utils.GAME_TOKEN_SYMBOL,
                settlement_network="solana",
                func_stack_hashes=func_stack_hashes,
                debug_mode=True,
                trace_context=trace_context
            )
            
            if payment_result:
                self.log_event(f"System payment initiated: {payer.name} -> Treasury ${amount}", "debug_payment")
                
                # Wait for payment completion
                payment_success = await self._wait_for_payment_completion(payment_result)
                
                if payment_success:
                    # Update player balance from TPay
                    self.log_event(f"System payment completed: {payer.name} -> Treasury ${amount}", "success_payment")
                    return payment_result
                else:
                    self.log_event(f"System payment failed to complete: {payer.name} -> Treasury ${amount}", "error_payment")
                    return None
            else:
                self.log_event(f"System payment creation failed: {payer.name} -> Treasury ${amount}", "error_payment")
                return None
                
        except Exception as e:
            self.log_event(f"System payment exception: {payer.name} -> Treasury ${amount} - {str(e)}", "error_payment")
            return None
    
    async def create_tpay_payment_system_to_player(self, recipient: Player, amount: float, reason: str,
                                                  event_description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Create a TPay payment from the system/treasury to a player.
        
        Args:
            recipient: The player receiving the payment
            amount: The payment amount
            reason: The reason for the payment
            event_description: Optional description of the event
            
        Returns:
            Optional[Dict[str, Any]]: Payment result or None if failed
        """
        self.log_event(f"Initiating system payment: Treasury -> {recipient.name} ${amount} ({reason})", "debug_payment")
        
        # Build payment context matching original GameController format exactly
        trace_context = {
            "payment_type": "system_to_player", 
            "game_context": {
                "game_uid": self.gc.game_uid,
                "turn_count": self.turn_count,
                "current_player": recipient.player_id,
                "game_phase": self.gc.pending_decision_type or "normal_play",
                "dice_roll": list(self.gc.dice) if self.gc.dice != (0, 0) else None,
                "dice_roll_outcome_processed": self.gc.dice_roll_outcome_processed,
                "game_over": self.gc.game_over,
                "max_turns": getattr(self.gc, 'max_turns', None)
            },
            "board_state": {
                "total_squares": len(self.board.squares),
                "current_square": {
                    "position": recipient.position,
                    "name": self.board.get_square(recipient.position).name if 0 <= recipient.position < len(self.board.squares) else "Unknown",
                    "type": self.board.get_square(recipient.position).square_type.value if 0 <= recipient.position < len(self.board.squares) else "Unknown"
                }
            },
            "player": {
                "id": recipient.player_id,
                "name": recipient.name,
                "position": recipient.position,
                "balance_before": float(recipient.money),
                "properties_owned": list(recipient.properties_owned_ids),
                "properties_count": len(recipient.properties_owned_ids),
                "is_in_jail": recipient.in_jail,
                "jail_turns_remaining": getattr(recipient, 'jail_turns_remaining', 0),
                "is_bankrupt": recipient.is_bankrupt,
                "has_gooj_cards": {
                    "chance": getattr(recipient, 'has_chance_gooj_card', False),
                    "community_chest": getattr(recipient, 'has_community_gooj_card', False)
                }
            },
            "all_players_summary": [
                {
                    "id": p.player_id,
                    "name": p.name,
                    "position": p.position,
                    "balance": float(p.money),
                    "properties_count": len(p.properties_owned_ids),
                    "is_bankrupt": p.is_bankrupt,
                    "is_in_jail": p.in_jail
                } for p in self.players
            ],
            "transaction": {
                "reason": reason,
                "amount": float(amount),
                "timestamp": datetime.datetime.now().isoformat()
            },
            "event": {
                "description": event_description or reason,
                "square_name": self.board.get_square(recipient.position).name if 0 <= recipient.position < len(self.board.squares) else "Unknown",
                "why_player_here": self._get_position_explanation(recipient)
            },
            "game_history": {
                "recent_events": self.gc.game_log[-10:] if hasattr(self.gc, 'game_log') and self.gc.game_log else [],
                "current_turn_events": [event for event in (self.gc.game_log[-20:] if hasattr(self.gc, 'game_log') and self.gc.game_log else []) if f"Turn {self.turn_count}" in event or f"T:{self.turn_count}" in event],
                "movement_context": self._get_movement_context(recipient)
            }
        }
        
        try:
            # Get function stack hashes
            func_stack_hashes = tpay.tools.get_current_stack_function_hashes()
            
            # Create TPay payment from treasury using correct original parameters
            payment_result = await self.gc.tpay_agent.create_payment(
                agent_id=self.gc.treasury_agent_id,
                receiving_agent_id=recipient.agent_tpay_id,
                amount=int(amount * 10 ** 6),
                currency=utils.GAME_TOKEN_SYMBOL,
                settlement_network="solana",
                func_stack_hashes=func_stack_hashes,
                debug_mode=True,
                trace_context=trace_context
            )
            
            if payment_result:
                self.log_event(f"System payment initiated: Treasury -> {recipient.name} ${amount}", "debug_payment")
                
                # Wait for payment completion
                payment_success = await self._wait_for_payment_completion(payment_result)
                
                if payment_success:
                    # Update player balance from TPay
                    self.log_event(f"System payment completed: Treasury -> {recipient.name} ${amount}", "success_payment")
                    return payment_result
                else:
                    self.log_event(f"System payment failed to complete: Treasury -> {recipient.name} ${amount}", "error_payment")
                    return None
            else:
                self.log_event(f"System payment creation failed: Treasury -> {recipient.name} ${amount}", "error_payment")
                return None
                
        except Exception as e:
            self.log_event(f"System payment exception: Treasury -> {recipient.name} ${amount} - {str(e)}", "error_payment")
            return None
    
    async def _wait_for_payment_completion(self, payment_result: Dict[str, Any], timeout_seconds: int = 30) -> bool:
        """
        Wait for a TPay payment to complete.
        
        Args:
            payment_result: The payment result from create_payment
            timeout_seconds: Maximum time to wait for completion
            
        Returns:
            bool: True if payment completed successfully, False otherwise
        """
        # Use original logic from GameController
        if not payment_result or not payment_result.get('id'):
            self.log_event("No payment ID to wait for", "error_payment")
            return False
            
        payment_id = payment_result['id']
        self.log_event(f"Waiting for payment {payment_id} to complete...", "debug_payment")
        
        import time
        start_time = time.time()
        poll_interval = 5.0  # poll every 5 seconds
        
        while time.time() - start_time < timeout_seconds:
            try:
                # async query payment status
                status_result = await self.gc.tpay_agent.get_payment_status(payment_id)
                
                if status_result and 'status' in status_result:
                    status = status_result['status']
                    self.log_event(f"Payment {payment_id} status: {status}", "debug_payment")
                    
                    if status == 'success':
                        self.log_event(f"Payment {payment_id} completed successfully", "debug_payment")
                        return True
                    elif status == 'failed':
                        self.log_event(f"Payment {payment_id} failed", "error_payment")
                        return False
                    elif status in ['pending', 'processing', 'initiated']:
                        # async wait
                        await asyncio.sleep(poll_interval)
                        continue
                    else:
                        self.log_event(f"Unknown payment status: {status}", "error_payment")
                        return False
                else:
                    self.log_event(f"Failed to get payment status for {payment_id}", "error_payment")
                    await asyncio.sleep(poll_interval)
                    
            except Exception as e:
                self.log_event(f"Error checking payment status: {e}", "error_payment")
                await asyncio.sleep(poll_interval)
        
        self.log_event(f"Payment {payment_id} timed out after {timeout_seconds}s", "error_payment")
        return False
    
    def _get_position_explanation(self, player: Player) -> str:
        """
        Generate explanation for why player is at current position
        
        Args:
            player: Player to explain position for
            
        Returns:
            String explanation of how player got to current position
        """
        try:
            # Look for recent movement events in game log
            recent_events = self.gc.game_log[-15:] if hasattr(self.gc, 'game_log') and self.gc.game_log else []
            
            # Find events related to this player's movement
            movement_reasons = []
            for event in recent_events:
                if player.name in event:
                    if "rolled" in event.lower() and "moved" in event.lower():
                        movement_reasons.append(f"dice_roll: {event}")
                    elif "moved directly" in event.lower():
                        movement_reasons.append(f"card_effect: {event}")
                    elif "sent to jail" in event.lower() or "go to jail" in event.lower():
                        movement_reasons.append(f"jail_movement: {event}")
                    elif "passed GO" in event.lower():
                        movement_reasons.append(f"go_passing: {event}")
            
            # Current game state context
            current_square = self.board.get_square(player.position) if 0 <= player.position < len(self.board.squares) else None
            square_type = current_square.square_type.value if current_square else "unknown"
            
            # Construct explanation
            explanation_parts = []
            
            if player.in_jail:
                explanation_parts.append(f"Player is in jail (turns remaining: {getattr(player, 'jail_turns_remaining', 0)})")
            
            if movement_reasons:
                explanation_parts.append(f"Recent movements: {'; '.join(movement_reasons[-3:])}")
            
            explanation_parts.append(f"Current position {player.position} is {square_type} type")
            
            if hasattr(self.gc, 'dice') and self.gc.dice != (0, 0):
                explanation_parts.append(f"Last dice roll: {self.gc.dice}")
            
            return " | ".join(explanation_parts)
            
        except Exception as e:
            return f"Error generating position explanation: {str(e)}"

    def _get_movement_context(self, player: Player) -> Dict[str, Any]:
        """
        Get detailed movement context for player
        
        Args:
            player: Player to get movement context for
            
        Returns:
            Dictionary with movement context information
        """
        try:
            context = {
                "current_position": player.position,
                "current_square_name": self.board.get_square(player.position).name if 0 <= player.position < len(self.board.squares) else "Unknown",
                "in_jail": player.in_jail,
                "last_dice_roll": list(self.gc.dice) if hasattr(self.gc, 'dice') and self.gc.dice != (0, 0) else None,
                "turn_number": self.turn_count,
                "is_current_turn": (self.current_player_index == player.player_id),
                "movement_events": []
            }
            
            # Extract movement-related events from recent game log
            if hasattr(self.gc, 'game_log') and self.gc.game_log:
                recent_events = self.gc.game_log[-20:]
                for event in recent_events:
                    if player.name in event:
                        # Categorize movement events
                        if any(keyword in event.lower() for keyword in ["moved", "position", "landed", "rolled", "jail", "go to"]):
                            context["movement_events"].append(event)
            
            # Limit to most recent movement events
            context["movement_events"] = context["movement_events"][-5:]
            
            # Add position change analysis if possible
            if len(context["movement_events"]) >= 2:
                context["recent_position_changes"] = len([e for e in context["movement_events"] if "moved" in e.lower() or "position" in e.lower()])
            
            return context
            
        except Exception as e:
            return {
                "error": f"Failed to generate movement context: {str(e)}",
                "current_position": player.position,
                "turn_number": self.turn_count
            }
    
    async def handle_collect_from_players(self, player: Player, amount_each: int) -> bool:
        """Handle card effect where current player collects money from all other players"""
        eligible_players = [p for p in self.players if p != player and not p.is_bankrupt]
        
        if not eligible_players:
            self.log_event(f"{player.name} has no other players to collect from.")
            return True
        
        self.log_event(f"{player.name} needs to collect ${amount_each} from each of {len(eligible_players)} other players (total ${amount_each * len(eligible_players)}).")
        
        # Execute TPay payments from all other players to current player
        successful_payments = []
        failed_payments = []
        
        for other_player in eligible_players:
            if other_player.money >= amount_each:
                # Create TPay payment from other player to current player
                payment_success = await self.create_tpay_payment_player_to_player(
                    payer=other_player,
                    recipient=player,
                    amount=int(amount_each * 10 ** 6),
                    reason=f"card effect payment to {player.name}",
                    agent_decision_context={
                        "card_effect": "collect_from_players",
                        "amount_per_player": amount_each,
                        "total_players_paying": len(eligible_players),
                        "card_context": "mandatory payment due to card drawn"
                    }
                )
                
                if payment_success:
                    successful_payments.append(other_player.name)
                    self.log_event(f"✅ {other_player.name} successfully paid ${amount_each} to {player.name} (card effect).")
                else:
                    failed_payments.append(other_player.name)
                    self.log_event(f"❌ {other_player.name} failed to pay ${amount_each} to {player.name} (card effect).")
                    # Handle bankruptcy for failed payment
                    self.gc._check_and_handle_bankruptcy(other_player, debt_to_creditor=amount_each, creditor=player)
            else:
                failed_payments.append(other_player.name)
                self.log_event(f"💰 {other_player.name} cannot afford ${amount_each} to {player.name} (has ${other_player.money}).")
                # Handle bankruptcy for insufficient funds
                self.gc._check_and_handle_bankruptcy(other_player, debt_to_creditor=amount_each, creditor=player)
        
        # Log summary of collection results
        if successful_payments:
            total_collected = len(successful_payments) * amount_each
            self.log_event(f"💵 {player.name} collected ${total_collected} from {len(successful_payments)} players: {', '.join(successful_payments)}")
        
        if failed_payments:
            total_failed = len(failed_payments) * amount_each
            self.log_event(f"⚠️ {player.name} could not collect ${total_failed} from {len(failed_payments)} players: {', '.join(failed_payments)}")
        
        return len(failed_payments) == 0
        
    async def handle_pay_to_players(self, player: Player, amount_each: int) -> bool:
        """Handle card effect where current player pays money to all other players"""
        eligible_recipients = [p for p in self.players if p != player and not p.is_bankrupt]
        total_amount_needed = amount_each * len(eligible_recipients)
        
        if not eligible_recipients:
            self.log_event(f"{player.name} has no other players to pay.")
            return True
        
        self.log_event(f"{player.name} needs to pay ${amount_each} to each of {len(eligible_recipients)} other players (total ${total_amount_needed}).")
        
        if player.money >= total_amount_needed:
            # Execute TPay payments from current player to all other players
            successful_payments = []
            failed_payments = []
            
            for other_player in eligible_recipients:
                # Create TPay payment from current player to other player
                payment_success = await self.create_tpay_payment_player_to_player(
                    payer=player,
                    recipient=other_player,
                    amount=int(amount_each * 10 ** 6),
                    reason=f"card effect payment to {other_player.name}",
                    agent_decision_context={
                        "card_effect": "pay_players",
                        "amount_per_player": amount_each,
                        "total_players_receiving": len(eligible_recipients),
                        "total_amount_needed": total_amount_needed,
                        "card_context": "mandatory payment due to card drawn"
                    }
                )
                
                if payment_success:
                    successful_payments.append(other_player.name)
                    self.log_event(f"✅ {player.name} successfully paid ${amount_each} to {other_player.name} (card effect).")
                else:
                    failed_payments.append(other_player.name)
                    self.log_event(f"❌ {player.name} failed to pay ${amount_each} to {other_player.name} (card effect).")
            
            # Log summary of payment results
            if successful_payments:
                total_paid = len(successful_payments) * amount_each
                self.log_event(f"💸 {player.name} paid ${total_paid} to {len(successful_payments)} players: {', '.join(successful_payments)}")
            
            if failed_payments:
                total_failed = len(failed_payments) * amount_each
                self.log_event(f"⚠️ {player.name} failed to pay ${total_failed} to {len(failed_payments)} players: {', '.join(failed_payments)}")
                # If any payments failed, handle bankruptcy
                self.gc._check_and_handle_bankruptcy(player, debt_to_creditor=total_failed, creditor=None)
                return False
            else:
                # All payments successful
                self.log_event(f"✅ {player.name} successfully completed all card effect payments.")
                return True
        else:
            self.log_event(f"💰 {player.name} cannot afford to pay ${total_amount_needed} total to other players (has ${player.money}).")
            self.gc._check_and_handle_bankruptcy(player, debt_to_creditor=total_amount_needed, creditor=None)
            return False