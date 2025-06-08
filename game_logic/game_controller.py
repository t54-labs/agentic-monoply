from typing import List, Optional, Tuple, Dict, Any
import random
import asyncio # Added for create_task
from dataclasses import dataclass, field

from .board import Board, CardData
from .player import Player
from .property import ActionSquare, BaseSquare, PurchasableSquare, PropertySquare, RailroadSquare, TaxSquare, UtilitySquare, SquareType, PropertyColor

# Import sqlalchemy components for DB interaction within GC methods
from sqlalchemy import insert, select, update # Added update
from sqlalchemy.orm import Session # if using session per operation
from database import engine, games_table, players_table, game_turns_table # agent_actions_table later
import json # For serializing game_state
import datetime # For timestamps

MAX_TRADE_REJECTIONS = 5 # Define at module level or as a class attribute

@dataclass
class TradeOfferItem:
    item_type: str # "property", "money", "get_out_of_jail_card"
    item_id: Optional[int] = None # property_id if item_type is property
    quantity: int = 0 # money amount, or 1 for property/card
    # card_type: Optional[str] = None # "chance" or "community_chest" if item_type is card - can be part of context or a different structure

@dataclass
class TradeOffer:
    trade_id: int # Unique ID for the trade offer
    proposer_id: int
    recipient_id: int
    items_offered_by_proposer: List[TradeOfferItem] = field(default_factory=list)
    items_requested_from_recipient: List[TradeOfferItem] = field(default_factory=list)
    status: str = "pending_response" # pending_response, accepted, rejected, countered, withdrawn
    counter_offer_to_trade_id: Optional[int] = None # If this is a counter to a previous offer
    turn_proposed: int = 0 # Game turn number when proposed
    message: Optional[str] = None  # New: Message from proposer
    rejection_count: int = 0       # New: Tracks rejections for this specific offer iteration

class GameController:
    def __init__(self, game_uid: str = "default_game", ws_manager: Optional[Any] = None,
                 game_db_id: Optional[int] = None, participants: Optional[List[Dict[str, Any]]] = None
                 ):
        
        self.game_uid = game_uid 
        self.ws_manager = ws_manager 
        self.game_db_id = game_db_id 
        self.current_game_turn_db_id: Optional[int] = None 
        
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError: 
            print(f"[GC Init Warning G:{self.game_uid}] No asyncio event loop currently running. Attempting to get/create a new one. Websocket communication from threads may fail if not managed correctly.")
            self.loop = asyncio.new_event_loop() 

        self.game_log: List[str] = [] 
        self.turn_count: int = 0

        self.board: Board = Board()
        self.players: List[Player] = [] 
        self._initialize_players(participants) 

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
        self._clear_pending_decision()
        self.log_event(f"Game Controller for G_UID:{self.game_uid} (DB_ID:{self.game_db_id}) initialized.")

    async def send_event_to_frontend(self, message_data: Dict[str, Any]):
        if self.ws_manager:
            if "game_id" not in message_data:
                message_data["game_id"] = self.game_uid
            await self.ws_manager.broadcast_to_game(self.game_uid, message_data)

    def log_event(self, event_message: str, event_type: str = "game_log_event") -> None:
        print(f"G_UID:{self.game_uid} - T{self.turn_count} - P{self.current_player_index if hasattr(self, 'current_player_index') else 'N/A'}: {event_message}") 
        self.game_log.append(event_message)
        if self.ws_manager:
            message_to_send = {"type": event_type, "message": event_message, "game_uid": self.game_uid, "turn": self.turn_count}
            if hasattr(self, 'loop') and self.loop and self.loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(self.send_event_to_frontend(message_to_send), self.loop)
                except Exception as e: 
                    print(f"[WS Send Error G:{self.game_uid}] Failed to schedule send_event_to_frontend via run_coroutine_threadsafe: {e} - Msg: {event_message}")
            else:
                print(f"[WS Send Critical G:{self.game_uid}] No running event loop available in GC.log_event for threadsafe call. WS message for '{event_message}' will NOT be sent.")
    
    def _initialize_players(self, participants: Optional[List[Dict[str, Any]]] = None) -> None:
        for i in range(len(participants)):
            name = participants[i]['name']
            agent_uid = participants[i]['agent_uid']
            agent_tpay_id = participants[i]['agent_tpay_id']
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
        return self.players[self.current_player_index]

    def start_game(self, 
                   all_players_start_in_jail_test_mode: bool = False, 
                   test_mode_trade_details: Optional[Dict[str, Any]] = None, # For initiating a trade
                   test_mode_auction_property_id: Optional[int] = None    # For initiating an auction
                   ) -> None: 
        self.log_event(f"GameController.start_game() called. JailTest: {all_players_start_in_jail_test_mode}, TradeTest: {test_mode_trade_details is not None}, AuctionTest: {test_mode_auction_property_id is not None}", "method_trace")
        
        if not self.players:
            self.log_event("[Error] No players initialized. Cannot start game.", "error_log"); self.game_over = True; return
        
        # Set starting player - for trade test mode, ensure proposer goes first
        if test_mode_trade_details:
            proposer_id = test_mode_trade_details.get("proposer_id", 0)
            if isinstance(proposer_id, int) and 0 <= proposer_id < len(self.players):
                self.current_player_index = proposer_id
                self.log_event(f"Trade Test Mode: Proposer P{proposer_id} ({self.players[proposer_id].name}) will start first.", "debug_test")
            else:
                self.current_player_index = random.randrange(len(self.players))
        else:
            self.current_player_index = random.randrange(len(self.players))
            
        self.turn_count = 1 
        self.game_over = False
        self.log_event(f"Game G_UID:{self.game_uid} starting. Player {self.players[self.current_player_index].name} (P{self.current_player_index}) goes first. Turn: {self.turn_count}.")

        if test_mode_trade_details:
            self.log_event(f"!!! TRADE TEST MODE: Setting up trade: {test_mode_trade_details} !!!", "warning_log")
            proposer_id = test_mode_trade_details.get("proposer_id")
            recipient_id = test_mode_trade_details.get("recipient_id")
            offered_prop_ids = test_mode_trade_details.get("offered_property_ids", [])
            requested_prop_ids = test_mode_trade_details.get("requested_property_ids", [])
            trade_message = test_mode_trade_details.get("message") # Get the message for the trade

            if not (isinstance(proposer_id, int) and 0 <= proposer_id < len(self.players) and 
                    isinstance(recipient_id, int) and 0 <= recipient_id < len(self.players)):
                self.log_event("[Error TradeTest] Invalid proposer or recipient ID.", "error_log"); return
            
            proposer = self.players[proposer_id]
            recipient = self.players[recipient_id]

            # Manually assign properties for testing if they don't own them
            # This is a simplified assignment for test setup.
            for prop_id in offered_prop_ids:
                if prop_id not in proposer.properties_owned_ids:
                    square = self.board.get_square(prop_id)
                    if isinstance(square, PurchasableSquare) and square.owner_id is None:
                        square.owner_id = proposer_id
                        proposer.add_property_id(prop_id)
                        self.log_event(f"TestMode: Assigned property {prop_id} ({square.name}) to proposer {proposer.name}", "debug_test")
                    elif isinstance(square, PurchasableSquare) and square.owner_id != proposer_id: # Forcefully reassign for test
                        old_owner_id = square.owner_id
                        if old_owner_id is not None: self.players[old_owner_id].remove_property_id(prop_id)
                        square.owner_id = proposer_id
                        proposer.add_property_id(prop_id)
                        self.log_event(f"TestMode: Re-Assigned property {prop_id} from P{old_owner_id} to proposer {proposer.name}", "debug_test")
            
            for prop_id in requested_prop_ids:
                if prop_id not in recipient.properties_owned_ids:
                    square = self.board.get_square(prop_id)
                    if isinstance(square, PurchasableSquare) and square.owner_id is None:
                        square.owner_id = recipient_id
                        recipient.add_property_id(prop_id)
                        self.log_event(f"TestMode: Assigned property {prop_id} ({square.name}) to recipient {recipient.name}", "debug_test")
                    elif isinstance(square, PurchasableSquare) and square.owner_id != recipient_id:
                        old_owner_id = square.owner_id
                        if old_owner_id is not None: self.players[old_owner_id].remove_property_id(prop_id)
                        square.owner_id = recipient_id
                        recipient.add_property_id(prop_id)
                        self.log_event(f"TestMode: Re-Assigned property {prop_id} from P{old_owner_id} to recipient {recipient.name}", "debug_test")

            # Propose the trade
            # The current_player_index is already set randomly. For a trade test, the proposer might not be current_player_index.
            # The propose_trade_action sets the pending decision for the RECIPIENT.
            self.propose_trade_action(
                proposer_id, recipient_id, 
                offered_prop_ids, 
                test_mode_trade_details.get("offered_money", 0),
                test_mode_trade_details.get("offered_gooj_cards", 0),
                requested_prop_ids,
                test_mode_trade_details.get("requested_money", 0),
                test_mode_trade_details.get("requested_gooj_cards", 0),
                message=trade_message  # Pass the retrieved message here
            )
            # The game will proceed with recipient_id needing to respond to the trade offer.
            # The server loop will pick up active_player_id based on pending_decision_context["player_id"]
            self.log_event(f"TestMode: Trade proposed from P{proposer_id} to P{recipient_id}. Pending decision for P{recipient_id}.", "debug_test")
            # Ensure dice_roll_outcome_processed is true so recipient can act without rolling
            self.dice_roll_outcome_processed = True
        
        elif all_players_start_in_jail_test_mode: # Moved this after trade test for priority
            # ... (jail test mode logic as before) ...
            self.log_event("!!! JAIL TEST MODE: All players start in JAIL. !!!", "warning_log")
            for i, player in enumerate(self.players):
                player.go_to_jail(); player.jail_turns_remaining = 0 
                self.log_event(f"TestMode: Player {player.name} (P{i}) sent to jail.", "debug_test")
            first_player_for_jail_options = self.get_current_player()
            if first_player_for_jail_options.in_jail: self._handle_jail_turn_initiation(first_player_for_jail_options)

        elif test_mode_auction_property_id is not None:
            self.log_event(f"!!! AUCTION TEST MODE: Initiating auction for property ID: {test_mode_auction_property_id} !!!", "warning_log")
            prop_to_auction = self.board.get_square(test_mode_auction_property_id)
            if isinstance(prop_to_auction, PurchasableSquare) and prop_to_auction.owner_id is None:
                self._initiate_auction(test_mode_auction_property_id)
                self.log_event(f"TestMode: Auction initiated for {prop_to_auction.name}. Pending decision for first bidder.", "debug_test")
            else:
                self.log_event(f"[Error AuctionTest] Property {test_mode_auction_property_id} is not unowned or not purchasable.", "error_log")
                # Fallback to normal start if auction setup fails
                self._clear_pending_decision(); self.dice_roll_outcome_processed = True 
        
        # --- End Test Mode Setups ---
        
        if self.game_db_id is not None: 
             self.log_event("Attempting to save initial turn snapshot in start_game.", "db_trace")
             self.current_game_turn_db_id = self._save_game_turn_snapshot(self.current_player_index)
             self.log_event(f"Initial turn snapshot saved. TurnDBID: {self.current_game_turn_db_id}.", "db_trace")
        else:
            self.log_event("game_db_id is None, skipping initial turn snapshot.", "db_warning")
        
        board_layout_data = self.get_board_layout_for_frontend()
        if self.ws_manager:
            message_to_send = {"type": "initial_board_layout", "data": board_layout_data}
            if hasattr(self, 'loop') and self.loop and self.loop.is_running():
                try: asyncio.run_coroutine_threadsafe(self.send_event_to_frontend(message_to_send), self.loop)
                except Exception as e: print(f"[WS Send Error G:{self.game_uid}] Failed to schedule initial_board_layout: {e}")
            else:
                try: asyncio.create_task(self.send_event_to_frontend(message_to_send))
                except RuntimeError as e: print(f"[WS Send Error G:{self.game_uid}] Failed to create_task for initial_board_layout: {e}")
            self.log_event(f"Sent initial_board_layout to frontend ({len(board_layout_data)} squares).", "debug_event_send")

        # If not in a specific test mode that sets a pending decision, proceed with normal start-of-turn checks for the first player.
        if not all_players_start_in_jail_test_mode and not test_mode_trade_details and not test_mode_auction_property_id:
            current_starting_player = self.get_current_player()
            if current_starting_player.in_jail:
                 self._handle_jail_turn_initiation(current_starting_player)
            elif current_starting_player.pending_mortgaged_properties_to_handle:
                 self._handle_received_mortgaged_property_initiation(current_starting_player)
            else: # Normal start, no specific pending decision from game setup
                self._clear_pending_decision() # Corrected: Indented under else
                self.dice_roll_outcome_processed = True # Corrected: Indented under else
        
        self.log_event(f"GameController.start_game() finished. Game Over: {self.game_over}", "method_trace")

    def roll_dice(self) -> Tuple[int, int]:
        current_player = self.get_current_player()
        if current_player.in_jail: # Should call specific jail roll tool
            self.log_event(f"[Warning] roll_dice called for player in jail. Use jail-specific roll tool.")
            # This roll should not count as main turn roll if it's for getting out of jail.
            # Let's assume _attempt_roll_out_of_jail handles its own dice rolling.
            # For now, if this happens, treat as an invalid action, agent should use correct tool.
            # Or, this function could route to jail roll if player.in_jail - but tools are better for explicitness
            # For this iteration, we assume the main loop directs to the correct jail tool.
            # Thus, a direct call to `roll_dice` means it's for a normal turn segment.
            pass # Or raise an error if state is inconsistent

        self.dice = (random.randint(1, 6), random.randint(1, 6))
        self.log_event(f"{current_player.name} rolled {self.dice[0]} and {self.dice[1]}.")
        self.dice_roll_outcome_processed = False # Dice rolled, outcome needs processing (move, land)
        
        if self.is_double_roll():
            self.doubles_streak += 1
            self.log_event(f"Doubles! Streak: {self.doubles_streak}")
            if self.doubles_streak == 3:
                self.log_event(f"{current_player.name} rolled doubles 3 times in a row. Go to Jail!")
                self._handle_go_to_jail_landing(current_player) # This also sets player.in_jail
                # Turn ends immediately after going to jail this way
                # self.next_turn() # Or signal that turn ends
                return self.dice # Return dice, but turn should end. Controller loop will handle this.
        else:
            self.doubles_streak = 0
        return self.dice
    
    def is_double_roll(self) -> bool:
        return self.dice[0] == self.dice[1]

    def _handle_go_passed(self, player: Player) -> None:
        player.add_money(200) # Standard GO salary
        self.log_event(f"{player.name} passed GO and collected $200.")

    def _move_player(self, player: Player, steps: int) -> None:
        if player.is_bankrupt:
            self.dice_roll_outcome_processed = True # Bankrupt player's "roll" is processed, no action
            self._clear_pending_decision()
            return

        current_pos = player.position
        old_pos = current_pos # For logging and GO comparison if needed
        new_pos = (current_pos + steps) % len(self.board.squares)
        self.dice_roll_outcome_processed = False # Movement initiated, landing outcome pending
        self._clear_pending_decision() # Clear any prior decision before new landing occurs

        if steps > 0 and new_pos < old_pos : # Player passed GO by moving forward
            self._handle_go_passed(player)
        # Note: Moving backward over GO does not grant salary.
        # Cards that say "Advance to GO (Collect $200)" handle salary separately.

        player.position = new_pos
        self.log_event(f"{player.name} moved from square {old_pos} ({self.board.get_square(old_pos).name}) to {player.position} ({self.board.get_square(player.position).name}).")
        self.land_on_square(player) # This will handle setting new pending_decision or dice_roll_outcome_processed = True

    def land_on_square(self, player: Player) -> None:
        if player.is_bankrupt:
            self.dice_roll_outcome_processed = True
            self._clear_pending_decision()
            return
        
        square = self.board.get_square(player.position)
        self.log_event(f"{player.name} landed on {square.name}.")
        self._clear_pending_decision() # Clear previous before specific handler potentially sets a new one.

        if isinstance(square, PropertySquare) or isinstance(square, RailroadSquare) or isinstance(square, UtilitySquare):
            self._handle_property_landing(player, square) # This will set pending_decision or resolve outcome
        elif isinstance(square, ActionSquare):
            self._handle_action_square_landing(player, square) # This will set pending_decision or resolve outcome
        elif isinstance(square, TaxSquare):
            self._handle_tax_square_landing(player, square) # This will set pending_decision or resolve outcome
        elif square.square_type == SquareType.GO_TO_JAIL:
            self._handle_go_to_jail_landing(player) # Resolves outcome for this landing
        elif square.square_type in [SquareType.GO, SquareType.JAIL_VISITING, SquareType.FREE_PARKING]:
            self._handle_special_square_landing(player, square) # Resolves outcome for this landing
        else:
            self.log_event(f"Landed on {square.name} - no specific action. Outcome processed.")
            self.dice_roll_outcome_processed = True
            self._clear_pending_decision()

    def _handle_property_landing(self, player: Player, square: PurchasableSquare) -> None:
        self.log_event(f"Handling property landing: {square.name} for {player.name}")
        card_forced_action = self.pending_decision_context.pop("card_forced_action", None)

        if square.owner_id is None:
            self.log_event(f"{square.name} is unowned. Price: ${square.price}")
            # Decision to buy/auction is pending, dice roll outcome is NOT yet fully processed.
            self._set_pending_decision("buy_or_auction_property", 
                                     context={"property_id": square.square_id, "player_id": player.player_id}, 
                                     outcome_processed=False) 
        elif square.owner_id == player.player_id:
            self.log_event(f"{player.name} landed on their own property: {square.name}.")
            self._resolve_current_action_segment() # Landing action resolved, no further decision here
        elif square.owner_id is not None and not square.is_mortgaged:
            owner = self.players[square.owner_id]
            rent_amount = 0
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
                self._player_pays_amount(player, rent_amount, f"rent for {square.name}", recipient=owner)
            else:
                self.log_event(f"No rent due for {square.name}.")
                self._resolve_current_action_segment()

            # If _player_pays_amount did not set a new pending_decision (e.g., asset_liquidation_for_debt)
            # then the outcome of this landing (rent payment) is processed.
            if self.pending_decision_type is None:
                self._resolve_current_action_segment()

        elif square.is_mortgaged:
            self.log_event(f"{square.name} is mortgaged by Player {square.owner_id}. No rent due.")
            self._resolve_current_action_segment()

    def _handle_action_square_landing(self, player: Player, action_sq: ActionSquare) -> None:
        card = None
        if action_sq.square_type == SquareType.COMMUNITY_CHEST:
            card = self.board.draw_community_chest_card()
            self.log_event(f"{player.name} drew a Community Chest card: {card[0]}")
        elif action_sq.square_type == SquareType.CHANCE:
            card = self.board.draw_chance_card()
            self.log_event(f"{player.name} drew a Chance card: {card[0]}")
        
        if card:
            self._handle_card_effect(player, card)
        else:
            self.log_event(f"[Error] Landed on ActionSquare {action_sq.name} but no card drawn.")
            self._resolve_current_action_segment()

    def _handle_tax_square_landing(self, player: Player, tax_sq: TaxSquare) -> None:
        amount_due = tax_sq.tax_amount
        self.log_event(f"{player.name} has to pay ${amount_due} for {tax_sq.name}.")
        self._player_pays_amount(player, amount_due, f"tax for {tax_sq.name}")
        # If _player_pays_amount resulted in successful payment without triggering bankruptcy flow (which sets its own pending decision):
        if player.money >= 0 and self.pending_decision_type is None:
            self._resolve_current_action_segment()

    def _handle_go_to_jail_landing(self, player: Player) -> None:
        self.log_event(f"{player.name} is going to jail!")
        player.go_to_jail()
        self.doubles_streak = 0 
        self._resolve_current_action_segment() # Going to jail is a resolved outcome for the landing action.
                                      # Jail options are handled at the start of the *next* turn for the player.

    def _handle_special_square_landing(self, player: Player, special_sq: BaseSquare) -> None:
        if special_sq.square_type == SquareType.GO:
            self.log_event(f"{player.name} landed on GO. (Salary already handled if passed).")
        elif special_sq.square_type == SquareType.JAIL_VISITING:
            if player.in_jail:
                self.log_event(f"{player.name} is in Jail.")
            else:
                self.log_event(f"{player.name} is Just Visiting Jail.")
        elif special_sq.square_type == SquareType.FREE_PARKING:
            self.log_event(f"{player.name} landed on Free Parking. Nothing happens (standard rules).")
            # House rules for collecting fines at Free Parking are not implemented by default.
        self._resolve_current_action_segment()

    def _handle_card_effect(self, player: Player, card: CardData) -> None:
        description, action_type, value = card
        self.log_event(f"Card effect for {player.name}: {description} (Action: {action_type}, Value: {value})")
        self._clear_pending_decision()
        self.dice_roll_outcome_processed = False

        # --- Simple Effects (resolve immediately) ---
        if action_type == "receive_money":
            player.add_money(value)
            self.log_event(f"{player.name} received ${value}.")
            self._resolve_current_action_segment()
        elif action_type == "get_out_of_jail_card":
            card_type_str = value if isinstance(value, str) else "unknown" 
            if value == "community_chest": player.add_get_out_of_jail_card("community_chest")
            elif value == "chance": player.add_get_out_of_jail_card("chance")
            self.log_event(f"{player.name} received a Get Out of Jail Free card ({card_type_str}).")
            self._resolve_current_action_segment()
        
        # --- Effects involving Payment (might lead to bankruptcy decision) ---
        elif action_type == "pay_money":
            self._player_pays_amount(player, value, description)
            # State (pending_decision, dice_roll_outcome_processed) is handled by _player_pays_amount or subsequent bankruptcy flow.
        elif action_type == "street_repairs":
            house_cost, hotel_cost = value 
            total_repair_cost = sum(
                hotel_cost if isinstance(sq := self.board.get_square(prop_id), PropertySquare) and sq.num_houses == 5 
                else (sq.num_houses * house_cost if isinstance(sq, PropertySquare) else 0) 
                for prop_id in player.properties_owned_ids
            )
            if total_repair_cost > 0:
                self.log_event(f"{player.name} needs to pay ${total_repair_cost} for street repairs.")
                self._player_pays_amount(player, total_repair_cost, "street repairs")
            else:
                self.log_event(f"{player.name} has no properties with buildings for street repairs.")
                self._resolve_current_action_segment()
        elif action_type == "receive_from_players":
            amount_each = value
            for other_player in self.players:
                if other_player != player and not other_player.is_bankrupt:
                    other_player.subtract_money(amount_each) 
                    player.add_money(amount_each)
                    self.log_event(f"{other_player.name} paid ${amount_each} to {player.name}.")
                    if other_player.money < 0:
                        self.log_event(f"[Warning] {other_player.name} (ID: {other_player.player_id}) now has negative money due to 'receive_from_players' card. Bankruptcy will be checked on their turn.")
            self._resolve_current_action_segment()
        elif action_type == "pay_players":
            amount_each = value
            all_paid_successfully_without_bankruptcy = True
            for other_player in self.players:
                if other_player != player and not other_player.is_bankrupt:
                    self.log_event(f"{player.name} owes ${amount_each} to {other_player.name}.")
                    self._player_pays_amount(player, amount_each, f"payment to {other_player.name}", recipient=other_player)
                    if player.is_bankrupt: 
                        all_paid_successfully_without_bankruptcy = False
                        break 
            if all_paid_successfully_without_bankruptcy and not player.is_bankrupt:
                self._resolve_current_action_segment()
            # If bankruptcy, pending_decision is set by _check_and_handle_bankruptcy.

        # --- Effects involving Movement (these will call land_on_square, which sets final state) ---
        elif action_type == "move_to_exact":
            current_pos = player.position; target_pos = value
            self._move_player_directly_to_square(player, target_pos, collect_go_salary_if_passed=(target_pos == 0 and current_pos != 0))
        elif action_type == "move_to_exact_with_go_check":
            current_pos = player.position; target_pos = value
            self._move_player_directly_to_square(player, target_pos, collect_go_salary_if_passed=((target_pos < current_pos and target_pos != 0) or (target_pos == 0 and current_pos != 0)))
        elif action_type == "move_relative":
            self._move_player(player, value)
        elif action_type == "go_to_jail":
            self._handle_go_to_jail_landing(player) # This calls _resolve_current_action_segment()
        elif action_type == "advance_to_nearest" or action_type == "advance_to_nearest_railroad_pay_double":
            target_type_str = value if action_type == "advance_to_nearest" else "railroad"
            target_square_type = SquareType.UTILITY if target_type_str == "utility" else SquareType.RAILROAD
            nearest_square_id = -1; current_pos = player.position
            for i in range(1, len(self.board.squares) + 1):
                prospective_sq_id = (current_pos + i) % len(self.board.squares)
                if self.board.get_square(prospective_sq_id).square_type == target_square_type:
                    nearest_square_id = prospective_sq_id; break
            if nearest_square_id != -1:
                self.log_event(f"Card: Advancing {player.name} to nearest {target_type_str}: {self.board.get_square(nearest_square_id).name}.")
                # Clear any old card_forced_action before setting a new one
                self.pending_decision_context.pop("card_forced_action", None)
                if action_type == "advance_to_nearest_railroad_pay_double":
                    self.pending_decision_context["card_forced_action"] = "pay_double_railroad_rent"
                elif target_square_type == SquareType.UTILITY:
                    self.pending_decision_context["card_forced_action"] = "pay_10x_dice_utility_rent"
                self._move_player_directly_to_square(player, nearest_square_id, collect_go_salary_if_passed=(nearest_square_id < current_pos and nearest_square_id != 0))
            else:
                self.log_event(f"[Error] Card: Could not find nearest {target_type_str} for {player.name}.")
                self._resolve_current_action_segment()
        else:
            self.log_event(f"[Warning] Card action_type '{action_type}' has no explicit state update logic in _handle_card_effect. Resolving segment.")
            self._resolve_current_action_segment()

    def _attempt_roll_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        player = self.players[player_id]
        if not player.in_jail:
            msg = f"{player.name} is not in jail. Cannot roll for doubles to get out."
            self.log_event(f"[Warning] {msg}")
            if self.pending_decision_type == "jail_options" and self.pending_decision_context.get("player_id") == player_id:
                self._resolve_current_action_segment()
            return {"status": "error", "message": msg, "dice_roll": self.dice, "got_out": True}

        if player.jail_turns_remaining >= 3:
            msg = f"{player.name} has already had 3 attempts to roll for doubles this jail term."
            self.log_event(f"[Warning] {msg}")
            self._set_pending_decision("jail_options", context={"player_id": player.player_id, "max_rolls_attempted": True, "jail_turns_attempted_this_incarceration": player.jail_turns_remaining}, outcome_processed=True)
            return {"status": "error", "message": msg, "dice_roll": self.dice , "got_out": False}
        
        local_dice = (random.randint(1, 6), random.randint(1, 6))
        self.dice = local_dice 
        player.attempt_to_get_out_of_jail() 
        self.log_event(f"{player.name} (in jail, attempt {player.jail_turns_remaining}) rolls {local_dice} for doubles.")

        if local_dice[0] == local_dice[1]:
            self.log_event(f"{player.name} rolled doubles {self.dice} and got out of jail!")
            player.leave_jail()
            self.doubles_streak = 0 
            self._set_pending_decision(None, outcome_processed=False) 
            self._move_player(player, sum(self.dice)) 
            return {"status": "success", "message": f"Rolled doubles {self.dice} and got out of jail.", "dice_roll": self.dice, "got_out": True}
        else:
            self.log_event(f"{player.name} did not roll doubles ({self.dice}). Stays in jail.")
            max_rolls_attempted_after_this = player.jail_turns_remaining >= 3
            self._set_pending_decision("jail_options", 
                                     context={"player_id": player.player_id, 
                                              "roll_failed": True, 
                                              "last_roll_dice": list(self.dice), 
                                              "jail_turns_attempted_this_incarceration": player.jail_turns_remaining,
                                              "max_rolls_attempted": max_rolls_attempted_after_this},
                                     outcome_processed=True)
            return {"status": "success", "message": f"Did not roll doubles. Dice: {self.dice}.", "dice_roll": self.dice, "got_out": False}

    def _check_and_handle_bankruptcy(self, player: Player, debt_to_creditor: int = 0, creditor: Optional[Player] = None) -> None:
        if player.is_bankrupt or player.money >=0:
            if player.money >=0 and self.pending_decision_type == "asset_liquidation_for_debt":
                 self.log_event(f"{player.name} successfully liquidated assets to cover debts. Money: ${player.money}")
                 self._resolve_current_action_segment()
            return

        self.log_event(f"ALERT: {player.name} has negative money (${player.money}). Current debt transaction: ${debt_to_creditor} to {creditor.name if creditor else 'Bank'}. ")
        # Set pending decision for asset liquidation. dice_roll_outcome_processed = True because this is a financial state, not dice result.
        self._set_pending_decision("asset_liquidation_for_debt", 
                                 context={"player_id": player.player_id, "debt_amount": -player.money, "original_transaction_debt": debt_to_creditor, "creditor_id": creditor.player_id if creditor else None}, 
                                 outcome_processed=True)

    def confirm_asset_liquidation_done(self, player_id: int) -> None:
        player = self.players[player_id]
        if self.pending_decision_type == "asset_liquidation_for_debt" and self.pending_decision_context.get("player_id") == player_id:
            if player.money < 0:
                self.log_event(f"{player.name} confirmed done with liquidation but still has negative money (${player.money}). Proceeding to declare bankruptcy.")
                creditor_id = self.pending_decision_context.get("creditor_id")
                creditor = self.players[creditor_id] if creditor_id is not None and 0 <= creditor_id < len(self.players) else None
                self._finalize_bankruptcy_declaration(player, creditor) 
                # _finalize_bankruptcy_declaration now calls _resolve_current_action_segment()
            else:
                self.log_event(f"{player.name} successfully liquidated assets after being prompted. Money: ${player.money}.")
                self._resolve_current_action_segment()
        else:
            self.log_event(f"[Warning] confirm_asset_liquidation_done called out of context for {player.name}")

    def _finalize_bankruptcy_declaration(self, player:Player, creditor: Optional[Player]) -> None:
        if not player.is_bankrupt: 
            player.declare_bankrupt()
            self.game_log.append(f"=== {player.name} IS BANKRUPT! === ")
            assets_transferred_to = "the Bank" if creditor is None else creditor.name
            self.log_event(f"Transferring all assets from {player.name} to {assets_transferred_to}.")
            
            if player.has_chance_gooj_card:
                if creditor: creditor.add_get_out_of_jail_card("chance")
                player.has_chance_gooj_card = False
            if player.has_community_gooj_card:
                if creditor: creditor.add_get_out_of_jail_card("community_chest")
                player.has_community_gooj_card = False
            
            properties_to_transfer_ids = list(player.properties_owned_ids)
            for prop_id in properties_to_transfer_ids:
                square = self.board.get_square(prop_id)
                if isinstance(square, PurchasableSquare):
                    player.remove_property_id(prop_id)
                    if creditor:
                        square.owner_id = creditor.player_id
                        creditor.add_property_id(prop_id)
                        if square.is_mortgaged:
                            creditor.add_pending_mortgaged_property_task(prop_id, None) 
                            self.log_event(f"{creditor.name} received mortgaged {square.name} from bankrupt {player.name}. Will need to handle it.")
                    else: 
                        square.owner_id = None; square.is_mortgaged = False
                        if isinstance(square, PropertySquare): square.num_houses = 0
                        self.log_event(f"{square.name} returns to bank, unmortgaged, buildings removed.")
            player.money = 0 
            self._resolve_current_action_segment() 
            self._check_for_game_over_condition()

    def next_turn(self) -> None:
        current_p_whose_turn_ended = self.get_current_player()
        self.log_event(f"Ending turn processing for {current_p_whose_turn_ended.name}. Doubles streak before reset: {self.doubles_streak}")
        self.doubles_streak = 0 
        
        original_player_index = self.current_player_index
        active_players_count = sum(1 for p in self.players if not p.is_bankrupt)
        
        if active_players_count <= 1:
            is_current_player_sole_survivor = (active_players_count == 1 and not current_p_whose_turn_ended.is_bankrupt)
            if active_players_count == 0 or is_current_player_sole_survivor:
                self.game_over = True
                self.log_event(f"Game over condition met (active players: {active_players_count}). Winner determined: {current_p_whose_turn_ended.name if is_current_player_sole_survivor else 'None'}")
                self._resolve_current_action_segment() 
                return

        next_player_found = False
        for _ in range(len(self.players)):
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
            if not self.players[self.current_player_index].is_bankrupt:
                next_player_found = True
                break
        
        if not next_player_found: 
            self.log_event("No active player found to start next turn. Game should be over.")
            self.game_over = True
            self._resolve_current_action_segment()
            return
        
        # ----- Turn Count Increment and DB Snapshot ----- START
        self.turn_count += 1 
        self.log_event(f"DB: Preparing to save turn snapshot for Turn {self.turn_count}, PIdx {self.current_player_index}", "db_trace")
        self.current_game_turn_db_id = self._save_game_turn_snapshot(self.current_player_index)
        if self.current_game_turn_db_id is not None:
            self.log_event(f"DB: Turn snapshot saved (TurnDBID:{self.current_game_turn_db_id}) for T:{self.turn_count}, PIdx:{self.current_player_index}", "db_trace")
        else:
            self.log_event(f"[Warning DB] Failed to save turn snapshot for T:{self.turn_count}, PIdx:{self.current_player_index}", "db_warning")
        # ----- Turn Count Increment and DB Snapshot ----- END

        self._clear_pending_decision() 
        self.dice_roll_outcome_processed = True 
        self.dice = (0,0) 
        
        new_main_turn_player = self.get_current_player()
        self.log_event(f"--- Player {new_main_turn_player.name}'s (P{new_main_turn_player.player_id}) turn begins (Turn {self.turn_count}) ---")

        if new_main_turn_player.pending_mortgaged_properties_to_handle:
            self._handle_received_mortgaged_property_initiation(new_main_turn_player)
        elif new_main_turn_player.in_jail:
            self._handle_jail_turn_initiation(new_main_turn_player)
        self._check_for_game_over_condition() 

    def _clear_pending_decision(self) -> None:
        self.pending_decision_type = None
        self.pending_decision_context = {}

    def _set_pending_decision(self, decision_type: str, context: Optional[Dict[str, Any]] = None, outcome_processed: bool = False) -> None:
        """Helper to set a new pending decision and manage dice_roll_outcome_processed consistently."""
        self.pending_decision_type = decision_type
        self.pending_decision_context = context if context is not None else {}
        self.dice_roll_outcome_processed = outcome_processed
        self.log_event(f"[State Update] Pending Decision: {self.pending_decision_type}, Context: {self.pending_decision_context}, Dice Outcome Processed: {self.dice_roll_outcome_processed}")

    def _resolve_current_action_segment(self) -> None:
        """Called when a sequence of actions or a dice roll's consequences are fully resolved, and no new specific decision is immediately pending."""
        self._clear_pending_decision()
        self.dice_roll_outcome_processed = True
        self.log_event(f"[State Update] Action segment resolved. Pending Decision: None, Dice Outcome Processed: True")
        if not self.game_over: 
            self._check_for_game_over_condition()

    def _check_for_game_over_condition(self) -> None:
        if self.game_over: # If already marked as over, do nothing further
            return

        active_players = [p for p in self.players if not p.is_bankrupt]
        if len(active_players) <= 1:
            self.game_over = True
            winner_name = active_players[0].name if active_players else "No one (draw or error)"
            self.log_event(f"GAME OVER! Winner: {winner_name}")
            # If game over is determined here, and there was a pending decision or 
            # dice roll outcome was not processed, it implies the game ended mid-action.
            # We should still resolve the segment to clear any pending state.
            if self.pending_decision_type is not None or not self.dice_roll_outcome_processed:
                 self.log_event(f"Resolving segment due to game over triggered by _check_for_game_over_condition. Pending: {self.pending_decision_type}, DiceDone: {self.dice_roll_outcome_processed}")
                 # Directly clear pending decision and set dice outcome processed
                 # to avoid potential recursive calls if _resolve_current_action_segment also calls this.
                 self._clear_pending_decision()
                 self.dice_roll_outcome_processed = True
        
        # Note: MAX_TURNS check is primarily handled by the server.py loop.
        # If GameController were to enforce its own MAX_TURNS, that logic could also go here,
        # but it would need access to MAX_TURNS (e.g., passed in __init__ or imported).

    def _player_pays_amount(self, player: Player, amount: int, reason: str, recipient: Optional[Player] = None) -> None:
        """Helper function for player to pay a certain amount, optionally to a recipient."""
        original_money = player.money
        self.log_event(f"{player.name} must pay ${amount} for {reason}.")
        
        can_pay_fully = original_money >= amount
        amount_to_pay_from_cash = amount

        if can_pay_fully:
            player.subtract_money(amount_to_pay_from_cash)
            if recipient:
                recipient.add_money(amount_to_pay_from_cash)
            self.log_event(f"{player.name} paid ${amount_to_pay_from_cash}. Money left: ${player.money}")
            # If payment was successful and no *other* specific decision was set by the caller of this method,
            # this payment itself resolves the immediate financial action.
            if self.pending_decision_type is None: # Check if the caller expects to set a decision after this.
                 self._resolve_current_action_segment() 
        else:
            amount_player_had = original_money if original_money > 0 else 0
            player.subtract_money(amount_to_pay_from_cash) 
            if recipient:
                recipient.add_money(amount_player_had) 
                self.log_event(f"{player.name} paid their available ${amount_player_had} to {recipient.name} for {reason}. Still owes ${amount_to_pay_from_cash - amount_player_had}.")
            else: 
                self.log_event(f"{player.name} paid their available ${amount_player_had} to the bank for {reason}. Still owes ${amount_to_pay_from_cash - amount_player_had}.")
            self.log_event(f"{player.name} is now at ${player.money}.")
            self._check_and_handle_bankruptcy(player, debt_to_creditor=(amount_to_pay_from_cash - amount_player_had), creditor=recipient)
            # _check_and_handle_bankruptcy will set pending_decision_type = "asset_liquidation_for_debt"
            # and dice_roll_outcome_processed = True (because a new, non-dice action is now pending).

    def _move_player_directly_to_square(self, player: Player, target_pos: int, collect_go_salary_if_passed: bool = False) -> None:
        """Moves player directly to a square, handles GO if applicable, and then triggers landing effects."""
        if player.is_bankrupt:
            return

        current_pos = player.position # For logging or GO logic if needed
        
        if collect_go_salary_if_passed: #This flag is true if card explicitly says collect, or we calculated they passed GO to a non-GO square.
            # This check might be redundant if _handle_go_passed also checks current_pos != 0, but good for clarity.
            if player.position != 0 or target_pos == 0: # Don't double pay if already on GO and card says advance to GO.
                 self._handle_go_passed(player)

        player.position = target_pos
        self.log_event(f"{player.name} moved directly to square {target_pos} ({self.board.get_square(target_pos).name}) by card/instruction.")
        self.land_on_square(player) # Process landing on the new square

    def get_game_state_for_agent(self, player_id: int) -> Dict[str, Any]: 
        player = self.players[player_id]
        if player.is_bankrupt:
            return {"status": "bankrupt", "player_id": player_id, "name": player.name}
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
            "my_jail_turns_remaining": player.jail_turns_remaining,
            "my_get_out_of_jail_cards": {
                "chance": player.has_chance_gooj_card,
                "community_chest": player.has_community_gooj_card
            },
            "current_turn_player_id": self.current_player_index,
            "active_decision_player_id": player_id,
            "pending_decision_type": self.pending_decision_type,
            "pending_decision_context": self.pending_decision_context,
            "dice_roll_outcome_processed": self.dice_roll_outcome_processed,
            "last_dice_roll": self.dice if self.dice != (0,0) else None,
            "current_trade_info": current_trade_info,  # New: Current active trade details
            "recent_trade_offers": recent_trade_offers,  # New: Recent trade history for context
            "board_squares": [], 
            "other_players": [],
            "game_log_tail": self.game_log[-20:] 
        }
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
        for p_other in self.players:
            if p_other.player_id != player_id:
                other_info = {
                    "player_id": p_other.player_id,
                    "name": p_other.name,
                    "position": p_other.position,
                    "in_jail": p_other.in_jail,
                    "is_bankrupt": p_other.is_bankrupt,
                    "num_properties": len(p_other.properties_owned_ids),
                }
                game_state["other_players"].append(other_info)
        return game_state

    def _handle_jail_turn(self, player: Player) -> bool:
        if not player.in_jail:
            return True 
        self.log_event(f"{player.name} is in jail. Turn {player.jail_turns_remaining + 1} in jail.")
        if self._can_use_gooj_card_internal(player): 
            pass 
        
        return False # Default to still in jail if this general handler is called without a specific action.

    def _can_use_gooj_card_internal(self, player: Player) -> bool:
        return player.has_chance_gooj_card or player.has_community_gooj_card

    def _handle_jail_turn_initiation(self, player: Player) -> None:
        """Called at the start of a turn if player is in jail to set up decision options."""
        if player.in_jail:
            self.pending_decision_type = "jail_options"
            self.pending_decision_context = {"player_id": player.player_id}
            self.dice_roll_outcome_processed = True 
        else:
            self._clear_pending_decision() 

    def execute_buy_property_decision(self, player_id: int, property_id_to_buy: int) -> bool:
        player = self.players[player_id]
        if not (self.pending_decision_type == "buy_or_auction_property" and 
                self.pending_decision_context.get("player_id") == player_id and 
                self.pending_decision_context.get("property_id") == property_id_to_buy):
            self.log_event(f"[Warning] execute_buy_property for P{player_id}, Prop{property_id_to_buy} called out of context. Pending: '{self.pending_decision_type}', Ctx: {self.pending_decision_context}")
            return False 
        square = self.board.get_square(property_id_to_buy)
        if not isinstance(square, PurchasableSquare):
            self.log_event(f"[Error] {square.name} is not a purchasable property type. Resolving decision.")
            self._resolve_current_action_segment() 
            return False
        if square.owner_id is not None:
            self.log_event(f"[Error] {square.name} is already owned by P{square.owner_id}. Cannot buy. Resolving decision.")
            self._resolve_current_action_segment() 
            return False
        if player.money >= square.price:
            player.subtract_money(square.price)
            square.owner_id = player.player_id
            player.add_property_id(square.square_id)
            self.log_event(f"{player.name} bought {square.name} for ${square.price}.")
            self._resolve_current_action_segment() 
            return True
        else:
            self.log_event(f"{player.name} attempted to buy {square.name} but has insufficient funds (${player.money} < ${square.price}). Decision to buy/pass remains pending.")
            return False

    def _pass_on_buying_property_action(self, player_id: int, property_id: int) -> Dict[str, Any]:
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
        self._initiate_auction(square_to_pass.square_id)
        return {"status": "success", "message": f"{player.name} passed on buying {square_to_pass.name}, auction initiated."}

    def _initiate_auction(self, property_id: int) -> None:
        square = self.board.get_square(property_id)
        if not isinstance(square, PurchasableSquare) or square.owner_id is not None:
            self.log_event(f"[Error] Cannot auction {square.name}, not purchasable/unowned.")
            self._resolve_current_action_segment()
            return

        self.log_event(f"--- Auction Started for: {square.name} (Price: ${square.price}) ---")
        self.auction_in_progress = True
        self.auction_property_id = property_id
        self.auction_current_bid = 1 
        self.auction_highest_bidder = None
        self.auction_participants = [p for p in self.players if not p.is_bankrupt]
        self.auction_active_bidders = list(self.auction_participants)
        self.auction_player_has_bid_this_round = {p.player_id: False for p in self.auction_participants}

        if not self.auction_active_bidders:
            self.log_event("No players eligible for auction. Property remains unowned.")
            self._conclude_auction(no_winner=True) 
            return
        
        self.auction_active_bidders.sort(key=lambda p: p.player_id)
        
        start_player_index_in_all_players = self.current_player_index 
        first_bidder_candidate = None
        
        for p_active in self.auction_active_bidders:
            if p_active.player_id > start_player_index_in_all_players:
                first_bidder_candidate = p_active
                break
        
        if not first_bidder_candidate and self.auction_active_bidders:
            first_bidder_candidate = self.auction_active_bidders[0]

        if not first_bidder_candidate:
            self.log_event("Critical error: Could not determine first bidder for auction.")
            self._conclude_auction(no_winner=True)
            return

        try:
            self.auction_current_bidder_turn_index = self.auction_active_bidders.index(first_bidder_candidate)
        except ValueError:
            self.log_event(f"[Error] Auction starter candidate {first_bidder_candidate.name} not in active list. Defaulting auction index.")
            self.auction_current_bidder_turn_index = 0 
            if not self.auction_active_bidders: 
                 self._conclude_auction(no_winner=True); return 

        first_bidder_to_actually_bid = self.auction_active_bidders[self.auction_current_bidder_turn_index]
        self.log_event(f"Auction participants: {[p.name for p in self.auction_active_bidders]}. First to bid: {first_bidder_to_actually_bid.name}")
        self._set_pending_decision("auction_bid", 
                                 context={"property_id": self.auction_property_id, "current_bid": self.auction_current_bid, "highest_bidder_id": None, "player_to_bid_id": first_bidder_to_actually_bid.player_id}, 
                                 outcome_processed=False)

    def _pay_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        player = self.players[player_id] 
        bail_amount = 50 
        if not player.in_jail:
            msg = f"{player.name} is not in jail. Cannot pay bail."
            self.log_event(f"[Warning] {msg}")
            if self.pending_decision_type == "jail_options" and self.pending_decision_context.get("player_id") == player_id:
                self._resolve_current_action_segment() 
            return {"status": "error", "message": msg}
        if player.money >= bail_amount:
            player.subtract_money(bail_amount)
            player.leave_jail() 
            self.doubles_streak = 0 
            msg = f"{player.name} paid ${bail_amount} bail and is now out of jail."
            self.log_event(msg)
            self._resolve_current_action_segment() 
            return {"status": "success", "message": msg, "paid_bail": True}
        else: 
            msg = f"{player.name} does not have enough money (${player.money}) to pay ${bail_amount} bail."
            self.log_event(msg)
            return {"status": "error", "message": msg, "paid_bail": False}

    def _use_card_to_get_out_of_jail(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        player = self.players[player_id]
        if not player.in_jail:
            msg = f"{player.name} is not in jail. Cannot use GOOJ card."
            self.log_event(f"[Warning] {msg}")
            if self.pending_decision_type == "jail_options" and self.pending_decision_context.get("player_id") == player_id:
                self._resolve_current_action_segment()
            return {"status": "error", "message": msg}

        if player.has_chance_gooj_card:
            player.use_get_out_of_jail_chance_card() 
            player.leave_jail()
            self.doubles_streak = 0
            msg = f"{player.name} used a Chance Get Out of Jail Free card and is now out of jail."
            self.log_event(msg)
            self._resolve_current_action_segment()
            return {"status": "success", "message": msg, "used_card": "chance"}
        elif player.has_community_gooj_card:
            player.use_get_out_of_jail_community_chest_card()
            player.leave_jail()
            self.doubles_streak = 0
            msg = f"{player.name} used a Community Chest Get Out of Jail Free card and is now out of jail."
            self.log_event(msg)
            self._resolve_current_action_segment()
            return {"status": "success", "message": msg, "used_card": "community_chest"}
        else:
            msg = f"{player.name} has no Get Out of Jail Free card to use."
            self.log_event(msg)
            return {"status": "error", "message": msg}

    def get_available_actions(self, player_id: int) -> List[str]:
        actions: List[str] = []
        player = self.players[player_id]
        if player.is_bankrupt: return []

        # --- Specific Pending Decisions ---
        if self.pending_decision_type == "jail_options":
            # ... (existing jail_options logic - ensure it's correct based on previous fixes)
            if player.in_jail and self.pending_decision_context.get("player_id") == player_id : 
                has_card = player.has_chance_gooj_card or player.has_community_gooj_card
                can_pay_bail_directly = player.money >= 50
                max_rolls_attempted = player.jail_turns_remaining >= 3 or self.pending_decision_context.get("max_rolls_attempted", False)
                if has_card: actions.append("tool_use_get_out_of_jail_card")
                if can_pay_bail_directly: actions.append("tool_pay_bail")
                if not max_rolls_attempted: actions.append("tool_roll_for_doubles_to_get_out_of_jail")
                if max_rolls_attempted and not has_card and not can_pay_bail_directly:
                    can_mortgage = any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids)
                    can_sell_houses = any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids)
                    if can_mortgage: actions.append("tool_mortgage_property")
                    if can_sell_houses: actions.append("tool_sell_house")
                if not actions or (max_rolls_attempted and (has_card or can_pay_bail_directly)):
                     actions.append("tool_end_turn") 
            else: self._clear_pending_decision()
        
        elif self.pending_decision_type == "respond_to_trade_offer":
             if self.pending_decision_context.get("player_id") == player_id: 
                 actions.extend(["tool_accept_trade", "tool_reject_trade", "tool_propose_counter_offer"]) 
             else: self._clear_pending_decision()

        elif self.pending_decision_type == "propose_new_trade_after_rejection": # New logic for re-proposal
            if self.pending_decision_context.get("player_id") == player_id:
                rejection_count = self.pending_decision_context.get("negotiation_rejection_count", 0)
                # Ensure MAX_TRADE_REJECTIONS is accessible here (e.g., defined at module level or self.MAX_TRADE_REJECTIONS)
                # For this example, assuming it's defined at module level as in previous context
                if rejection_count < MAX_TRADE_REJECTIONS:
                    actions.append("tool_propose_trade") # Player can propose a new trade (potentially modified)
                actions.append("tool_end_trade_negotiation") # Always allow ending the negotiation
            else: self._clear_pending_decision()

        # ... (other existing elif blocks for buy_or_auction_property, asset_liquidation_for_debt, auction_bid, handle_received_mortgaged_property)
        elif self.pending_decision_type == "buy_or_auction_property":
            if self.pending_decision_context.get("player_id") == player_id: actions.extend(["tool_buy_property", "tool_pass_on_buying_property"])
            else: self._clear_pending_decision()
        elif self.pending_decision_type == "asset_liquidation_for_debt":
            if self.pending_decision_context.get("player_id") == player_id:
                if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): actions.append("tool_sell_house")
                if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): actions.append("tool_mortgage_property")
                actions.append("tool_confirm_asset_liquidation_actions_done") 
            else: self._clear_pending_decision()
        elif self.pending_decision_type == "auction_bid": 
            if self.pending_decision_context.get("player_to_bid_id") == player_id and player_id in [p.player_id for p in self.auction_active_bidders]: actions.extend(["tool_bid_on_auction", "tool_pass_auction_bid"]) 
            elif player_id in [p.player_id for p in self.auction_active_bidders]: actions.append("tool_wait") 
        elif self.pending_decision_type == "handle_received_mortgaged_property":
            if self.pending_decision_context.get("player_id") == player_id and self.pending_decision_context.get("property_id_to_handle") is not None:
                actions.extend(["tool_pay_mortgage_interest_fee", "tool_unmortgage_property_immediately"]) 
            else: self._clear_pending_decision()

        # --- General Turn Actions (if no specific decision is pending) ---
        if not actions and self.pending_decision_type is None: 
            # ... (rest of general actions logic as previously corrected)
            if self.current_player_index == player_id:
                if not player.in_jail: 
                    if self.dice_roll_outcome_processed: 
                        actions.append("tool_roll_dice")
                        can_build_on_any_property = False
                        for p_id_check in player.properties_owned_ids:
                            square_check = self.board.get_square(p_id_check)
                            if isinstance(square_check, PropertySquare) and square_check.owner_id == player_id and \
                               not square_check.is_mortgaged and square_check.num_houses < 5 and player.money >= square_check.house_price and \
                               square_check.group_id is not None and square_check.group_id >= 3:
                                owns_all_in_group_unmortgaged = True
                                if not square_check.group_members: 
                                    owns_all_in_group_unmortgaged = False
                                else:
                                    for member_id_check in square_check.group_members:
                                        member_square_check = self.board.get_square(member_id_check)
                                        if not (isinstance(member_square_check, PropertySquare) and 
                                                member_square_check.owner_id == player_id and 
                                                not member_square_check.is_mortgaged):
                                            owns_all_in_group_unmortgaged = False; break
                                if owns_all_in_group_unmortgaged:
                                    min_houses_in_group = min((s.num_houses for s_id in square_check.group_members if (s := self.board.get_square(s_id)) and isinstance(s, PropertySquare) and s.owner_id == player_id), default=float('inf'))
                                    if square_check.num_houses == min_houses_in_group: 
                                        can_build_on_any_property = True; break
                        if can_build_on_any_property: actions.append("tool_build_house")
                        if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): actions.append("tool_sell_house")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): actions.append("tool_mortgage_property")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and sq.is_mortgaged and player.money >= int(sq.mortgage_value*1.1) for pid in player.properties_owned_ids): actions.append("tool_unmortgage_property")
                        if len([p_other for p_other in self.players if not p_other.is_bankrupt and p_other.player_id != player_id]) > 0: actions.append("tool_propose_trade")
                        actions.append("tool_end_turn")
                    elif not self.dice_roll_outcome_processed and self.pending_decision_type is None: 
                        if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): actions.append("tool_sell_house")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): actions.append("tool_mortgage_property")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and sq.is_mortgaged and player.money >= int(sq.mortgage_value*1.1) for pid in player.properties_owned_ids): actions.append("tool_unmortgage_property")
                        if len([p_other for p_other in self.players if not p_other.is_bankrupt and p_other.player_id != player_id]) > 0: actions.append("tool_propose_trade")
                        actions.append("tool_end_turn")
                    if not actions : actions.append("tool_wait") 
                    actions.append("tool_resign_game")
                elif player.in_jail: 
                    self.log_event(f"[Warning] P{player_id} ({player.name}) in jail, but no jail_options pending. Fallback.", "warning_log")
                    actions.extend(["tool_end_turn", "tool_resign_game"]) 
            else: 
                actions.append("tool_wait")

        if not actions and not player.is_bankrupt: 
            self.log_event(f"[Fallback Warning No Actions] P{player_id} ({player.name}). Pend: {self.pending_decision_type}, DiceDone: {self.dice_roll_outcome_processed}. Adding tool_wait/end_turn.", "warning_log")
            if self.current_player_index == player_id and self.pending_decision_type is None and self.dice_roll_outcome_processed: 
                actions.append("tool_end_turn") 
                actions.append("tool_wait")
        return list(dict.fromkeys(actions))

    def _save_game_turn_snapshot(self, acting_player_index: int) -> Optional[int]:
        # self.log_event(f"_save_game_turn_snapshot called for PIdx: {acting_player_index}, Turn: {self.turn_count}. GameDBID: {self.game_db_id}", "method_trace")
        if self.game_db_id is None: 
            self.log_event("[DB E] No game_db_id for turn snapshot. Cannot save.", "error_log")
            return None
        turn_db_id = None
        try:
            # self.log_event(f"Attempting to get game state for agent {acting_player_index} for snapshot.", "debug_trace")
            game_state_dict = self.get_game_state_for_agent(acting_player_index) 
            # self.log_event(f"Successfully got game state for agent {acting_player_index}. Attempting to dump JSON.", "debug_trace")
            game_state_str = json.dumps(game_state_dict)
            # self.log_event(f"JSON dump successful. Length: {len(game_state_str)}. Attempting DB insert.", "debug_trace")
            with Session(engine) as session:
                stmt = insert(game_turns_table).values(
                    game_id=self.game_db_id,
                    turn_number=self.turn_count,
                    acting_player_game_index=acting_player_index, 
                    game_state_json=game_state_str,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                ).returning(game_turns_table.c.id)
                result = session.execute(stmt)
                turn_db_id = result.scalar_one_or_none()
                session.commit()
                if turn_db_id is not None:
                    # self.log_event(f"Saved turn snapshot (TurnDBID:{turn_db_id}) for T:{self.turn_count}, PIdx:{acting_player_index}. Game Over: {self.game_over}", "db_log")
                    self.current_game_turn_db_id = turn_db_id 
                else: 
                    self.log_event("[DB E] Failed to get DB ID for saved turn snapshot (result was None).", "error_log")
        except json.JSONDecodeError as json_err:
            self.log_event(f"[CRITICAL JSON ERROR] Failed to serialize game_state_dict for PIdx {acting_player_index} in _save_game_turn_snapshot: {json_err}", "error_log")
        except Exception as e:
            self.log_event(f"[CRITICAL DB/OTHER ERROR] in _save_game_turn_snapshot for PIdx {acting_player_index}: {e}", "error_log")
            import traceback
            self.log_event(traceback.format_exc(), "error_trace") 
        # self.log_event(f"_save_game_turn_snapshot finished. Returning TurnDBID: {turn_db_id}. Game Over: {self.game_over}", "method_trace")
        return turn_db_id

    def get_board_layout_for_frontend(self) -> List[Dict[str, Any]]:
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

    def _validate_trade_items(self, player_id: int, items: List[TradeOfferItem]) -> bool:
        player = self.players[player_id]
        for item in items:
            if item.item_type == "money":
                if player.money < item.quantity: return False
            elif item.item_type == "property":
                if item.item_id is None or item.item_id not in player.properties_owned_ids : return False
                square = self.board.get_square(item.item_id)
                if isinstance(square, PropertySquare) and square.num_houses > 0 : return False
            elif item.item_type == "get_out_of_jail_card":
                num_offered = item.quantity
                available_cards = 0
                if player.has_chance_gooj_card: available_cards +=1
                if player.has_community_gooj_card: available_cards +=1
                if num_offered > available_cards : return False
        return True

    def _transfer_gooj_card(self, giver: Player, receiver: Player, card_item_id_hint: Optional[int]):
        transferred_card_type = None
        if card_item_id_hint == 0 and giver.has_chance_gooj_card: 
            giver.use_get_out_of_jail_chance_card() 
            receiver.add_get_out_of_jail_card("chance") 
            transferred_card_type = "Chance"
        elif card_item_id_hint == 1 and giver.has_community_gooj_card: 
            giver.use_get_out_of_jail_community_chest_card()
            receiver.add_get_out_of_jail_card("community_chest")
            transferred_card_type = "Community Chest"
        elif card_item_id_hint is None: 
            used_card_type = None 
            if giver.has_chance_gooj_card:
                if hasattr(giver, 'use_get_out_of_jail_chance_card'): giver.use_get_out_of_jail_chance_card()
                else: giver.has_chance_gooj_card = False
                receiver.add_get_out_of_jail_card("chance")
                transferred_card_type = "Chance"
            elif giver.has_community_gooj_card:
                if hasattr(giver, 'use_get_out_of_jail_community_chest_card'): giver.use_get_out_of_jail_community_chest_card()
                else: giver.has_community_gooj_card = False
                receiver.add_get_out_of_jail_card("community_chest")
                transferred_card_type = "Community Chest"
        
        if transferred_card_type:
            self.log_event(f"{giver.name} gives a {transferred_card_type} GOOJ card to {receiver.name}.", "trade_log")
        else:
            self.log_event(f"[Warning] {giver.name} had no GOOJ card (or specified type {card_item_id_hint}) to transfer to {receiver.name} when expected during trade.", "trade_log")

    def _generate_trade_id(self) -> int:
        trade_id = self.next_trade_id
        self.next_trade_id += 1
        return trade_id

    def _validate_trade_items(self, player_id: int, items: List[TradeOfferItem]) -> bool:
        player = self.players[player_id]
        for item in items:
            if item.item_type == "money":
                if player.money < item.quantity:
                    self.log_event(f"Validation fail: P{player_id} has ${player.money}, needs ${item.quantity} for trade.", "trade_debug")
                    return False
            elif item.item_type == "property":
                if item.item_id is None or item.item_id not in player.properties_owned_ids:
                    self.log_event(f"Validation fail: P{player_id} does not own property {item.item_id} for trade.", "trade_debug")
                    return False
                square = self.board.get_square(item.item_id)
                if isinstance(square, PropertySquare) and square.num_houses > 0:
                    self.log_event(f"Validation fail: Property {item.item_id} ({square.name}) has houses, cannot be traded directly.", "trade_debug")
                    return False
            elif item.item_type == "get_out_of_jail_card":
                num_offered = item.quantity
                available_cards = 0
                if player.has_chance_gooj_card: available_cards +=1
                if player.has_community_gooj_card: available_cards +=1
                if num_offered > available_cards:
                    self.log_event(f"Validation fail: P{player_id} does not have {num_offered} GOOJ card(s) to offer. Has: Chance-{player.has_chance_gooj_card}, CC-{player.has_community_gooj_card}", "trade_debug")
                    return False
        return True

    def propose_trade_action(self, proposer_id: int, recipient_id: int, 
                             offered_property_ids: List[int], offered_money: int, offered_gooj_cards: int, 
                             requested_property_ids: List[int], requested_money: int, requested_gooj_cards: int,
                             message: Optional[str] = None,
                             counter_to_trade_id: Optional[int] = None 
                             ) -> Optional[int]:
        proposer = self.players[proposer_id]
        recipient = self.players[recipient_id]

        if proposer.is_bankrupt or recipient.is_bankrupt:
            self.log_event(f"Trade failed: Proposer P{proposer_id} ({proposer.name}) or Recipient P{recipient_id} ({recipient.name}) is bankrupt.", "trade_log")
            return None
        if proposer_id == recipient_id:
            self.log_event(f"Trade failed: P{proposer_id} ({proposer.name}) cannot trade with oneself.", "trade_log")
            return None
        
        temp_items_proposer: List[TradeOfferItem] = []
        if offered_money > 0: temp_items_proposer.append(TradeOfferItem(item_type="money", quantity=offered_money))
        for prop_id in offered_property_ids: temp_items_proposer.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        if offered_gooj_cards > 0: temp_items_proposer.append(TradeOfferItem(item_type="get_out_of_jail_card", quantity=offered_gooj_cards))
        
        if not self._validate_trade_items(proposer_id, temp_items_proposer):
            self.log_event(f"Trade invalid: Proposer P{proposer_id} ({proposer.name}) validation failed for offered items.", "trade_log"); return None

        temp_items_recipient: List[TradeOfferItem] = []
        if requested_money > 0: temp_items_recipient.append(TradeOfferItem(item_type="money", quantity=requested_money))
        for prop_id in requested_property_ids: temp_items_recipient.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        if requested_gooj_cards > 0: temp_items_recipient.append(TradeOfferItem(item_type="get_out_of_jail_card", quantity=requested_gooj_cards))

        if not self._validate_trade_items(recipient_id, temp_items_recipient):
            self.log_event(f"Trade invalid: Recipient P{recipient_id} ({recipient.name}) validation failed for requested items.", "trade_log"); return None

        trade_id = self._generate_trade_id()
        
        offer_items_proposer_detailed: List[TradeOfferItem] = []
        if offered_money > 0: offer_items_proposer_detailed.append(TradeOfferItem(item_type="money", quantity=offered_money))
        for prop_id in offered_property_ids: offer_items_proposer_detailed.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        
        temp_offered_gooj_remaining = offered_gooj_cards
        if temp_offered_gooj_remaining > 0 and proposer.has_chance_gooj_card:
            offer_items_proposer_detailed.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=0, quantity=1))
            temp_offered_gooj_remaining -=1
        if temp_offered_gooj_remaining > 0 and proposer.has_community_gooj_card: 
            offer_items_proposer_detailed.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=1, quantity=1))
            temp_offered_gooj_remaining -=1
        if temp_offered_gooj_remaining > 0 and offered_gooj_cards > 0: 
             self.log_event(f"Trade invalid: Proposer P{proposer_id} does not have enough GOOJ cards of specific types to offer {offered_gooj_cards}. Offered {offered_gooj_cards - temp_offered_gooj_remaining} of available cards.", "trade_log"); return None

        requested_items_recipient_detailed: List[TradeOfferItem] = []
        if requested_money > 0: requested_items_recipient_detailed.append(TradeOfferItem(item_type="money", quantity=requested_money))
        for prop_id in requested_property_ids: requested_items_recipient_detailed.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        
        temp_requested_gooj_remaining = requested_gooj_cards
        if temp_requested_gooj_remaining > 0 and recipient.has_chance_gooj_card:
             requested_items_recipient_detailed.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=0, quantity=1))
             temp_requested_gooj_remaining -=1
        if temp_requested_gooj_remaining > 0 and recipient.has_community_gooj_card:
             requested_items_recipient_detailed.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=1, quantity=1))
             temp_requested_gooj_remaining -=1
        if temp_requested_gooj_remaining > 0 and requested_gooj_cards > 0:
            self.log_event(f"Trade invalid: Recipient P{recipient_id} does not have enough GOOJ cards of specific types to fulfill request for {requested_gooj_cards}. Could provide {requested_gooj_cards - temp_requested_gooj_remaining} of available cards.", "trade_log"); return None
        
        # rejection_count for a new offer (even a counter) should be 0 initially for this specific offer object.
        # The negotiation_rejection_count is tracked in the context for propose_new_trade_after_rejection.
        offer = TradeOffer(
            trade_id=trade_id, proposer_id=proposer_id, recipient_id=recipient_id,
            items_offered_by_proposer=offer_items_proposer_detailed, 
            items_requested_from_recipient=requested_items_recipient_detailed,
            turn_proposed=self.turn_count, message=message, rejection_count=0, # New offers start with 0 rejections
            counter_offer_to_trade_id=counter_to_trade_id
        )
        self.trade_offers[trade_id] = offer
        self.log_event(f"P{proposer.name} (P{proposer_id}) proposed T:{trade_id} to P{recipient.name} (P{recipient_id}). Msg: '{message if message else 'N/A'}'", "trade_log")
        
        self._set_pending_decision("respond_to_trade_offer", 
                                 context={"trade_id": trade_id, "player_id": recipient_id, "proposer_id": proposer_id, "message_from_proposer": message},
                                 outcome_processed=True)
        return trade_id

    def _respond_to_trade_offer_action(self, player_id: int, trade_id: int, response: str, 
                                     counter_offered_prop_ids: Optional[List[int]] = None, 
                                     counter_offered_money: Optional[int] = None, 
                                     counter_offered_gooj_cards: Optional[int] = None,
                                     counter_requested_prop_ids: Optional[List[int]] = None, 
                                     counter_requested_money: Optional[int] = None, 
                                     counter_requested_gooj_cards: Optional[int] = None,
                                     counter_message: Optional[str] = None 
                                     ) -> bool:
        # ... (initial checks for trade_id, offer.recipient_id, offer.status as before)
        if trade_id not in self.trade_offers: 
            self.log_event(f'[E] Trade ID {trade_id} not found for response by P{player_id}.'); 
            self._resolve_current_action_segment(); return False
        offer = self.trade_offers[trade_id]
        if offer.recipient_id != player_id: 
            self.log_event(f'[E] Player {player_id} is not the recipient of Trade ID {trade_id}. Current recipient: P{offer.recipient_id}.'); return False
        if offer.status != "pending_response": 
            self.log_event(f'[E] Trade ID {trade_id} is not in a respondable state (status: {offer.status}) for P{player_id}.'); 
            return False 

        player = self.players[player_id] 
        original_proposer = self.players[offer.proposer_id]
        self.log_event(f"P{player.name} (P{player_id}) responds to T{trade_id} from P{original_proposer.name} (P{offer.proposer_id}) with: {response.upper()}", "trade_log")

        if response.lower() == "accept":
            # ... (accept logic as before) ...
            if not (self._validate_trade_items(original_proposer.player_id, offer.items_offered_by_proposer) and \
                    self._validate_trade_items(player.player_id, offer.items_requested_from_recipient)):
                self.log_event(f"Trade {trade_id} conditions changed. Auto-cancelled.", "trade_log"); offer.status = "cancelled_conditions_changed"; 
                self._resolve_current_action_segment(); return False
            try:
                mortgaged_props_received_by_player: List[Dict[str,Any]] = [] 
                mortgaged_props_received_by_proposer: List[Dict[str,Any]] = []
                for item in offer.items_offered_by_proposer: 
                    if item.item_type == "money": original_proposer.subtract_money(item.quantity); player.add_money(item.quantity)
                    elif item.item_type == "property":
                        sq = self.board.get_square(item.item_id) 
                        original_proposer.remove_property_id(item.item_id); player.add_property_id(item.item_id); sq.owner_id = player.player_id
                        if sq.is_mortgaged: mortgaged_props_received_by_player.append({"property_id": item.item_id, "source_trade_id": trade_id})
                    elif item.item_type == "get_out_of_jail_card": self._transfer_gooj_card(original_proposer, player, item.item_id)
                for item in offer.items_requested_from_recipient: 
                    if item.item_type == "money": player.subtract_money(item.quantity); original_proposer.add_money(item.quantity)
                    elif item.item_type == "property":
                        sq = self.board.get_square(item.item_id) 
                        player.remove_property_id(item.item_id); original_proposer.add_property_id(item.item_id); sq.owner_id = original_proposer.player_id
                        if sq.is_mortgaged: mortgaged_props_received_by_proposer.append({"property_id": item.item_id, "source_trade_id": trade_id})
                    elif item.item_type == "get_out_of_jail_card": self._transfer_gooj_card(player, original_proposer, item.item_id)
                offer.status = "accepted"
                self.log_event(f"Trade {trade_id} accepted! Assets exchanged.", "trade_log")
                self._clear_pending_decision() 
                for task_data in mortgaged_props_received_by_proposer:
                    original_proposer.add_pending_mortgaged_property_task(task_data["property_id"], task_data["source_trade_id"])
                if mortgaged_props_received_by_player:
                    for task_data in mortgaged_props_received_by_player:
                         player.add_pending_mortgaged_property_task(task_data["property_id"], task_data["source_trade_id"])
                    self._handle_received_mortgaged_property_initiation(player) 
                    return True 
                self._resolve_current_action_segment(); return True
            except Exception as e: 
                self.log_event(f"[E] Asset transfer for T{trade_id} failed: {e}. Trade cancelled.", "error_log"); offer.status = "failed_transfer"; 
                self._resolve_current_action_segment(); return False
        
        elif response.lower() == "reject": 
            offer.status = "rejected_by_recipient"; 
            offer.rejection_count += 1 # Increment rejection_count on this specific offer
            self.log_event(f"T{trade_id} rejected by P{player.name}. This offer instance rejection count: {offer.rejection_count}.", "trade_log"); 
            
            # The overall negotiation rejection count is for the original proposer of this negotiation chain.
            # If this offer was already a counter, offer.proposer_id is the one who made the counter.
            # We need to track rejections for the *initial* proposer of the whole negotiation sequence.
            # Let's assume for now the `negotiation_rejection_count` in context is the one that matters for MAX_TRADE_REJECTIONS.
            # This context would be passed when setting "propose_new_trade_after_rejection".
            # For a first-time rejection of an initial offer, the context wouldn't have this count yet.

            negotiation_rejection_count_for_proposer = self.pending_decision_context.get("negotiation_rejection_count", 0) # Get from current context if it was a re-proposal stage
            if offer.counter_offer_to_trade_id is None: # This was an initial offer being rejected
                negotiation_rejection_count_for_proposer = 1 # First rejection in this chain for original_proposer
            else: # This was a counter-offer being rejected; increment based on existing context
                negotiation_rejection_count_for_proposer = self.pending_decision_context.get("negotiation_rejection_count", 0) + 1 
                # We need to ensure the correct proposer (original one) is identified for this count

            if negotiation_rejection_count_for_proposer >= MAX_TRADE_REJECTIONS:
                self.log_event(f"Negotiation thread involving original proposer P{offer.proposer_id} for T{trade_id} reached max rejections ({MAX_TRADE_REJECTIONS}). Terminated.", "trade_log")
                offer.status = "terminated_max_rejections" 
                self._resolve_current_action_segment() 
            else:
                self._set_pending_decision(
                    "propose_new_trade_after_rejection", 
                    context={
                        "player_id": offer.proposer_id,                 # Original proposer needs to act now
                        "original_trade_id_rejected": trade_id,       
                        "rejected_by_player_id": player_id,           
                        "negotiation_rejection_count": negotiation_rejection_count_for_proposer, 
                        "message_from_rejector": f"Your trade T{trade_id} (message: '{offer.message if offer.message else 'N/A'}') was rejected by P{player_id} ({player.name})."
                    },
                    outcome_processed=True
                )
            return True 
        
        elif response.lower() == "counter_offer": 
            offer.status = "countered_by_recipient"; 
            self.log_event(f"P{player.name} counters T{trade_id}. P{player_id} now proposing to P{offer.proposer_id}.", "trade_log"); 
            self._clear_pending_decision() 
            
            new_trade_id = self.propose_trade_action(
                proposer_id=player_id, recipient_id=offer.proposer_id, 
                offered_property_ids=counter_offered_prop_ids or [], offered_money=counter_offered_money or 0, offered_gooj_cards=counter_offered_gooj_cards or 0,
                requested_property_ids=counter_requested_prop_ids or [], requested_money=counter_requested_money or 0, requested_gooj_cards=counter_requested_gooj_cards or 0,
                message=counter_message,
                counter_to_trade_id=trade_id 
            )
            if new_trade_id is not None: 
                self.log_event(f"Counter-offer (New T{new_trade_id}) to P{offer.proposer_id} created by P{player_id}.");
            else: 
                self.log_event(f"[E] Failed to create counter for T{trade_id}. Reverting T{trade_id} to P{player_id} to respond again.", "error_log")
                offer.status = "pending_response" 
                self._set_pending_decision("respond_to_trade_offer", 
                                         context={"trade_id": trade_id, "player_id": player_id, "proposer_id": offer.proposer_id, "message_from_proposer": offer.message},
                                         outcome_processed=True)
                return False 
            self._resolve_current_action_segment(); return True 
        else: 
            self.log_event(f"[E] Invalid response '{response}' to T{trade_id}. Re-prompting P{player.name}.", "warning_log");
            self._set_pending_decision("respond_to_trade_offer", self.pending_decision_context, True)
            return False

    def _end_trade_negotiation_action(self, player_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        context = self.pending_decision_context
        current_player = self.players[player_id]
        if self.pending_decision_type == "propose_new_trade_after_rejection" and context.get("player_id") == player_id:
            original_trade_id_rejected = context.get("original_trade_id_rejected")
            rejected_by_player_id = context.get("rejected_by_player_id")
            self.log_event(f"P{current_player.name} (P{player_id}) chose to end trade negotiation with P{rejected_by_player_id} regarding original T{original_trade_id_rejected}.", "trade_log")
            if original_trade_id_rejected and original_trade_id_rejected in self.trade_offers:
                self.trade_offers[original_trade_id_rejected].status = "terminated_by_proposer_after_rejection"
            self._resolve_current_action_segment()
            return {"status": "success", "message": "Trade negotiation ended by proposer."}
        else:
            msg = f"P{player_id} ({current_player.name}) cannot end trade negotiation: not in correct state ('{self.pending_decision_type}'). Expected 'propose_new_trade_after_rejection' for this player."
            self.log_event(f"[Warning] {msg}")
            return {"status": "error", "message": msg}

    def _conclude_auction(self, no_winner: bool = False) -> None:
        prop_id = self.auction_property_id
        prop_name = self.board.get_square(prop_id).name if prop_id is not None else "Property"
        if no_winner or self.auction_highest_bidder is None or (self.auction_current_bid <= 1 and not self.auction_highest_bidder): 
            self.log_event(f"Auction for {prop_name} concluded with no winner or only minimum unaccepted bid. Property remains unowned.")
        else:
            winner = self.auction_highest_bidder
            price_paid = self.auction_current_bid
            property_square = self.board.get_square(prop_id)
            self.log_event(f"Auction for {prop_name} won by {winner.name} for ${price_paid}.")
            self._player_pays_amount(winner, price_paid, f"winning auction bid for {prop_name}")
            if not winner.is_bankrupt: 
                property_square.owner_id = winner.player_id
                winner.add_property_id(prop_id)
                self.log_event(f"{winner.name} now owns {prop_name}.")
            else:
                self.log_event(f"{winner.name} went bankrupt paying for {prop_name}. Property remains unowned.")
                if isinstance(property_square, PurchasableSquare): 
                    property_square.owner_id = None 
        self.auction_in_progress = False
        self.auction_property_id = None
        self.auction_current_bid = 0
        self.auction_highest_bidder = None
        self.auction_participants = []
        self.auction_active_bidders = []
        self.auction_player_has_bid_this_round = {}
        self.auction_current_bidder_turn_index = 0
        self._resolve_current_action_segment()