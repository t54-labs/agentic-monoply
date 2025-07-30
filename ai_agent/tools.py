from typing import Dict, Any, List, Optional, Tuple

from tpay.tools import tradar_verifier

# It's better to import GameController directly if possible to get type hinting,
# but this can cause circular dependencies if GameController also needs to know about tools.
# Using 'Any' for game_controller for now, and casting internally or relying on duck typing.
# from game_logic.game_controller import GameController # Ideal import

# --- Helper to log tool usage (optional, can be integrated into each tool)
def generate_smart_action_suggestions(gc, player_id: int, failed_action: str, failed_params: Dict[str, Any], error_message: str) -> str:
    """
    Generate smart suggestions for fixing failed actions.
    
    Args:
        gc: Game controller instance
        player_id: ID of the player who had the failed action
        failed_action: Name of the failed action (e.g., 'tool_propose_trade')
        failed_params: Parameters that were used in the failed action
        error_message: The error message returned
        
    Returns:
        str: Smart suggestions for fixing the action
    """
    suggestions = []
    player = gc.players[player_id]
    
    try:
        if "ownership" in error_message.lower() or "doesn't own" in error_message.lower():
            # Property ownership issues
            if failed_action in ["tool_propose_trade", "tool_propose_counter_offer"]:
                suggestions.append("🎯 PROPERTY OWNERSHIP FIX:")
                
                # Suggest correct properties to offer
                if player.properties_owned_ids:
                    suggestions.append(f"✅ Properties you CAN offer: {[f'{gc.board.get_square(pid).name}(ID:{pid})' for pid in sorted(player.properties_owned_ids)]}")
                else:
                    suggestions.append("❌ You own no properties - consider offering money instead")
                
                # If this is a trade action, suggest valid recipients and their properties
                if "recipient_id" in failed_params:
                    recipient_id = failed_params.get("recipient_id")
                    if 0 <= recipient_id < len(gc.players):
                        recipient = gc.players[recipient_id]
                        if recipient.properties_owned_ids:
                            suggestions.append(f"✅ Properties you CAN request from {recipient.name}: {[f'{gc.board.get_square(pid).name}(ID:{pid})' for pid in sorted(recipient.properties_owned_ids)]}")
                        else:
                            suggestions.append(f"❌ {recipient.name} owns no properties - consider requesting money instead")
            
            elif failed_action == "tool_mortgage_property":
                # Find properties that can be mortgaged
                mortgageable = []
                for pid in player.properties_owned_ids:
                    square = gc.board.get_square(pid)
                    if hasattr(square, 'is_mortgaged') and not square.is_mortgaged:
                        mortgageable.append(f"{square.name}(ID:{pid})")
                
                if mortgageable:
                    suggestions.append(f"✅ Properties you CAN mortgage: {mortgageable}")
                else:
                    suggestions.append("❌ No properties available to mortgage (all already mortgaged or you own none)")
        
        elif "mortgaged" in error_message.lower():
            # Mortgage-related issues
            if "already mortgaged" in error_message.lower():
                suggestions.append("🏦 MORTGAGE STATUS FIX:")
                suggestions.append("❌ You tried to mortgage an already mortgaged property")
                
                # Find unmortgaged properties
                unmortgaged = []
                for pid in player.properties_owned_ids:
                    square = gc.board.get_square(pid)
                    if hasattr(square, 'is_mortgaged') and not square.is_mortgaged:
                        unmortgaged.append(f"{square.name}(ID:{pid})")
                
                if unmortgaged:
                    suggestions.append(f"✅ Try these unmortgaged properties instead: {unmortgaged}")
                else:
                    suggestions.append("❌ All your properties are already mortgaged")
            
            elif "not mortgaged" in error_message.lower():
                suggestions.append("🏦 UNMORTGAGE STATUS FIX:")
                suggestions.append("❌ You tried to unmortgage a property that isn't mortgaged")
                
                # Find mortgaged properties
                mortgaged = []
                for pid in player.properties_owned_ids:
                    square = gc.board.get_square(pid)
                    if hasattr(square, 'is_mortgaged') and square.is_mortgaged:
                        mortgaged.append(f"{square.name}(ID:{pid})")
                
                if mortgaged:
                    suggestions.append(f"✅ Try these mortgaged properties instead: {mortgaged}")
                else:
                    suggestions.append("❌ None of your properties are mortgaged")
        
        elif "funds" in error_message.lower() or "money" in error_message.lower() or "afford" in error_message.lower():
            # Money-related issues
            suggestions.append("💰 INSUFFICIENT FUNDS FIX:")
            suggestions.append(f"❌ Current money: ${player.money}")
            
            if failed_action == "tool_build_house":
                property_id = failed_params.get("property_id")
                if property_id:
                    square = gc.board.get_square(property_id)
                    if hasattr(square, 'house_price'):
                        suggestions.append(f"❌ House cost: ${square.house_price}")
                        suggestions.append(f"💡 Need ${square.house_price - player.money} more")
            
            # Suggest ways to get money
            money_options = []
            for pid in player.properties_owned_ids:
                square = gc.board.get_square(pid)
                if hasattr(square, 'is_mortgaged') and not square.is_mortgaged:
                    if hasattr(square, 'mortgage_value'):
                        money_options.append(f"Mortgage {square.name} for ${square.mortgage_value}")
            
            if money_options:
                suggestions.append(f"💡 Ways to get money: {money_options[:3]}")  # Show first 3 options
        
        elif "monopoly" in error_message.lower() or "color group" in error_message.lower():
            # Monopoly/color group issues
            suggestions.append("🏠 MONOPOLY REQUIREMENT FIX:")
            suggestions.append("❌ You need to own ALL properties in a color group to build houses")
            
            # Analyze current color group ownership
            property_id = failed_params.get("property_id")
            if property_id:
                square = gc.board.get_square(property_id)
                if hasattr(square, 'color_group'):
                    color_group = square.color_group
                    suggestions.append(f"🎯 For {color_group.name} group, you need:")
                    
                    # Find all properties in this color group
                    all_in_group = []
                    owned_in_group = []
                    missing_in_group = []
                    
                    for pid in range(40):
                        try:
                            sq = gc.board.get_square(pid)
                            if hasattr(sq, 'color_group') and sq.color_group == color_group:
                                all_in_group.append(sq)
                                if sq.owner_id == player_id:
                                    owned_in_group.append(sq.name)
                                else:
                                    owner_name = "Bank" if sq.owner_id is None else gc.players[sq.owner_id].name
                                    missing_in_group.append(f"{sq.name} (owned by {owner_name})")
                        except:
                            pass
                    
                    if owned_in_group:
                        suggestions.append(f"✅ You own: {owned_in_group}")
                    if missing_in_group:
                        suggestions.append(f"❌ You need: {missing_in_group}")
        
    except Exception as e:
        suggestions.append(f"❌ Could not generate specific suggestions: {e}")
    
    if suggestions:
        return "\n" + "\n".join(suggestions) + "\n"
    else:
        return "\n💡 Check the game state and try a different approach.\n"


# 🎯 ENHANCED: Add smart suggestions to error handling
def _log_agent_action(gc, player_id: int, action_name: str, params: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Enhanced logging with smart suggestions for failed actions"""
    player_name = gc.players[player_id].name if 0 <= player_id < len(gc.players) else f"Player {player_id}"
    status = result.get("status", "unknown")
    message = result.get("message", "No message")
    
    # Basic logging
    status_display = status.upper() if status else "UNKNOWN"
    gc.log_event(f"[AGENT ACTION] {player_name}: {action_name} -> {status_display}", "agent_action")
    if message:
        gc.log_event(f"[AGENT RESULT] {message}", "agent_action")
    
    # 🎯 NEW: Add smart suggestions for failed actions
    if status in ["failure", "error"]:
        smart_suggestions = generate_smart_action_suggestions(gc, player_id, action_name, params, message)
        gc.log_event(f"[SMART SUGGESTIONS] {smart_suggestions}", "agent_suggestion")
        
        # Track failed action for deadlock prevention
        gc.track_failed_action(player_id, action_name, params)

# --- Basic Turn Actions ---
@tradar_verifier
def tool_roll_dice(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player rolls the dice to take their main turn action (move, etc.)."""
    player = gc.players[player_id]
    try:
        if player.is_bankrupt: 
            return {"status": "failure", "message": "Bankrupt."}
            
        is_main_turn_player = (gc.current_player_index == player_id)
        
        if not (is_main_turn_player and gc.pending_decision_type is None and not gc.auction_in_progress):
             return {"status": "failure", "message": "Not in state for main turn roll."}
            
        if not gc.dice_roll_outcome_processed: 
            return {"status": "failure", "message": "Dice outcome pending."}
            
        if player.in_jail: 
            return {"status": "failure", "message": "In jail; use jail roll tool."}
            
        dice_roll = gc.roll_dice()
        went_to_jail = (gc.doubles_streak == 3 and player.in_jail)
        msg = f"Rolled {dice_roll}."
        if went_to_jail: msg += " Went to jail (3x doubles)."
        result = {"status": "success", "message": msg, "dice_roll": dice_roll, "went_to_jail": went_to_jail}
        
        _log_agent_action(gc, player_id, "tool_roll_dice", {}, result)
        return result
    except Exception as e: 
        gc.log_event(f"[ERROR] tool_roll_dice P{player_id}: {type(e).__name__}: {str(e)}", "error_log")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_end_turn(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player explicitly ends their turn or current segment of complex actions."""
    player = gc.players[player_id]
    try:
        # 🚨 DEADLOCK PREVENTION: Clear failed actions when ending turn
        if hasattr(gc, 'clear_failed_actions_for_player'):
            gc.clear_failed_actions_for_player(player_id)
            gc.log_event(f"🔄 [TURN END] Cleared failed action history for {player.name}", "debug_log")
        
        # GC.get_available_actions should primarily gate this.
        # This tool just signals intent; GC resolves the state.
        gc._resolve_current_action_segment()
        result = {"status": "success", "message": f"{player.name} signals end of segment/turn."}
        _log_agent_action(gc, player_id, "tool_end_turn", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Property Actions ---
@tradar_verifier
def tool_buy_property(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player attempts to buy an unowned property. If property_id is None, it tries to buy the one set in pending_decision_context."""
    
    # 🚨 CRITICAL DEBUG: This should print every time tool_buy_property is called
    print("🏠 TOOL_BUY_PROPERTY CALLED!")
    print(f"🏠 Player ID: {player_id}, Property ID: {property_id}")
    print(f"🏠 GameController type: {type(gc).__name__}")
    print(f"🏠 PaymentManager type: {type(gc.payment_manager).__name__}")
    
    player = gc.players[player_id]
    try:
        target_property_id = property_id if property_id is not None else gc.pending_decision_context.get("property_id")
        
        if not (gc.pending_decision_type == "buy_or_auction_property" and 
                gc.pending_decision_context.get("player_id") == player_id and 
                target_property_id is not None):
            return {"status": "failure", "message": "Not in correct state to buy property or property_id missing."}
        
        square_to_buy = gc.board.get_square(target_property_id)
        
        # 🚨 CRITICAL FIX: Check if property is already owned before attempting purchase
        if square_to_buy.owner_id is not None:
            owner_name = gc.players[square_to_buy.owner_id].name if 0 <= square_to_buy.owner_id < len(gc.players) else f"Player {square_to_buy.owner_id}"
            gc.log_event(f"🚨 [STATE RESET] Property {square_to_buy.name} already owned by {owner_name}. Clearing stuck pending decision.", "warning_property")
            
            # Clear the stuck state and resolve the segment
            gc._resolve_current_action_segment()
            
            return {"status": "failure", "message": f"Property {square_to_buy.name} is already owned by {owner_name}. State has been reset."}
        
        # 🚨 ADDITIONAL CHECK: If player doesn't have enough money, clear stuck state
        if player.money < square_to_buy.price:
            gc.log_event(f"🚨 [STATE RESET] {player.name} cannot afford {square_to_buy.name} (${square_to_buy.price}, has ${player.money}). Clearing stuck pending decision.", "warning_property")
            
            # Clear the stuck state and resolve the segment
            gc._resolve_current_action_segment()
            
            return {"status": "failure", "message": f"Cannot afford {square_to_buy.name}. Need ${square_to_buy.price}, have ${player.money}. State has been reset."}
        
        # Call async GC method 
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc.execute_buy_property_decision(player_id, target_property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc.execute_buy_property_decision(player_id, target_property_id))
        
        if success:
            # Purchase successful - clear pending decision and send success notification
            gc._resolve_current_action_segment()
            
            # Reset failure count on successful purchase
            if hasattr(gc, '_buy_property_failure_count') and player_id in gc._buy_property_failure_count:
                gc._buy_property_failure_count[player_id] = 0
            
            # Send special event notification for successful purchase
            if hasattr(gc, '_threaded_game_instance') and gc._threaded_game_instance:
                gc._threaded_game_instance.send_message_safely({
                    'type': 'special_event_notification',
                    'game_uid': gc.game_uid,
                    'event_type': 'property_buy',
                    'player_name': player.name,
                    'event_data': {
                        'property_name': square_to_buy.name,
                        'amount': square_to_buy.price
                    }
                })
            
            result = {"status": "success", "message": f"Buy {square_to_buy.name}: OK."}
        else:
            # Purchase failed - send failure notification but don't clear pending decision yet
            status_msg = "FAIL"
            if player.money < square_to_buy.price:
                status_msg += " (Insufficient funds likely)"
            else:
                status_msg += " (Reasons in GC log or property already owned/invalid state)"

            # 🚨 NEW: If this is the 3rd+ consecutive failure, force clear the stuck state
            if not hasattr(gc, '_buy_property_failure_count'):
                gc._buy_property_failure_count = {}
            
            if player_id not in gc._buy_property_failure_count:
                gc._buy_property_failure_count[player_id] = 0
                
            gc._buy_property_failure_count[player_id] += 1
            
            if gc._buy_property_failure_count[player_id] >= 3:
                gc.log_event(f"🚨 [FORCE STATE RESET] {player.name} has failed to buy property {gc._buy_property_failure_count[player_id]} times. Forcing state reset.", "warning_property")
                gc._buy_property_failure_count[player_id] = 0  # Reset counter
                gc._resolve_current_action_segment()  # Force clear stuck state
                status_msg += " - State forcefully reset after multiple failures"
            
            # Send special event notification for failed purchase
            if hasattr(gc, '_threaded_game_instance') and gc._threaded_game_instance:
                gc._threaded_game_instance.send_message_safely({
                    'type': 'special_event_notification',
                    'game_uid': gc.game_uid,
                    'event_type': 'property_buy_failed',
                    'player_name': player.name,
                    'event_data': {
                        'property_name': square_to_buy.name,
                        'property_price': square_to_buy.price,
                        'player_money': player.money,
                        'reason': status_msg,
                        'failure_count': gc._buy_property_failure_count.get(player_id, 0)
                    }
                })
            
            result = {"status": "failure", "message": f"Buy {square_to_buy.name}: {status_msg}."}
        
        _log_agent_action(gc, player_id, "tool_buy_property", {"property_id": target_property_id}, result)
        return result
    except Exception as e: 
        gc.log_event(f"[Exception] tool_buy_property: {e}")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_pass_on_buying_property(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player landed on an unowned property and chooses NOT to buy it, which should trigger an auction."""
    player = gc.players[player_id]
    try:
        target_property_id = property_id if property_id is not None else gc.pending_decision_context.get("property_id")
        if not (gc.pending_decision_type == "buy_or_auction_property" and 
                gc.pending_decision_context.get("player_id") == player_id and 
                target_property_id is not None):
            return {"status": "failure", "message": "Not in correct state to pass on buying property."}

        square = gc.board.get_square(target_property_id)
        # Call async GC method
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc._pass_on_buying_property_action(player_id, target_property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc._pass_on_buying_property_action(player_id, target_property_id))
        result = {"status": "success" if success else "failure", "message": f"Passed on buying {square.name}. Auction initiated by GC."}
        _log_agent_action(gc, player_id, "tool_pass_on_buying_property", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Asset Management (These tools might be called when pending_decision_type is None or "asset_management") ---
@tradar_verifier
def tool_build_house(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to build a house/hotel on one of their properties."""
    try:
        # Asset management can happen when no other specific decision is pending.
        # gc.pending_decision_type might be None or a generic "manage_assets" phase.
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc.build_house_on_property(player_id, property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc.build_house_on_property(player_id, property_id))
        
        status = "success" if success else "failure"
        # GameController method build_house_on_property already logs details.
        message = f"Build house on property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_build_house", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_sell_house(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to sell a house/hotel from one of their properties."""
    try:
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc.sell_house_on_property(player_id, property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc.sell_house_on_property(player_id, property_id))
        
        status = "success" if success else "failure"
        message = f"Sell house on property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_sell_house", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_mortgage_property(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to mortgage one of their properties."""
    try:
        # 🚨 DEADLOCK PREVENTION: Check if this action has failed repeatedly
        action_params = {"property_id": property_id}
        if hasattr(gc, 'check_repeated_failure') and gc.check_repeated_failure(player_id, "tool_mortgage_property", action_params):
            player_name = gc.players[player_id].name if 0 <= player_id < len(gc.players) else f"Player {player_id}"
            
            # Get property name for better error message
            property_name = "Unknown Property"
            try:
                if 0 <= property_id < len(gc.board.squares):
                    property_square = gc.board.get_square(property_id)
                    property_name = property_square.name
                    is_mortgaged = getattr(property_square, 'is_mortgaged', False)
                    if is_mortgaged:
                        property_name += " (ALREADY MORTGAGED)"
            except:
                pass
            
            blocked_message = f"🚨 DEADLOCK PREVENTION: {player_name} has tried to mortgage {property_name} multiple times and failed. This action is now BLOCKED to prevent infinite loop. Try a different action like tool_end_turn or tool_resign_game."
            print(blocked_message)
            gc.log_event(blocked_message, "error_log")
            
            result = {"status": "failure", "message": blocked_message}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # 🔍 ENHANCED VALIDATION AND DEBUGGING
        player = gc.players[player_id]
        
        # Validate property ID
        if not (0 <= property_id < len(gc.board.squares)):
            error_msg = f"Invalid property ID {property_id}. Valid range: 0-{len(gc.board.squares)-1}"
            result = {"status": "failure", "message": error_msg}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # Get property details
        try:
            property_square = gc.board.get_square(property_id)
            property_name = property_square.name
        except Exception as e:
            error_msg = f"Failed to get property {property_id} details: {e}"
            result = {"status": "failure", "message": error_msg}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # 🎯 COMPREHENSIVE PRE-VALIDATION
        print(f"🏦 [MORTGAGE DEBUG] {player.name} attempting to mortgage {property_name} (ID: {property_id})")
        print(f"🏦 [MORTGAGE DEBUG] Player properties: {player.properties_owned_ids}")
        print(f"🏦 [MORTGAGE DEBUG] Property owner: {getattr(property_square, 'owner_id', 'N/A')}")
        print(f"🏦 [MORTGAGE DEBUG] Property mortgaged: {getattr(property_square, 'is_mortgaged', 'N/A')}")
        
        # Check ownership
        if property_id not in player.properties_owned_ids:
            owned_props = [f"{pid}:{gc.board.get_square(pid).name}" for pid in player.properties_owned_ids]
            error_msg = f"You don't own {property_name} (ID: {property_id}). Your properties: {owned_props}"
            result = {"status": "failure", "message": error_msg}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # Check if already mortgaged
        if hasattr(property_square, 'is_mortgaged') and property_square.is_mortgaged:
            error_msg = f"{property_name} is already mortgaged. Cannot mortgage an already mortgaged property."
            result = {"status": "failure", "message": error_msg}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # Check if property has houses/hotels (must sell first)
        if hasattr(property_square, 'num_houses') and property_square.num_houses > 0:
            houses_str = f"{property_square.num_houses} houses" if property_square.num_houses < 5 else "1 hotel"
            error_msg = f"{property_name} has {houses_str}. You must sell all houses/hotels before mortgaging. Use tool_sell_house first."
            result = {"status": "failure", "message": error_msg}
            _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
            return result
        
        # Check if other properties in color group have houses (must be even)
        from game_logic.board import PropertySquare
        if isinstance(property_square, PropertySquare):
            color_group = property_square.color_group
            group_properties = [
                gc.board.get_square(pid) for pid in player.properties_owned_ids 
                if isinstance(gc.board.get_square(pid), PropertySquare) and 
                gc.board.get_square(pid).color_group == color_group
            ]
            
            properties_with_houses = [prop for prop in group_properties if prop.num_houses > 0]
            if properties_with_houses:
                house_info = [f"{prop.name}({prop.num_houses})" for prop in properties_with_houses]
                error_msg = f"Cannot mortgage {property_name} - other properties in {color_group} group have houses: {house_info}. Must sell houses evenly first."
                result = {"status": "failure", "message": error_msg}
                _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
                return result
        
        # Get mortgage value for debugging
        mortgage_value = getattr(property_square, 'mortgage_value', getattr(property_square, 'price', 0) // 2)
        print(f"🏦 [MORTGAGE DEBUG] Pre-validation passed. Mortgage value: ${mortgage_value}")
        
        # 🎯 Call the actual GameController method
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc.mortgage_property_for_player(player_id, property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc.mortgage_property_for_player(player_id, property_id))
        
        status = "success" if success else "failure"
        
        if success:
            message = f"Successfully mortgaged {property_name} for ${mortgage_value}. Your money: ${player.money}"
            print(f"🏦 [MORTGAGE SUCCESS] {player.name} mortgaged {property_name} for ${mortgage_value}")
        else:
            # Get more detailed error from GameController if available
            last_error = getattr(gc, '_last_mortgage_error', 'Unknown reason')
            message = f"Failed to mortgage {property_name}. Reason: {last_error}. Check property status and game rules."
            print(f"🏦 [MORTGAGE FAILURE] {player.name} failed to mortgage {property_name}. Error: {last_error}")
        
        result = {"status": status, "message": message}
        
        # 🚨 DEADLOCK PREVENTION: Track failed actions
        if not success and hasattr(gc, 'track_failed_action'):
            gc.track_failed_action(player_id, "tool_mortgage_property", action_params)
        elif success and hasattr(gc, 'clear_failed_actions_for_player'):
            # Clear failed actions on success
            gc.clear_failed_actions_for_player(player_id)
            
        _log_agent_action(gc, player_id, "tool_mortgage_property", action_params, result)
        return result
    except Exception as e:
        error_msg = f"Exception in tool_mortgage_property: {str(e)}"
        print(f"🏦 [MORTGAGE EXCEPTION] {error_msg}")
        import traceback
        traceback.print_exc()
        result = {"status": "error", "message": error_msg}
        _log_agent_action(gc, player_id, "tool_mortgage_property", {"property_id": property_id}, result)
        return result

@tradar_verifier
def tool_unmortgage_property(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to unmortgage one of their properties."""
    try:
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc.unmortgage_property_for_player(player_id, property_id), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc.unmortgage_property_for_player(player_id, property_id))
        
        status = "success" if success else "failure"
        message = f"Unmortgage property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_unmortgage_property", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Jail Actions (Called when gc.pending_decision_type == "jail_options") ---
@tradar_verifier
def tool_pay_bail(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        # 🚨 CRITICAL: Pre-validate jail state to prevent race conditions
        if not player.in_jail:
            return {"status": "failure", "message": f"Cannot pay bail: {player.name} is not in jail anymore. Position: {player.position}"}
            
        if not (gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot pay bail: not in correct jail decision state."}
        
        # 🏛️ JAIL STATE DEBUG: Log current jail state for debugging
        gc.log_event(f"[JAIL DEBUG] {player.name} pay bail attempt: in_jail={player.in_jail}, position={player.position}, jail_turns={getattr(player, 'jail_turns_remaining', 'N/A')}", "jail_event")
        
        # Store initial jail state to detect race conditions
        initial_jail_state = player.in_jail
        initial_position = player.position
        
        # Call async GC method with player_id and params (non-blocking)
        import asyncio
        import threading
        
        def run_pay_bail_async():
            """Run pay bail in new event loop to avoid blocking"""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Double-check jail state before executing
                    if not player.in_jail:
                        return {"status": "failure", "message": "Race condition detected: player left jail during execution"}
                    
                    result = loop.run_until_complete(gc._pay_to_get_out_of_jail(player_id, params))
                    return result
                finally:
                    loop.close()
            except Exception as e:
                gc.log_event(f"Pay bail thread error: {e}", "error_jail")
                return {"status": "error", "message": f"Pay bail execution error: {e}"}
        
        # Run pay bail in thread with timeout to avoid blocking
        bail_thread = threading.Thread(target=lambda: setattr(bail_thread, 'result', run_pay_bail_async()))
        bail_thread.start()
        bail_thread.join(timeout=30)  # 30 second timeout
        
        if bail_thread.is_alive():
            gc.log_event(f"Pay bail timeout for {player.name}", "error_jail")
            action_outcome = {"status": "error", "message": "Pay bail operation timed out"}
        else:
            action_outcome = getattr(bail_thread, 'result', {"status": "error", "message": "No result from pay bail"})
        
        # 🎯 RACE CONDITION CHECK: Verify final state consistency
        if initial_jail_state and not player.in_jail and player.position != initial_position:
            # Player was released and moved - this is expected
            gc.log_event(f"✅ [JAIL RELEASE] {player.name} paid bail and moved to position {player.position}", "jail_event")
        
        # Extract result data safely
        status = action_outcome.get("status", "unknown")
        message = action_outcome.get("message", "Pay bail attempt processed.")
        
        # Convert jail manager response format to tool format
        if action_outcome.get("success") is True:
            status = "success"
        elif action_outcome.get("success") is False:
            status = "failure"
        elif status not in ["success", "failure", "error"]:
            status = "unknown"
        
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_pay_bail", params, result)
        return result
    except Exception as e: 
        gc.log_event(f"[ERROR] tool_pay_bail P{player_id}: {type(e).__name__}: {str(e)}", "error_log")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_use_get_out_of_jail_card(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        # 🚨 CRITICAL: Pre-validate jail state to prevent race conditions
        if not player.in_jail:
            return {"status": "failure", "message": f"Cannot use GOOJ card: {player.name} is not in jail anymore. Position: {player.position}"}
            
        if not (gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot use GOOJ card: not in correct jail decision state."}
        
        if not (player.has_chance_gooj_card or player.has_community_gooj_card or player.get_out_of_jail_free_cards > 0):
            return {"status": "failure", "message": "No GOOJ card to use."}
        
        # 🏛️ JAIL STATE DEBUG: Log current jail state for debugging
        gc.log_event(f"[JAIL DEBUG] {player.name} GOOJ card attempt: in_jail={player.in_jail}, position={player.position}, chance={player.has_chance_gooj_card}, community={player.has_community_gooj_card}, generic={player.get_out_of_jail_free_cards}", "jail_event")
        
        # Store initial jail state to detect race conditions
        initial_jail_state = player.in_jail
        initial_position = player.position
        
        # Call async GC method with player_id and params (non-blocking)
        import asyncio
        import threading
        
        def run_gooj_card_async():
            """Run GOOJ card in new event loop to avoid blocking"""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Double-check jail state before executing
                    if not player.in_jail:
                        return {"status": "failure", "message": "Race condition detected: player left jail during execution"}
                    
                    result = loop.run_until_complete(gc._use_card_to_get_out_of_jail(player_id, params))
                    return result
                finally:
                    loop.close()
            except Exception as e:
                gc.log_event(f"GOOJ card thread error: {e}", "error_jail")
                return {"status": "error", "message": f"GOOJ card execution error: {e}"}
        
        # Run GOOJ card in thread with timeout to avoid blocking
        gooj_thread = threading.Thread(target=lambda: setattr(gooj_thread, 'result', run_gooj_card_async()))
        gooj_thread.start()
        gooj_thread.join(timeout=30)  # 30 second timeout
        
        if gooj_thread.is_alive():
            gc.log_event(f"GOOJ card timeout for {player.name}", "error_jail")
            action_outcome = {"status": "error", "message": "GOOJ card operation timed out"}
        else:
            action_outcome = getattr(gooj_thread, 'result', {"status": "error", "message": "No result from GOOJ card"})
        
        # 🎯 RACE CONDITION CHECK: Verify final state consistency
        if initial_jail_state and not player.in_jail and player.position != initial_position:
            # Player was released and moved - this is expected
            gc.log_event(f"✅ [JAIL RELEASE] {player.name} used GOOJ card and moved to position {player.position}", "jail_event")
        
        # Extract result data safely
        status = action_outcome.get("status", "unknown")
        message = action_outcome.get("message", "Use GOOJ card attempt processed.")
        
        # Convert jail manager response format to tool format
        if action_outcome.get("success") is True:
            status = "success"
        elif action_outcome.get("success") is False:
            status = "failure"
        elif status not in ["success", "failure", "error"]:
            status = "unknown"
        
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_use_get_out_of_jail_card", params, result)
        return result
    except Exception as e: 
        gc.log_event(f"[ERROR] tool_use_get_out_of_jail_card P{player_id}: {type(e).__name__}: {str(e)}", "error_log")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_roll_for_doubles_to_get_out_of_jail(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        # 🚨 CRITICAL: Pre-validate jail state to prevent race conditions
        if not player.in_jail:
            return {"status": "failure", "message": "Cannot roll for jail: player is not in jail anymore."}
            
        if not (gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot roll for jail: not in correct jail decision state."}
        
        # Check if player has already used all roll attempts
        if player.jail_turns_remaining >=3 and not gc.pending_decision_context.get("max_rolls_attempted", False):
             # This condition is a bit redundant if _attempt_roll_out_of_jail handles it robustly by returning error
             # For safety, ensure agent doesn't try to roll if GC logic already determined max attempts.
             pass # Let GC method handle max attempts error
        
        # Store initial jail state to detect race conditions
        initial_jail_state = player.in_jail
        initial_position = player.position
        
        # Call async GC method with player_id and params
        import asyncio
        import threading
        
        def run_jail_roll_async():
            """Run jail roll in new event loop to avoid blocking"""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Double-check jail state before executing
                    if not player.in_jail:
                        return {"status": "failure", "message": "Race condition detected: player left jail during execution"}
                    
                    result = loop.run_until_complete(gc._attempt_roll_out_of_jail(player_id, params))
                    return result
                finally:
                    loop.close()
            except Exception as e:
                gc.log_event(f"Jail roll thread error: {e}", "error_jail")
                return {"status": "error", "message": f"Jail roll execution error: {e}"}
        
        # Run jail roll in thread with timeout to avoid blocking
        jail_thread = threading.Thread(target=lambda: setattr(jail_thread, 'result', run_jail_roll_async()))
        jail_thread.start()
        jail_thread.join(timeout=30)  # 30 second timeout
        
        if jail_thread.is_alive():
            gc.log_event(f"Jail roll timeout for {player.name}", "error_jail")
            action_outcome = {"status": "error", "message": "Jail roll operation timed out"}
        else:
            action_outcome = getattr(jail_thread, 'result', {"status": "error", "message": "No result from jail roll"})
        
        # 🎯 RACE CONDITION CHECK: Verify final state consistency
        if initial_jail_state and not player.in_jail and player.position != initial_position:
            # Player was released and moved - this is expected
            gc.log_event(f"✅ [JAIL RELEASE] {player.name} successfully left jail and moved to position {player.position}", "jail_event")
        
        # Extract result data safely
        dice_rolled = action_outcome.get("dice", action_outcome.get("dice_roll", gc.dice))
        got_out = action_outcome.get("released", action_outcome.get("got_out", False))
        message = action_outcome.get("message", f"Roll for doubles (in jail): Dice {dice_rolled}, Got out: {got_out}.")
        status = action_outcome.get("status", "unknown")
        
        # Convert jail manager response format to tool format
        if action_outcome.get("success") is True:
            status = "success"
        elif action_outcome.get("success") is False:
            status = "failure"
        elif status not in ["success", "failure", "error"]:
            status = "unknown"
        
        result = {"status": status, "message": message, "dice_roll": dice_rolled, "got_out": got_out}
        _log_agent_action(gc, player_id, "tool_roll_for_doubles_to_get_out_of_jail", params, result)
        return result
    except Exception as e: 
        gc.log_event(f"[ERROR] tool_roll_for_doubles_to_get_out_of_jail P{player_id}: {type(e).__name__}: {str(e)}", "error_log")
        return {"status": "error", "message": str(e)}

# --- Bankruptcy Flow Tool ---
@tradar_verifier
def tool_confirm_asset_liquidation_actions_done(gc: Any, player_id: int) -> Dict[str, Any]:
    """Agent signals they have finished (or cannot do more) selling/mortgaging to cover debt."""
    player = gc.players[player_id]
    try:
        if not (gc.pending_decision_type == "asset_liquidation_for_debt" and gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": "Not in asset liquidation phase for this player."}
        
        gc.confirm_asset_liquidation_done(player_id)
        # confirm_asset_liquidation_done will either finalize bankruptcy or clear the pending decision.
        message = f"{player.name} confirmed asset liquidation actions are done. Current money: ${player.money}"
        if player.is_bankrupt:
            message += " Player is now bankrupt."
        elif player.money <0:
             message += " Player still has negative money, should have been declared bankrupt unless error."
        
        result = {"status": "success", "message": message}
        _log_agent_action(gc, player_id, "tool_confirm_asset_liquidation_actions_done", {}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Placeholder/Fallback Actions ---
@tradar_verifier
def tool_do_nothing(gc: Any, player_id: int, reason: str = "No specific action chosen") -> Dict[str, Any]:
    player = gc.players[player_id]
    try:
        gc.log_event(f"Agent {player.name} (P{player_id}) chose to do nothing. Reason: {reason}")
        # This tool is usually for specific states where doing nothing has a defined game consequence.
        # Example: In jail, after 3 failed rolls, no card, no money -> doing nothing passes the turn segment.
        if gc.pending_decision_type == "jail_options" and player.in_jail and player.jail_turns_remaining >=3 and not (player.has_chance_gooj_card or player.has_community_gooj_card or player.money >=50) :
             gc._resolve_current_action_segment() 
        elif gc.pending_decision_type == "asset_liquidation_for_debt":
             # Doing nothing here means they won't sell/mortgage more. Should call confirm.
             gc.log_event(f"[Info] {player.name} chose do_nothing during asset liquidation. Interpreting as confirm_done.")
             gc.confirm_asset_liquidation_done(player_id)
        elif gc.pending_decision_type is not None:
             gc.log_event(f"[Warning] {player.name} did nothing on pending decision '{gc.pending_decision_type}'. This might be an agent error or unhandled state by tool.")
             # Defaulting to clearing decision to avoid agent getting stuck in a loop if agent chose this by mistake.
             gc._clear_pending_decision()
             gc.dice_roll_outcome_processed = True # Assume this state resolves the segment.
        else: # No specific decision, general turn. Doing nothing usually means waiting for next opportunity or ending turn.
             gc.dice_roll_outcome_processed = True # If no specific decision, assume current actions are processed.
        
        result = {"status": "success", "message": f"Did nothing. Reason: {reason}"}
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_wait(gc: Any, player_id: int) -> Dict[str, Any]: # Typically used if not agent's turn but somehow asked
    try:
        result = {"status": "success", "message": "Player is waiting (e.g., not their active turn segment)."}
        _log_agent_action(gc, player_id, "tool_wait", {}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_resign_game(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player chooses to resign from the game, leading to bankruptcy to the bank."""
    player = gc.players[player_id]
    try:
        gc.log_event(f"Agent {player.name} (P{player_id}) resigns.")
        gc._check_and_handle_bankruptcy(player, debt_to_creditor=player.money if player.money < 0 else 0, creditor=None)
        msg = "Resignation processed." 
        if gc.pending_decision_type == "asset_liquidation_for_debt": msg += " Must liquidate/confirm bankruptcy."
        elif player.is_bankrupt: msg += " Player now bankrupt."
        result = {"status": "success", "message": msg}
        _log_agent_action(gc, player_id, "tool_resign_game", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Auction Tools ---
@tradar_verifier
def tool_bid_on_auction(gc: Any, player_id: int, bid_amount: int) -> Dict[str, Any]:
    """Player places a bid in an ongoing auction."""
    player = gc.players[player_id]
    try:
        # 🎪 AUCTION BID: Check if it's player's turn to bid
        if not gc.auction_in_progress:
            return {"status": "failure", "message": "No auction in progress."}
        
        if gc.pending_decision_type != "auction_bid_decision":
            return {"status": "failure", "message": f"Not in auction bidding phase. Current decision: {gc.pending_decision_type}"}
            
        auction_player_id = gc.pending_decision_context.get("player_id")
        if auction_player_id != player_id:
            return {"status": "failure", "message": f"Not your turn to bid. Current bidder: {auction_player_id}"}
        
        # Validate bid amount
        current_bid = gc.auction_current_bid
        if bid_amount <= current_bid:
            return {"status": "failure", "message": f"Bid ${bid_amount} must be higher than current bid ${current_bid}"}
            
        if player.money < bid_amount:
            return {"status": "failure", "message": f"Cannot afford bid ${bid_amount}. You have ${player.money}"}
        
        # Execute bid through auction manager
        success = gc.auction_manager.handle_auction_bid(player_id, bid_amount)
        
        if success:
            message = f"{player.name} successfully bid ${bid_amount}"
            result = {"status": "success", "message": message, "bid_amount": bid_amount}
        else:
            result = {"status": "failure", "message": f"Bid ${bid_amount} was rejected"}
            
        _log_agent_action(gc, player_id, "tool_bid_on_auction", {"bid_amount": bid_amount}, result)
        return result
    except Exception as e: 
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Auction bid error: {str(e)}"}

@tradar_verifier
def tool_pass_auction_bid(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player passes their turn to bid in an ongoing auction."""
    player = gc.players[player_id]
    try:
        # 🎪 AUCTION PASS: Check if it's player's turn to pass
        if not gc.auction_in_progress:
            return {"status": "failure", "message": "No auction in progress."}
        
        if gc.pending_decision_type != "auction_bid_decision":
            return {"status": "failure", "message": f"Not in auction bidding phase. Current decision: {gc.pending_decision_type}"}
            
        auction_player_id = gc.pending_decision_context.get("player_id")
        if auction_player_id != player_id:
            return {"status": "failure", "message": f"Not your turn to pass. Current bidder: {auction_player_id}"}
        
        # Execute pass through auction manager
        success = gc.auction_manager.handle_auction_pass(player_id)
        
        if success:
            message = f"{player.name} passed on auction bid"
            result = {"status": "success", "message": message}
        else:
            result = {"status": "failure", "message": "Failed to pass auction bid"}
            
        _log_agent_action(gc, player_id, "tool_pass_auction_bid", {}, result)
        return result
    except Exception as e: 
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Auction pass error: {str(e)}"}

@tradar_verifier
def tool_withdraw_from_auction(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player withdraws from the current auction entirely."""
    player = gc.players[player_id]
    try:
        is_active = player_id in [p.player_id for p in gc.auction_active_bidders]
        if not (gc.auction_in_progress and is_active):
             return {"status": "failure", "message": "Cannot withdraw: not in auction or not an active participant."}
        # Note: GC's _handle_auction_withdraw might be same as pass. Agent might not need this if pass covers it.
        gc._handle_auction_withdraw(player)
        result = {"status": "success", "message": f"{player.name} withdrew from auction."}
        _log_agent_action(gc, player_id, "tool_withdraw_from_auction", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Trade Tools ---
@tradar_verifier
def validate_and_correct_trade_property_ids(gc, proposer_id: int, recipient_id: int, 
                                           offered_property_ids: List[int], 
                                           requested_property_ids: List[int]) -> Tuple[bool, List[int], List[int], str]:
    """
    Validate and intelligently correct property IDs in trade proposals.
    
    Returns:
        Tuple[success, corrected_offered_ids, corrected_requested_ids, error_message]
    """
    error_messages = []
    corrected_offered = offered_property_ids.copy()
    corrected_requested = requested_property_ids.copy()
    
    proposer = gc.players[proposer_id]
    recipient = gc.players[recipient_id]
    
    # Build property name to ID mappings for smart suggestions
    all_properties = {}
    proposer_properties = {}
    recipient_properties = {}
    
    try:
        for pid in range(40):  # Standard Monopoly board has 40 squares
            square = gc.board.get_square(pid)
            if hasattr(square, 'owner_id') and hasattr(square, 'name'):
                all_properties[square.name.lower()] = pid
                if square.owner_id == proposer_id:
                    proposer_properties[square.name.lower()] = pid
                elif square.owner_id == recipient_id:
                    recipient_properties[square.name.lower()] = pid
    except:
        pass  # Continue without smart suggestions if board access fails
    
    # Validate offered properties (proposer must own them)
    invalid_offered = []
    for prop_id in offered_property_ids:
        if prop_id not in proposer.properties_owned_ids:
            invalid_offered.append(prop_id)
    
    if invalid_offered:
        prop_names = []
        suggestion_text = ""
        
        for prop_id in invalid_offered:
            try:
                square = gc.board.get_square(prop_id)
                prop_names.append(f"{square.name} (ID: {prop_id})")
                
                # Add smart suggestion if this property is owned by recipient
                if hasattr(square, 'owner_id') and square.owner_id == recipient_id:
                    suggestion_text += f"\n💡 SUGGESTION: {square.name} is owned by {recipient.name}. Did you mean to REQUEST it instead of OFFER it?\n"
                    
            except:
                prop_names.append(f"Property ID: {prop_id}")
        
        error_messages.append(f"❌ {proposer.name} doesn't own: {', '.join(prop_names)}")
        
        # Show what proposer actually owns in a clear format
        owned_list = []
        for pid in sorted(proposer.properties_owned_ids):
            try:
                square = gc.board.get_square(pid)
                owned_list.append(f"{square.name} (ID: {pid})")
            except:
                owned_list.append(f"ID: {pid}")
        
        if owned_list:
            error_messages.append(f"✅ {proposer.name} actually owns: {owned_list}")
        else:
            error_messages.append(f"✅ {proposer.name} owns no properties")
            
        if suggestion_text:
            error_messages.append(suggestion_text)
        
        # Remove invalid IDs
        corrected_offered = [pid for pid in offered_property_ids if pid in proposer.properties_owned_ids]
    
    # Validate requested properties (recipient must own them)
    invalid_requested = []
    for prop_id in requested_property_ids:
        if prop_id not in recipient.properties_owned_ids:
            invalid_requested.append(prop_id)
    
    if invalid_requested:
        prop_names = []
        suggestion_text = ""
        
        for prop_id in invalid_requested:
            try:
                square = gc.board.get_square(prop_id)
                prop_names.append(f"{square.name} (ID: {prop_id})")
                
                # Add smart suggestion if this property is owned by proposer
                if hasattr(square, 'owner_id') and square.owner_id == proposer_id:
                    suggestion_text += f"\n💡 SUGGESTION: {square.name} is owned by {proposer.name}. Did you mean to OFFER it instead of REQUEST it?\n"
                    
            except:
                prop_names.append(f"Property ID: {prop_id}")
        
        error_messages.append(f"❌ {recipient.name} doesn't own: {', '.join(prop_names)}")
        
        # Show what recipient actually owns in a clear format
        owned_list = []
        for pid in sorted(recipient.properties_owned_ids):
            try:
                square = gc.board.get_square(pid)
                owned_list.append(f"{square.name} (ID: {pid})")
            except:
                owned_list.append(f"ID: {pid}")
        
        if owned_list:
            error_messages.append(f"✅ {recipient.name} actually owns: {owned_list}")
        else:
            error_messages.append(f"✅ {recipient.name} owns no properties")
            
        if suggestion_text:
            error_messages.append(suggestion_text)
        
        # Remove invalid IDs
        corrected_requested = [pid for pid in requested_property_ids if pid in recipient.properties_owned_ids]
    
    if error_messages:
        full_error = "PROPERTY OWNERSHIP VALIDATION FAILED:\n" + "\n".join(error_messages)
        full_error += f"\n\n🎯 QUICK FIX GUIDE:"
        full_error += f"\n1. ✅ Check the 'PROPERTY OWNERSHIP REFERENCE' section in your prompt"
        full_error += f"\n2. ✅ Use property IDs from 'MY PROPERTIES' for offered_property_ids"
        full_error += f"\n3. ✅ Use property IDs from '{recipient.name.upper()} PROPERTIES' for requested_property_ids"
        full_error += f"\n4. ✅ Verify the property name matches the ID you're using"
        return False, corrected_offered, corrected_requested, full_error
    
    return True, corrected_offered, corrected_requested, ""

@tradar_verifier
def tool_propose_trade(gc: Any, player_id: int, recipient_id: int,
                         offered_property_ids: Optional[List[int]] = None, offered_money: int = 0, offered_get_out_of_jail_free_cards: int = 0,
                         requested_property_ids: Optional[List[int]] = None, requested_money: int = 0, requested_get_out_of_jail_free_cards: int = 0,
                         message: Optional[str] = None) -> Dict[str, Any]:
    try:
        # 🔍 ENHANCED VALIDATION WITH INTELLIGENT ERROR MESSAGES
        
        if player_id == recipient_id: 
            return {"status": "failure", "message": "Cannot propose trade to yourself. Choose a different recipient_id."}
        
        if not (0 <= recipient_id < len(gc.players)) or gc.players[recipient_id].is_bankrupt:
            available_recipients = [f"P{i} ({gc.players[i].name})" for i in range(len(gc.players)) if i != player_id and not gc.players[i].is_bankrupt]
            return {"status": "failure", "message": f"Invalid or bankrupt recipient P{recipient_id}. Available recipients: {available_recipients}"}

        # Normalize empty lists
        offered_property_ids = offered_property_ids or []
        requested_property_ids = requested_property_ids or []
        
        proposer = gc.players[player_id]
        recipient = gc.players[recipient_id]
        
        # 🎯 NEW: Use enhanced validation function
        is_valid, corrected_offered, corrected_requested, error_msg = validate_and_correct_trade_property_ids(
            gc, player_id, recipient_id, offered_property_ids, requested_property_ids
        )
        
        if not is_valid:
            return {"status": "failure", "message": error_msg}
        
        # Validate money amounts
        if offered_money > proposer.money:
            return {"status": "failure", "message": f"You only have ${proposer.money}, cannot offer ${offered_money}. Reduce offered_money parameter."}
        
        if requested_money > recipient.money:
            return {"status": "failure", "message": f"Recipient {recipient.name} only has ${recipient.money}, cannot pay ${requested_money}. Reduce requested_money parameter."}

        # 🎯 Now call the GC method with validated parameters
        trade_id = gc.propose_trade_action(player_id, recipient_id, 
                                         offered_property_ids or [], offered_money or 0, offered_get_out_of_jail_free_cards or 0,
                                         requested_property_ids or [], requested_money or 0, requested_get_out_of_jail_free_cards or 0,
                                         message=message
                                         )
        status = "success" if trade_id is not None else "failure"
        log_message_str = f"Trade proposal to P{recipient_id} ({gc.players[recipient_id].name}): {status}."
        if trade_id is not None: 
            log_message_str += f" Trade ID: {trade_id}"
        else: 
            log_message_str += " (Proposal failed validation in GC - check logs). This may be due to game state constraints."
        
        params_log = {
            "recipient_id": recipient_id,
            "offered_property_ids": offered_property_ids or [],
            "offered_money": offered_money or 0,
            "offered_get_out_of_jail_free_cards": offered_get_out_of_jail_free_cards or 0,
            "requested_property_ids": requested_property_ids or [],
            "requested_money": requested_money or 0,
            "requested_get_out_of_jail_free_cards": requested_get_out_of_jail_free_cards or 0,
            "message": message
        }
        result = {"status": status, "message": log_message_str, "trade_id": trade_id}
        _log_agent_action(gc, player_id, "tool_propose_trade", params_log, result)
        return result
    except Exception as e: 
        gc.log_event(f"[Tool Exception] tool_propose_trade: {e}", "error_log")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_accept_trade(gc: Any, player_id: int, trade_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        tid = trade_id if trade_id is not None else gc.pending_decision_context.get("trade_id")
        if tid is None: return {"status": "failure", "message": "Trade ID missing for accept."}
        if not (gc.pending_decision_type == "respond_to_trade_offer" and gc.pending_decision_context.get("trade_id") == tid and gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": f"Not in state to accept trade {tid}. Pend: '{gc.pending_decision_type}', CtxP: {gc.pending_decision_context.get('player_id')}"}
        
        # Call async GC method properly
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc._respond_to_trade_offer_action(player_id, tid, "accept"), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc._respond_to_trade_offer_action(player_id, tid, "accept"))
            
        log_message_str = f"Accepted trade {tid}: {'OK' if success else 'FAIL'}."
        if not success: log_message_str += " (Conditions may have changed or transfer failed - see GC logs)"
        result = {"status": "success" if success else "failure", "message": log_message_str}
        _log_agent_action(gc, player_id, "tool_accept_trade", {"trade_id": tid}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_reject_trade(gc: Any, player_id: int, trade_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        tid = trade_id if trade_id is not None else gc.pending_decision_context.get("trade_id")
        if tid is None: return {"status": "failure", "message": "Trade ID missing for reject."}
        if not (gc.pending_decision_type == "respond_to_trade_offer" and gc.pending_decision_context.get("trade_id") == tid and gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": "Not in state to reject this trade."}
        
        # Call async GC method properly
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc._respond_to_trade_offer_action(player_id, tid, "reject"), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc._respond_to_trade_offer_action(player_id, tid, "reject"))
            
        result = {"status": "success" if success else "failure", "message": f"Rejected trade {tid}: {'OK' if success else 'FAIL'}."}
        _log_agent_action(gc, player_id, "tool_reject_trade", {"trade_id": tid}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_propose_counter_offer(gc: Any, player_id: int, trade_id: Optional[int] = None, 
                                 offered_property_ids: Optional[List[int]] = None, offered_money: int = 0, offered_get_out_of_jail_free_cards: int = 0,
                                 requested_property_ids: Optional[List[int]] = None, requested_money: int = 0, requested_get_out_of_jail_free_cards: int = 0,
                                 counter_message: Optional[str] = None) -> Dict[str, Any]:
    try:
        original_trade_id = trade_id if trade_id is not None else gc.pending_decision_context.get("trade_id")
        if original_trade_id is None: return {"status": "failure", "message": "Original Trade ID missing for counter."}
        
        if not (gc.pending_decision_type == "respond_to_trade_offer" and 
                gc.pending_decision_context.get("trade_id") == original_trade_id and 
                gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": "Not in state to counter this trade."}

        # Get the original proposer (who will be the recipient of the counter-offer)
        if original_trade_id not in gc.trade_offers:
            return {"status": "failure", "message": f"Original trade {original_trade_id} not found."}
        
        original_offer = gc.trade_offers[original_trade_id]
        original_proposer_id = original_offer.proposer_id  # This is who we're countering to
        
        # Normalize empty lists
        offered_property_ids = offered_property_ids or []
        requested_property_ids = requested_property_ids or []
        
        # 🎯 NEW: Use pre-validation for quick error detection
        counter_params = {
            "recipient_id": original_proposer_id,
            "offered_property_ids": offered_property_ids,
            "offered_money": offered_money,
            "offered_get_out_of_jail_free_cards": offered_get_out_of_jail_free_cards,
            "requested_property_ids": requested_property_ids,
            "requested_money": requested_money,
            "requested_get_out_of_jail_free_cards": requested_get_out_of_jail_free_cards
        }
        
        is_valid, validation_error = pre_validate_action(gc, player_id, "tool_propose_counter_offer", counter_params)
        if not is_valid:
            result = {"status": "failure", "message": f"COUNTER-OFFER PRE-VALIDATION FAILED:\n{validation_error}"}
            _log_agent_action(gc, player_id, "tool_propose_counter_offer", counter_params, result)
            return result
        
        # Enhanced validation using existing system (for more complex checks)
        is_valid, corrected_offered, corrected_requested, error_msg = validate_and_correct_trade_property_ids(
            gc, player_id, original_proposer_id, offered_property_ids, requested_property_ids
        )
        
        if not is_valid:
            result = {"status": "failure", "message": f"COUNTER-OFFER VALIDATION FAILED:\n{error_msg}"}
            _log_agent_action(gc, player_id, "tool_propose_counter_offer", counter_params, result)
            return result

        # Call async GC method properly
        import asyncio
        try:
            # If we're already in an async context, use await
            loop = asyncio.get_running_loop()
            # We're in asyncio.to_thread, so we need to call the async method differently
            success = asyncio.run_coroutine_threadsafe(
                gc._respond_to_trade_offer_action(player_id, original_trade_id, "counter",
                                                 counter_offered_prop_ids=offered_property_ids or [], 
                                                 counter_offered_money=offered_money or 0,
                                                 counter_offered_gooj_cards=offered_get_out_of_jail_free_cards or 0, 
                                                 counter_requested_prop_ids=requested_property_ids or [],
                                                 counter_requested_money=requested_money or 0, 
                                                 counter_requested_gooj_cards=requested_get_out_of_jail_free_cards or 0,
                                                 counter_message=counter_message), loop
            ).result()
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            success = asyncio.run(gc._respond_to_trade_offer_action(player_id, original_trade_id, "counter",
                                                 counter_offered_prop_ids=offered_property_ids or [], 
                                                 counter_offered_money=offered_money or 0,
                                                 counter_offered_gooj_cards=offered_get_out_of_jail_free_cards or 0, 
                                                 counter_requested_prop_ids=requested_property_ids or [],
                                                 counter_requested_money=requested_money or 0, 
                                                 counter_requested_gooj_cards=requested_get_out_of_jail_free_cards or 0,
                                                 counter_message=counter_message))
                                                 
        log_message_str = f"Counter-offer to trade {original_trade_id}: {'OK' if success else 'FAIL'}."
        if not success: log_message_str += " (Counter proposal failed validation - see GC logs)"
        result = {"status": "success" if success else "failure", "message": log_message_str}
        
        params_log = {
            "trade_id": original_trade_id,
            "offered_property_ids": offered_property_ids or [], "offered_money": offered_money or 0, "offered_get_out_of_jail_free_cards": offered_get_out_of_jail_free_cards or 0,
            "requested_property_ids": requested_property_ids or [], "requested_money": requested_money or 0, "requested_get_out_of_jail_free_cards": requested_get_out_of_jail_free_cards or 0,
            "counter_message": counter_message
        }
        _log_agent_action(gc, player_id, "tool_propose_counter_offer", params_log, result)
        return result
    except Exception as e: 
        gc.log_event(f"[Tool Exception] tool_propose_counter_offer: {e}", "error_log")
        return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_end_trade_negotiation(gc: Any, player_id: int, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Player (original proposer) decides to end the trade negotiation after their offer was rejected."""
    if params is None: params = {}
    try:
        action_result = gc._end_trade_negotiation_action(player_id, params)
        
        _log_agent_action(gc, player_id, "tool_end_trade_negotiation", params, action_result)
        return action_result
    except Exception as e:
        gc.log_event(f"[Tool Exception] tool_end_trade_negotiation: {e}", "error_log")
        return {"status": "error", "message": str(e)}

# --- Tools for Handling Received Mortgaged Property ---
@tradar_verifier
def tool_pay_mortgage_interest_fee(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player pays the 10% fee on a mortgaged property they received via trade."""
    try:
        target_property_id = property_id
        if target_property_id is None:
            if gc.pending_decision_type == "handle_received_mortgaged_properties" and gc.pending_decision_context.get("property_id_to_handle"):
                target_property_id = gc.pending_decision_context["property_id_to_handle"]
            else: return {"status": "failure", "message": "Property ID missing or not in handle_mortgaged_property phase for 10% fee."}
        
        success = gc._handle_received_mortgaged_property_action(player_id, target_property_id, "pay_fee")
        message = f"Pay 10% fee for mortgaged prop {target_property_id}: {'OK' if success else 'Fail'}."
        if not success: message += " (Could not afford or other issue - see GC logs)"
        result = {"status": "success" if success else "failure", "message": message}
        _log_agent_action(gc, player_id, "tool_pay_mortgage_interest_fee", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

@tradar_verifier
def tool_unmortgage_property_immediately(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player chooses to immediately unmortgage a property they received via trade (pays 1.1x mortgage value)."""
    try:
        target_property_id = property_id
        if target_property_id is None:
            if gc.pending_decision_type == "handle_received_mortgaged_properties" and gc.pending_decision_context.get("property_id_to_handle"):
                target_property_id = gc.pending_decision_context["property_id_to_handle"]
            else: return {"status": "failure", "message": "Property ID missing or not in handle_mortgaged_property phase for unmortgage."}

        success = gc._handle_received_mortgaged_property_action(player_id, target_property_id, "unmortgage_now")
        message = f"Unmortgage prop {target_property_id} immediately: {'OK' if success else 'Fail'}."
        if not success: message += " (Could not afford or other issue - see GC logs)"
        result = {"status": "success" if success else "failure", "message": message}
        _log_agent_action(gc, player_id, "tool_unmortgage_property_immediately", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)} 

# Add intelligent property name to ID conversion system
@tradar_verifier
def smart_property_name_to_id_converter(gc, property_names_or_ids: List[str]) -> Tuple[List[int], List[str]]:
    """
    Intelligently convert property names or IDs to valid property IDs.
    
    Args:
        gc: Game controller instance
        property_names_or_ids: List of property names (strings) or IDs (integers as strings)
    
    Returns:
        Tuple[resolved_ids, error_messages]
    """
    resolved_ids = []
    error_messages = []
    
    for item in property_names_or_ids:
        if isinstance(item, int):
            # Already an ID
            try:
                square = gc.board.get_square(item)
                resolved_ids.append(item)
            except:
                error_messages.append(f"Invalid property ID: {item}")
        elif isinstance(item, str):
            if item.isdigit():
                # String representation of ID
                prop_id = int(item)
                try:
                    square = gc.board.get_square(prop_id)
                    resolved_ids.append(prop_id)
                except:
                    error_messages.append(f"Invalid property ID: {prop_id}")
            else:
                # Property name - search for it
                found_id = None
                for i, square in enumerate(gc.board.squares):
                    if hasattr(square, 'name') and square.name.lower() == item.lower():
                        found_id = i
                        break
                
                if found_id is not None:
                    resolved_ids.append(found_id)
                else:
                    # Fuzzy matching for common mistakes
                    similar_properties = []
                    for i, square in enumerate(gc.board.squares):
                        if hasattr(square, 'name'):
                            # Simple fuzzy matching
                            if (item.lower() in square.name.lower() or 
                                square.name.lower() in item.lower()):
                                similar_properties.append(f"{square.name} (ID: {i})")
                    
                    if similar_properties:
                        error_messages.append(f"Property '{item}' not found. Did you mean: {', '.join(similar_properties[:3])}?")
                    else:
                        error_messages.append(f"Property '{item}' not found.")
        else:
            error_messages.append(f"Invalid property reference: {item} (must be name or ID)")
    
    return resolved_ids, error_messages 

# Alternative structured trade tool to reduce parameter confusion
@tradar_verifier
def tool_propose_trade_structured(gc: Any, player_id: int, trade_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Propose a trade using structured input to reduce parameter confusion.
    
    Expected trade_details format:
    {
        "to_player": "player_name_or_id",
        "i_give": {
            "properties": ["property_name_1", "property_name_2"] or [id1, id2],
            "money": 100,
            "gooj_cards": 0
        },
        "i_want": {
            "properties": ["property_name_3"],
            "money": 50,
            "gooj_cards": 0
        },
        "message": "Let's make a deal!"
    }
    """
    try:
        # Extract and validate structure
        if not isinstance(trade_details, dict):
            return {"status": "failure", "message": "trade_details must be a dictionary with 'to_player', 'i_give', 'i_want' keys"}
        
        # Find recipient
        to_player = trade_details.get("to_player")
        if not to_player:
            return {"status": "failure", "message": "Missing 'to_player' in trade_details"}
        
        recipient_id = None
        if isinstance(to_player, int):
            recipient_id = to_player
        elif isinstance(to_player, str):
            # Try to find by name
            for i, player in enumerate(gc.players):
                if player.name.lower() == to_player.lower():
                    recipient_id = i
                    break
            
            # Try as ID string
            if recipient_id is None and to_player.isdigit():
                recipient_id = int(to_player)
        
        if recipient_id is None:
            available_players = [f"P{i} ({gc.players[i].name})" for i in range(len(gc.players)) if i != player_id]
            return {"status": "failure", "message": f"Player '{to_player}' not found. Available: {available_players}"}
        
        # Extract what I give
        i_give = trade_details.get("i_give", {})
        offered_properties = i_give.get("properties", [])
        offered_money = i_give.get("money", 0)
        offered_gooj = i_give.get("gooj_cards", 0)
        
        # Extract what I want
        i_want = trade_details.get("i_want", {})
        requested_properties = i_want.get("properties", [])
        requested_money = i_want.get("money", 0)
        requested_gooj = i_want.get("gooj_cards", 0)
        
        # Convert property names to IDs
        offered_prop_ids, offer_errors = smart_property_name_to_id_converter(gc, offered_properties)
        requested_prop_ids, request_errors = smart_property_name_to_id_converter(gc, requested_properties)
        
        if offer_errors or request_errors:
            error_msg = "PROPERTY CONVERSION ERRORS:\n"
            if offer_errors:
                error_msg += "Offered properties: " + "; ".join(offer_errors) + "\n"
            if request_errors:
                error_msg += "Requested properties: " + "; ".join(request_errors)
            return {"status": "failure", "message": error_msg}
        
        # Use the existing validated trade function
        return tool_propose_trade(
            gc, player_id, recipient_id,
            offered_property_ids=offered_prop_ids,
            offered_money=offered_money,
            offered_get_out_of_jail_free_cards=offered_gooj,
            requested_property_ids=requested_prop_ids,
            requested_money=requested_money,
            requested_get_out_of_jail_free_cards=requested_gooj,
            message=trade_details.get("message")
        )
        
    except Exception as e:
        return {"status": "error", "message": f"Error in structured trade: {str(e)}"} 

def pre_validate_action(gc, player_id: int, action_name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Pre-validate action parameters before execution to catch common errors early.
    
    Args:
        gc: Game controller instance
        player_id: ID of the player attempting the action
        action_name: Name of the action to validate
        params: Parameters for the action
        
    Returns:
        Tuple[is_valid, error_message]: True if valid, False with error message if invalid
    """
    try:
        player = gc.players[player_id]
        
        # Trade action pre-validation
        if action_name in ["tool_propose_trade", "tool_propose_counter_offer"]:
            recipient_id = params.get("recipient_id")
            offered_property_ids = params.get("offered_property_ids", [])
            requested_property_ids = params.get("requested_property_ids", [])
            offered_money = params.get("offered_money", 0)
            requested_money = params.get("requested_money", 0)
            
            # Basic recipient validation
            if recipient_id is None:
                return False, "❌ QUICK FIX: recipient_id parameter is missing"
            
            if not (0 <= recipient_id < len(gc.players)):
                return False, f"❌ QUICK FIX: recipient_id {recipient_id} is invalid. Valid IDs: 0-{len(gc.players)-1}"
            
            if recipient_id == player_id:
                return False, "❌ QUICK FIX: Cannot trade with yourself. Choose a different recipient_id"
            
            recipient = gc.players[recipient_id]
            if recipient.is_bankrupt:
                return False, f"❌ QUICK FIX: {recipient.name} is bankrupt. Choose a different recipient"
            
            # Quick property ownership check
            if offered_property_ids:
                for prop_id in offered_property_ids:
                    if prop_id not in player.properties_owned_ids:
                        try:
                            square = gc.board.get_square(prop_id)
                            return False, f"❌ QUICK FIX: You don't own {square.name} (ID:{prop_id}). Check your property list"
                        except:
                            return False, f"❌ QUICK FIX: Invalid property ID {prop_id} in offered_property_ids"
            
            if requested_property_ids:
                for prop_id in requested_property_ids:
                    if prop_id not in recipient.properties_owned_ids:
                        try:
                            square = gc.board.get_square(prop_id)
                            # Find who actually owns this property
                            actual_owner_name = "Bank"
                            if hasattr(square, 'owner_id') and square.owner_id is not None:
                                actual_owner_name = gc.players[square.owner_id].name if 0 <= square.owner_id < len(gc.players) else f"Player {square.owner_id}"
                            
                            if action_name == "tool_propose_counter_offer":
                                return False, f"❌ QUICK FIX: {recipient.name} doesn't own {square.name} (ID:{prop_id}). Check their property list\n💡 COUNTER-OFFER TIP: You can only request properties from {recipient.name}, not from {actual_owner_name}.\n🔄 Consider: 1) Accept/reject current offer, 2) Start new trade with {actual_owner_name}, or 3) Request different properties from {recipient.name}"
                            else:
                                return False, f"❌ QUICK FIX: {recipient.name} doesn't own {square.name} (ID:{prop_id}). It's owned by {actual_owner_name}. Check their property list"
                        except:
                            return False, f"❌ QUICK FIX: Invalid property ID {prop_id} in requested_property_ids"
            
            # Money validation
            if offered_money > player.money:
                return False, f"❌ QUICK FIX: You only have ${player.money}, cannot offer ${offered_money}"
            
            if requested_money > recipient.money:
                return False, f"❌ QUICK FIX: {recipient.name} only has ${recipient.money}, cannot request ${requested_money}"
        
        # Jail action pre-validation
        elif action_name in ["tool_roll_for_doubles_to_get_out_of_jail", "tool_pay_bail", "tool_use_get_out_of_jail_card"]:
            # These actions should only be available when player is in jail with appropriate decision context
            if not player.in_jail:
                return False, f"❌ QUICK FIX: {player.name} is not in jail. Current position: {player.position}"
            
            if gc.pending_decision_type != "jail_options":
                return False, f"❌ QUICK FIX: Not in jail decision state. Current pending decision: {gc.pending_decision_type or 'None'}"
            
            if gc.pending_decision_context.get("player_id") != player_id:
                return False, f"❌ QUICK FIX: Jail decision is not for {player.name}. Wait for your jail turn."
            
            # Specific validation for roll attempts
            if action_name == "tool_roll_for_doubles_to_get_out_of_jail":
                if gc.pending_decision_context.get("max_rolls_attempted", False):
                    return False, "❌ QUICK FIX: You have used all your roll attempts. Use tool_pay_bail or tool_use_get_out_of_jail_card"
        
        # Property action pre-validation
        elif action_name in ["tool_mortgage_property", "tool_unmortgage_property", "tool_build_house", "tool_sell_house"]:
            property_id = params.get("property_id")
            
            if property_id is None:
                return False, "❌ QUICK FIX: property_id parameter is missing"
            
            if property_id not in player.properties_owned_ids:
                try:
                    square = gc.board.get_square(property_id)
                    if hasattr(square, 'owner_id') and square.owner_id is not None:
                        owner_name = gc.players[square.owner_id].name if 0 <= square.owner_id < len(gc.players) else f"Player {square.owner_id}"
                        return False, f"❌ QUICK FIX: You don't own {square.name} (ID:{property_id}). It's owned by {owner_name}"
                    else:
                        return False, f"❌ QUICK FIX: {square.name} (ID:{property_id}) is unowned (bank property)"
                except:
                    return False, f"❌ QUICK FIX: Invalid property_id {property_id}"
            
            # Get the property square for further validation
            try:
                square = gc.board.get_square(property_id)
            except:
                return False, f"❌ QUICK FIX: Invalid property_id {property_id}"
            
            # Mortgage-specific validation
            if action_name == "tool_mortgage_property":
                if hasattr(square, 'is_mortgaged') and square.is_mortgaged:
                    return False, f"❌ QUICK FIX: {square.name} is already mortgaged. Use tool_unmortgage_property instead"
                
                # Check for houses
                if hasattr(square, 'num_houses') and square.num_houses > 0:
                    houses_str = f"{square.num_houses} houses" if square.num_houses < 5 else "a hotel"
                    return False, f"❌ QUICK FIX: {square.name} has {houses_str}. Sell houses first with tool_sell_house"
            
            elif action_name == "tool_unmortgage_property":
                if hasattr(square, 'is_mortgaged') and not square.is_mortgaged:
                    return False, f"❌ QUICK FIX: {square.name} is not mortgaged. Use tool_mortgage_property to mortgage it"
                
                # Check if player has enough money to unmortgage
                if hasattr(square, 'mortgage_value'):
                    unmortgage_cost = int(square.mortgage_value * 1.1)  # 10% interest
                    if player.money < unmortgage_cost:
                        return False, f"❌ QUICK FIX: Need ${unmortgage_cost} to unmortgage {square.name}, you only have ${player.money}"
            
            elif action_name == "tool_build_house":
                # Quick monopoly check
                if hasattr(square, 'color_group'):
                    color_group = square.color_group
                    owned_in_group = 0
                    total_in_group = 0
                    
                    for pid in range(40):
                        try:
                            sq = gc.board.get_square(pid)
                            if hasattr(sq, 'color_group') and sq.color_group == color_group:
                                total_in_group += 1
                                if sq.owner_id == player_id:
                                    owned_in_group += 1
                        except:
                            pass
                    
                    if owned_in_group < total_in_group:
                        return False, f"❌ QUICK FIX: You need ALL {color_group.name} properties to build houses. You own {owned_in_group}/{total_in_group}"
                
                # Check if already has hotel
                if hasattr(square, 'num_houses') and square.num_houses >= 5:
                    return False, f"❌ QUICK FIX: {square.name} already has a hotel (maximum development)"
                
                # Check money for house cost
                if hasattr(square, 'house_price') and player.money < square.house_price:
                    return False, f"❌ QUICK FIX: House costs ${square.house_price}, you only have ${player.money}"
        
        # Buy property validation
        elif action_name == "tool_buy_property":
            property_id = params.get("property_id")
            
            if property_id is not None:
                try:
                    square = gc.board.get_square(property_id)
                    if hasattr(square, 'owner_id') and square.owner_id is not None:
                        owner_name = gc.players[square.owner_id].name if 0 <= square.owner_id < len(gc.players) else f"Player {square.owner_id}"
                        return False, f"❌ QUICK FIX: {square.name} is already owned by {owner_name}"
                    
                    if hasattr(square, 'price') and player.money < square.price:
                        return False, f"❌ QUICK FIX: {square.name} costs ${square.price}, you only have ${player.money}"
                        
                except:
                    return False, f"❌ QUICK FIX: Invalid property_id {property_id}"
        
        return True, ""  # No issues found
        
    except Exception as e:
        return False, f"❌ VALIDATION ERROR: {e}"


# Enhanced wrapper for tool functions with pre-validation
def execute_tool_with_validation(gc, player_id: int, tool_name: str, params: Dict[str, Any], tool_function):
    """
    Execute a tool function with pre-validation and enhanced error handling.
    """
    # 🎯 PRE-VALIDATION: Check for obvious errors before execution
    is_valid, validation_error = pre_validate_action(gc, player_id, tool_name, params)
    if not is_valid:
        result = {"status": "failure", "message": validation_error}
        _log_agent_action(gc, player_id, tool_name, params, result)
        return result
    
    # 🚨 DEADLOCK PREVENTION: Check for repeated failures
    if gc.check_repeated_failure(player_id, tool_name, params):
        result = {
            "status": "failure", 
            "message": "🚨 DEADLOCK PREVENTION: This exact action has failed multiple times recently. Try a different approach or end turn."
        }
        _log_agent_action(gc, player_id, tool_name, params, result)
        return result
    
    # Execute the actual tool function
    try:
        result = tool_function(gc, player_id, **params)
        _log_agent_action(gc, player_id, tool_name, params, result)
        return result
    except Exception as e:
        result = {"status": "error", "message": f"Tool execution error: {e}"}
        _log_agent_action(gc, player_id, tool_name, params, result)
        return result