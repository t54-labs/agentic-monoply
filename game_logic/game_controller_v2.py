from typing import List, Optional, Tuple, Dict, Any
import random
import asyncio
from dataclasses import dataclass, field

from .board import Board, CardData
from .player import Player
from .property import ActionSquare, BaseSquare, PurchasableSquare, PropertySquare, RailroadSquare, TaxSquare, UtilitySquare, SquareType, PropertyColor

# Import sqlalchemy components for DB interaction within GC methods
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session
from database import engine, games_table, players_table, game_turns_table
import json
import datetime

# Import tpay for payment processing
import tpay
import utils

# Import managers for modular architecture
from .managers import (
    PaymentManager, PropertyManager, TradeManager, StateManager,
    AuctionManager, JailManager, BankruptcyManager
)

from admin.game_event_handler import get_game_event_handler

MAX_TRADE_REJECTIONS = 3


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


class GameControllerV2:
    """
    Modular version of GameController using specialized managers.
    All game logic is delegated to appropriate managers while maintaining
    the same interface and functionality as the original GameController.
    
    This version preserves the original GameController intact while providing
    a clean, modular architecture for future development.
    """
    
    def __init__(self, game_uid: str = "default_game", ws_manager: Optional[Any] = None,
                 game_db_id: Optional[int] = None, participants: Optional[List[Dict[str, Any]]] = None,
                 treasury_agent_id: Optional[str] = None):
        
        self.game_uid = game_uid 
        self.ws_manager = ws_manager 
        self.game_db_id = game_db_id 
        self.current_game_turn_db_id: Optional[int] = None 
        self.treasury_agent_id = treasury_agent_id  # System/bank agent ID for payments
        
        # Initialize TPayAgent for payment processing
        self.tpay_agent: tpay.agent.AsyncTPayAgent = tpay.agent.AsyncTPayAgent()
        
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError: 
            print(f"[GC Init Warning G:{self.game_uid}] No asyncio event loop currently running. Attempting to get/create a new one.")
            self.loop = asyncio.new_event_loop() 

        self.game_log: List[str] = [] 
        self.turn_count: int = 0

        self.board: Board = Board()
        self.players: List[Player] = [] 

        self.current_player_index: int = 0
        self.dice: Tuple[int, int] = (0, 0)
        self.doubles_streak: int = 0
        self.game_over: bool = False
        self.pending_decision_type: Optional[str] = None 
        self.pending_decision_context: Dict[str, Any] = {}
        self.dice_roll_outcome_processed: bool = True
        self.auction_in_progress: bool = False
        self.auction_property_id: Optional[int] = None
        self.auction_current_bid: int = 0
        self.auction_highest_bidder: Optional[Player] = None 
        self.auction_participants: List[Player] = [] 
        self.auction_active_bidders: List[Player] = [] 
        self.auction_player_has_bid_this_round: Dict[int, bool] = {}
        self.auction_current_bidder_turn_index: int = 0
        self.trade_offers: Dict[int, TradeOffer] = {}
        self.next_trade_id: int = 1
        self.MAX_TRADE_REJECTIONS: int = 5  # Maximum number of rejections allowed for a trade
        
        # Initialize managers for modular architecture FIRST
        self.payment_manager = PaymentManager(self)
        self.property_manager = PropertyManager(self)
        self.trade_manager = TradeManager(self)
        self.state_manager = StateManager(self)
        self.auction_manager = AuctionManager(self)
        self.jail_manager = JailManager(self)
        self.bankruptcy_manager = BankruptcyManager(self)
        
        # Initialize all managers
        for manager in [self.payment_manager, self.property_manager, self.trade_manager, 
                       self.state_manager, self.auction_manager, self.jail_manager, 
                       self.bankruptcy_manager]:
            manager.initialize()
        
        # NOW initialize players (which may call methods that need managers)
        self._initialize_players(participants) 
        
        self._clear_pending_decision()
        self.log_event(f"GameControllerV2 for G_UID:{self.game_uid} (DB_ID:{self.game_db_id}) initialized with modular managers.")

        # Set threaded game instance reference (will be set by ThreadSafeGameInstance)
        self._threaded_game_instance = None

        # 🎯 NEW: Turn phase to distinguish between different states
        # "pre_roll": Player must roll dice (start of turn)
        # "post_roll": Player can do property management (after roll and movement)
        self.turn_phase = "pre_roll"

    # ======= Core Game Methods (Delegate to Managers) =======
    
    def log_event(self, event_message: str, event_type: str = "game_log_event") -> None:
        """Log game event with timestamp - Thread-safe version"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {event_message}"
        
        # Always add to game log first - this is the most important part
        self.game_log.append(formatted_message)
        
        # Try to send via WebSocket, but don't let failures break logging
        try:
            if hasattr(self, '_threaded_game_instance') and self._threaded_game_instance:
                # Use thread-safe message sending for threaded games
                ws_message = {
                    "type": event_type,
                    "message": formatted_message,
                    "timestamp": timestamp,
                    "game_id": self.game_uid
                }
                self._threaded_game_instance.send_message_safely(ws_message)
        except Exception:
            # Silently ignore WebSocket errors - the message is already in game_log
            pass
    
    async def notify_special_event(self, event_type: str, player_name: str, event_data: Dict[str, Any] = None):
        """Notify special game events (buy property, go to jail, trade, etc.)"""
        try:
            # Get game event handler and send notification
            if hasattr(self, '_threaded_game_instance') and self._threaded_game_instance:
                # In threaded game instance, we need to send via message queue
                notification_message = {
                    'type': 'special_event_notification',
                    'event_type': event_type,
                    'player_name': player_name,
                    'game_uid': self.game_uid,
                    'event_data': event_data or {}
                }
                self._threaded_game_instance.send_message_safely(notification_message)
            else:
                # Directly call event handler
                from admin.game_event_handler import get_game_event_handler
                event_handler = get_game_event_handler()
                if event_handler:
                    combined_event_data = (event_data or {}).copy()
                    combined_event_data['game_uid'] = self.game_uid
                    await event_handler.handle_special_event(self.game_uid, event_type, player_name, combined_event_data)
        except Exception as e:
            self.log_event(f"[Warning] Failed to send special event notification: {e}", "warning_log")

    async def send_event_to_frontend(self, message_data: Dict[str, Any]):
        """Send events to frontend - Thread-safe via message queue"""
        if "game_id" not in message_data:
            message_data["game_id"] = self.game_uid
            
        if self._threaded_game_instance:
            # Use thread-safe message queue
            self._threaded_game_instance.send_message_safely(message_data)
        elif self.ws_manager:
            # Fallback to direct WebSocket (for non-threaded usage)
            await self.ws_manager.broadcast_to_game(self.game_uid, message_data)

    def _clear_pending_decision(self) -> None:
        """Delegate to StateManager"""
        self.state_manager.clear_pending_decision()

    def _set_pending_decision(self, decision_type: str, context: Optional[Dict[str, Any]] = None, outcome_processed: bool = False) -> None:
        """Delegate to StateManager"""
        self.state_manager.set_pending_decision(decision_type, context, outcome_processed)

    def _resolve_current_action_segment(self) -> None:
        """Delegate to StateManager"""
        self.state_manager.resolve_current_action_segment()

    def _check_for_game_over_condition(self) -> None:
        """Delegate to StateManager"""
        self.state_manager.check_for_game_over_condition()
        
    def next_turn(self) -> None:
        """Delegate to StateManager"""
        self.state_manager.next_turn()
        
    # ======= Payment Methods (Delegate to PaymentManager) =======
    
    async def _create_tpay_payment_player_to_player(self, payer: Player, recipient: Player, amount: float, reason: str, 
                                             agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """Delegate to PaymentManager"""
        return await self.payment_manager.create_tpay_payment_player_to_player(payer, recipient, amount, reason, agent_decision_context)
        
    async def _create_tpay_payment_player_to_system(self, payer: Player, amount: float, reason: str, 
                                             event_description: Optional[str] = None) -> bool:
        """Delegate to PaymentManager"""
        return await self.payment_manager.create_tpay_payment_player_to_system(payer, amount, reason, event_description)
        
    async def _create_tpay_payment_system_to_player(self, recipient: Player, amount: float, reason: str,
                                             event_description: Optional[str] = None) -> bool:
        """Delegate to PaymentManager"""
        return await self.payment_manager.create_tpay_payment_system_to_player(recipient, amount, reason, event_description)
        
    async def _wait_for_payment_completion(self, payment_result: Dict[str, Any], timeout_seconds: int = 30) -> bool:
        """Delegate to PaymentManager"""
        return await self.payment_manager._wait_for_payment_completion(payment_result, timeout_seconds)
        
    # ======= Property Methods (Delegate to PropertyManager) =======
    
    async def build_house_on_property(self, player_id: int, property_id: int) -> bool:
        """Delegate to PropertyManager"""
        return await self.property_manager.build_house_on_property(player_id, property_id)
        
    async def sell_house_on_property(self, player_id: int, property_id: int) -> bool:
        """Delegate to PropertyManager"""
        return await self.property_manager.sell_house_on_property(player_id, property_id)
        
    async def mortgage_property_for_player(self, player_id: int, property_id: int) -> bool:
        """Delegate to PropertyManager"""
        return await self.property_manager.mortgage_property_for_player(player_id, property_id)
        
    async def unmortgage_property_for_player(self, player_id: int, property_id: int) -> bool:
        """Delegate to PropertyManager"""
        return await self.property_manager.unmortgage_property_for_player(player_id, property_id)
        
    async def execute_buy_property_decision(self, player_id: int, property_id_to_buy: int) -> bool:
        """Delegate to PropertyManager"""
        return await self.property_manager.execute_buy_property_decision(player_id, property_id_to_buy)
        
    # ======= Trade Methods (Delegate to TradeManager) =======
    
    def propose_trade_action(self, proposer_id: int, recipient_id: int, 
                           offered_property_ids: List[int], offered_money: int, offered_gooj_cards: int,
                           requested_property_ids: List[int], requested_money: int, requested_gooj_cards: int,
                           message: Optional[str] = None,
                           counter_to_trade_id: Optional[int] = None) -> Optional[int]:
        """Delegate to TradeManager"""
        return self.trade_manager.propose_trade_action(proposer_id, recipient_id, offered_property_ids, offered_money, 
                                                     offered_gooj_cards, requested_property_ids, requested_money, 
                                                     requested_gooj_cards, message, counter_to_trade_id)
        
    async def _respond_to_trade_offer_action(self, player_id: int, trade_id: int, response: str,
                                          counter_offered_prop_ids: Optional[List[int]] = None,
                                          counter_offered_money: Optional[int] = None,
                                          counter_offered_gooj_cards: Optional[int] = None,
                                          counter_requested_prop_ids: Optional[List[int]] = None,
                                          counter_requested_money: Optional[int] = None,
                                          counter_requested_gooj_cards: Optional[int] = None,
                                          counter_message: Optional[str] = None) -> bool:
        """Delegate to TradeManager"""
        return await self.trade_manager.respond_to_trade_offer_action(player_id, trade_id, response, 
                                                                    counter_offered_prop_ids, counter_offered_money, 
                                                                    counter_offered_gooj_cards, counter_requested_prop_ids, 
                                                                    counter_requested_money, counter_requested_gooj_cards, 
                                                                    counter_message)
        
    def _end_trade_negotiation_action(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to TradeManager"""
        return self.trade_manager.end_trade_negotiation_action(player_id, params)
        
    # ======= Movement Methods (To be implemented) =======
    
    async def _move_player(self, player: Player, steps: int) -> None:
        """Move player with proper GO handling"""
        old_position = player.position
        new_position = (old_position + steps) % len(self.board.squares)
        
        # Check for passing GO
        if new_position < old_position:
            await self._handle_go_passed(player)
            
        player.position = new_position
        self.log_event(f"{player.name} moved {steps} spaces to {self.board.get_square(new_position).name}")
        
        # Handle landing on the square
        await self.land_on_square(player)
        
    async def _handle_go_passed(self, player: Player) -> None:
        """Handle player passing GO and collecting salary"""
        go_salary = 200
        self.log_event(f"{player.name} passed GO!")
        
        # Create TPay payment from system to player
        payment_success = await self._create_tpay_payment_system_to_player(
            recipient=player,
            amount=float(go_salary),
            reason="GO salary",
            event_description=f"{player.name} passed GO and collects ${go_salary} salary"
        )
        
        if payment_success:
            self.log_event(f"{player.name} collected ${go_salary} for passing GO")
            
            # Send GO salary event notification
            await self.notify_special_event('go_salary', player.name, {
                'amount': go_salary
            })
        else:
            self.log_event(f"[Error] {player.name} GO salary payment failed")
        
    async def land_on_square(self, player: Player) -> None:
        """Handle landing on square with full logic matching original GameController"""
        if player.is_bankrupt:
            self.dice_roll_outcome_processed = True
            self._clear_pending_decision()
            return
        
        square = self.board.get_square(player.position)
        self.log_event(f"{player.name} landed on {square.name}.")
        self._clear_pending_decision()  # Clear previous before specific handler potentially sets a new one.

        if isinstance(square, PropertySquare) or isinstance(square, RailroadSquare) or isinstance(square, UtilitySquare):
            await self._handle_property_landing(player, square)  # This will set pending_decision or resolve outcome
        elif isinstance(square, ActionSquare):
            await self._handle_action_square_landing(player, square)  # This will set pending_decision or resolve outcome
        elif isinstance(square, TaxSquare):
            await self._handle_tax_square_landing(player, square)  # This will set pending_decision or resolve outcome
        elif square.square_type == SquareType.GO_TO_JAIL:
            self._handle_go_to_jail_landing(player)  # Resolves outcome for this landing
        elif square.square_type in [SquareType.GO, SquareType.JAIL_VISITING, SquareType.FREE_PARKING]:
            self._handle_special_square_landing(player, square)  # Resolves outcome for this landing
        else:
            self.log_event(f"Landed on {square.name} - no specific action. Outcome processed.")
            self.dice_roll_outcome_processed = True
            self._clear_pending_decision()
            
    async def _handle_property_landing(self, player: Player, square: PurchasableSquare) -> None:
        """Handle landing on property with rent calculation and TPay payments"""
        self.log_event(f"Handling property landing: {square.name} for {player.name}")
        card_forced_action = self.pending_decision_context.pop("card_forced_action", None)

        if square.owner_id is None:
            self.log_event(f"{square.name} is unowned. Price: ${square.price}")
            self._set_pending_decision("buy_or_auction_property", 
                                     context={"property_id": square.square_id, "player_id": player.player_id}, 
                                     outcome_processed=False) 
        elif square.owner_id == player.player_id:
            self.log_event(f"{player.name} landed on their own property: {square.name}.")
            
            # 🏠 When landing on own property, enter post-roll phase for property management
            # Don't call _resolve_current_action_segment() as that would end the segment immediately
            # Instead, set the state to allow property management actions
            self.dice_roll_outcome_processed = True
            self._clear_pending_decision()
            
            # 🎯 Set turn phase to post-roll to enable property management actions
            if hasattr(self, 'turn_phase'):
                self.turn_phase = "post_roll"
            
            self.log_event(f"{player.name} can now do property management (build houses, trade, etc.) or end turn", "property_management")
        elif square.owner_id is not None and not square.is_mortgaged:
            owner = self.players[square.owner_id]
            rent_amount = 0
            
            # Handle special card-forced rent calculations
            if card_forced_action == "pay_double_railroad_rent" and isinstance(square, RailroadSquare):
                num_railroads_owned = sum(1 for prop_id in owner.properties_owned_ids if isinstance(self.board.get_square(prop_id), RailroadSquare))
                base_rent = square.get_rent(num_railroads_owned)
                rent_amount = base_rent * 2
                self.log_event(f"Card forces payment of 2x railroad rent: ${rent_amount}")
            elif card_forced_action == "pay_10x_dice_utility_rent" and isinstance(square, UtilitySquare):
                utility_dice_roll_for_card = (random.randint(1,6) + random.randint(1,6))
                self.log_event(f"{player.name} rolls {utility_dice_roll_for_card} for special utility rent.")
                rent_amount = 10 * utility_dice_roll_for_card
                self.log_event(f"Card forces payment of 10x dice roll for utility rent: ${rent_amount}")
            else: 
                # Normal rent calculation
                if isinstance(square, PropertySquare):
                    num_in_group = len(self.board.get_properties_in_group(square.color_group))
                    owned_in_group = sum(1 for prop_id in owner.properties_owned_ids if isinstance(self.board.get_square(prop_id), PropertySquare) and self.board.get_square(prop_id).color_group == square.color_group)
                    rent_amount = square.get_rent(num_properties_in_group_owned_by_owner=owned_in_group, total_properties_in_group=num_in_group)
                elif isinstance(square, RailroadSquare):
                    num_railroads_owned = sum(1 for prop_id in owner.properties_owned_ids if isinstance(self.board.get_square(prop_id), RailroadSquare))
                    rent_amount = square.get_rent(num_railroads_owned)
                elif isinstance(square, UtilitySquare):
                    num_utilities_owned = sum(1 for prop_id in owner.properties_owned_ids if isinstance(self.board.get_square(prop_id), UtilitySquare))
                    dice_total_for_movement = self.dice[0] + self.dice[1]
                    rent_amount = square.get_rent(dice_total_for_movement, num_utilities_owned)
            
            if rent_amount > 0:
                self.log_event(f"{player.name} owes ${rent_amount} to {owner.name} for {square.name}.")
                
                # Use TPay for rent payment between players
                payment_success = await self._create_tpay_payment_player_to_player(
                    payer=player,
                    recipient=owner,
                    amount=float(rent_amount),
                    reason=f"rent for {square.name}"
                )
                
                if payment_success:
                    self.log_event(f"{player.name} successfully paid ${rent_amount} rent to {owner.name}.")
                    
                    # Send rent payment event notification
                    await self.notify_special_event('rent_payment', player.name, {
                        'property_name': square.name,
                        'amount': rent_amount,
                        'owner_name': owner.name
                    })
                    
                    self._resolve_current_action_segment()
                else:
                    self.log_event(f"{player.name} failed to pay ${rent_amount} rent - payment failed or could not be initiated.")
                    self._check_and_handle_bankruptcy(player, debt_to_creditor=rent_amount, creditor=owner)
            else:
                self.log_event(f"No rent due for {square.name}.")
                self._resolve_current_action_segment()

        elif square.is_mortgaged:
            self.log_event(f"{square.name} is mortgaged by Player {square.owner_id}. No rent due.")
            self._resolve_current_action_segment()
            
    async def _handle_action_square_landing(self, player: Player, action_sq: ActionSquare) -> None:
        """Handle landing on Community Chest or Chance square"""
        card = None
        card_type = ""
        
        if action_sq.square_type == SquareType.COMMUNITY_CHEST:
            card = self.board.draw_community_chest_card()
            card_type = "Community Chest"
            self.log_event(f"{player.name} drew a Community Chest card: {card[0]}")
        elif action_sq.square_type == SquareType.CHANCE:
            card = self.board.draw_chance_card()
            card_type = "Chance"
            self.log_event(f"{player.name} drew a Chance card: {card[0]}")
        
        if card:
            # Send card drawn notification
            await self.notify_special_event('card_drawn', player.name, {
                'card_type': card_type,
                'card_description': card[0]
            })
            
            await self._handle_card_effect(player, card)
        else:
            self.log_event(f"[Error] Landed on ActionSquare {action_sq.name} but no card drawn.")
            self._resolve_current_action_segment()
            
    async def _handle_tax_square_landing(self, player: Player, tax_sq: TaxSquare) -> None:
        """Handle landing on tax square with TPay payment"""
        amount_due = tax_sq.tax_amount
        self.log_event(f"{player.name} has to pay ${amount_due} for {tax_sq.name}.")
        
        # Use TPay for tax payment to system
        payment_success = await self._create_tpay_payment_player_to_system(
            payer=player,
            amount=float(amount_due),
            reason=f"tax - {tax_sq.name}",
            event_description=f"{player.name} paid ${amount_due} tax on {tax_sq.name}"
        )
        
        if payment_success:
            self.log_event(f"{player.name} successfully paid ${amount_due} tax.")
            
            # Send income tax event notification
            try:
                # Check if we have a threaded game instance reference for safe communication
                if hasattr(self, '_threaded_game_instance') and self._threaded_game_instance:
                    # Use thread-safe message sending
                    notification_message = {
                        'type': 'special_event_notification',
                        'game_uid': self.game_uid,
                        'event_type': 'income_tax',
                        'player_name': player.name,
                        'event_data': {
                            'amount': amount_due,
                            'tax_type': tax_sq.name,
                            'position': tax_sq.square_id
                        }
                    }
                    self._threaded_game_instance.send_message_safely(notification_message)
                else:
                    # Fallback for non-threaded environments
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            asyncio.create_task(self.notify_special_event('income_tax', player.name, {
                                'amount': amount_due,
                                'tax_type': tax_sq.name,
                                'position': tax_sq.square_id
                            }))
                    except (RuntimeError, AttributeError):
                        # If no event loop is running or we're in wrong thread, just log
                        self.log_event(f"[Info] {player.name} paid {tax_sq.name} ${amount_due} (notification skipped - no async context)")
            except Exception as e:
                self.log_event(f"[Warning] Failed to send income tax notification for {player.name}: {e}")
            
            self._resolve_current_action_segment()
        else:
            self.log_event(f"{player.name} failed to pay ${amount_due} tax.")
            self._check_and_handle_bankruptcy(player, debt_to_creditor=amount_due, creditor=None)
            
    def _handle_special_square_landing(self, player: Player, special_sq: BaseSquare) -> None:
        """Handle landing on special squares like GO, Jail Visiting, Free Parking"""
        if special_sq.square_type == SquareType.GO:
            self.log_event(f"{player.name} landed on GO. (Salary already handled if passed).")
        elif special_sq.square_type == SquareType.JAIL_VISITING:
            if player.in_jail:
                self.log_event(f"{player.name} is in Jail.")
            else:
                self.log_event(f"{player.name} is Just Visiting Jail.")
        elif special_sq.square_type == SquareType.FREE_PARKING:
            self.log_event(f"{player.name} landed on Free Parking. Nothing happens (standard rules).")
        self._resolve_current_action_segment()
        
    async def _move_player_directly_to_square(self, player: Player, target_pos: int, collect_go_salary_if_passed: bool = False) -> None:
        """Move player directly to square with proper GO handling"""
        old_position = player.position
        
        # Check for passing GO if moving forward
        if collect_go_salary_if_passed and target_pos < old_position:
            await self._handle_go_passed(player)
            
        player.position = target_pos
        self.log_event(f"{player.name} moved directly to {self.board.get_square(target_pos).name}")
        
        # Handle landing on the square
        await self.land_on_square(player)
        
    # ======= Card Methods (To be implemented) =======
    
    async def _handle_card_effect(self, player: Player, card: CardData) -> None:
        """Handle card effect with complete logic matching original GameController"""
        description, action_type, value = card
        self.log_event(f"Card effect for {player.name}: {description} (Action: {action_type}, Value: {value})")
        self._clear_pending_decision()
        self.dice_roll_outcome_processed = False

        # --- Simple Effects (resolve immediately) ---
        if action_type == "receive_money":
            # Use TPay for bank reward payment to player
            payment_success = await self._create_tpay_payment_system_to_player(
                recipient=player,
                amount=float(value),
                reason="card reward",
                event_description=f"{player.name} received ${value} from card: {description}"
            )
            
            if payment_success:
                self.log_event(f"{player.name} received ${value}.")
            else:
                self.log_event(f"{player.name} failed to receive ${value}.")
                
            self._resolve_current_action_segment()
        elif action_type == "get_out_of_jail_card":
            card_type_str = value if isinstance(value, str) else "unknown" 
            if value == "community_chest": 
                player.add_get_out_of_jail_card("community_chest")
            elif value == "chance": 
                player.add_get_out_of_jail_card("chance")
            self.log_event(f"{player.name} received a Get Out of Jail Free card ({card_type_str}).")
            self._resolve_current_action_segment()
        
        # --- Effects involving Payment (might lead to bankruptcy decision) ---
        elif action_type == "pay_money":
            # Use TPay for card penalty payment to system
            payment_success = await self._create_tpay_payment_player_to_system(
                payer=player,
                amount=float(value),
                reason=f"card penalty - {description}",
                event_description=f"{player.name} paid ${value} from card: {description}"
            )
            
            if payment_success:
                self.log_event(f"{player.name} successfully paid ${value} card penalty.")
                self._resolve_current_action_segment()
            else:
                self.log_event(f"{player.name} failed to pay ${value} card penalty.")
                self._check_and_handle_bankruptcy(player, debt_to_creditor=value, creditor=None)
        elif action_type == "street_repairs":
            house_cost, hotel_cost = value 
            total_repair_cost = sum(
                hotel_cost if isinstance(sq := self.board.get_square(prop_id), PropertySquare) and sq.num_houses == 5 
                else (sq.num_houses * house_cost if isinstance(sq, PropertySquare) else 0) 
                for prop_id in player.properties_owned_ids
            )
            if total_repair_cost > 0:
                self.log_event(f"{player.name} needs to pay ${total_repair_cost} for street repairs.")
                
                # Use TPay for street repairs payment to system
                payment_success = await self._create_tpay_payment_player_to_system(
                    payer=player,
                    amount=float(total_repair_cost),
                    reason="street repairs",
                    event_description=f"{player.name} paid ${total_repair_cost} for street repairs"
                )
                
                if payment_success:
                    self.log_event(f"{player.name} successfully paid ${total_repair_cost} for street repairs.")
                    self._resolve_current_action_segment()
                else:
                    self.log_event(f"{player.name} failed to pay ${total_repair_cost} for street repairs.")
                    self._check_and_handle_bankruptcy(player, debt_to_creditor=total_repair_cost, creditor=None)
            else:
                self.log_event(f"{player.name} has no properties with buildings for street repairs.")
                self._resolve_current_action_segment()
        # --- Effects involving Movement (these will call land_on_square, which sets final state) ---
        elif action_type == "move_to_exact":
            current_pos = player.position
            target_pos = value
            await self._move_player_directly_to_square(player, target_pos, collect_go_salary_if_passed=(target_pos == 0 and current_pos != 0))
        elif action_type == "move_to_exact_with_go_check":
            current_pos = player.position
            target_pos = value
            await self._move_player_directly_to_square(player, target_pos, collect_go_salary_if_passed=((target_pos < current_pos and target_pos != 0) or (target_pos == 0 and current_pos != 0)))
        elif action_type == "move_relative":
            await self._move_player(player, value)
        elif action_type == "go_to_jail":
            self._handle_go_to_jail_landing(player)  # This calls _resolve_current_action_segment()
        elif action_type == "advance_to_nearest" or action_type == "advance_to_nearest_railroad_pay_double":
            target_type_str = value if action_type == "advance_to_nearest" else "railroad"
            target_square_type = SquareType.UTILITY if target_type_str == "utility" else SquareType.RAILROAD
            nearest_square_id = -1
            current_pos = player.position
            for i in range(1, len(self.board.squares) + 1):
                prospective_sq_id = (current_pos + i) % len(self.board.squares)
                if self.board.get_square(prospective_sq_id).square_type == target_square_type:
                    nearest_square_id = prospective_sq_id
                    break
            if nearest_square_id != -1:
                self.log_event(f"Card: Advancing {player.name} to nearest {target_type_str}: {self.board.get_square(nearest_square_id).name}.")
                # Clear any old card_forced_action before setting a new one
                self.pending_decision_context.pop("card_forced_action", None)
                if action_type == "advance_to_nearest_railroad_pay_double":
                    self.pending_decision_context["card_forced_action"] = "pay_double_railroad_rent"
                elif target_square_type == SquareType.UTILITY:
                    self.pending_decision_context["card_forced_action"] = "pay_10x_dice_utility_rent"
                await self._move_player_directly_to_square(player, nearest_square_id, collect_go_salary_if_passed=(nearest_square_id < current_pos and nearest_square_id != 0))
            else:
                self.log_event(f"[Error] Card: Could not find nearest {target_type_str} for {player.name}.")
                self._resolve_current_action_segment()
        elif action_type == "collect_from_players":
            # Delegate to PaymentManager
            payment_success = await self.payment_manager.handle_collect_from_players(player, value)
            self._resolve_current_action_segment()
        elif action_type == "pay_players":
            # Delegate to PaymentManager
            payment_success = await self.payment_manager.handle_pay_to_players(player, value)
            self._resolve_current_action_segment()
        else:
            self.log_event(f"[Warning] Card action_type '{action_type}' has no explicit state update logic in _handle_card_effect. Resolving segment.")
            self._resolve_current_action_segment()
        
    # ======= Jail Methods (Delegate to JailManager) =======
    
    def _handle_jail_turn_initiation(self, player: Player) -> None:
        """Delegate to JailManager"""
        self.jail_manager.handle_jail_turn_initiation(player)
        
    async def _attempt_roll_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to JailManager"""
        return await self.jail_manager.attempt_roll_out_of_jail(player_id, params)
        
    async def _pay_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle paying bail to get out of jail"""
        return await self.jail_manager.pay_to_get_out_of_jail(player_id, params)
        
    async def _use_card_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle using Get Out of Jail Free card"""  
        return await self.jail_manager.use_card_to_get_out_of_jail(player_id, params)
        
    # ======= Auction Methods (Delegate to AuctionManager) =======
    
    async def _initiate_auction(self, property_id: int) -> None:
        """Initiate auction for a property"""
        return await self.auction_manager.initiate_auction(property_id)
        
    async def _conclude_auction(self, no_winner: bool = False) -> None:
        """Delegate to AuctionManager"""
        await self.auction_manager.conclude_auction(no_winner)
        
    # ======= Bankruptcy Methods (Delegate to BankruptcyManager) =======
    
    def _check_and_handle_bankruptcy(self, player: Player, debt_to_creditor: int = 0, creditor: Optional[Player] = None) -> None:
        """Delegate to BankruptcyManager"""
        self.bankruptcy_manager.check_and_handle_bankruptcy(player, debt_to_creditor, creditor)
        
    def confirm_asset_liquidation_done(self, player_id: int) -> None:
        """Delegate to BankruptcyManager"""
        self.bankruptcy_manager.confirm_asset_liquidation_done(player_id)
        
    def _finalize_bankruptcy_declaration(self, player: Player, creditor: Optional[Player]) -> None:
        """Delegate to BankruptcyManager"""
        self.bankruptcy_manager.finalize_bankruptcy_declaration(player, creditor)

    # ======= Preserved Original Methods =======
    
    def _initialize_players(self, participants: Optional[List[Dict[str, Any]]] = None) -> None:
        """Initialize players (preserved from original)"""
        for i in range(len(participants)):
            name = participants[i]['name']
            agent_uid = participants[i]['agent_uid']
            agent_tpay_id = participants[i]['tpay_account_id']
            player_db_id = participants[i].get('db_id')
            if player_db_id is None and self.game_db_id is not None: 
                self.log_event(f"[CRITICAL DB Error] DB ID for P_idx {i} not found. Player not DB-linked.", "error_log")
            
            new_player = Player(player_id=i, name=name, is_ai=True, db_id=player_db_id, agent_uid=agent_uid, agent_tpay_id=agent_tpay_id)
            self.players.append(new_player)
        self.log_event(f"Initialized {len(self.players)} AI players: {[p.name + (f'(DBID:{p.db_id})' if p.db_id else '(No DBID)') for p in self.players]}")
        self.pending_decision_type = None 
        self.dice_roll_outcome_processed = True 
        self._clear_pending_decision() 

    def get_current_player(self) -> Player:
        """Get current player (preserved from original)"""
        return self.players[self.current_player_index]

    def roll_dice(self) -> Tuple[int, int]:
        """Roll dice (preserved from original)"""
        current_player = self.get_current_player()
        if current_player.in_jail:
            self.log_event(f"[Warning] roll_dice called for player in jail. Use jail-specific roll tool.")

        self.dice = (random.randint(1, 6), random.randint(1, 6))
        self.log_event(f"{current_player.name} rolled {self.dice[0]} and {self.dice[1]}.")
        self.dice_roll_outcome_processed = False
        
        # 🎯 When rolling dice, we're in "processing" state - not pre_roll or post_roll
        # This will be set to post_roll after movement and landing are processed
        
        if self.is_double_roll():
            self.doubles_streak += 1
            self.log_event(f"Doubles! Streak: {self.doubles_streak}")
            if self.doubles_streak == 3:
                self.log_event(f"{current_player.name} rolled doubles 3 times in a row. Go to Jail!")
                self._handle_go_to_jail_landing(current_player)
                return self.dice
        else:
            self.doubles_streak = 0
        return self.dice

    def is_double_roll(self) -> bool:
        """Check if dice roll is doubles (preserved from original)"""
        return self.dice[0] == self.dice[1]
        
    def _handle_go_to_jail_landing(self, player: Player) -> None:
        """Handle go to jail (preserved from original)"""
        self.log_event(f"{player.name} is going to jail!")
        player.go_to_jail()
        self.doubles_streak = 0 
        
        # Send jail event notification - fixed for thread safety
        try:
            # Check if we have a threaded game instance reference for safe communication
            if hasattr(self, '_threaded_game_instance') and self._threaded_game_instance:
                # Use thread-safe message sending
                notification_message = {
                    'type': 'special_event_notification',
                    'game_uid': self.game_uid,
                    'event_type': 'jail',
                    'player_name': player.name,
                    'event_data': {}
                }
                self._threaded_game_instance.send_message_safely(notification_message)
            else:
                # Fallback for non-threaded environments
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        asyncio.create_task(self.notify_special_event('jail', player.name))
                except (RuntimeError, AttributeError):
                    # If no event loop is running or we're in wrong thread, just log
                    self.log_event(f"[Info] {player.name} went to jail (notification skipped - no async context)")
        except Exception as e:
            self.log_event(f"[Warning] Failed to send jail notification for {player.name}: {e}")
        
        self._resolve_current_action_segment()

    # ======= Placeholder Methods (To be completed) =======
    
    def start_game(self, all_players_start_in_jail_test_mode: bool = False, 
                   test_mode_trade_details: Optional[Dict[str, Any]] = None,
                   test_mode_auction_property_id: Optional[int] = None) -> None:
        """Start game with comprehensive setup matching original GameController"""
        import datetime
        
        self.log_event(f"GameControllerV2.start_game() called. Game starting with {len(self.players)} players.")
        if not self.players:
            self.log_event("[Error] No players initialized. Cannot start game.", "error_log")
            self.game_over = True
            return
        
        # Record game start time for duration tracking
        self.start_time = datetime.datetime.now()
        
        # Initialize game state
        self.current_player_index = random.randrange(len(self.players))
        self.turn_count = 1 
        self.game_over = False
        self.log_event(f"Game G_UID:{self.game_uid} starting. Player {self.players[self.current_player_index].name} (P{self.current_player_index}) goes first. Turn: {self.turn_count}.")
        
        # Handle test modes
        if all_players_start_in_jail_test_mode:
            self.log_event("[TEST MODE] All players starting in jail.")
            for player in self.players:
                player.go_to_jail()
                player.jail_turns_remaining = 0  # Allow them to start trying to get out immediately
                
        if test_mode_trade_details:
            self.log_event(f"[TEST MODE] Trade will be initiated: {test_mode_trade_details}")
            # Trade setup can be handled by TradeManager
            
        if test_mode_auction_property_id is not None:
            self.log_event(f"[TEST MODE] Auction will be initiated for property {test_mode_auction_property_id}")
            # Auction setup can be handled by AuctionManager
            
        # Clear any pending decisions and set initial state
        self._clear_pending_decision()
        self.dice_roll_outcome_processed = True
        
        # 🎯 Set initial turn phase to pre-roll (first player must roll dice)
        self.turn_phase = "pre_roll"
        
        # Check if starting player is in jail (for test mode or other reasons)
        current_player = self.get_current_player()
        if current_player.in_jail:
            self._handle_jail_turn_initiation(current_player)
            
        self.log_event(f"Game initialized successfully. Current player: {current_player.name}. Ready for first action - PRE-ROLL phase.")
        
    def _handle_jail_turn_initiation(self, player: Player) -> None:
        """Handle jail turn initiation - delegate to JailManager"""
        self.jail_manager.handle_jail_turn_initiation(player)
        
    def get_available_actions(self, player_id: int) -> List[str]:
        """Get available actions with comprehensive logic matching original GameController"""
        actions: List[str] = []
        if not (0 <= player_id < len(self.players)):
            return []
            
        player = self.players[player_id]
        if player.is_bankrupt: 
            return []

        # --- Specific Pending Decisions ---
        if self.pending_decision_type == "jail_options":
            if player.in_jail and self.pending_decision_context.get("player_id") == player_id:
                has_card = getattr(player, 'has_chance_gooj_card', False) or getattr(player, 'has_community_gooj_card', False)
                can_pay_bail_directly = player.money >= 50
                max_rolls_attempted = getattr(player, 'jail_turns_remaining', 0) >= 3 or self.pending_decision_context.get("max_rolls_attempted", False)
                if has_card: 
                    actions.append("tool_use_get_out_of_jail_card")
                if can_pay_bail_directly: 
                    actions.append("tool_pay_bail")
                if not max_rolls_attempted: 
                    actions.append("tool_roll_for_doubles_to_get_out_of_jail")
                if max_rolls_attempted and not has_card and not can_pay_bail_directly:
                    can_mortgage = any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids)
                    can_sell_houses = any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids)
                    if can_mortgage: 
                        actions.append("tool_mortgage_property")
                    if can_sell_houses: 
                        actions.append("tool_sell_house")
                if not actions or (max_rolls_attempted and (has_card or can_pay_bail_directly)):
                    actions.append("tool_end_turn") 
            else: 
                self._clear_pending_decision()
        
        elif self.pending_decision_type == "respond_to_trade_offer":
            if self.pending_decision_context.get("player_id") == player_id: 
                actions.extend(["tool_accept_trade", "tool_reject_trade", "tool_propose_counter_offer"]) 
            else: 
                self._clear_pending_decision()

        elif self.pending_decision_type == "propose_new_trade_after_rejection":
            if self.pending_decision_context.get("player_id") == player_id:
                rejection_count = self.pending_decision_context.get("rejection_count", 0)
                self.log_event(f"[TRADE DEBUG] P{player_id} in propose_new_trade_after_rejection state, rejection_count: {rejection_count}, max: {MAX_TRADE_REJECTIONS}", "error_trade")
                if rejection_count < MAX_TRADE_REJECTIONS:
                    actions.append("tool_propose_trade")
                actions.append("tool_end_trade_negotiation")
            else: 
                self._clear_pending_decision()

        elif self.pending_decision_type == "buy_or_auction_property":
            if self.pending_decision_context.get("player_id") == player_id: 
                actions.extend(["tool_buy_property", "tool_pass_on_buying_property"])
            else: 
                self._clear_pending_decision()
                
        elif self.pending_decision_type == "asset_liquidation_for_debt":
            if self.pending_decision_context.get("player_id") == player_id:
                if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): 
                    actions.append("tool_sell_house")
                if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): 
                    actions.append("tool_mortgage_property")
                actions.append("tool_confirm_asset_liquidation_actions_done") 
            else: 
                self._clear_pending_decision()
                
        elif self.pending_decision_type == "auction_bid": 
            if self.pending_decision_context.get("player_to_bid_id") == player_id and player_id in [p.player_id for p in self.auction_active_bidders]: 
                actions.extend(["tool_bid_on_auction", "tool_pass_auction_bid"]) 
            elif player_id in [p.player_id for p in self.auction_active_bidders]: 
                actions.append("tool_wait") 

        # --- General Turn Actions (if no specific decision is pending) ---
        if not actions and self.pending_decision_type is None: 
            if self.current_player_index == player_id:
                if not player.in_jail: 
                    if self.turn_phase == "pre_roll":
                        # 🎲 RULE: In Monopoly, rolling dice is MANDATORY at the start of each turn
                        # Players cannot choose to skip rolling dice to avoid moving
                        actions.append("tool_roll_dice")
                        
                        # 🚫 IMPORTANT: NO property management before rolling dice
                        # Players must roll dice first, then move, then handle property management
                        
                        # The only exception is resign game
                        actions.append("tool_resign_game")
                        
                    elif self.turn_phase == "post_roll":
                        # 🎲 Dice has been rolled and player has moved to new position
                        # Now player can do property management in "post-roll" phase
                        
                        # 🏠 Property management actions (after rolling and moving)
                        # Check if can build houses
                        can_build_on_any_property = False

                        # Debug: Log player's properties for build house analysis
                        self.log_event(f"[BUILD HOUSE DEBUG] P{player_id} ({player.name}) analysis:", "debug_build_house")
                        self.log_event(f"  - Money: ${player.money}", "debug_build_house")
                        self.log_event(f"  - Owns properties: {list(player.properties_owned_ids)}", "debug_build_house")
                        self.log_event(f"  - Turn phase: {getattr(self, 'turn_phase', 'unknown')}", "debug_build_house")

                        for p_id_check in player.properties_owned_ids:
                            square_check = self.board.get_square(p_id_check)
                            
                            if isinstance(square_check, PropertySquare):
                                self.log_event(f"  - Checking property {square_check.name} (ID: {p_id_check}):", "debug_build_house")
                                self.log_event(f"    * Owner: {square_check.owner_id} (me: {player_id})", "debug_build_house")
                                self.log_event(f"    * Mortgaged: {square_check.is_mortgaged}", "debug_build_house")
                                self.log_event(f"    * Houses: {square_check.num_houses}/5", "debug_build_house")
                                self.log_event(f"    * House price: ${square_check.house_price}", "debug_build_house")
                                self.log_event(f"    * Color group: {square_check.color_group.value if square_check.color_group else 'N/A'}", "debug_build_house")
                                
                                if square_check.owner_id == player_id and \
                                   not square_check.is_mortgaged and \
                                   square_check.num_houses < 5 and \
                                   player.money >= square_check.house_price:
                                    
                                    # Check if owns all properties in the color group
                                    color_group_properties = self.board.get_properties_in_group(square_check.color_group)
                                    self.log_event(f"    * Color group has {len(color_group_properties)} properties total", "debug_build_house")
                                    
                                    owns_all_in_group_unmortgaged = True
                                    owned_count = 0
                                    mortgaged_count = 0
                                    
                                    for i, prop_square in enumerate(color_group_properties):
                                        prop_name = prop_square.name if hasattr(prop_square, 'name') else f"Property_{i}"
                                        prop_owner = prop_square.owner_id if hasattr(prop_square, 'owner_id') else None
                                        prop_mortgaged = prop_square.is_mortgaged if hasattr(prop_square, 'is_mortgaged') else False
                                        prop_houses = prop_square.num_houses if hasattr(prop_square, 'num_houses') else 0
                                        
                                        self.log_event(f"      - {prop_name}: owner={prop_owner}, mortgaged={prop_mortgaged}, houses={prop_houses}", "debug_build_house")
                                        
                                        if isinstance(prop_square, PropertySquare) and prop_square.owner_id == player_id:
                                            owned_count += 1
                                            if prop_square.is_mortgaged:
                                                mortgaged_count += 1
                                                
                                        if not (isinstance(prop_square, PropertySquare) and 
                                               prop_square.owner_id == player_id and 
                                               not prop_square.is_mortgaged):
                                            owns_all_in_group_unmortgaged = False
                                    
                                    self.log_event(f"    * Owned in group: {owned_count}/{len(color_group_properties)}", "debug_build_house")
                                    self.log_event(f"    * Mortgaged in group: {mortgaged_count}", "debug_build_house")
                                    self.log_event(f"    * Owns all unmortgaged: {owns_all_in_group_unmortgaged}", "debug_build_house")
                                    
                                    if owns_all_in_group_unmortgaged:
                                        # Check even building rule
                                        min_houses_in_group = min(prop.num_houses for prop in color_group_properties 
                                                                 if isinstance(prop, PropertySquare) and prop.owner_id == player_id)
                                        self.log_event(f"    * Min houses in group: {min_houses_in_group}", "debug_build_house")
                                        self.log_event(f"    * This property houses: {square_check.num_houses}", "debug_build_house")
                                        self.log_event(f"    * Can build (even rule): {square_check.num_houses == min_houses_in_group}", "debug_build_house")
                                        
                                        if square_check.num_houses == min_houses_in_group:
                                            can_build_on_any_property = True
                                            self.log_event(f"    ✅ CAN BUILD on {square_check.name}!", "debug_build_house")
                                            break
                                        else:
                                            self.log_event(f"    ❌ Cannot build - must build on properties with {min_houses_in_group} houses first", "debug_build_house")
                                    else:
                                        if owned_count < len(color_group_properties):
                                            self.log_event(f"    ❌ Cannot build - don't own complete color group", "debug_build_house")
                                        elif mortgaged_count > 0:
                                            self.log_event(f"    ❌ Cannot build - {mortgaged_count} properties mortgaged in group", "debug_build_house")
                                        else:
                                            self.log_event(f"    ❌ Cannot build - other ownership/mortgage issues", "debug_build_house")
                            else:
                                # For non-PropertySquare types (Railroad, Utility), houses cannot be built
                                square_type = type(square_check).__name__
                                self.log_event(f"  - Skipping {square_check.name} (ID: {p_id_check}): {square_type} cannot have houses built", "debug_build_house")

                        self.log_event(f"[BUILD HOUSE DEBUG] Final result: can_build_on_any_property = {can_build_on_any_property}", "debug_build_house")

                        if can_build_on_any_property: 
                            actions.append("tool_build_house")
                            
                        # Other property management actions (post-roll only)
                        if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): 
                            actions.append("tool_sell_house")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): 
                            actions.append("tool_mortgage_property")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and sq.is_mortgaged and player.money >= int(sq.mortgage_value*1.1) for pid in player.properties_owned_ids): 
                            actions.append("tool_unmortgage_property")
                        if len([p_other for p_other in self.players if not p_other.is_bankrupt and p_other.player_id != player_id]) > 0: 
                            actions.append("tool_propose_trade")
                        
                        # 🎲 BONUS TURN: If player rolled doubles, they can roll again after property management
                        if self.doubles_streak > 0 and self.doubles_streak < 3:
                            actions.append("tool_roll_dice")  # Allow another dice roll for bonus turn
                            self.log_event(f"[Bonus Turn] {player.name} can roll dice again due to doubles (streak: {self.doubles_streak})", "debug_bonus_turn")
                        
                        # In post-roll phase, player can end turn (but only if no bonus turn available or they choose to skip it)
                        actions.append("tool_end_turn")
                        actions.append("tool_resign_game")
                        
                    if not actions: 
                        actions.append("tool_wait") 
                elif player.in_jail: 
                    # 🔒 Handle jail scenario properly
                    self.log_event(f"[Info] P{player_id} ({player.name}) in jail, triggering jail options.", "warning_log")
                    self._set_pending_decision("jail_options", {"player_id": player_id})
                    # Re-run get_available_actions to get jail options
                    return self.get_available_actions(player_id)
            else: 
                actions.append("tool_wait")

        if not actions and not player.is_bankrupt: 
            self.log_event(f"[Fallback Warning No Actions] P{player_id} ({player.name}). Pend: {self.pending_decision_type}, DiceDone: {self.dice_roll_outcome_processed}. Adding tool_wait/end_turn.", "warning_log")
            if self.current_player_index == player_id and self.pending_decision_type is None and self.dice_roll_outcome_processed: 
                actions.append("tool_end_turn") 
                actions.append("tool_wait")
        return list(dict.fromkeys(actions))
        
    def get_game_state_for_agent(self, player_id: int) -> Dict[str, Any]:
        """Get game state for agent with comprehensive information matching original GameController"""
        if not (0 <= player_id < len(self.players)):
            return {"error": "Invalid player_id"}
            
        player = self.players[player_id]
        if player.is_bankrupt:
            return {"status": "bankrupt", "player_id": player_id, "name": player.name}
            
        # Get current square info
        current_square_name = "Unknown (Off Board?)"
        current_square_type = "Unknown"
        if 0 <= player.position < len(self.board.squares):
            current_square = self.board.get_square(player.position)
            current_square_name = current_square.name
            current_square_type = current_square.square_type.value
        else:
            self.log_event(f"[Warning] Player {player.name} has invalid position: {player.position}")
        
        # Prepare trade-related information for better context
        current_trade_info = None
        recent_trade_offers = []
        
        # If there's a current trade decision, include detailed trade info
        if self.pending_decision_type in ["respond_to_trade_offer", "propose_new_trade_after_rejection"]:
            trade_id = self.pending_decision_context.get("trade_id") or self.pending_decision_context.get("original_trade_id_rejected")
            if trade_id and trade_id in self.trade_offers:
                offer = self.trade_offers[trade_id]
                current_trade_info = {
                    "trade_id": offer.trade_id,
                    "proposer_id": offer.proposer_id,
                    "recipient_id": offer.recipient_id,
                    "status": offer.status,
                    "message": offer.message,
                    "items_offered_by_proposer": [
                        {
                            "item_type": item.item_type,
                            "item_id": item.item_id,
                            "quantity": item.quantity
                        } for item in offer.items_offered_by_proposer
                    ],
                    "items_requested_from_recipient": [
                        {
                            "item_type": item.item_type,
                            "item_id": item.item_id,
                            "quantity": item.quantity
                        } for item in offer.items_requested_from_recipient
                    ]
                }
        
        # Include recent trade offers for context (last 3 trades)
        sorted_trades = sorted(self.trade_offers.values(), key=lambda x: x.trade_id, reverse=True)
        for offer in sorted_trades[:3]:
            if offer.proposer_id == player_id or offer.recipient_id == player_id:
                recent_trade_offers.append({
                    "trade_id": offer.trade_id,
                    "proposer_id": offer.proposer_id,
                    "recipient_id": offer.recipient_id,
                    "status": offer.status,
                    "message": offer.message,
                    "items_offered_by_proposer": [
                        {
                            "item_type": item.item_type,
                            "item_id": item.item_id,
                            "quantity": item.quantity
                        } for item in offer.items_offered_by_proposer
                    ],
                    "items_requested_from_recipient": [
                        {
                            "item_type": item.item_type,
                            "item_id": item.item_id,
                            "quantity": item.quantity
                        } for item in offer.items_requested_from_recipient
                    ]
                })
        
        game_state = {
            "my_player_id": player.player_id,
            "my_name": player.name,
            "my_money": player.money,
            "my_position": player.position,
            "my_position_name": current_square_name,
            "my_properties_owned_ids": sorted(list(player.properties_owned_ids)),
            "my_in_jail": player.in_jail,
            "my_jail_turns_remaining": getattr(player, 'jail_turns_remaining', 0),
            "my_get_out_of_jail_cards": {
                "chance": getattr(player, 'has_chance_gooj_card', False),
                "community_chest": getattr(player, 'has_community_gooj_card', False)
            },
            "current_turn_player_id": self.current_player_index,
            "active_decision_player_id": player_id,
            "pending_decision_type": self.pending_decision_type,
            "pending_decision_context": self.pending_decision_context,
            "dice_roll_outcome_processed": self.dice_roll_outcome_processed,
            "last_dice_roll": self.dice if self.dice != (0,0) else None,
            "current_trade_info": current_trade_info,
            "recent_trade_offers": recent_trade_offers,
            "board_squares": [], 
            "other_players": [],
            "game_log_tail": self.game_log[-20:],
            "turn_count": self.turn_count,
            "game_uid": self.game_uid,
            "game_over": self.game_over,
            "auction_in_progress": self.auction_in_progress,
            "auction_info": {
                "property_id": self.auction_property_id,
                "current_bid": self.auction_current_bid,
                "highest_bidder_id": self.auction_highest_bidder.player_id if self.auction_highest_bidder else None,
                "active_bidders": [p.player_id for p in self.auction_active_bidders] if hasattr(self, 'auction_active_bidders') else []
            } if self.auction_in_progress else None
        }
        
        # Debug log for balance issues
        self.log_event(f"[DEBUG BALANCE] P{player_id} ({player.name}) - Agent sees balance: ${player.money}, TPay ID: {player.agent_tpay_id}", "debug_balance")
        
        # Build board squares information
        for i, square_obj in enumerate(self.board.squares):
            sq_info = {
                "id": i,
                "name": square_obj.name,
                "type": square_obj.square_type.value,
            }
            if isinstance(square_obj, PurchasableSquare):
                sq_info["price"] = square_obj.price
                sq_info["owner_id"] = square_obj.owner_id
                sq_info["is_mortgaged"] = square_obj.is_mortgaged
                sq_info["color_group"] = square_obj.color_group.value if hasattr(square_obj, 'color_group') and square_obj.color_group is not None else None
                if isinstance(square_obj, PropertySquare):
                    sq_info["rent_levels"] = square_obj.rent_levels
                    sq_info["house_price"] = square_obj.house_price
                    sq_info["num_houses"] = square_obj.num_houses
                elif isinstance(square_obj, RailroadSquare):
                    sq_info["base_rent"] = square_obj.base_rent 
                elif isinstance(square_obj, UtilitySquare):
                    pass 
            elif isinstance(square_obj, TaxSquare):
                sq_info["tax_amount"] = square_obj.tax_amount
            game_state["board_squares"].append(sq_info)
            
        # Build other players information
        for p_other in self.players:
            if p_other.player_id != player_id:
                # 🎯 CRITICAL FIX: Include detailed property information for other players
                # This prevents AI agents from guessing property IDs in trades
                other_player_properties = []
                for prop_id in p_other.properties_owned_ids:
                    prop_square = self.board.get_square(prop_id)
                    if isinstance(prop_square, PurchasableSquare):
                        prop_info = {
                            "id": prop_id,
                            "name": prop_square.name,
                            "type": prop_square.square_type.value,
                            "color_group": prop_square.color_group.value if hasattr(prop_square, 'color_group') and prop_square.color_group else None,
                            "is_mortgaged": prop_square.is_mortgaged,
                        }
                        # Add house info for properties
                        if isinstance(prop_square, PropertySquare):
                            prop_info["num_houses"] = prop_square.num_houses
                        other_player_properties.append(prop_info)
                
                other_info = {
                    "player_id": p_other.player_id,
                    "name": p_other.name,
                    "position": p_other.position,
                    "in_jail": p_other.in_jail,
                    "is_bankrupt": p_other.is_bankrupt,
                    "num_properties": len(p_other.properties_owned_ids),
                    "properties_owned": other_player_properties,  # 🎯 NEW: Detailed property information
                }
                game_state["other_players"].append(other_info)
                
        return game_state
        
    def get_board_layout_for_frontend(self) -> List[Dict[str, Any]]:
        """Get board layout for frontend - matching original GameController"""
        layout = []
        for i, square_obj in enumerate(self.board.squares):
            sq_info = {
                "id": i,
                "name": square_obj.name,
                "type": square_obj.square_type.value, 
            }
            if isinstance(square_obj, PurchasableSquare):
                sq_info["price"] = square_obj.price
                sq_info["group_id"] = square_obj.group_id if hasattr(square_obj, 'group_id') else None
                if hasattr(square_obj, 'color_group') and square_obj.color_group:
                     sq_info["color_group"] = square_obj.color_group.value 
                else:
                     sq_info["color_group"] = None
                if isinstance(square_obj, PropertySquare):
                    sq_info["rent_levels"] = square_obj.rent_levels
                    sq_info["house_price"] = square_obj.house_price
                    sq_info["num_houses"] = square_obj.num_houses
                elif isinstance(square_obj, RailroadSquare):
                    sq_info["base_rent"] = square_obj.base_rent 
                elif isinstance(square_obj, UtilitySquare):
                    pass 
            elif isinstance(square_obj, TaxSquare):
                sq_info["tax_amount"] = square_obj.tax_amount
            layout.append(sq_info)
        return layout 

    async def _pass_on_buying_property_action(self, player_id: int, property_id: int) -> Dict[str, Any]:
        """Handle player passing on buying a property (initiate auction)"""
        player = self.players[player_id]
        
        if not (0 <= property_id < len(self.board.squares)):
            msg = f"Invalid property_id {property_id} for pass_on_buying by P{player_id}."
            self.log_event(f"[Error] {msg}")
            if self.pending_decision_type == "buy_or_auction_property" and self.pending_decision_context.get("player_id") == player_id:
                 self._resolve_current_action_segment() 
            return {"status": "error", "message": msg}

        square_to_pass = self.board.get_square(property_id)

        if not (self.pending_decision_type == "buy_or_auction_property" and 
                self.pending_decision_context.get("player_id") == player_id and 
                self.pending_decision_context.get("property_id") == property_id):
            msg = f"_pass_on_buying_property_action called out of context for P{player_id}, Prop{property_id}. Pending: '{self.pending_decision_type}', Ctx: {self.pending_decision_context}"
            self.log_event(f"[Warning] {msg}")
            return {"status": "error", "message": msg}
            
        if not isinstance(square_to_pass, PurchasableSquare):
            msg = f"Property ID {property_id} ({square_to_pass.name}) is not a purchasable square for passing/auctioning."
            self.log_event(f"[Error] {msg}")
            self._resolve_current_action_segment() 
            return {"status": "error", "message": msg}
            
        self.log_event(f"{player.name} passed on buying {square_to_pass.name}. Initiating auction.")
        await self._initiate_auction(square_to_pass.square_id)
        return {"status": "success", "message": f"{player.name} passed on buying {square_to_pass.name}, auction initiated."} 