from typing import Dict, Any, Optional, List
from .base_manager import BaseManager
from ..player import Player
from ..property import PurchasableSquare


class AuctionManager(BaseManager):
    """
    Handles property auction mechanics including bidding, 
    auction progression, and completion.
    """
    
    def get_manager_name(self) -> str:
        return "AuctionManager"
    
    async def initiate_auction(self, property_id: int) -> None:
        """
        Initiate an auction for a property.
        
        Args:
            property_id: ID of the property to auction
        """
        prop_square = self.board.get_square(property_id)
        if not isinstance(prop_square, PurchasableSquare):
            self.log_event(f"Cannot auction non-purchasable square {property_id}", "error_auction")
            return
            
        if prop_square.owner_id is not None:
            self.log_event(f"Cannot auction owned property {prop_square.name}", "error_auction")
            return
            
        # Set auction state
        self.gc.auction_in_progress = True
        self.gc.auction_property_id = property_id
        self.gc.auction_current_bid = 1  # Start at $1
        self.gc.auction_highest_bidder = None
        
        # Include all non-bankrupt players
        self.gc.auction_participants = [p for p in self.players if not p.is_bankrupt]
        self.gc.auction_active_bidders = self.gc.auction_participants.copy()
        self.gc.auction_player_has_bid_this_round = {p.player_id: False for p in self.gc.auction_participants}
        self.gc.auction_current_bidder_turn_index = 0
        
        self.log_event(f"Auction initiated for {prop_square.name}. {len(self.gc.auction_participants)} players participating.", "auction_event")
        
        # Set pending decision for first bidder
        if self.gc.auction_active_bidders:
            first_bidder = self.gc.auction_active_bidders[0]
            self.gc._set_pending_decision(
                "auction_bid_decision",
                context={
                    "player_id": first_bidder.player_id,
                    "property_id": property_id,
                    "current_bid": self.gc.auction_current_bid,
                    "property_name": prop_square.name
                },
                outcome_processed=False
            )
            
    async def conclude_auction(self, no_winner: bool = False) -> None:
        """
        Conclude the auction and transfer property.
        
        Args:
            no_winner: Whether the auction ended with no winner
        """
        prop_id = self.gc.auction_property_id
        prop_name = self.board.get_square(prop_id).name if prop_id is not None else "Property"
        
        if no_winner or self.gc.auction_highest_bidder is None or (self.gc.auction_current_bid <= 1 and not self.gc.auction_highest_bidder): 
            self.log_event(f"Auction for {prop_name} concluded with no winner or only minimum unaccepted bid. Property remains unowned.", "auction_event")
        else:
            winner = self.gc.auction_highest_bidder
            price_paid = self.gc.auction_current_bid
            property_square = self.board.get_square(prop_id)
            
            self.log_event(f"Auction for {prop_name} won by {winner.name} for ${price_paid}.", "auction_event")
            
            # Use TPay for auction payment to system
            payment_result = await self.gc.payment_manager.create_tpay_payment_player_to_system(
                payer=winner,
                amount=float(price_paid),
                reason=f"auction payment - {prop_name}",
                event_description=f"{winner.name} won auction for {prop_name} at ${price_paid}"
            )
            
            if payment_result:
                payment_success = await self.gc.payment_manager._wait_for_payment_completion(payment_result)
                
                if payment_success:
                    property_square.owner_id = winner.player_id
                    winner.add_property_id(prop_id)
                    self.log_event(f"{winner.name} now owns {prop_name}.", "auction_event")
                else:
                    self.log_event(f"{winner.name} failed to pay for {prop_name} - auction payment failed.", "error_auction")
                    # Handle bankruptcy if needed
                    self.gc.bankruptcy_manager.check_and_handle_bankruptcy(winner, debt_to_creditor=price_paid, creditor=None)
                    if isinstance(property_square, PurchasableSquare): 
                        property_square.owner_id = None
            else:
                self.log_event(f"{winner.name} failed to pay for {prop_name} - auction payment could not be initiated.", "error_auction")
                self.gc.bankruptcy_manager.check_and_handle_bankruptcy(winner, debt_to_creditor=price_paid, creditor=None)
                if isinstance(property_square, PurchasableSquare): 
                    property_square.owner_id = None 
        
        # Clear auction state
        self.gc.auction_in_progress = False
        self.gc.auction_property_id = None
        self.gc.auction_current_bid = 0
        self.gc.auction_highest_bidder = None
        self.gc.auction_participants = []
        self.gc.auction_active_bidders = []
        self.gc.auction_player_has_bid_this_round = {}
        self.gc.auction_current_bidder_turn_index = 0
        
        self.gc._resolve_current_action_segment()
        
    def handle_auction_bid(self, player_id: int, bid_amount: int) -> bool:
        """
        Handle a player's auction bid.
        
        Args:
            player_id: ID of the player making the bid
            bid_amount: Amount being bid
            
        Returns:
            bool: True if bid was accepted, False otherwise
        """
        if not self.gc.auction_in_progress:
            self.log_event(f"No auction in progress for bid from player {player_id}", "error_auction")
            return False
            
        player = self.players[player_id]
        
        if bid_amount <= self.gc.auction_current_bid:
            self.log_event(f"{player.name} bid ${bid_amount} is not higher than current bid ${self.gc.auction_current_bid}", "error_auction")
            return False
            
        if player.money < bid_amount:
            self.log_event(f"{player.name} cannot afford bid of ${bid_amount}", "error_auction")
            return False
            
        # Accept the bid
        self.gc.auction_current_bid = bid_amount
        self.gc.auction_highest_bidder = player
        self.gc.auction_player_has_bid_this_round[player_id] = True
        
        prop_name = self.board.get_square(self.gc.auction_property_id).name
        self.log_event(f"{player.name} bids ${bid_amount} for {prop_name}", "auction_event")
        
        return True
        
    def handle_auction_pass(self, player_id: int) -> bool:
        """
        Handle a player passing on the auction.
        
        Args:
            player_id: ID of the player passing
            
        Returns:
            bool: True if pass was processed, False otherwise
        """
        if not self.gc.auction_in_progress:
            self.log_event(f"No auction in progress for pass from player {player_id}", "error_auction")
            return False
            
        player = self.players[player_id]
        
        # Remove player from active bidders
        if player in self.gc.auction_active_bidders:
            self.gc.auction_active_bidders.remove(player)
            
        self.gc.auction_player_has_bid_this_round[player_id] = True
        
        prop_name = self.board.get_square(self.gc.auction_property_id).name
        self.log_event(f"{player.name} passes on auction for {prop_name}", "auction_event")
        
        return True 