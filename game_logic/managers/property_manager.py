from typing import Dict, Any, Optional, List
from .base_manager import BaseManager
from ..player import Player
from ..property import PropertySquare, RailroadSquare, UtilitySquare, PurchasableSquare, PropertyColor


class PropertyManager(BaseManager):
    """
    Handles all property-related operations including buying, selling,
    mortgaging, house construction, and rent calculations.
    """
    
    def get_manager_name(self) -> str:
        return "PropertyManager"
    
    async def build_house_on_property(self, player_id: int, property_id: int) -> bool:
        """
        Build a house on a property owned by the player.
        
        Args:
            player_id: ID of the player building the house
            property_id: ID of the property to build on
            
        Returns:
            bool: True if house was built successfully, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"Invalid player_id: {player_id}", "error_property")
            return False
            
        player = self.players[player_id]
        if player.is_bankrupt:
            self.log_event(f"{player.name} is bankrupt and cannot build houses", "error_property")
            return False
            
        # Get the property square
        property_square = self.board.get_square(property_id)
        if not isinstance(property_square, PropertySquare):
            self.log_event(f"Square {property_id} is not a buildable property", "error_property")
            return False
            
        # Check ownership
        if property_square.owner_id != player_id:
            self.log_event(f"{player.name} doesn't own property {property_square.name}", "error_property")
            return False
            
        # Check if property is mortgaged
        if property_square.is_mortgaged:
            self.log_event(f"Cannot build on mortgaged property {property_square.name}", "error_property")
            return False
            
        # Check monopoly ownership
        if not self._player_owns_monopoly(player, property_square.color_group):
            self.log_event(f"{player.name} doesn't own monopoly for {property_square.color_group.name} group", "error_property")
            return False
            
        # Check if can build more houses (max 4 houses before hotel)
        if property_square.num_houses >= 4:
            # PropertySquare uses num_houses == 5 to represent hotel
            if property_square.num_houses == 5:
                self.log_event(f"Property {property_square.name} already has a hotel", "error_property")
                return False
            else:
                # Build hotel instead (convert 4 houses to hotel)
                return await self._build_hotel_on_property(player, property_square)
                
        # Check even development rule
        if not self._can_build_house_even_development(property_square):
            self.log_event(f"Even development rule violated for {property_square.name}", "error_property")
            return False
            
        # Check if player has enough money
        house_cost = property_square.house_price
        if player.money < house_cost:
            self.log_event(f"{player.name} cannot afford ${house_cost} house cost for {property_square.name}", "error_property")
            return False
            
        # Execute TPay payment for house construction
        payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_system(
            payer=player,
            amount=float(house_cost),
            reason=f"house construction on {property_square.name}",
            event_description=f"{player.name} built house on {property_square.name}"
        )
        
        if payment_success:
            # Build the house
            property_square.num_houses += 1
            
            self.log_event(f"{player.name} built house on {property_square.name} (now has {property_square.num_houses} houses)", "success_property")
            return True
        else:
            self.log_event(f"Payment failed for house construction on {property_square.name}", "error_property")
            return False
    
    async def sell_house_on_property(self, player_id: int, property_id: int) -> bool:
        """
        Sell a house from a property owned by the player.
        
        Args:
            player_id: ID of the player selling the house
            property_id: ID of the property to sell house from
            
        Returns:
            bool: True if house was sold successfully, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"Invalid player_id: {player_id}", "error_property")
            return False
            
        player = self.players[player_id]
        
        # Get the property square
        property_square = self.board.get_square(property_id)
        if not isinstance(property_square, PropertySquare):
            self.log_event(f"Square {property_id} is not a buildable property", "error_property")
            return False
            
        # Check ownership
        if property_square.owner_id != player_id:
            self.log_event(f"{player.name} doesn't own property {property_square.name}", "error_property")
            return False
            
        # Check if has houses to sell
        if property_square.num_houses == 0:
            self.log_event(f"Property {property_square.name} has no houses or hotel to sell", "error_property")
            return False
            
        # Check even development rule for selling
        if not self._can_sell_house_even_development(property_square):
            self.log_event(f"Even development rule violated for selling house on {property_square.name}", "error_property")
            return False
            
        # Determine sale price (50% of build cost)
        house_cost = property_square.house_price
        sale_price = house_cost // 2
        
        # Handle hotel vs house selling
        if property_square.num_houses == 5:
            # Sell hotel, convert to 4 houses
            property_square.num_houses = 4
            building_type = "hotel"
        else:
            # Sell one house
            property_square.num_houses -= 1
            building_type = "house"
            
        # Execute TPay payment from system to player
        payment_success = await self.gc.payment_manager.create_tpay_payment_system_to_player(
            recipient=player,
            amount=float(sale_price),
            reason=f"{building_type} sale from {property_square.name}",
            event_description=f"{player.name} sold {building_type} from {property_square.name}"
        )
        
        if payment_success:
            self.log_event(f"{player.name} sold {building_type} from {property_square.name} for ${sale_price}", "success_property")
            return True
        else:
            self.log_event(f"Payment failed for {building_type} sale from {property_square.name}", "error_property")
            # Revert the building change
            if building_type == "hotel":
                property_square.num_houses = 5
            else:
                property_square.num_houses += 1
            return False
    
    async def mortgage_property_for_player(self, player_id: int, property_id: int) -> bool:
        """
        Mortgage a property owned by the player.
        
        Args:
            player_id: ID of the player mortgaging the property
            property_id: ID of the property to mortgage
            
        Returns:
            bool: True if property was mortgaged successfully, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"Invalid player_id: {player_id}", "error_property")
            # Store error for debugging
            self.gc._last_mortgage_error = f"Invalid player_id: {player_id}"
            return False
            
        player = self.players[player_id]
        
        # Get the property square
        try:
            property_square = self.board.get_square(property_id)
        except Exception as e:
            error_msg = f"Failed to get property {property_id}: {e}"
            self.log_event(error_msg, "error_property")
            self.gc._last_mortgage_error = error_msg
            return False
            
        if not isinstance(property_square, PurchasableSquare):
            error_msg = f"Square {property_id} ({property_square.name}) is not a mortgageable property"
            self.log_event(error_msg, "error_property")
            self.gc._last_mortgage_error = error_msg
            return False
            
        # Check ownership
        if property_square.owner_id != player_id:
            owner_name = "Bank/Unowned" if property_square.owner_id is None else f"Player {property_square.owner_id}"
            error_msg = f"{player.name} doesn't own {property_square.name} (owned by {owner_name})"
            print(f"🚨 [MORTGAGE ERROR] {error_msg}")
            self.log_event(f"🚨 CRITICAL: {error_msg}", "error_property")
            self.gc._last_mortgage_error = error_msg
            return False
            
        # Check if already mortgaged
        if property_square.is_mortgaged:
            error_msg = f"{property_square.name} is already mortgaged"
            print(f"🚨 [MORTGAGE ERROR] {player.name} tried to mortgage {property_square.name} but it's ALREADY MORTGAGED!")
            self.log_event(f"🚨 CRITICAL: {player.name} tried to mortgage {property_square.name} but it's ALREADY MORTGAGED!", "error_property")
            self.gc._last_mortgage_error = error_msg
            return False
            
        # Check if property has houses (must sell houses first)
        if isinstance(property_square, PropertySquare) and property_square.num_houses > 0:
            houses_str = f"{property_square.num_houses} houses" if property_square.num_houses < 5 else "1 hotel"
            error_msg = f"Cannot mortgage {property_square.name} - has {houses_str}, must sell first"
            self.log_event(error_msg, "error_property")
            self.gc._last_mortgage_error = error_msg
            return False
            
        # Check color group houses rule (must be sold evenly)
        if isinstance(property_square, PropertySquare):
            color_group = property_square.color_group
            owned_in_group = [
                self.board.get_square(pid) for pid in player.properties_owned_ids 
                if isinstance(self.board.get_square(pid), PropertySquare) and 
                self.board.get_square(pid).color_group == color_group
            ]
            
            properties_with_houses = [prop for prop in owned_in_group if prop.num_houses > 0]
            if properties_with_houses:
                house_info = [f"{prop.name}({prop.num_houses})" for prop in properties_with_houses]
                error_msg = f"Cannot mortgage {property_square.name} - other {color_group} properties have houses: {house_info}"
                self.log_event(error_msg, "error_property")
                self.gc._last_mortgage_error = error_msg
                return False
            
        # Calculate mortgage amount (50% of property price)
        mortgage_amount = property_square.price // 2
        
        print(f"🏦 [MORTGAGE] {player.name} mortgaging {property_square.name} for ${mortgage_amount}")
        print(f"🏦 [MORTGAGE] Player money before: ${player.money}")
        
        # 🎯 Check for test mode (skip TPay for testing)
        is_test_mode = (
            getattr(self.gc, 'game_uid', '').startswith('test_') or 
            getattr(self.gc, 'game_uid', '').startswith('mortgage_test') or
            not hasattr(self.gc, 'payment_manager') or
            self.gc.payment_manager is None
        )
        
        if is_test_mode:
            print(f"🧪 [TEST MODE] Skipping TPay payment for mortgage - directly adding money")
            # In test mode, directly add money without TPay
            player.money += mortgage_amount
            property_square.is_mortgaged = True
            
            self.log_event(f"[TEST MODE] {player.name} mortgaged {property_square.name} for ${mortgage_amount}", "success_property")
            self.gc._last_mortgage_error = None  # Clear error on success
            print(f"🏦 [MORTGAGE SUCCESS] {player.name} money after: ${player.money}")
            return True
        
        # Production mode: Use TPay payment
        try:
            # Execute TPay payment from system to player (mortgage loan)
            payment_success = await self.gc.payment_manager.create_tpay_payment_system_to_player(
                recipient=player,
                amount=float(mortgage_amount),
                reason=f"mortgage loan for {property_square.name}",
                event_description=f"{player.name} mortgaged {property_square.name}"
            )
            
            if payment_success:
                # Mortgage the property
                property_square.is_mortgaged = True
                
                self.log_event(f"{player.name} mortgaged {property_square.name} for ${mortgage_amount}", "success_property")
                self.gc._last_mortgage_error = None  # Clear error on success
                print(f"🏦 [MORTGAGE SUCCESS] {player.name} money after: ${player.money}")
                return True
            else:
                error_msg = f"TPay payment failed for mortgaging {property_square.name}"
                self.log_event(error_msg, "error_property")
                self.gc._last_mortgage_error = error_msg
                print(f"🏦 [MORTGAGE FAILED] {error_msg}")
                return False
                
        except Exception as payment_error:
            error_msg = f"Payment system error for mortgaging {property_square.name}: {payment_error}"
            self.log_event(error_msg, "error_property")
            self.gc._last_mortgage_error = error_msg
            print(f"🏦 [MORTGAGE EXCEPTION] {error_msg}")
            import traceback
            traceback.print_exc()
            return False
    
    async def unmortgage_property_for_player(self, player_id: int, property_id: int) -> bool:
        """
        Unmortgage a property owned by the player.
        
        Args:
            player_id: ID of the player unmortgaging the property
            property_id: ID of the property to unmortgage
            
        Returns:
            bool: True if property was unmortgaged successfully, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"Invalid player_id: {player_id}", "error_property")
            return False
            
        player = self.players[player_id]
        
        # Get the property square
        property_square = self.board.get_square(property_id)
        if not isinstance(property_square, PurchasableSquare):
            self.log_event(f"Square {property_id} is not a mortgageable property", "error_property")
            return False
            
        # Check ownership
        if property_square.owner_id != player_id:
            self.log_event(f"{player.name} doesn't own property {property_square.name}", "error_property")
            return False
            
        # Check if property is mortgaged
        if not property_square.is_mortgaged:
            self.log_event(f"Property {property_square.name} is not mortgaged", "error_property")
            return False
            
        # Calculate unmortgage cost (110% of mortgage value = 55% of original price)
        mortgage_value = property_square.price // 2
        unmortgage_cost = int(mortgage_value * 1.1)  # 10% interest
        
        # Check if player has enough money
        if player.money < unmortgage_cost:
            self.log_event(f"{player.name} cannot afford ${unmortgage_cost} to unmortgage {property_square.name}", "error_property")
            return False
            
        # Execute TPay payment from player to system
        payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_system(
            payer=player,
            amount=float(unmortgage_cost),
            reason=f"unmortgage payment for {property_square.name}",
            event_description=f"{player.name} unmortgaged {property_square.name}"
        )
        
        if payment_success:
            # Unmortgage the property
            property_square.is_mortgaged = False
            
            self.log_event(f"{player.name} unmortgaged {property_square.name} for ${unmortgage_cost}", "success_property")
            return True
        else:
            self.log_event(f"Payment failed for unmortgaging {property_square.name}", "error_property")
            return False
    
    async def execute_buy_property_decision(self, player_id: int, property_id_to_buy: int) -> bool:
        """
        Execute a player's decision to buy a property.
        
        Args:
            player_id: ID of the player buying the property
            property_id_to_buy: ID of the property to buy
            
        Returns:
            bool: True if property was purchased successfully, False otherwise
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"❌ Invalid player_id: {player_id}", "error_property")
            return False
            
        player = self.players[player_id]
        property_square = self.board.get_square(property_id_to_buy)
        
        self.log_event(f"🏠 [BUY ATTEMPT] {player.name} attempting to buy {property_square.name} (ID: {property_id_to_buy})", "debug_property")
        self.log_event(f"💰 [BUY PRE-CHECK] Player money: ${player.money}, Property price: ${property_square.price if hasattr(property_square, 'price') else 'N/A'}", "debug_property")
        
        if not isinstance(property_square, PurchasableSquare):
            self.log_event(f"❌ Square {property_id_to_buy} is not purchasable", "error_property")
            return False
            
        if property_square.owner_id is not None:
            owner_name = self.players[property_square.owner_id].name if 0 <= property_square.owner_id < len(self.players) else f"Player {property_square.owner_id}"
            self.log_event(f"❌ Property {property_square.name} is already owned by {owner_name}", "error_property")
            return False
            
        if player.money < property_square.price:
            self.log_event(f"❌ {player.name} cannot afford ${property_square.price} for {property_square.name} (has ${player.money})", "error_property")
            return False
            
        # Execute TPay payment for property purchase
        print(f"🏠 [PROPERTY PURCHASE] {player.name} attempting to buy {property_square.name} for ${property_square.price}")
        self.log_event(f"💳 [PAYMENT START] Initiating TPay payment: {player.name} -> Treasury ${property_square.price}", "debug_property")
        
        payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_system(
            payer=player,
            amount=float(property_square.price),
            reason=f"property purchase - {property_square.name}",
            event_description=f"{player.name} bought {property_square.name}"
        )
        
        print(f"🏠 [PAYMENT RESULT] Payment result: {payment_success}")
        self.log_event(f"💳 [PAYMENT RESULT] Payment success: {payment_success}", "debug_property")
        
        if payment_success:
            # Complete the purchase
            property_square.owner_id = player_id
            player.add_property_id(property_id_to_buy)
            
            print(f"🏠 [PURCHASE COMPLETE] {player.name} successfully purchased {property_square.name}!")
            self.log_event(f"✅ {player.name} successfully bought {property_square.name} for ${property_square.price}", "success_property")
            self.log_event(f"🏠 [OWNERSHIP UPDATED] Property {property_square.name} now owned by {player.name} (ID: {player_id})", "debug_property")
            return True
        else:
            print(f"🏠 [PURCHASE FAILED] {player.name} failed to purchase {property_square.name}")
            self.log_event(f"❌ Payment failed for buying {property_square.name}", "error_property")
            self.log_event(f"🚨 [PAYMENT FAILURE] Player money after failed payment: ${player.money}", "debug_property")
            return False
    
    def calculate_rent(self, property_square: PurchasableSquare, dice_roll: Optional[int] = None) -> int:
        """
        Calculate rent for a property.
        
        Args:
            property_square: The property square
            dice_roll: The dice roll (for utilities)
            
        Returns:
            int: The rent amount
        """
        if property_square.owner_id is None or property_square.is_mortgaged:
            return 0
            
        owner = self.players[property_square.owner_id]
        
        if isinstance(property_square, PropertySquare):
            num_in_group = len(self.board.get_properties_in_group(property_square.color_group))
            owned_in_group = sum(1 for prop_id in owner.properties_owned_ids 
                               if isinstance(self.board.get_square(prop_id), PropertySquare) 
                               and self.board.get_square(prop_id).color_group == property_square.color_group)
            return property_square.get_rent(num_properties_in_group_owned_by_owner=owned_in_group, 
                                          total_properties_in_group=num_in_group)
        elif isinstance(property_square, RailroadSquare):
            num_railroads_owned = sum(1 for prop_id in owner.properties_owned_ids 
                                    if isinstance(self.board.get_square(prop_id), RailroadSquare))
            return property_square.get_rent(num_railroads_owned)
        elif isinstance(property_square, UtilitySquare):
            num_utilities_owned = sum(1 for prop_id in owner.properties_owned_ids 
                                    if isinstance(self.board.get_square(prop_id), UtilitySquare))
            return property_square.get_rent(dice_roll or 7, num_utilities_owned)
        
        return 0
    
    def _player_owns_monopoly(self, player: Player, color_group: PropertyColor) -> bool:
        """Check if player owns all properties in a color group"""
        properties_in_group = self.board.get_properties_in_group(color_group)
        # Convert PropertySquare objects to their IDs for comparison
        property_ids_in_group = [prop.square_id for prop in properties_in_group]
        owned_in_group = [prop_id for prop_id in player.properties_owned_ids 
                         if prop_id in property_ids_in_group]
        return len(owned_in_group) == len(properties_in_group)
    
    def _can_build_house_even_development(self, property_square: PropertySquare) -> bool:
        """Check if building a house violates the even development rule"""
        if property_square.owner_id is None:
            return False
            
        owner = self.players[property_square.owner_id]
        properties_in_group = self.board.get_properties_in_group(property_square.color_group)
        
        min_houses = float('inf')
        for prop in properties_in_group:
            if prop.square_id in owner.properties_owned_ids:
                if isinstance(prop, PropertySquare):
                    min_houses = min(min_houses, prop.num_houses)
        
        # Can build if this property doesn't have more houses than the minimum
        return property_square.num_houses <= min_houses
    
    def _can_sell_house_even_development(self, property_square: PropertySquare) -> bool:
        """Check if selling a house violates the even development rule"""
        if property_square.owner_id is None:
            return False
            
        owner = self.players[property_square.owner_id]
        properties_in_group = self.board.get_properties_in_group(property_square.color_group)
        
        max_houses = 0
        for prop in properties_in_group:
            if prop.square_id in owner.properties_owned_ids:
                if isinstance(prop, PropertySquare):
                    max_houses = max(max_houses, prop.num_houses)
        
        # Can sell if this property has the maximum number of houses
        return property_square.num_houses >= max_houses
    
    async def _build_hotel_on_property(self, player: Player, property_square: PropertySquare) -> bool:
        """Build a hotel on a property (internal method)"""
        hotel_cost = property_square.house_price  # Hotel costs same as house
        
        # Execute TPay payment for hotel construction
        payment_success = await self.gc.payment_manager.create_tpay_payment_player_to_system(
            payer=player,
            amount=float(hotel_cost),
            reason=f"hotel construction on {property_square.name}",
            event_description=f"{player.name} built hotel on {property_square.name}"
        )
        
        if payment_success:
            # Build the hotel (set num_houses to 5 to represent hotel)
            property_square.num_houses = 5
            
            self.log_event(f"{player.name} built hotel on {property_square.name}", "success_property")
            return True
        else:
            self.log_event(f"Payment failed for hotel construction on {property_square.name}", "error_property")
            return False 