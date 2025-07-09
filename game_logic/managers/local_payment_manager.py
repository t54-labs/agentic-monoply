"""
Local Payment Manager for Test Environment

This module provides a local payment manager that operates without external TPay services.
Used in test environments to avoid network dependencies while maintaining the same interface.
"""

import os
from typing import Dict, Any, Optional
from .base_manager import BaseManager
from ..player import Player


class LocalPaymentManager(BaseManager):
    """
    Local payment manager for test environments.
    
    Handles payments by directly modifying player balances without external service calls.
    Maintains the same interface as the regular PaymentManager for compatibility.
    """
    
    def get_manager_name(self) -> str:
        return "LocalPaymentManager"
    
    def initialize(self) -> None:
        """Initialize local payment tracking"""
        if not hasattr(self.gc, '_local_payment_history'):
            self.gc._local_payment_history = []
        if not hasattr(self.gc, '_local_payment_id_counter'):
            self.gc._local_payment_id_counter = 1
    
    def _generate_payment_id(self) -> str:
        """Generate a mock payment ID for tracking"""
        payment_id = f"local_payment_{self.gc._local_payment_id_counter}"
        self.gc._local_payment_id_counter += 1
        return payment_id
    
    def _record_payment(self, payment_type: str, payer: Player, recipient: Optional[Player], 
                       amount: float, reason: str, payment_id: str, success: bool) -> None:
        """Record payment for debugging and verification"""
        payment_record = {
            "payment_id": payment_id,
            "type": payment_type,
            "payer_id": payer.player_id,
            "payer_name": payer.name,
            "recipient_id": recipient.player_id if recipient else None,
            "recipient_name": recipient.name if recipient else "System",
            "amount": amount,
            "reason": reason,
            "success": success,
            "timestamp": self.gc.turn_count
        }
        self.gc._local_payment_history.append(payment_record)
        
        if success:
            self.log_event(f"[LOCAL PAY] {payment_type}: {payer.name} → {recipient.name if recipient else 'System'} ${amount:.0f} ({reason})", "payment_event")
        else:
            self.log_event(f"[LOCAL PAY FAILED] {payment_type}: {payer.name} → {recipient.name if recipient else 'System'} ${amount:.0f} ({reason})", "error_payment")
    
    async def create_tpay_payment_player_to_player(self, payer: Player, recipient: Player, 
                                                  amount: float, reason: str, 
                                                  agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Local implementation of player-to-player payment.
        Directly modifies player balances instead of using TPay.
        """
        payment_id = self._generate_payment_id()
        
        try:
            # Check if payer has sufficient funds
            if payer.money < amount:
                self.log_event(f"[LOCAL PAY] Insufficient funds: {payer.name} has ${payer.money:.0f}, needs ${amount:.0f}", "error_payment")
                self._record_payment("player_to_player", payer, recipient, amount, reason, payment_id, False)
                return False
            
            # Execute payment by modifying balances directly
            payer.money -= amount
            recipient.money += amount
            
            # Update cached balances to reflect the change
            payer._cached_money = payer.money
            recipient._cached_money = recipient.money
            
            self._record_payment("player_to_player", payer, recipient, amount, reason, payment_id, True)
            return True
            
        except Exception as e:
            self.log_event(f"[LOCAL PAY ERROR] Player-to-player payment failed: {e}", "error_payment")
            self._record_payment("player_to_player", payer, recipient, amount, reason, payment_id, False)
            return False
    
    async def create_tpay_payment_player_to_system(self, payer: Player, amount: float, reason: str,
                                                  agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Local implementation of player-to-system payment.
        Removes money from player without external service.
        """
        payment_id = self._generate_payment_id()
        
        try:
            # Check if payer has sufficient funds
            if payer.money < amount:
                self.log_event(f"[LOCAL PAY] Insufficient funds: {payer.name} has ${payer.money:.0f}, needs ${amount:.0f}", "error_payment")
                self._record_payment("player_to_system", payer, None, amount, reason, payment_id, False)
                return False
            
            # Execute payment by reducing player balance
            payer.money -= amount
            
            # Update cached balance
            payer._cached_money = payer.money
            
            self._record_payment("player_to_system", payer, None, amount, reason, payment_id, True)
            return True
            
        except Exception as e:
            self.log_event(f"[LOCAL PAY ERROR] Player-to-system payment failed: {e}", "error_payment")
            self._record_payment("player_to_system", payer, None, amount, reason, payment_id, False)
            return False
    
    async def create_tpay_payment_system_to_player(self, recipient: Player, amount: float, reason: str,
                                                  agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Local implementation of system-to-player payment.
        Adds money to player without external service.
        """
        payment_id = self._generate_payment_id()
        
        try:
            # Execute payment by increasing player balance
            recipient.money += amount
            
            # Update cached balance
            recipient._cached_money = recipient.money
            
            self._record_payment("system_to_player", None, recipient, amount, reason, payment_id, True)
            return True
            
        except Exception as e:
            self.log_event(f"[LOCAL PAY ERROR] System-to-player payment failed: {e}", "error_payment")
            self._record_payment("system_to_player", None, recipient, amount, reason, payment_id, False)
            return False
    
    async def _wait_for_payment_completion(self, payment_id: str, timeout_seconds: int = 30) -> bool:
        """
        Local implementation - payments are immediate, so always return True.
        """
        return True
    
    def get_payment_history(self) -> list:
        """Get the local payment history for debugging/verification"""
        return getattr(self.gc, '_local_payment_history', [])
    
    def clear_payment_history(self) -> None:
        """Clear payment history (useful for tests)"""
        self.gc._local_payment_history = []
        self.gc._local_payment_id_counter = 1