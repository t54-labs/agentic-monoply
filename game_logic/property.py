from enum import Enum
from typing import Optional, List, Any

class SquareType(Enum):
    PROPERTY = "PROPERTY"
    RAILROAD = "RAILROAD"
    UTILITY = "UTILITY"
    CHANCE = "CHANCE"
    COMMUNITY_CHEST = "COMMUNITY_CHEST"
    TAX = "TAX"
    GO = "GO"
    JAIL_VISITING = "JAIL_VISITING"
    FREE_PARKING = "FREE_PARKING"
    GO_TO_JAIL = "GO_TO_JAIL"

class PropertyColor(Enum):
    BROWN = "BROWN"
    LIGHT_BLUE = "LIGHT_BLUE"
    PINK = "PINK"
    ORANGE = "ORANGE"
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    DARK_BLUE = "DARK_BLUE"
    NONE = "NONE" # For railroads, utilities, etc.

class BaseSquare:
    def __init__(self, square_id: int, name: str, square_type: SquareType):
        self.square_id = square_id # 0-39
        self.name = name
        self.square_type = square_type

    def __str__(self):
        return f"{self.name} (Type: {self.square_type.value})"

class PurchasableSquare(BaseSquare):
    def __init__(self, square_id: int, name: str, square_type: SquareType, price: int, mortgage_value: int, 
                 group_id: int, # Changed from groupNumber, corresponds to classic groupNumber
                 color_group: PropertyColor = PropertyColor.NONE # color_group is more for visual/strict typing of color properties
                 ):
        super().__init__(square_id, name, square_type)
        self.price = price
        self.mortgage_value = mortgage_value # Typically price / 2
        self.owner_id: Optional[int] = None # Player ID, None if unowned (bank)
        self.is_mortgaged: bool = False
        self.group_id = group_id # e.g. 1 for railroads, 3 for browns, etc.
        self.color_group = color_group # Specific enum for colored properties
        self.group_members: List[int] = [] # List of square_ids in the same monopoly group, to be populated by Board

    def __str__(self):
        owner_status = f"Owner: Player {self.owner_id}" if self.owner_id is not None else "Unowned"
        mortgage_status = ", Mortgaged" if self.is_mortgaged else ""
        return f"{super().__str__()} - Price: ${self.price}, {owner_status}{mortgage_status}"

class PropertySquare(PurchasableSquare):
    def __init__(self, square_id: int, name: str, price: int, mortgage_value: int, 
                 group_id: int, color_group: PropertyColor, 
                 rent_levels: List[int], house_price: int):
        super().__init__(square_id, name, SquareType.PROPERTY, price, mortgage_value, group_id, color_group)
        # rent_levels: [base_rent, rent_1_house, rent_2_houses, rent_3_houses, rent_4_houses, rent_hotel]
        if len(rent_levels) != 6:
            raise ValueError("Rent levels must contain 6 values.")
        self.rent_levels = rent_levels
        self.house_price = house_price
        self.num_houses: int = 0 # 0-4 houses, 5 means a hotel

    def get_rent(self, num_properties_in_group_owned_by_owner: int = 1, total_properties_in_group: int = 1) -> int:
        if self.is_mortgaged or self.owner_id is None:
            return 0
        
        if self.num_houses == 0: # No houses
            # Rent is doubled on unimproved lots if player owns all lots of the color-group
            if num_properties_in_group_owned_by_owner == total_properties_in_group:
                return self.rent_levels[0] * 2
            return self.rent_levels[0]
        elif self.num_houses <= 4: # 1-4 houses
            return self.rent_levels[self.num_houses]
        elif self.num_houses == 5: # Hotel (represented by 5 houses)
            return self.rent_levels[5]
        return 0 # Should not happen

    def __str__(self):
        house_display = "Hotel" if self.num_houses == 5 else f"{self.num_houses} Houses"
        details = f", Houses: {house_display}" if self.num_houses > 0 else ""
        return f"{super().__str__()}{details}, Rent (0 Houses): ${self.rent_levels[0]}, House Price: ${self.house_price}"

class RailroadSquare(PurchasableSquare):
    def __init__(self, square_id: int, name: str, price: int = 200, mortgage_value: int = 100, group_id: int = 1):
        super().__init__(square_id, name, SquareType.RAILROAD, price, mortgage_value, group_id, PropertyColor.NONE)
        self.base_rent = 25 # Rent if 1 railroad is owned

    def get_rent(self, num_railroads_owned: int) -> int:
        if self.is_mortgaged or self.owner_id is None:
            return 0
        if not (0 < num_railroads_owned <= 4):
            return 0 # Or raise error for invalid num_railroads_owned
        # Rent is $25, $50, $100, $200 for 1, 2, 3, 4 railroads owned respectively
        return self.base_rent * (2**(num_railroads_owned - 1))

    def __str__(self):
        return f"{super().__str__()} - Base Rent (1 RR): ${self.base_rent}"

class UtilitySquare(PurchasableSquare):
    def __init__(self, square_id: int, name: str, price: int = 150, mortgage_value: int = 75, group_id: int = 2):
        super().__init__(square_id, name, SquareType.UTILITY, price, mortgage_value, group_id, PropertyColor.NONE)

    def get_rent(self, dice_roll: int, num_utilities_owned: int) -> int:
        if self.is_mortgaged or self.owner_id is None:
            return 0
        if num_utilities_owned == 1:
            return 4 * dice_roll
        elif num_utilities_owned == 2:
            return 10 * dice_roll
        return 0

    def __str__(self):
        return f"{super().__str__()} - Rent: 4x dice (1 owned), 10x dice (2 owned)"

class ActionSquare(BaseSquare): # For Chance, Community Chest
    def __init__(self, square_id: int, name: str, square_type: SquareType):
        if square_type not in [SquareType.CHANCE, SquareType.COMMUNITY_CHEST]:
            raise ValueError("ActionSquare must be of type CHANCE or COMMUNITY_CHEST")
        super().__init__(square_id, name, square_type)

class TaxSquare(BaseSquare):
    def __init__(self, square_id: int, name: str, tax_amount: int):
        super().__init__(square_id, name, SquareType.TAX)
        self.tax_amount = tax_amount

    def __str__(self):
        return f"{super().__str__()} - Amount: ${self.tax_amount}"

class SpecialSquare(BaseSquare): # For GO, Jail, Free Parking, Go to Jail
    def __init__(self, square_id: int, name: str, square_type: SquareType):
        if square_type not in [SquareType.GO, SquareType.JAIL_VISITING, SquareType.FREE_PARKING, SquareType.GO_TO_JAIL]:
            raise ValueError("Invalid square type for SpecialSquare")
        super().__init__(square_id, name, square_type)
