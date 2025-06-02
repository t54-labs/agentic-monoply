from typing import List, Dict, Tuple, Optional, Any
import random

from .property import (
    BaseSquare, PropertySquare, RailroadSquare, UtilitySquare, ActionSquare, TaxSquare, SpecialSquare,
    SquareType, PropertyColor, PurchasableSquare
)

# Card actions could be simple functions or more complex objects later
# For now, a tuple: (description: str, action_type: str, value: any)
CardData = Tuple[str, str, Any]

class Board:
    def __init__(self):
        self.squares: List[BaseSquare] = self._initialize_squares_and_groups()
        
        self.community_chest_cards: List[CardData] = self._initialize_community_chest_cards()
        self.chance_cards: List[CardData] = self._initialize_chance_cards()
        
        self.current_community_chest_card_index: int = 0
        self.current_chance_card_index: int = 0
        
        self.shuffle_chance_cards()
        self.shuffle_community_chest_cards()

    def _initialize_squares_and_groups(self) -> List[BaseSquare]:
        squares = [None] * 40 # type: List[Optional[BaseSquare]]

        # Data based on classicedition.js (name, price, color_group_enum, group_id_from_js, rents..., house_price)
        # group_id: Railroads=1, Utilities=2, Brown=3, LightBlue=4, Pink=5, Orange=6, Red=7, Yellow=8, Green=9, DarkBlue=10
        # Non-purchasable squares will have a placeholder group_id (e.g., 0 or a specific higher number)

        squares[0] = SpecialSquare(0, "GO", SquareType.GO)
        squares[1] = PropertySquare(1, "Mediterranean Avenue", 60, 30, 3, PropertyColor.BROWN, [2, 10, 30, 90, 160, 250], 50)
        squares[2] = ActionSquare(2, "Community Chest", SquareType.COMMUNITY_CHEST)
        squares[3] = PropertySquare(3, "Baltic Avenue", 60, 30, 3, PropertyColor.BROWN, [4, 20, 60, 180, 320, 450], 50)
        squares[4] = TaxSquare(4, "Income Tax", 200)
        squares[5] = RailroadSquare(5, "Reading Railroad", group_id=1)
        squares[6] = PropertySquare(6, "Oriental Avenue", 100, 50, 4, PropertyColor.LIGHT_BLUE, [6, 30, 90, 270, 400, 550], 50)
        squares[7] = ActionSquare(7, "Chance", SquareType.CHANCE)
        squares[8] = PropertySquare(8, "Vermont Avenue", 100, 50, 4, PropertyColor.LIGHT_BLUE, [6, 30, 90, 270, 400, 550], 50)
        squares[9] = PropertySquare(9, "Connecticut Avenue", 120, 60, 4, PropertyColor.LIGHT_BLUE, [8, 40, 100, 300, 450, 600], 50)
        squares[10] = SpecialSquare(10, "Jail / Just Visiting", SquareType.JAIL_VISITING)
        squares[11] = PropertySquare(11, "St. Charles Place", 140, 70, 5, PropertyColor.PINK, [10, 50, 150, 450, 625, 750], 100)
        squares[12] = UtilitySquare(12, "Electric Company", group_id=2)
        squares[13] = PropertySquare(13, "States Avenue", 140, 70, 5, PropertyColor.PINK, [10, 50, 150, 450, 625, 750], 100)
        squares[14] = PropertySquare(14, "Virginia Avenue", 160, 80, 5, PropertyColor.PINK, [12, 60, 180, 500, 700, 900], 100)
        squares[15] = RailroadSquare(15, "Pennsylvania Railroad", group_id=1)
        squares[16] = PropertySquare(16, "St. James Place", 180, 90, 6, PropertyColor.ORANGE, [14, 70, 200, 550, 750, 950], 100)
        squares[17] = ActionSquare(17, "Community Chest", SquareType.COMMUNITY_CHEST)
        squares[18] = PropertySquare(18, "Tennessee Avenue", 180, 90, 6, PropertyColor.ORANGE, [14, 70, 200, 550, 750, 950], 100)
        squares[19] = PropertySquare(19, "New York Avenue", 200, 100, 6, PropertyColor.ORANGE, [16, 80, 220, 600, 800, 1000], 100)
        squares[20] = SpecialSquare(20, "Free Parking", SquareType.FREE_PARKING)
        squares[21] = PropertySquare(21, "Kentucky Avenue", 220, 110, 7, PropertyColor.RED, [18, 90, 250, 700, 875, 1050], 150)
        squares[22] = ActionSquare(22, "Chance", SquareType.CHANCE)
        squares[23] = PropertySquare(23, "Indiana Avenue", 220, 110, 7, PropertyColor.RED, [18, 90, 250, 700, 875, 1050], 150)
        squares[24] = PropertySquare(24, "Illinois Avenue", 240, 120, 7, PropertyColor.RED, [20, 100, 300, 750, 925, 1100], 150)
        squares[25] = RailroadSquare(25, "B. & O. Railroad", group_id=1)
        squares[26] = PropertySquare(26, "Atlantic Avenue", 260, 130, 8, PropertyColor.YELLOW, [22, 110, 330, 800, 975, 1150], 150)
        squares[27] = PropertySquare(27, "Ventnor Avenue", 260, 130, 8, PropertyColor.YELLOW, [22, 110, 330, 800, 975, 1150], 150)
        squares[28] = UtilitySquare(28, "Water Works", group_id=2)
        squares[29] = PropertySquare(29, "Marvin Gardens", 280, 140, 8, PropertyColor.YELLOW, [24, 120, 360, 850, 1025, 1200], 150)
        squares[30] = SpecialSquare(30, "Go To Jail", SquareType.GO_TO_JAIL)
        squares[31] = PropertySquare(31, "Pacific Avenue", 300, 150, 9, PropertyColor.GREEN, [26, 130, 390, 900, 1100, 1275], 200)
        squares[32] = PropertySquare(32, "North Carolina Avenue", 300, 150, 9, PropertyColor.GREEN, [26, 130, 390, 900, 1100, 1275], 200)
        squares[33] = ActionSquare(33, "Community Chest", SquareType.COMMUNITY_CHEST)
        squares[34] = PropertySquare(34, "Pennsylvania Avenue", 320, 160, 9, PropertyColor.GREEN, [28, 150, 450, 1000, 1200, 1400], 200)
        squares[35] = RailroadSquare(35, "Short Line Railroad", group_id=1)
        squares[36] = ActionSquare(36, "Chance", SquareType.CHANCE)
        squares[37] = PropertySquare(37, "Park Place", 350, 175, 10, PropertyColor.DARK_BLUE, [35, 175, 500, 1100, 1300, 1500], 200)
        squares[38] = TaxSquare(38, "Luxury Tax", 100)
        squares[39] = PropertySquare(39, "Boardwalk", 400, 200, 10, PropertyColor.DARK_BLUE, [50, 200, 600, 1400, 1700, 2000], 200)
        
        if any(s is None for s in squares): raise RuntimeError("Not all squares initialized!")
        final_squares = [s for s in squares if s is not None] # type: List[BaseSquare]

        # Populate group_members for all PurchasableSquares
        groups: Dict[int, List[int]] = {}
        for i, square_obj in enumerate(final_squares):
            if isinstance(square_obj, PurchasableSquare):
                if square_obj.group_id not in groups:
                    groups[square_obj.group_id] = []
                groups[square_obj.group_id].append(i) # Store square_id (which is its index)
        
        for square_obj in final_squares:
            if isinstance(square_obj, PurchasableSquare):
                if square_obj.group_id in groups:
                    square_obj.group_members = groups[square_obj.group_id]

        return final_squares

    def get_square(self, square_id: int) -> BaseSquare:
        if not (0 <= square_id < len(self.squares)):
            raise ValueError(f"Square ID {square_id} is out of bounds.")
        return self.squares[square_id]

    def _initialize_community_chest_cards(self) -> List[CardData]:
        # Based on classic Monopoly cards, actions will need specific handlers in GameController
        cards = [
            ("Advance to GO (Collect $200)", "move_to_exact", 0),
            ("Bank error in your favor. Collect $200", "receive_money", 200),
            ("Doctor's fees. Pay $50", "pay_money", 50),
            ("From sale of stock you get $50", "receive_money", 50),
            ("Get Out of Jail Free", "get_out_of_jail_card", "community_chest"),
            ("Go to Jail. Go directly to jail. Do not pass GO, do not collect $200", "go_to_jail", None),
            ("Grand Opera Night. Collect $50 from every player for opening night seats", "receive_from_players", 50),
            ("Holiday Fund matures. Receive $100", "receive_money", 100),
            ("Income tax refund. Collect $20", "receive_money", 20),
            ("It is your birthday. Collect $10 from every player", "receive_from_players", 10), # Variant
            ("Life insurance matures. Collect $100", "receive_money", 100),
            ("Pay hospital fees of $100", "pay_money", 100),
            ("Pay school fees of $50", "pay_money", 50),
            ("Receive $25 consultancy fee", "receive_money", 25),
            ("You are assessed for street repairs. $40 per house, $115 per hotel", "street_repairs", (40, 115)),
            ("You have won second prize in a beauty contest. Collect $10", "receive_money", 10),
            # ("You inherit $100", "receive_money", 100) # Example of one not always present
        ]
        return cards

    def _initialize_chance_cards(self) -> List[CardData]:
        cards = [
            ("Advance to GO (Collect $200)", "move_to_exact", 0),
            ("Advance to Illinois Ave. If you pass GO, collect $200", "move_to_exact_with_go_check", 24),
            ("Advance to St. Charles Place. If you pass GO, collect $200", "move_to_exact_with_go_check", 11),
            ("Advance to the nearest Utility. If unowned, you may buy it from the Bank. If owned, throw dice and pay owner a total ten times amount thrown.", "advance_to_nearest", "utility"),
            ("Advance to the nearest Railroad and pay owner twice the rental to which he/she is otherwise entitled. If Railroad is unowned, you may buy it from the Bank.", "advance_to_nearest_railroad_pay_double", None),
            ("Bank pays you dividend of $50", "receive_money", 50),
            ("Get Out of Jail Free. This card may be kept until needed, or traded/sold.", "get_out_of_jail_card", "chance"),
            ("Go Back 3 Spaces", "move_relative", -3),
            ("Go to Jail. Go directly to Jail. Do not pass GO, do not collect $200", "go_to_jail", None),
            ("Make general repairs on all your property. For each house pay $25. For each hotel $100", "street_repairs", (25, 100)),
            ("Pay poor tax of $15", "pay_money", 15),
            ("Take a trip to Reading Railroad. If you pass GO collect $200", "move_to_exact_with_go_check", 5),
            ("You have been elected Chairman of the Board. Pay each player $50", "pay_players", 50),
            ("Your building loan matures. Collect $150", "receive_money", 150),
            # ("Advance to Boardwalk", "move_to_exact_with_go_check", 39), # One variant, might be too powerful early
            ("Advance token to nearest Railroad and pay owner twice the rental to which he/she is otherwise entitled. (There are two of these)", "advance_to_nearest_railroad_pay_double", None), # Second instance of this card
        ]
        return cards

    def shuffle_community_chest_cards(self) -> None:
        random.shuffle(self.community_chest_cards)
        self.current_community_chest_card_index = 0

    def shuffle_chance_cards(self) -> None:
        random.shuffle(self.chance_cards)
        self.current_chance_card_index = 0

    def draw_community_chest_card(self) -> Optional[CardData]:
        if not self.community_chest_cards: return None
        card = self.community_chest_cards[self.current_community_chest_card_index]
        self.current_community_chest_card_index = (self.current_community_chest_card_index + 1) % len(self.community_chest_cards)
        # Special handling for Get Out of Jail Free: it's removed from the deck until used/returned.
        # This simple model just cycles. A more complex one would remove it.
        # If we implement card removal, need to handle reshuffling when deck is empty.
        return card

    def draw_chance_card(self) -> Optional[CardData]:
        if not self.chance_cards: return None
        card = self.chance_cards[self.current_chance_card_index]
        self.current_chance_card_index = (self.current_chance_card_index + 1) % len(self.chance_cards)
        # Similar to Community Chest, Get Out of Jail Free card might be handled differently.
        return card

    def get_properties_in_group(self, color_group: PropertyColor) -> List[PurchasableSquare]:
        # Ensure to import or define PurchasableSquare if not done
        # from .property import PurchasableSquare 
        return [sq for sq in self.squares 
                if isinstance(sq, PurchasableSquare) and sq.color_group == color_group]

    def get_railroads(self) -> List[RailroadSquare]:
        # from .property import RailroadSquare
        return [sq for sq in self.squares if isinstance(sq, RailroadSquare)]

    def get_utilities(self) -> List[UtilitySquare]:
        # from .property import UtilitySquare
        return [sq for sq in self.squares if isinstance(sq, UtilitySquare)] 