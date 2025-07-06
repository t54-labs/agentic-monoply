from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from .base_manager import BaseManager
from ..player import Player


@dataclass
class TradeOfferItem:
    item_type: str  # "property", "money", "get_out_of_jail_card"
    item_id: Optional[int] = None  # property_id if item_type is property
    quantity: int = 0  # money amount, or 1 for property/card


@dataclass  
class TradeOffer:
    trade_id: int  # Unique ID for the trade offer
    proposer_id: int
    recipient_id: int
    items_offered_by_proposer: List[TradeOfferItem] = field(default_factory=list)
    items_requested_from_recipient: List[TradeOfferItem] = field(default_factory=list)
    status: str = "pending_response"  # pending_response, accepted, rejected, countered, withdrawn
    counter_offer_to_trade_id: Optional[int] = None  # If this is a counter to a previous offer
    turn_proposed: int = 0  # Game turn number when proposed
    message: Optional[str] = None  # Message from proposer
    rejection_count: int = 0  # Tracks rejections for this specific offer iteration


class TradeManager(BaseManager):
    """
    Handles all trade-related operations including trade proposals,
    responses, counter-offers, and trade execution.
    """
    
    def get_manager_name(self) -> str:
        return "TradeManager"
        
    def initialize(self) -> None:
        """Initialize trade-related data structures"""
        if not hasattr(self.gc, 'trade_offers'):
            self.gc.trade_offers = {}
        if not hasattr(self.gc, 'next_trade_id'):
            self.gc.next_trade_id = 1
    
    def propose_trade_action(self, proposer_id: int, recipient_id: int, 
                           offered_property_ids: List[int], offered_money: int, offered_gooj_cards: int,
                           requested_property_ids: List[int], requested_money: int, requested_gooj_cards: int,
                           message: Optional[str] = None,
                           counter_to_trade_id: Optional[int] = None) -> Optional[int]:
        """
        Propose a trade between two players.
        
        Args:
            proposer_id: ID of the player proposing the trade
            recipient_id: ID of the player receiving the trade proposal
            offered_property_ids: List of property IDs offered by proposer
            offered_money: Amount of money offered by proposer
            offered_gooj_cards: Number of Get Out of Jail cards offered by proposer
            requested_property_ids: List of property IDs requested from recipient
            requested_money: Amount of money requested from recipient
            requested_gooj_cards: Number of Get Out of Jail cards requested from recipient
            message: Optional message from proposer
            counter_to_trade_id: Optional ID of trade this is countering
            
        Returns:
            Optional[int]: Trade ID if successful, None if failed
        """
        # 🔍 DEBUG: Log trade proposal details
        self.log_event(f"[TRADE DEBUG] Proposing trade: P{proposer_id} -> P{recipient_id}", "error_trade")
        self.log_event(f"  Offered properties: {offered_property_ids}, money: ${offered_money}, GOOJ: {offered_gooj_cards}", "error_trade")
        self.log_event(f"  Requested properties: {requested_property_ids}, money: ${requested_money}, GOOJ: {requested_gooj_cards}", "error_trade")
        
        # 🚨 Check if this is a new trade proposal after rejection - enforce same recipient rule
        if (self.gc.pending_decision_type == "propose_new_trade_after_rejection" and 
            hasattr(self.gc, 'pending_decision_context') and 
            self.gc.pending_decision_context.get("player_id") == proposer_id):
            
            # Get the original trade information
            rejected_trade_id = self.gc.pending_decision_context.get("rejected_trade_id")
            if rejected_trade_id and rejected_trade_id in self.gc.trade_offers:
                original_offer = self.gc.trade_offers[rejected_trade_id]
                original_recipient_id = original_offer.recipient_id
                
                # Enforce same recipient rule
                if recipient_id != original_recipient_id:
                    original_recipient_name = self.players[original_recipient_id].name
                    attempted_recipient_name = self.players[recipient_id].name
                    self.log_event(f"[TRADE RULE VIOLATION] {self.players[proposer_id].name} cannot propose trade to {attempted_recipient_name} after rejection. Must continue negotiation with {original_recipient_name}.", "error_trade")
                    return None
                    
                # Check rejection count limit
                rejection_count = self.gc.pending_decision_context.get("rejection_count", 0)
                if rejection_count >= self.gc.MAX_TRADE_REJECTIONS:
                    self.log_event(f"[TRADE RULE VIOLATION] {self.players[proposer_id].name} has reached maximum trade rejections ({self.gc.MAX_TRADE_REJECTIONS}) with {self.players[recipient_id].name}.", "error_trade")
                    return None
        
        # Validate players
        if not (0 <= proposer_id < len(self.players)) or not (0 <= recipient_id < len(self.players)):
            self.log_event(f"[TRADE DEBUG] Invalid player IDs: proposer={proposer_id}, recipient={recipient_id}", "error_trade")
            return None
            
        if proposer_id == recipient_id:
            self.log_event("[TRADE DEBUG] Cannot trade with yourself", "error_trade")
            return None
            
        proposer = self.players[proposer_id]
        recipient = self.players[recipient_id]
        
        # 🔍 DEBUG: Log player info
        self.log_event(f"[TRADE DEBUG] Proposer {proposer.name} (P{proposer_id}): money=${proposer.money}, properties={list(proposer.properties_owned_ids)}", "error_trade")
        self.log_event(f"[TRADE DEBUG] Recipient {recipient.name} (P{recipient_id}): money=${recipient.money}, properties={list(recipient.properties_owned_ids)}", "error_trade")
        
        if proposer.is_bankrupt or recipient.is_bankrupt:
            self.log_event(f"[TRADE DEBUG] Bankrupt players: proposer={proposer.is_bankrupt}, recipient={recipient.is_bankrupt}", "error_trade")
            return None
        
        # Build trade offer items
        offered_items = []
        requested_items = []
        
        # Add offered properties
        for prop_id in offered_property_ids:
            if prop_id not in proposer.properties_owned_ids:
                property_name = self.board.get_square(prop_id).name if hasattr(self.board, 'get_square') else f"Property {prop_id}"
                self.log_event(f"[TRADE DEBUG] {proposer.name} doesn't own property {prop_id} ({property_name})", "error_trade")
                self.log_event(f"[TRADE DEBUG] {proposer.name} owns: {list(proposer.properties_owned_ids)}", "error_trade")
                return None
            offered_items.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        
        # Add offered money
        if offered_money > 0:
            if proposer.money < offered_money:
                self.log_event(f"[TRADE DEBUG] {proposer.name} doesn't have ${offered_money} (has ${proposer.money})", "error_trade")
                return None
            offered_items.append(TradeOfferItem(item_type="money", quantity=offered_money))
        
        # Add offered GOOJ cards
        if offered_gooj_cards > 0:
            if proposer.get_out_of_jail_free_cards < offered_gooj_cards:
                self.log_event(f"[TRADE DEBUG] {proposer.name} doesn't have {offered_gooj_cards} GOOJ cards (has {proposer.get_out_of_jail_free_cards})", "error_trade")
                return None
            offered_items.append(TradeOfferItem(item_type="get_out_of_jail_card", quantity=offered_gooj_cards))
        
        # Add requested properties
        for prop_id in requested_property_ids:
            if prop_id not in recipient.properties_owned_ids:
                property_name = self.board.get_square(prop_id).name if hasattr(self.board, 'get_square') else f"Property {prop_id}"
                self.log_event(f"[TRADE DEBUG] {recipient.name} doesn't own property {prop_id} ({property_name})", "error_trade")
                self.log_event(f"[TRADE DEBUG] {recipient.name} owns: {list(recipient.properties_owned_ids)}", "error_trade")
                return None
            requested_items.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        
        # Add requested money
        if requested_money > 0:
            if recipient.money < requested_money:
                self.log_event(f"[TRADE DEBUG] {recipient.name} doesn't have ${requested_money} (has ${recipient.money})", "error_trade")
                return None
            requested_items.append(TradeOfferItem(item_type="money", quantity=requested_money))
        
        # Add requested GOOJ cards
        if requested_gooj_cards > 0:
            if recipient.get_out_of_jail_free_cards < requested_gooj_cards:
                self.log_event(f"[TRADE DEBUG] {recipient.name} doesn't have {requested_gooj_cards} GOOJ cards (has {recipient.get_out_of_jail_free_cards})", "error_trade")
                return None
            requested_items.append(TradeOfferItem(item_type="get_out_of_jail_card", quantity=requested_gooj_cards))
        
        # Create trade offer
        trade_id = self._generate_trade_id()
        trade_offer = TradeOffer(
            trade_id=trade_id,
            proposer_id=proposer_id,
            recipient_id=recipient_id,
            items_offered_by_proposer=offered_items,
            items_requested_from_recipient=requested_items,
            status="pending_response",
            counter_offer_to_trade_id=counter_to_trade_id,
            turn_proposed=self.turn_count,
            message=message,
            rejection_count=0
        )
        
        self.gc.trade_offers[trade_id] = trade_offer
        
        # Set pending decision for recipient
        self.gc._set_pending_decision(
            "respond_to_trade_offer",
            context={
                "player_id": recipient_id,
                "trade_id": trade_id,
                "proposer_name": proposer.name,
                "recipient_name": recipient.name
            },
            outcome_processed=False
        )
        
        self.log_event(f"[TRADE DEBUG] Trade {trade_id} successfully created: {proposer.name} -> {recipient.name}", "error_trade")
        if message:
            self.log_event(f"Trade {trade_id} message: {message}", "trade_event")
        
        return trade_id
    
    async def respond_to_trade_offer_action(self, player_id: int, trade_id: int, response: str,
                                          counter_offered_prop_ids: Optional[List[int]] = None,
                                          counter_offered_money: Optional[int] = None,
                                          counter_offered_gooj_cards: Optional[int] = None,
                                          counter_requested_prop_ids: Optional[List[int]] = None,
                                          counter_requested_money: Optional[int] = None,
                                          counter_requested_gooj_cards: Optional[int] = None,
                                          counter_message: Optional[str] = None) -> bool:
        """
        Respond to a trade offer.
        
        Args:
            player_id: ID of the player responding
            trade_id: ID of the trade being responded to
            response: "accept", "reject", or "counter"
            counter_*: Counter-offer parameters (if response is "counter")
            
        Returns:
            bool: True if response was processed successfully, False otherwise
        """
        if trade_id not in self.gc.trade_offers:
            self.log_event(f"Trade {trade_id} not found", "error_trade")
            return False
            
        offer = self.gc.trade_offers[trade_id]
        
        if offer.recipient_id != player_id:
            self.log_event(f"Player {player_id} cannot respond to trade {trade_id}", "error_trade")
            return False
            
        if offer.status != "pending_response":
            self.log_event(f"Trade {trade_id} is not pending response (status: {offer.status})", "error_trade")
            return False
        
        player = self.players[player_id]
        proposer = self.players[offer.proposer_id]
        
        if response == "accept":
            # Execute the trade
            success = await self._execute_trade(offer)
            if success:
                offer.status = "accepted"
                self.log_event(f"Trade {trade_id} accepted and executed by {player.name}", "trade_event")
                self.gc._resolve_current_action_segment()
            else:
                self.log_event(f"Trade {trade_id} acceptance failed during execution", "error_trade")
            return success
            
        elif response == "reject":
            offer.status = "rejected"
            offer.rejection_count += 1
            
            self.log_event(f"Trade {trade_id} rejected by {player.name}", "trade_event")
            
            # Check if max rejections reached
            if offer.rejection_count >= self.gc.MAX_TRADE_REJECTIONS:
                self.log_event(f"Trade {trade_id} reached maximum rejections ({self.gc.MAX_TRADE_REJECTIONS})", "trade_event")
                self.gc._resolve_current_action_segment()
            else:
                # Allow proposer to make a new offer or end negotiation
                self.gc._set_pending_decision(
                    "propose_new_trade_after_rejection",
                    context={
                        "player_id": offer.proposer_id,
                        "rejected_trade_id": trade_id,
                        "rejection_count": offer.rejection_count
                    },
                    outcome_processed=False
                )
            return True
            
        elif response == "counter":
            # Create counter-offer
            counter_trade_id = self.propose_trade_action(
                proposer_id=player_id,
                recipient_id=offer.proposer_id,
                offered_property_ids=counter_offered_prop_ids or [],
                offered_money=counter_offered_money or 0,
                offered_gooj_cards=counter_offered_gooj_cards or 0,
                requested_property_ids=counter_requested_prop_ids or [],
                requested_money=counter_requested_money or 0,
                requested_gooj_cards=counter_requested_gooj_cards or 0,
                message=counter_message,
                counter_to_trade_id=trade_id
            )
            
            if counter_trade_id:
                offer.status = "countered"
                self.log_event(f"Trade {trade_id} countered by {player.name} with trade {counter_trade_id}", "trade_event")
                return True
            else:
                self.log_event(f"Failed to create counter-offer for trade {trade_id}", "error_trade")
                return False
        
        else:
            self.log_event(f"Invalid response '{response}' to trade {trade_id}", "error_trade")
            return False
    
    async def _execute_trade(self, offer: TradeOffer) -> bool:
        """
        Execute a trade offer by transferring all items between players.
        
        Args:
            offer: The trade offer to execute
            
        Returns:
            bool: True if trade executed successfully, False otherwise
        """
        proposer = self.players[offer.proposer_id]
        recipient = self.players[offer.recipient_id]
        
        try:
            # Track mortgaged properties for notifications
            mortgaged_props_received_by_recipient = []
            mortgaged_props_received_by_proposer = []
            
            # Execute TPay payments for trade money transfers
            trade_payment_successful = True
            trade_payments_completed = []
            trade_payments_failed = []
            
            # Process money transfers from proposer to recipient
            for item in offer.items_offered_by_proposer:
                if item.item_type == "money":
                    payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_player(
                        payer=proposer,
                        recipient=recipient,
                        amount=float(item.quantity),
                        reason=f"trade {offer.trade_id} - payment from proposer",
                        agent_decision_context={
                            "trade_id": offer.trade_id,
                            "trade_context": "proposer_to_recipient_payment",
                            "original_proposer": proposer.name,
                            "original_recipient": recipient.name
                        }
                    )
                    
                    if payment_success:
                        trade_payments_completed.append(f"${item.quantity} from {proposer.name} to {recipient.name}")
                    else:
                        trade_payments_failed.append(f"${item.quantity} from {proposer.name} to {recipient.name}")
                        trade_payment_successful = False
            
            # Process money transfers from recipient to proposer
            for item in offer.items_requested_from_recipient:
                if item.item_type == "money":
                    payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_player(
                        payer=recipient,
                        recipient=proposer,
                        amount=float(item.quantity),
                        reason=f"trade {offer.trade_id} - payment from recipient",
                        agent_decision_context={
                            "trade_id": offer.trade_id,
                            "trade_context": "recipient_to_proposer_payment",
                            "original_proposer": proposer.name,
                            "original_recipient": recipient.name
                        }
                    )
                    
                    if payment_success:
                        trade_payments_completed.append(f"${item.quantity} from {recipient.name} to {proposer.name}")
                    else:
                        trade_payments_failed.append(f"${item.quantity} from {recipient.name} to {proposer.name}")
                        trade_payment_successful = False
            
            if not trade_payment_successful:
                self.log_event(f"Trade {offer.trade_id} failed due to payment failures: {trade_payments_failed}", "error_trade")
                return False
            
            # Log successful payments
            if trade_payments_completed:
                self.log_event(f"Trade {offer.trade_id} payments completed: {trade_payments_completed}", "trade_event")
            
            # Transfer properties from proposer to recipient
            for item in offer.items_offered_by_proposer:
                if item.item_type == "property" and item.item_id is not None:
                    property_square = self.board.get_square(item.item_id)
                    
                    # Check if property is mortgaged
                    if hasattr(property_square, 'is_mortgaged') and property_square.is_mortgaged:
                        mortgaged_props_received_by_recipient.append({
                            "property_id": item.item_id,
                            "property_name": property_square.name,
                            "mortgage_value": property_square.price // 2
                        })
                    
                    # Transfer ownership
                    property_square.owner_id = offer.recipient_id
                    proposer.remove_property_id(item.item_id)
                    recipient.add_property_id(item.item_id)
                    
                    self.log_event(f"Trade {offer.trade_id}: {property_square.name} transferred to {recipient.name}", "trade_event")
            
            # Transfer properties from recipient to proposer
            for item in offer.items_requested_from_recipient:
                if item.item_type == "property" and item.item_id is not None:
                    property_square = self.board.get_square(item.item_id)
                    
                    # Check if property is mortgaged
                    if hasattr(property_square, 'is_mortgaged') and property_square.is_mortgaged:
                        mortgaged_props_received_by_proposer.append({
                            "property_id": item.item_id,
                            "property_name": property_square.name,
                            "mortgage_value": property_square.price // 2
                        })
                    
                    # Transfer ownership
                    property_square.owner_id = offer.proposer_id
                    recipient.remove_property_id(item.item_id)
                    proposer.add_property_id(item.item_id)
                    
                    self.log_event(f"Trade {offer.trade_id}: {property_square.name} transferred to {proposer.name}", "trade_event")
            
            # Transfer Get Out of Jail Free cards
            for item in offer.items_offered_by_proposer:
                if item.item_type == "get_out_of_jail_card":
                    self._transfer_gooj_card(proposer, recipient, item.item_id)
                    self.log_event(f"Trade {offer.trade_id}: {item.quantity} GOOJ card(s) transferred to {recipient.name}", "trade_event")
            
            for item in offer.items_requested_from_recipient:
                if item.item_type == "get_out_of_jail_card":
                    self._transfer_gooj_card(recipient, proposer, item.item_id)
                    self.log_event(f"Trade {offer.trade_id}: {item.quantity} GOOJ card(s) transferred to {proposer.name}", "trade_event")
            
            # Handle mortgaged property notifications
            if mortgaged_props_received_by_recipient:
                recipient.pending_mortgaged_properties_to_handle.extend(mortgaged_props_received_by_recipient)
                self.log_event(f"{recipient.name} received {len(mortgaged_props_received_by_recipient)} mortgaged properties", "trade_event")
            
            if mortgaged_props_received_by_proposer:
                proposer.pending_mortgaged_properties_to_handle.extend(mortgaged_props_received_by_proposer)
                self.log_event(f"{proposer.name} received {len(mortgaged_props_received_by_proposer)} mortgaged properties", "trade_event")
            
            self.log_event(f"Trade {offer.trade_id} executed successfully", "trade_event")
            return True
            
        except Exception as e:
            self.log_event(f"Trade {offer.trade_id} execution failed: {str(e)}", "error_trade")
            return False
    
    def end_trade_negotiation_action(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        End trade negotiation for a player.
        
        Args:
            player_id: ID of the player ending negotiation
            params: Additional parameters
            
        Returns:
            Dict[str, Any]: Result of the action
        """
        player = self.players[player_id]
        
        self.log_event(f"{player.name} ended trade negotiation", "trade_event")
        self.gc._resolve_current_action_segment()
        
        return {
            "success": True,
            "message": f"{player.name} ended trade negotiation",
            "game_continues": True
        }
    
    def _generate_trade_id(self) -> int:
        """Generate a unique trade ID"""
        trade_id = self.gc.next_trade_id
        self.gc.next_trade_id += 1
        return trade_id
    
    def _validate_trade_items(self, player_id: int, items: List[TradeOfferItem]) -> bool:
        """
        Validate that a player owns the items they're trying to trade.
        
        Args:
            player_id: ID of the player
            items: List of items to validate
            
        Returns:
            bool: True if all items are valid, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            return False
            
        player = self.players[player_id]
        
        for item in items:
            if item.item_type == "property":
                if item.item_id is None or item.item_id not in player.properties_owned_ids:
                    return False
            elif item.item_type == "money":
                if player.money < item.quantity:
                    return False
            elif item.item_type == "get_out_of_jail_card":
                if player.get_out_of_jail_free_cards < item.quantity:
                    return False
        
        return True
    
    def _transfer_gooj_card(self, giver: Player, receiver: Player, card_item_id_hint: Optional[int]):
        """
        Transfer a Get Out of Jail Free card between players.
        
        Args:
            giver: Player giving the card
            receiver: Player receiving the card
            card_item_id_hint: Optional hint for card identification
        """
        if giver.get_out_of_jail_free_cards > 0:
            giver.get_out_of_jail_free_cards -= 1
            receiver.get_out_of_jail_free_cards += 1
            self.log_event(f"GOOJ card transferred from {giver.name} to {receiver.name}", "trade_event")
        else:
            self.log_event(f"Warning: {giver.name} has no GOOJ cards to transfer", "error_trade") 