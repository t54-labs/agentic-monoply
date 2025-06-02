from typing import List, Optional, Tuple, Dict, Any
import random
from dataclasses import dataclass, field

from .board import Board, CardData
from .player import Player
from .property import ActionSquare, BaseSquare, PurchasableSquare, PropertySquare, RailroadSquare, TaxSquare, UtilitySquare, SquareType, PropertyColor

@dataclass
class TradeOfferItem:
    item_type: str # \"property\", \"money\", \"get_out_of_jail_card\"
    item_id: Optional[int] = None # property_id if item_type is property
    quantity: int = 0 # money amount, or 1 for property/card
    # card_type: Optional[str] = None # \"chance\" or \"community_chest\" if item_type is card - can be part of context or a different structure

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

class GameController:
    def __init__(self, num_players: int = 4, player_names: Optional[List[str]] = None):
        if not (2 <= num_players <= 8): # Standard Monopoly player range
            self.log_event(f"[Warning] Player count {num_players} out of range (2-8). Defaulting to 4.")
            num_players = 4

        self.board: Board = Board()
        self.players: List[Player] = []
        self.turn_count: int = 0
        self.game_log: List[str] = [] # Ensure game_log is initialized HERE

        self._initialize_players(num_players, player_names)

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

    def _initialize_players(self, num_players: int, player_names: Optional[List[str]] = None) -> None:
        default_ai_names = ["Agent Smith", "Agent Brown", "Agent Jones", "Agent White"] # Example names
        for i in range(num_players):
            name = ""
            if player_names and i < len(player_names):
                name = player_names[i]
            else:
                name = default_ai_names[i % len(default_ai_names)] + (f" {i // len(default_ai_names) + 1}" if num_players > len(default_ai_names) else "")
            
            # For this project, all players are AI
            self.players.append(Player(player_id=i, name=name, is_ai=True))
        self.log_event(f"Initialized {num_players} AI players: {[p.name for p in self.players]}")
        self.pending_decision_type = None # Initial state, no decision pending until game starts for a player
        self.dice_roll_outcome_processed = True # Ready for first player to roll
        self._clear_pending_decision() # Ensure clean state at init

    def get_current_player(self) -> Player:
        return self.players[self.current_player_index]

    def log_event(self, event_message: str) -> None:
        print(event_message) # For now, print to console
        self.game_log.append(event_message)

    def start_game(self) -> None:
        self.current_player_index = random.randrange(len(self.players)) # Randomly select starting player
        self.log_event(f"Game started. Player {self.get_current_player().name} goes first.")
        # self.next_turn() # Or the external loop calls for the first turn actions

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

    def _attempt_roll_out_of_jail(self, player: Player) -> bool:
        if not player.in_jail: return True 
        
        local_dice = (random.randint(1, 6), random.randint(1, 6))
        self.log_event(f"{player.name} (in jail) rolls for doubles: {local_dice[0]},{local_dice[1]}.")
        player.attempt_to_get_out_of_jail() 

        if local_dice[0] == local_dice[1]:
            self.log_event(f"{player.name} rolled doubles and got out of jail!")
            player.leave_jail()
            self._clear_pending_decision() 
            self.dice = local_dice 
            self.doubles_streak = 0 
            self._set_pending_decision(None, outcome_processed=False) # Dice rolled, outcome (move/land) pending
            self._move_player(player, sum(self.dice)) 
            return True
        else:
            self.log_event(f"{player.name} did not roll doubles. Stays in jail.")
            if player.jail_turns_remaining >= 3:
                self.log_event(f"This was the 3rd failed roll attempt for {player.name}.")
                # If no other options (card/money for bail), this jail segment ends. Player stays in jail.
                if not (player.has_get_out_of_jail_card or player.has_get_out_of_jail_community_chest_card or player.money >= 50):
                    self.log_event(f"{player.name} has no other options to get out of jail this turn.")
                    self._resolve_current_action_segment() # No more jail choices this turn.
                else:
                    # Still has options (pay/card), so jail_options decision persists for agent to choose.
                    self._set_pending_decision("jail_options", context={"player_id": player.player_id}, outcome_processed=True)
            else:
                # Not 3rd turn yet, can try rolling again or choose other options.
                self._set_pending_decision("jail_options", context={"player_id": player.player_id}, outcome_processed=True)
            return False

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
            if player.has_get_out_of_jail_chance_card:
                if creditor: creditor.add_get_out_of_jail_card("chance")
                player.has_get_out_of_jail_chance_card = False
            if player.has_get_out_of_jail_community_chest_card:
                if creditor: creditor.add_get_out_of_jail_card("community_chest")
                player.has_get_out_of_jail_community_chest_card = False
            properties_to_transfer_ids = list(player.properties_owned_ids)
            for prop_id in properties_to_transfer_ids:
                square = self.board.get_square(prop_id)
                if isinstance(square, PurchasableSquare):
                    player.remove_property_id(prop_id)
                    if creditor:
                        square.owner_id = creditor.player_id
                        creditor.add_property_id(prop_id)
                        if square.is_mortgaged:
                            interest_payment = int(square.mortgage_value * 0.1)
                            self.log_event(f"{creditor.name} must pay 10% interest (${interest_payment}) for {square.name}.")
                            self._player_pays_amount(creditor, interest_payment, f"10% interest on {square.name}") 
                    else: 
                        square.owner_id = None; square.is_mortgaged = False
                        if isinstance(square, PropertySquare): square.num_houses = 0
                        self.log_event(f"{square.name} returns to bank, unmortgaged, buildings removed.")
            
            self._resolve_current_action_segment() # Bankruptcy fully processed for this player.
            self._check_for_game_over_condition()

    def next_turn(self) -> None:
        # This method is called when a player's turn (or their sequence of bonus turns) definitively ends.
        # It should advance to the next player and reset states for that new turn.

        current_p_whose_turn_ended = self.get_current_player()
        self.log_event(f"Ending turn processing for {current_p_whose_turn_ended.name}. Doubles streak before reset: {self.doubles_streak}")
        self.doubles_streak = 0 # Always reset doubles streak when moving to a new player's turn
        
        original_player_index = self.current_player_index
        while True:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
            next_player = self.players[self.current_player_index]
            if not next_player.is_bankrupt:
                break # Found next active player
            if self.current_player_index == original_player_index: 
                self.log_event(f"All other players are bankrupt. {current_p_whose_turn_ended.name} might be the winner if not also bankrupt.")
                self.game_over = True
                self._resolve_current_action_segment() # Game ended
                return
        
        self._clear_pending_decision() # Clear any decision from previous player
        self.dice_roll_outcome_processed = True # New player's turn, ready for their first action
        self.dice = (0,0) # Reset dice visual/value for the new player
        
        new_main_turn_player = self.get_current_player()
        self.log_event(f"--- Player {new_main_turn_player.name}'s (P{new_main_turn_player.player_id}) turn begins ---")

        # PRIORITY: Handle pending mortgaged properties from previous trades first.
        if new_main_turn_player.pending_mortgaged_properties_to_handle:
            self._handle_received_mortgaged_property_initiation(new_main_turn_player)
        elif new_main_turn_player.in_jail:
            self._handle_jail_turn_initiation(new_main_turn_player)
        # Else, normal turn start (pending_decision is None, dice_roll_outcome_processed is True)
        # get_available_actions will offer appropriate general actions (like roll_dice)

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

        # Get current square details safely
        current_square_name = "Unknown (Off Board?)"
        current_square_type = "Unknown"
        if 0 <= player.position < len(self.board.squares):
            current_square = self.board.get_square(player.position)
            current_square_name = current_square.name
            current_square_type = current_square.square_type.value
        else:
            self.log_event(f"[Warning] Player {player.name} has invalid position: {player.position}")

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
                "chance": player.has_chance_gooj_card, # Corrected attribute name
                "community_chest": player.has_community_gooj_card # Corrected attribute name
            },
            "current_turn_player_id": self.current_player_index, # Main turn player
            "active_decision_player_id": player_id, # The player this state is for (could be different in auction/trade)
            "pending_decision_type": self.pending_decision_type,
            "pending_decision_context": self.pending_decision_context,
            "dice_roll_outcome_processed": self.dice_roll_outcome_processed,
            "last_dice_roll": self.dice if self.dice != (0,0) else None,
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
                sq_info["color_group"] = square_obj.color_group.value if hasattr(square_obj, 'color_group') else None
                if isinstance(square_obj, PropertySquare):
                    sq_info["rent_levels"] = square_obj.rent_levels
                    sq_info["house_price"] = square_obj.house_price
                    sq_info["num_houses"] = square_obj.num_houses
                elif isinstance(square_obj, RailroadSquare):
                    sq_info["base_rent"] = square_obj.base_rent 
                elif isinstance(square_obj, UtilitySquare):
                    # Rent depends on dice and num_owned, agent needs to know this rule or be told rent by GC.
                    pass # No specific static rent info here beyond what's in its class type
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
                    # Optionally, money and property details of others can be limited for harder AI challenge
                    # "money_approx": (p_other.money // 100) * 100, # Example of fuzzing money
                }
                game_state["other_players"].append(other_info)

        return game_state

    def _handle_jail_turn(self, player: Player) -> bool:
        """
        Handles a turn for a player in jail. Returns True if player got out of jail this turn.
        The agent will need to make a decision on how to get out.
        For now, implements a simple automatic logic for testing.
        """
        if not player.in_jail:
            return True # Not in jail, so effectively "out"

        self.log_event(f"{player.name} is in jail. Turn {player.jail_turns_remaining + 1} in jail.")
        player.attempt_to_get_out_of_jail() # Increments jail_turns_remaining

        # AGENT DECISION POINT: How to get out of jail?
        # Options: Pay $50, Use GOOJ Card, Roll Doubles.
        # Placeholder: try card, then try pay, then roll.
        if self._use_card_to_get_out_of_jail(player):
            return True
        
        if player.jail_turns_remaining <= 3: # Can attempt to roll for 3 turns
             # Agent might choose to pay before rolling on turns 1 or 2
            if player.money >= 50 and player.jail_turns_remaining == 3: # Force pay on 3rd turn if didn't roll out and can afford
                # Or agent decides to pay earlier.
                # For now, let's say if it's the 3rd failed roll attempt and they have money, they pay.
                # This part needs AI input. What if they *want* to roll on the 3rd turn?
                # Let's simplify: if agent *chooses* to pay (or is forced on 3rd turn)
                # For now, let AI decide to roll. If it fails on 3rd turn, then force pay or asset management.
                pass # Agent will call the specific tool like tool_try_rolling_doubles_to_get_out_of_jail

        # If after 3 turns of attempting (or choosing not to pay/use card), and still in jail:
        if player.jail_turns_remaining >= 3 and player.in_jail:
            self.log_event(f"{player.name} has been in jail for 3 turns. Must pay $50 or use a card if still not out.")
            if self._use_card_to_get_out_of_jail(player): # Try card again if available and not used
                 return True
            if self._pay_to_get_out_of_jail(player): # Try to pay
                 return True
            else:
                self.log_event(f"{player.name} could not pay to get out of jail. Must try to roll or manage assets.")
                # If they can't pay, they are stuck until they roll doubles or can pay or game ends.
                # Or the game rules might force asset selling here. For now, they just attempt to roll.
                # The agent needs to be aware of this situation.
                return False # Still in jail
        return False # Still in jail after this turn's attempt (unless rolled out)

    def _handle_jail_turn_initiation(self, player: Player) -> None:
        """Called at the start of a turn if player is in jail to set up decision options."""
        if player.in_jail:
            self.pending_decision_type = "jail_options"
            self.pending_decision_context = {"player_id": player.player_id}
            self.dice_roll_outcome_processed = True # True because we haven't rolled for main turn yet. Jail decision comes first.
        else:
            self._clear_pending_decision() # Should not happen if called correctly

    def execute_buy_property_decision(self, player_id: int, property_id_to_buy: int) -> bool:
        """Called by the agent's tool_buy_property when a buy decision is made."""
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
            self._resolve_current_action_segment() # Buy decision made and executed.
            return True
        else:
            self.log_event(f"{player.name} attempted to buy {square.name} but has insufficient funds (${player.money} < ${square.price}). Decision to buy/pass remains pending.")
            # IMPORTANT: Do NOT clear pending_decision_type here. dice_roll_outcome_processed remains False.
            # Agent should now be re-prompted (available actions will still include buy/pass).
            return False # Buy attempt failed due to funds.

    def _pass_on_buying_property_action(self, player: Player, square_to_pass: PurchasableSquare) -> bool:
        """Called by the corresponding tool when player passes on buying."""
        if not (self.pending_decision_type == "buy_or_auction_property" and 
                self.pending_decision_context.get("player_id") == player.player_id and 
                self.pending_decision_context.get("property_id") == square_to_pass.square_id):
            self.log_event(f"[Warning] _pass_on_buying_property_action called out of context for P{player.player_id}, Prop{square_to_pass.square_id}. Pending: '{self.pending_decision_type}', Ctx: {self.pending_decision_context}")
            return False
            
        self.log_event(f"{player.name} passed on buying {square_to_pass.name}. Initiating auction.")
        self._initiate_auction(square_to_pass.square_id)
        # _initiate_auction will set pending_decision_type = "auction_bid" and outcome_processed = False.
        return True

    def _initiate_auction(self, property_id: int) -> None:
        square = self.board.get_square(property_id)
        if not isinstance(square, PurchasableSquare) or square.owner_id is not None:
            self.log_event(f"[Error] Cannot auction {square.name}, not purchasable/unowned.")
            self._resolve_current_action_segment()
            return

        self.log_event(f"--- Auction Started for: {square.name} (Price: ${square.price}) ---")
        self.auction_in_progress = True
        self.auction_property_id = property_id
        self.auction_current_bid = 1 # Start bid at $1 (or some other minimum)
        self.auction_highest_bidder = None
        
        self.auction_participants = [p for p in self.players if not p.is_bankrupt]
        self.auction_active_bidders = list(self.auction_participants) # Initially all participants are active
        self.auction_player_has_bid_this_round = {p.player_id: False for p in self.auction_participants}

        if not self.auction_participants:
            self.log_event("No players eligible for auction. Property remains unowned.")
            self._conclude_auction(no_winner=True) 
            return
        
        # Start with the player to the left of the current turn player (who declined/triggered auction)
        start_player_index_in_all_players = self.current_player_index 
        # Find next non-bankrupt player in main player list order to start auction bidding
        found_starter = False
        for i in range(len(self.players)):
            next_idx_in_all_players = (start_player_index_in_all_players + 1 + i) % len(self.players)
            potential_starter = self.players[next_idx_in_all_players]
            if potential_starter in self.auction_participants:
                try:
                    self.auction_current_bidder_turn_index = self.auction_participants.index(potential_starter)
                    found_starter = True
                    break
                except ValueError: # Should not happen if participant list is correct
                    pass
        
        if not found_starter and self.auction_participants: # Fallback if above logic fails
             self.auction_current_bidder_turn_index = 0 
        elif not self.auction_participants: # Should be caught by earlier check
            self.log_event("Critical error: No participants for auction at start index phase.")
            self._conclude_auction(no_winner=True)
            return

        first_bidder = self.auction_active_bidders[self.auction_current_bidder_turn_index] if self.auction_active_bidders else None
        if not first_bidder:
            self.log_event("Critical error: No first bidder found. Concluding auction.")
            self._conclude_auction(no_winner=True)
            return

        self.log_event(f"Auction participants: {[p.name for p in self.auction_active_bidders]}. First to bid: {first_bidder.name}")

        self._set_pending_decision("auction_bid", 
                                 context={"property_id": self.auction_property_id, "current_bid": self.auction_current_bid, "highest_bidder_id": None, "player_to_bid_id": first_bidder.player_id}, 
                                 outcome_processed=False)

    def _get_next_auction_bidder(self) -> Optional[Player]:
        if not self.auction_active_bidders:
            return None
        # Iterate through the original participants list to maintain order, but only pick from active_bidders
        # This is complex. Simpler: iterate through auction_active_bidders directly by an index for that list.
        # Let's refine: the auction_current_bidder_turn_index should be an index for auction_active_bidders.
        # When a player passes/withdraws, they are removed from auction_active_bidders.
        # The index needs to be adjusted if an element before current index is removed.

        # Simpler turn order for active bidders for now:
        # The self.auction_current_bidder_turn_index will be index for self.auction_active_bidders
        if not self.auction_active_bidders: return None
        self.auction_current_bidder_turn_index = (self.auction_current_bidder_turn_index +1) % len(self.auction_active_bidders)
        return self.auction_active_bidders[self.auction_current_bidder_turn_index]


    def _handle_auction_bid(self, player: Player, bid_amount: int) -> None:
        if not self.auction_in_progress or self.pending_decision_type != "auction_bid" or self.pending_decision_context.get("player_to_bid_id") != player.player_id:
            self.log_event(f"[Warning] Invalid auction bid by {player.name}. State/Turn error.")
            return

        prop_name = self.board.get_square(self.auction_property_id).name if self.auction_property_id is not None else "Property"
        min_bid_increment = 1 # Can be configurable

        if bid_amount < (self.auction_current_bid + min_bid_increment) and self.auction_current_bid > 0: # Allow bid_amount == default starting bid (e.g. $1) if current_bid is 0 or initial minimal
             if self.auction_current_bid == 1 and bid_amount == 1 and self.auction_highest_bidder is None: # Allow first bid to be $1
                 pass # Valid first bid
             else:
                self.log_event(f"{player.name}'s bid ${bid_amount} for {prop_name} must be at least ${self.auction_current_bid + min_bid_increment}. Rejected.")
                self._set_pending_decision("auction_bid", self.pending_decision_context, outcome_processed=False) # Same player bids again
                return
        if player.money < bid_amount:
            self.log_event(f"{player.name}'s bid ${bid_amount} for {prop_name} exceeds money (${player.money}). Rejected.")
            self._set_pending_decision("auction_bid", self.pending_decision_context, outcome_processed=False) # Same player bids again
            return

        self.auction_current_bid = bid_amount
        self.auction_highest_bidder = player
        self.auction_player_has_bid_this_round = {pid: False for pid in self.auction_player_has_bid_this_round} # Reset for new round of passes
        self.auction_player_has_bid_this_round[player.player_id] = True
        self.log_event(f"{player.name} bids ${bid_amount} for {prop_name}. Highest bid: ${self.auction_current_bid} by {player.name}.")
        
        # Find current bidder's index in active_bidders to continue from there
        try:
            current_active_idx = self.auction_active_bidders.index(player)
            self.auction_current_bidder_turn_index = current_active_idx
        except ValueError:
            self.log_event(f"[Error] Bidder {player.name} not in active auction list. Concluding auction.")
            self._conclude_auction(no_winner=True if self.auction_highest_bidder is None else False)
            return

        next_bidder = self._get_next_auction_bidder()
        if not next_bidder : # Should mean only current bidder is left active, they win.
             self._conclude_auction()
             return

        self._set_pending_decision("auction_bid", 
                                 context={"property_id": self.auction_property_id, "current_bid": self.auction_current_bid, "highest_bidder_id": self.auction_highest_bidder.player_id, "player_to_bid_id": next_bidder.player_id}, 
                                 outcome_processed=False)

    def _handle_auction_pass(self, player: Player) -> None:
        if not self.auction_in_progress or self.pending_decision_type != "auction_bid" or self.pending_decision_context.get("player_to_bid_id") != player.player_id:
            self.log_event(f"[Warning] Invalid auction pass by {player.name}. State/Turn error.")
            return
        
        prop_name = self.board.get_square(self.auction_property_id).name if self.auction_property_id is not None else "Property"
        self.log_event(f"{player.name} passes on bidding for {prop_name}.")
        
        # Player is now out of this specific auction.
        if player in self.auction_active_bidders:
            # Find player's current index in active_bidders to correctly adjust turn index after removal
            try:
                passed_player_idx_in_active = self.auction_active_bidders.index(player)
                self.auction_active_bidders.remove(player)
                # If the removed player was before or at the current turn index for active_bidders, decrement it.
                if passed_player_idx_in_active <= self.auction_current_bidder_turn_index:
                    self.auction_current_bidder_turn_index = max(0, self.auction_current_bidder_turn_index - 1)
            except ValueError:
                 self.log_event(f"[Warning] Player {player.name} passed but was not in active_bidders list.")
        
        self.log_event(f"Active bidders for {prop_name}: {[p.name for p in self.auction_active_bidders]}")

        if not self.auction_active_bidders: # All active players passed.
            self._conclude_auction(no_winner=True if self.auction_highest_bidder is None else False)
        elif len(self.auction_active_bidders) == 1:
            # If only one active bidder remains, they are the winner (if there was a prior bid).
            if self.auction_highest_bidder == self.auction_active_bidders[0]:
                self._conclude_auction()
            elif self.auction_highest_bidder is None and self.auction_current_bid <= 1: # No valid bids yet, last one needs to bid or it's no sale
                self.auction_current_bidder_turn_index = 0 # only one left, their turn
                next_bidder = self.auction_active_bidders[0]
                self._set_pending_decision("auction_bid", 
                                         context={"property_id": self.auction_property_id, "current_bid": self.auction_current_bid, "highest_bidder_id": None, "player_to_bid_id": next_bidder.player_id}, 
                                         outcome_processed=False)
            else: # Highest bidder dropped out, last remaining person wins at current highest bid if they accept it by not passing.
                  # Or, if they were the highest bidder and others dropped, they win.
                  # This case is effectively: the only one left is the highest_bidder or becomes it.
                  self.auction_highest_bidder = self.auction_active_bidders[0]
                  self.log_event(f"{self.auction_highest_bidder.name} is the last bidder. Concluding auction.")
                  self._conclude_auction()
        else:
            # Still multiple active bidders. Continue to the next one.
            # _get_next_auction_bidder already handles wrap around for the reduced list.
            # auction_current_bidder_turn_index was adjusted above, so _get_next_auction_bidder should pick up correctly.
            current_bidder_of_pass = player # Player who just passed
            next_bidder = self.auction_active_bidders[self.auction_current_bidder_turn_index] 
            # Check if we have looped through all remaining active players and returned to the one who made the highest bid
            # This is the condition for ending the auction: highest bidder exists, and all other *active* players have passed consecutively.
            
            # A simple way to check if everyone else passed: has everyone in auction_active_bidders (excluding current highest_bidder if they are in it)
            # had a chance to bid since the last actual bid was made?
            # The self.auction_player_has_bid_this_round flag can track this.
            all_others_passed_since_last_bid = True
            if self.auction_highest_bidder:
                for p_active in self.auction_active_bidders:
                    if p_active != self.auction_highest_bidder and not self.auction_player_has_bid_this_round.get(p_active.player_id, True): # If not True, means they haven't bid/passed yet THIS round
                        all_others_passed_since_last_bid = False
                        break
            else: # No highest bidder yet, auction continues if >1 active
                all_others_passed_since_last_bid = False 
            
            if all_others_passed_since_last_bid and self.auction_highest_bidder:
                self._conclude_auction()
            else:
                self._set_pending_decision("auction_bid", 
                                        context={"property_id": self.auction_property_id, "current_bid": self.auction_current_bid, "highest_bidder_id": self.auction_highest_bidder.player_id if self.auction_highest_bidder else None, "player_to_bid_id": next_bidder.player_id}, 
                                        outcome_processed=False)

    def _conclude_auction(self, no_winner: bool = False) -> None:
        prop_id = self.auction_property_id
        prop_name = self.board.get_square(prop_id).name if prop_id is not None else "Property"

        if no_winner or self.auction_highest_bidder is None or (self.auction_current_bid == 1 and not self.auction_highest_bidder): # Consider $1 bid not enough if no one else bids
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
                if isinstance(property_square, PurchasableSquare): # Should always be true
                    property_square.owner_id = None # Ensure it's unowned if winner bankrupts
        
        # Reset all auction state variables
        self.auction_in_progress = False
        self.auction_property_id = None
        self.auction_current_bid = 0
        self.auction_highest_bidder = None
        self.auction_participants = []
        self.auction_active_bidders = []
        self.auction_player_has_bid_this_round = {}
        self.auction_current_bidder_turn_index = 0
        
        self._resolve_current_action_segment() # Auction process is complete.

    def _generate_trade_id(self) -> int:
        trade_id = self.next_trade_id
        self.next_trade_id += 1
        return trade_id

    def propose_trade_action(self, proposer_id: int, recipient_id: int, \
                             offered_property_ids: List[int], offered_money: int, offered_gooj_cards: int, 
                             requested_property_ids: List[int], requested_money: int, requested_gooj_cards: int) -> Optional[int]:
        """Initiated by an agent tool. Creates a trade offer and sets pending decision for recipient."""
        proposer = self.players[proposer_id]
        recipient = self.players[recipient_id]

        if proposer.is_bankrupt or recipient.is_bankrupt:
            self.log_event(f"Trade failed: {proposer.name} or {recipient.name} is bankrupt.")
            return None
        if proposer_id == recipient_id:
            self.log_event(f"Trade failed: Cannot trade with oneself.")
            return None
        
        for prop_id in offered_property_ids:
            square = self.board.get_square(prop_id)
            if not (isinstance(square, PurchasableSquare) and square.owner_id == proposer_id):
                self.log_event(f"Trade invalid: {proposer.name} does not own {square.name} or it's not tradable.")
                return None
            if isinstance(square, PropertySquare) and square.num_houses > 0:
                self.log_event(f"Trade invalid: {square.name} has buildings. Sell them first.")
                return None
        if proposer.money < offered_money:
            self.log_event(f"Trade invalid: {proposer.name} does not have ${offered_money} to offer.")
            return None
        
        num_proposer_gooj_chance = 1 if proposer.has_get_out_of_jail_chance_card else 0
        num_proposer_gooj_community = 1 if proposer.has_get_out_of_jail_community_chest_card else 0
        total_proposer_gooj = num_proposer_gooj_chance + num_proposer_gooj_community
        if total_proposer_gooj < offered_gooj_cards:
            self.log_event(f"Trade invalid: {proposer.name} does not have {offered_gooj_cards} Get Out of Jail Free cards.")
            return None

        # TODO: Validate requested items similarly against recipient's assets
        for prop_id in requested_property_ids:
            square = self.board.get_square(prop_id)
            if not (isinstance(square, PurchasableSquare) and square.owner_id == recipient_id):
                self.log_event(f"Trade invalid: {recipient.name} does not own requested {square.name} or it's not tradable.")
                return None
            if isinstance(square, PropertySquare) and square.num_houses > 0:
                self.log_event(f"Trade invalid: Requested {square.name} has buildings. Must be sold first.")
                return None
        if recipient.money < requested_money:
            self.log_event(f"Trade invalid: {recipient.name} does not have ${requested_money} to fulfill request.")
            return None
        num_recipient_gooj_chance = 1 if recipient.has_get_out_of_jail_chance_card else 0
        num_recipient_gooj_community = 1 if recipient.has_get_out_of_jail_community_chest_card else 0
        total_recipient_gooj = num_recipient_gooj_chance + num_recipient_gooj_community
        if total_recipient_gooj < requested_gooj_cards:
            self.log_event(f"Trade invalid: {recipient.name} does not have {requested_gooj_cards} Get Out of Jail Free cards to fulfill request.")
            return None

        trade_id = self._generate_trade_id()
        offer_items_proposer = []
        if offered_money > 0: offer_items_proposer.append(TradeOfferItem(item_type="money", quantity=offered_money))
        for prop_id in offered_property_ids: offer_items_proposer.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        # Simplified GOOJ card logic for offer structure: record which type is offered if possible
        temp_offered_gooj_cards = offered_gooj_cards
        if temp_offered_gooj_cards > 0 and proposer.has_get_out_of_jail_chance_card:
            offer_items_proposer.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=0, quantity=1)) # item_id 0 for chance, 1 for community (arbitrary)
            temp_offered_gooj_cards -=1
        if temp_offered_gooj_cards > 0 and proposer.has_get_out_of_jail_community_chest_card:
            offer_items_proposer.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=1, quantity=1))
            temp_offered_gooj_cards -=1
        
        requested_items_recipient = []
        if requested_money > 0: requested_items_recipient.append(TradeOfferItem(item_type="money", quantity=requested_money))
        for prop_id in requested_property_ids: requested_items_recipient.append(TradeOfferItem(item_type="property", item_id=prop_id, quantity=1))
        temp_requested_gooj_cards = requested_gooj_cards
        if temp_requested_gooj_cards > 0 and recipient.has_get_out_of_jail_chance_card: # Check if recipient has it to give
            requested_items_recipient.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=0, quantity=1))
            temp_requested_gooj_cards -= 1
        if temp_requested_gooj_cards > 0 and recipient.has_get_out_of_jail_community_chest_card:
            requested_items_recipient.append(TradeOfferItem(item_type="get_out_of_jail_card", item_id=1, quantity=1))
            temp_requested_gooj_cards -= 1

        offer = TradeOffer(
            trade_id=trade_id,
            proposer_id=proposer_id,
            recipient_id=recipient_id,
            items_offered_by_proposer=offer_items_proposer,
            items_requested_from_recipient=requested_items_recipient,
            turn_proposed=self.turn_count if hasattr(self, 'turn_count') else 0 
        )
        self.trade_offers[trade_id] = offer
        self.log_event(f"{proposer.name} proposed a trade (ID: {trade_id}) to {recipient.name}.")
        
        offered_descs = []
        for item in offer_items_proposer:
            if item.item_type == "money": desc = f"${item.quantity}"
            elif item.item_type == "property": desc = self.board.get_square(item.item_id).name if item.item_id is not None else "Unknown Property"
            elif item.item_type == "get_out_of_jail_card": desc = f"Get Out of Jail Free Card ({'Chance' if item.item_id == 0 else 'Community' if item.item_id == 1 else 'Unknown' })"
            else: desc = item.item_type
            offered_descs.append(desc)
        
        requested_descs = []
        for item in offer.items_requested_from_recipient:
            if item.item_type == "money": desc = f"${item.quantity}"
            elif item.item_type == "property": desc = self.board.get_square(item.item_id).name if item.item_id is not None else "Unknown Property"
            elif item.item_type == "get_out_of_jail_card": desc = f"Get Out of Jail Free Card ({'Chance' if item.item_id == 0 else 'Community' if item.item_id == 1 else 'Unknown' })"
            else: desc = item.item_type
            requested_descs.append(desc)

        self.log_event(f"Trade {trade_id} details: {proposer.name} offers [{', '.join(offered_descs)}] for [{', '.join(requested_descs)}] from {recipient.name}.")

        self._set_pending_decision("respond_to_trade_offer", 
                                 context={"trade_id": trade_id, "player_id": recipient_id}, 
                                 outcome_processed=True)
        return trade_id

    def _respond_to_trade_offer_action(self, player_id: int, trade_id: int, response: str, 
                                     counter_offered_prop_ids: Optional[List[int]] = None, 
                                     counter_offered_money: Optional[int] = None, 
                                     counter_offered_gooj_cards: Optional[int] = None,
                                     counter_requested_prop_ids: Optional[List[int]] = None, 
                                     counter_requested_money: Optional[int] = None, 
                                     counter_requested_gooj_cards: Optional[int] = None) -> bool:
        if trade_id not in self.trade_offers: self.log_event(f'[E] T{trade_id} NF'); self._clear_pending_decision(); return False
        offer = self.trade_offers[trade_id]
        if offer.recipient_id != player_id: self.log_event(f'[E] P{player_id} not recip T{trade_id}.'); return False
        if offer.status != "pending_response": self.log_event(f'[E] T{trade_id} not pending({offer.status}).'); self._clear_pending_decision(); return False
        
        player = self.players[player_id] 
        proposer = self.players[offer.proposer_id]
        self.log_event(f"{player.name} responds to T{trade_id} from {proposer.name} with: {response.upper()}")

        if response.lower() == "accept":
            if not (self._validate_trade_items(proposer.player_id, offer.items_offered_by_proposer) and \
                    self._validate_trade_items(player.player_id, offer.items_requested_from_recipient)):
                self.log_event(f"T{trade_id} conditions changed. Cancelled."); offer.status = "cancelled_conditions_changed"; self._resolve_current_action_segment(); return False
            
            try:
                mortgaged_props_received_by_player: List[Dict[str,Any]] = [] 
                mortgaged_props_received_by_proposer: List[Dict[str,Any]] = []

                # Perform asset transfers
                for item in offer.items_offered_by_proposer: # Proposer gives to Player
                    if item.item_type == "money": proposer.subtract_money(item.quantity); player.add_money(item.quantity)
                    elif item.item_type == "property":
                        sq = self.board.get_square(item.item_id)
                        proposer.remove_property_id(item.item_id); player.add_property_id(item.item_id); sq.owner_id = player.player_id
                        if sq.is_mortgaged: mortgaged_props_received_by_player.append({"property_id": item.item_id, "source_trade_id": trade_id})
                    elif item.item_type == "get_out_of_jail_card": self._transfer_gooj_card(proposer, player, item.item_id)
                
                for item in offer.items_requested_from_recipient: # Player gives to Proposer
                    if item.item_type == "money": player.subtract_money(item.quantity); proposer.add_money(item.quantity)
                    elif item.item_type == "property":
                        sq = self.board.get_square(item.item_id)
                        player.remove_property_id(item.item_id); proposer.add_property_id(item.item_id); sq.owner_id = proposer.player_id
                        if sq.is_mortgaged: mortgaged_props_received_by_proposer.append({"property_id": item.item_id, "source_trade_id": trade_id})
                    elif item.item_type == "get_out_of_jail_card": self._transfer_gooj_card(player, proposer, item.item_id)
                
                offer.status = "accepted"
                self.log_event(f"Trade {trade_id} accepted! Assets exchanged.")
                self._clear_pending_decision() # Current player's decision (respond_to_trade_offer) is resolved.

                # Add pending tasks for the original proposer if they received mortgaged properties.
                for task_data in mortgaged_props_received_by_proposer:
                    proposer.add_pending_mortgaged_property_task(task_data["property_id"], task_data["source_trade_id"])
                    self.log_event(f"Mortgaged property task for P{proposer.player_id} ({proposer.name}) to handle prop {task_data['property_id']} added.")

                # If the current player (original recipient) received mortgaged properties, initiate handling for them immediately.
                if mortgaged_props_received_by_player:
                    for task_data in mortgaged_props_received_by_player:
                         player.add_pending_mortgaged_property_task(task_data["property_id"], task_data["source_trade_id"])
                    self._handle_received_mortgaged_property_initiation(player) 
                    # _handle_received_mortgaged_property_initiation will set a new pending_decision for the current player.
                    # outcome_processed should remain True because the trade response is done.
                    self.dice_roll_outcome_processed = True 
                    return True 
                
                # If no new decision for current player from this trade acceptance.
                if not self.pending_decision_type: self._resolve_current_action_segment()
                return True
            except Exception as e: 
                self.log_event(f"[E] Asset transfer T{trade_id} fail: {e}. Cancelled."); offer.status = "failed_transfer"; self._resolve_current_action_segment(); return False

        elif response.lower() == "reject": # ... (reject logic as before, calls _resolve_current_action_segment())
            offer.status = "rejected"; self.log_event(f"T{trade_id} rejected by {player.name}."); self._resolve_current_action_segment(); return True
        
        elif response.lower() == "counter_offer": 
            offer.status = "countered"; self.log_event(f"{player.name} counters T{trade_id}."); self._clear_pending_decision()
            new_trade_id = self.propose_trade_action(
                player_id, offer.proposer_id, 
                counter_offered_prop_ids or [], counter_offered_money or 0, counter_offered_gooj_cards or 0,
                counter_requested_prop_ids or [], counter_requested_money or 0, counter_requested_gooj_cards or 0)
            if new_trade_id is not None: 
                self.trade_offers[new_trade_id].counter_offer_to_trade_id = trade_id
                self.log_event(f"Counter-offer (New T{new_trade_id}) sent to {proposer.name}.");
                # propose_trade_action sets pending_decision for the new recipient (original proposer).
                # The current player's (counter-offeror) action segment is resolved for this trade response.
                self.dice_roll_outcome_processed = True 
            else: 
                self.log_event(f"[E] Failed to create counter for T{trade_id}. Original trade ({offer.trade_id}) remains '{offer.status}'.");
                self.dice_roll_outcome_processed = True # Still resolve this player's segment for the attempted counter.
            return True
        else: # Invalid response
            self.log_event(f"[E] Invalid response '{response}' to T{trade_id}. Re-prompting {player.name}.");
            self._set_pending_decision("respond_to_trade_offer", self.pending_decision_context, True); return False

    def _handle_received_mortgaged_property_initiation(self, player: Player) -> None:
        next_task = player.get_next_pending_mortgaged_property_task()
        if next_task:
            self.log_event(f"{player.name} to handle received mortgaged prop ID {next_task['property_id']} from trade T{next_task['source_trade_id']}.");
            self._set_pending_decision("handle_received_mortgaged_property",
                                     context={"player_id": player.player_id, "property_id_to_handle": next_task["property_id"], "source_trade_id": next_task["source_trade_id"]},
                                     outcome_processed=True) # True, as this is a new decision point, not a dice outcome.
        else:
            self.log_event(f"No more pending mortgaged properties for {player.name} from trades to handle now.");
            self._resolve_current_action_segment()

    def _handle_received_mortgaged_property_action(self, player_id: int, property_id_acted_on: int, action: str) -> bool:
        player = self.players[player_id]
        if not (self.pending_decision_type == "handle_received_mortgaged_property" and \
                self.pending_decision_context.get("player_id") == player_id and \
                self.pending_decision_context.get("property_id_to_handle") == property_id_acted_on):
            self.log_event(f"[W] _handle_received_mortgaged_property_action called out of context/wrong property. Current context: {self.pending_decision_context}"); return False
        
        square = self.board.get_square(property_id_acted_on)
        if not (isinstance(square, PurchasableSquare) and square.is_mortgaged and square.owner_id == player_id):
            self.log_event(f"[E] Prop {property_id_acted_on} not mortgaged or not owned by {player.name}. Removing task.");
            player.resolve_pending_mortgaged_property_task(property_id_acted_on) 
            self._handle_received_mortgaged_property_initiation(player) 
            return False

        success = False
        paid_successfully_without_bankruptcy = False
        if action == "pay_fee":
            fee = int(square.mortgage_value * 0.1)
            if player.money >= fee:
                self._player_pays_amount(player, fee, f"10% fee for {square.name}") 
                paid_successfully_without_bankruptcy = player.money >= 0 and not player.is_bankrupt # Check after payment
                success = True # Attempt was made
            else: self.log_event(f"{player.name} cannot afford 10% fee (${fee}) for {square.name}.");
        elif action == "unmortgage_now":
            unmortgage_cost = int(square.mortgage_value * 1.1) 
            if player.money >= unmortgage_cost:
                # _player_pays_amount not used here as it's a direct payment for unmortgage, not to another entity from whom we get it back on bankruptcy
                player.subtract_money(unmortgage_cost) 
                if player.money < 0: # Went bankrupt trying to unmortgage
                    self.log_event(f"{player.name} went bankrupt trying to unmortgage {square.name}.");
                    self._check_and_handle_bankruptcy(player, unmortgage_cost - (unmortgage_cost + player.money) , None ) # player.money is negative
                    # Bankruptcy flow takes over, don't mark as unmortgaged yet.
                    success = False # Unmortgage effectively failed due to bankruptcy
                else:
                    square.is_mortgaged = False
                    self.log_event(f"{square.name} unmortgaged for ${unmortgage_cost}."); success = True
                    paid_successfully_without_bankruptcy = True 
            else: self.log_event(f"{player.name} cannot afford to unmortgage {square.name} for ${unmortgage_cost}.");
        else: self.log_event(f"[E] Invalid action '{action}' for received mortgaged property.");

        if success and paid_successfully_without_bankruptcy: # Only resolve if successful and didn't trigger immediate bankruptcy from this action
            player.resolve_pending_mortgaged_property_task(property_id_acted_on)
        
        # Always re-initiate to check for more properties or to resolve the segment if list is now empty,
        # unless asset liquidation has taken precedence.
        if self.pending_decision_type != "asset_liquidation_for_debt":
            self._handle_received_mortgaged_property_initiation(player) 
        return success

    def get_available_actions(self, player_id: int) -> List[str]:
        actions: List[str] = []
        player = self.players[player_id]

        if player.is_bankrupt: return []

        # --- Phase 1: Specific Pending Decisions --- 
        if self.pending_decision_type == "jail_options":
            if player.in_jail: 
                if player.has_chance_gooj_card or player.has_community_gooj_card: actions.append("tool_use_get_out_of_jail_card")
                if player.money >= 50: actions.append("tool_pay_bail")
                if player.jail_turns_remaining < 3: actions.append("tool_roll_for_doubles_to_get_out_of_jail")
                if not actions and player.jail_turns_remaining >=3: actions.append("tool_do_nothing") 
            else: self._clear_pending_decision()
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
            if self.pending_decision_context.get("player_to_bid_id") == player_id and player_id in [p.player_id for p in self.auction_active_bidders]: actions.extend(["tool_bid_on_auction", "tool_pass_auction_bid", "tool_withdraw_from_auction"])
            elif player_id in [p.player_id for p in self.auction_active_bidders]: actions.append("tool_wait") 
        elif self.pending_decision_type == "respond_to_trade_offer":
             if self.pending_decision_context.get("player_id") == player_id: actions.extend(["tool_accept_trade", "tool_reject_trade", "tool_propose_counter_offer"]) 
             else: self._clear_pending_decision()
        elif self.pending_decision_type == "handle_received_mortgaged_property":
            if self.pending_decision_context.get("player_id") == player_id and self.pending_decision_context.get("property_id_to_handle") is not None:
                actions.extend(["tool_pay_mortgage_interest_fee", "tool_unmortgage_property_immediately"]) 
            else: self._clear_pending_decision()

        # --- Phase 2: General Turn Actions ---
        if not actions and self.pending_decision_type is None: 
            if self.current_player_index == player_id:
                if not player.in_jail: 
                    if self.dice_roll_outcome_processed: # Pre-roll or after a segment fully resolved
                        actions.append("tool_roll_dice")
                        # Offer asset management if any are possible
                        # Build House: Owns all unmortgaged properties in a color group, has money, property can have more houses.
                        can_build_on_any_property = False
                        for p_id in player.properties_owned_ids:
                            square = self.board.get_square(p_id)
                            if isinstance(square, PropertySquare) and square.owner_id == player_id and \
                               not square.is_mortgaged and square.num_houses < 5 and player.money >= square.house_price and \
                               square.group_id >= 3: # group_id 3-10 are color properties, 1=RR, 2=Util
                                # Check for monopoly (owns all in group, all unmortgaged in group)
                                owns_all_in_group_unmortgaged = True
                                if not square.group_members: # Should be populated by Board
                                    owns_all_in_group_unmortgaged = False
                                else:
                                    for member_id in square.group_members:
                                        member_square = self.board.get_square(member_id)
                                        if not (member_square.owner_id == player_id and 
                                                (not hasattr(member_square, 'is_mortgaged') or not member_square.is_mortgaged)):
                                            owns_all_in_group_unmortgaged = False; break
                                if owns_all_in_group_unmortgaged:
                                    # Check even building rule: can build on this square if it has fewest houses (or tied) in the group
                                    # This simplified check allows offering tool_build_house if *any* such property exists.
                                    # Agent then needs to pick a valid property_id for the tool.
                                    min_houses_in_group = min(self.board.get_square(m_id).num_houses for m_id in square.group_members if self.board.get_square(m_id).owner_id == player_id)
                                    if square.num_houses == min_houses_in_group:
                                        can_build_on_any_property = True; break
                        if can_build_on_any_property: actions.append("tool_build_house")
                        
                        if any(isinstance(sq := self.board.get_square(pid), PropertySquare) and sq.owner_id == player_id and sq.num_houses > 0 for pid in player.properties_owned_ids): actions.append("tool_sell_house")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and not sq.is_mortgaged and not (isinstance(sq, PropertySquare) and sq.num_houses > 0) for pid in player.properties_owned_ids): actions.append("tool_mortgage_property")
                        if any(isinstance(sq := self.board.get_square(pid), PurchasableSquare) and sq.owner_id == player_id and sq.is_mortgaged and player.money >= int(sq.mortgage_value*1.1) for pid in player.properties_owned_ids): actions.append("tool_unmortgage_property")
                        if len([p_other for p_other in self.players if not p_other.is_bankrupt and p_other.player_id != player_id]) > 0: actions.append("tool_propose_trade")
                        actions.append("tool_end_turn")
                    # Note: If dice_roll_outcome_processed is False, it means GC is handling a landing/card that might set a new pending_decision.
                    # The main loop should wait for GC state to update before asking agent again, unless a specific decision is already pending.
                    # So, if actions is still empty here AND pending_decision_type is None AND dice_roll_outcome_processed is False, it implies a wait state for GC.
                    if not actions and not self.dice_roll_outcome_processed:
                        actions.append("tool_wait") # Waiting for GC to resolve current dice roll action

                    actions.append("tool_resign_game")
                elif player.in_jail: 
                    self.log_event(f"[Info] P{player_id} ({player.name}) in jail, no specific jail action pending. Offering end_turn.")
                    actions.append("tool_end_turn") 
            else: # Not current player's turn for general actions.
                actions.append("tool_wait")

        # Final fallback
        if not actions and not player.is_bankrupt: 
            is_main_turn_player_active_slot = (self.current_player_index == player_id and self.pending_decision_type is None and self.dice_roll_outcome_processed)
            is_auction_bidder_turn = (self.pending_decision_type == "auction_bid" and self.pending_decision_context.get("player_to_bid_id") == player_id)
            is_trade_responder_turn = (self.pending_decision_type == "respond_to_trade_offer" and self.pending_decision_context.get("player_id") == player_id)
            is_mortgage_handler_turn = (self.pending_decision_type == "handle_received_mortgaged_property" and self.pending_decision_context.get("player_id") == player_id)
            is_asset_liquidator_turn = (self.pending_decision_type == "asset_liquidation_for_debt" and self.pending_decision_context.get("player_id") == player_id)
            can_act = is_main_turn_player_active_slot or is_auction_bidder_turn or is_trade_responder_turn or is_mortgage_handler_turn or is_asset_liquidator_turn
            
            # Corrected f-string closing below
            self.log_event(f"[Fallback Warning] No actions for P{player_id} ({player.name}). Pend: {self.pending_decision_type}, DiceDone: {self.dice_roll_outcome_processed}, CanAct: {can_act}.")
            if can_act : 
                actions.append("tool_end_turn") 
            else:
                actions.append("tool_wait")

        return list(dict.fromkeys(actions))

if __name__ == '__main__':
    # Basic test of GameController initialization
    controller = GameController(num_players=4)
    controller.start_game()
    print(f"Current player: {controller.get_current_player().name}")
    d1, d2 = controller.roll_dice()
    print(f"Dice: {d1}, {d2}")
    
    # Test game state generation
    gs = controller.get_game_state_for_agent(controller.get_current_player().player_id)
    import json
    # print(json.dumps(gs, indent=2))
    print(f"Generated game state for {gs['my_name']}")
    print(f"Money: {gs['my_money']}")
    print(f"First square name: {gs['board_squares'][1]['name']}")
    print(f"Log: {gs['game_log_tail']}") 
    print(f"Log: {gs['game_log_tail']}") 