from typing import List, Set, Optional, Dict, Any
# It's good practice to import specific classes if possible,
# but for now, to avoid circular dependencies before all files are set up,
# we might use forward references with strings or just 'object' if PropertySquare is not yet fully defined
# For now, let's assume we will import it properly once board.py and property.py are stable.
# from .property import PurchasableSquare # This will be the eventual import

INITIAL_MONEY = 1500
INITIAL_POSITION = 0 # GO square

class Player:
    def __init__(self, player_id: int, name: str, is_ai: bool = False):
        self.player_id: int = player_id
        self.name: str = name
        self.is_ai: bool = is_ai # To distinguish between human and AI agent

        self.money: int = INITIAL_MONEY
        self.position: int = INITIAL_POSITION # square_id from 0-39
        
        # Store IDs of properties owned. The actual PropertySquare objects will be managed by the Board or GameController.
        self.properties_owned_ids: Set[int] = set() 
        
        self.in_jail: bool = False
        self.jail_turns_remaining: int = 0 # Number of turns spent in jail attempting to roll doubles
        # Specific Get Out of Jail Free cards
        self.has_chance_gooj_card: bool = False
        self.has_community_gooj_card: bool = False 
        
        self.is_bankrupt: bool = False
        # New attribute to track mortgaged properties received from trades that need handling
        self.pending_mortgaged_properties_to_handle: List[Dict[str, Any]] = [] # List of {property_id: int, source_trade_id: int}

    def __str__(self) -> str:
        jail_status = ", In Jail" if self.in_jail else ""
        bankrupt_status = ", BANKRUPT" if self.is_bankrupt else ""
        gooj_status = []
        if self.has_chance_gooj_card: gooj_status.append("Chance")
        if self.has_community_gooj_card: gooj_status.append("CommunityChest")
        gooj_str = f", GOOJ: {', '.join(gooj_status) if gooj_status else 'None'}"
        pending_mort_str = f", PendingMort: {len(self.pending_mortgaged_properties_to_handle)}" if self.pending_mortgaged_properties_to_handle else ""

        return (f"Player {self.player_id}: {self.name} (${self.money}, Position: {self.position}{jail_status}, "
                f"Properties: {len(self.properties_owned_ids)}{gooj_str}{pending_mort_str})"
                f"{bankrupt_status}")

    def add_money(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("Amount to add must be non-negative.")
        if not self.is_bankrupt:
            self.money += amount

    def subtract_money(self, amount: int) -> bool:
        """
        Subtracts money from the player. 
        Returns True if the player can afford the payment, False otherwise.
        Does not automatically handle bankruptcy here, that's for the game controller.
        """
        if amount < 0:
            raise ValueError("Amount to subtract must be non-negative.")
        if self.is_bankrupt: # Bankrupt players can't pay
            return False 
            
        self.money -= amount # Allow money to go negative, GC handles bankruptcy check
        return self.money >= 0 # Returns true if still solvent after this subtraction

    def move_to(self, new_position: int, passed_go: bool, go_salary: int = 200) -> None:
        if not (0 <= new_position < 40): # Assuming 40 squares
            raise ValueError("New position is out of board bounds.")
        
        self.position = new_position
        # if passed_go: # This logic is now in GameController._move_player
        #     self.add_money(go_salary)
        #     print(f"{self.name} passed GO and collected ${go_salary}.") # Placeholder for game log

    def add_property_id(self, property_id: int) -> None:
        self.properties_owned_ids.add(property_id)

    def remove_property_id(self, property_id: int) -> None:
        if property_id in self.properties_owned_ids:
            self.properties_owned_ids.remove(property_id)
        # else: error or warning?

    def get_net_worth(self, board_squares: list) -> int: # board_squares would be a list of all Square objects
        """Calculates player's net worth: cash + unmortgaged property values + mortgaged property values (at mortgage value) + houses/hotels value."""
        net_worth = self.money
        
        # This requires access to the actual square objects to get their prices/mortgage values/house prices
        # We'll need to pass the board or a way to look up square details
        # from .property import PurchasableSquare, PropertySquare # Delayed import
        
        for prop_id in self.properties_owned_ids:
            square = board_squares[prop_id]
            # Check if square is a PurchasableSquare, then PropertySquare for houses.
            # This dynamic check is a bit fragile. Better to have a clear way to get these values.
            if hasattr(square, 'is_mortgaged'): # Check if it's a PurchasableSquare or subclass
                if square.is_mortgaged:
                    net_worth += square.mortgage_value
                else:
                    net_worth += square.price
                    if hasattr(square, 'num_houses') and hasattr(square, 'house_price'): # Check if it's a PropertySquare
                        net_worth += square.num_houses * square.house_price # num_houses = 5 for hotel, house_price should be for one house
        return net_worth


    def go_to_jail(self) -> None:
        self.position = 10 # Jail square_id
        self.in_jail = True
        self.jail_turns_remaining = 0 # Reset turn counter for attempts to get out

    def leave_jail(self) -> None:
        self.in_jail = False
        self.jail_turns_remaining = 0
        
    def attempt_to_get_out_of_jail(self) -> None:
        """Increments the count of turns spent trying to roll out of jail."""
        if self.in_jail:
            self.jail_turns_remaining +=1

    def add_get_out_of_jail_card(self, card_type: str) -> None: 
        card_type = card_type.lower()
        if card_type == "chance":
            self.has_chance_gooj_card = True
        elif card_type == "community_chest" or card_type == "community": # Allow short form
            self.has_community_gooj_card = True
        else:
            # Log error or raise ValueError for robustness, but for now, silent if unknown type
            print(f"[Warning] Player.add_get_out_of_jail_card: Unknown card type '{card_type}\".")

    def use_get_out_of_jail_card(self) -> Optional[str]:
        """Uses a Get Out of Jail Free card. Prefers Chance card if both are available. Returns type of card used or None."""
        if self.has_chance_gooj_card:
            self.has_chance_gooj_card = False
            self.leave_jail()
            return "chance"
        elif self.has_community_gooj_card:
            self.has_community_gooj_card = False
            self.leave_jail()
            return "community_chest"
        return None

    def declare_bankrupt(self, creditor_id: Optional[int] = None) -> None: # creditor_id=0 for bank
        self.is_bankrupt = True
        self.money = 0 # Or handle asset transfer logic here/elsewhere
        print(f"{self.name} has declared bankruptcy!") # Placeholder for game log
        # Assets transfer logic would be handled by GameController 

    def add_pending_mortgaged_property_task(self, property_id: int, source_trade_id: int) -> None:
        """Adds a mortgaged property received from a trade that needs a decision."""
        self.pending_mortgaged_properties_to_handle.append({"property_id": property_id, "source_trade_id": source_trade_id})

    def get_next_pending_mortgaged_property_task(self) -> Optional[Dict[str, Any]]:
        """Gets the next mortgaged property task, does not remove it yet."""
        if self.pending_mortgaged_properties_to_handle:
            return self.pending_mortgaged_properties_to_handle[0]
        return None

    def resolve_pending_mortgaged_property_task(self, property_id: int) -> None:
        """Removes a specific mortgaged property task after it has been handled."""
        self.pending_mortgaged_properties_to_handle = [
            task for task in self.pending_mortgaged_properties_to_handle if task["property_id"] != property_id
        ] 