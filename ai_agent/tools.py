from typing import Dict, Any, List, Optional

# It's better to import GameController directly if possible to get type hinting,
# but this can cause circular dependencies if GameController also needs to know about tools.
# Using 'Any' for game_controller for now, and casting internally or relying on duck typing.
# from game_logic.game_controller import GameController # Ideal import

# --- Helper to log tool usage (optional, can be integrated into each tool)
def _log_agent_action(gc: Any, player_id: int, tool_name: str, params: Dict[str, Any], result: Dict[str, Any]):
    player = gc.players[player_id]
    gc.log_event(f"Agent {player.name} (P{player_id}) used Tool '{tool_name}' with {params}. Result: {result.get('status')} - {result.get('message', '')}")

# --- Basic Turn Actions ---

def tool_roll_dice(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player rolls the dice to take their main turn action (move, etc.)."""
    player = gc.players[player_id]
    try:
        if player.is_bankrupt: return {"status": "failure", "message": "Bankrupt."}
        is_main_turn_player = (gc.current_player_index == player_id)
        if not (is_main_turn_player and gc.pending_decision_type is None and not gc.auction_in_progress):
             return {"status": "failure", "message": "Not in state for main turn roll."}
        if not gc.dice_roll_outcome_processed: return {"status": "failure", "message": "Dice outcome pending."}
        if player.in_jail: return {"status": "failure", "message": "In jail; use jail roll tool."}
        dice_roll = gc.roll_dice()
        went_to_jail = (gc.doubles_streak == 3 and player.in_jail)
        msg = f"Rolled {dice_roll}."
        if went_to_jail: msg += " Went to jail (3x doubles)."
        result = {"status": "success", "message": msg, "dice_roll": dice_roll, "went_to_jail": went_to_jail}
        _log_agent_action(gc, player_id, "tool_roll_dice", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_end_turn(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player explicitly ends their turn or current segment of complex actions."""
    player = gc.players[player_id]
    try:
        # GC.get_available_actions should primarily gate this.
        # This tool just signals intent; GC resolves the state.
        gc._resolve_current_action_segment()
        result = {"status": "success", "message": f"{player.name} signals end of segment/turn."}
        _log_agent_action(gc, player_id, "tool_end_turn", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Property Actions ---
def tool_buy_property(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player attempts to buy an unowned property. If property_id is None, it tries to buy the one set in pending_decision_context."""
    player = gc.players[player_id]
    try:
        target_property_id = property_id if property_id is not None else gc.pending_decision_context.get("property_id")
        
        if not (gc.pending_decision_type == "buy_or_auction_property" and 
                gc.pending_decision_context.get("player_id") == player_id and 
                target_property_id is not None):
            return {"status": "failure", "message": "Not in correct state to buy property or property_id missing."}
        
        square_to_buy = gc.board.get_square(target_property_id)
        success = gc.execute_buy_property_decision(player_id, target_property_id)
        
        status_msg = "OK" if success else "FAIL"
        if not success:
            # Try to get a more specific reason if buy failed due to funds (GC method would log it)
            if player.money < square_to_buy.price: # Re-check, though GC method does it.
                status_msg += " (Insufficient funds likely)"
            else:
                status_msg += " (Reasons in GC log or property already owned/invalid state)"

        result = {"status": "success" if success else "failure", "message": f"Buy {square_to_buy.name}: {status_msg}."}
        _log_agent_action(gc, player_id, "tool_buy_property", {"property_id": target_property_id}, result)
        return result
    except Exception as e: 
        gc.log_event(f"[Exception] tool_buy_property: {e}")
        return {"status": "error", "message": str(e)}

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
        success = gc._pass_on_buying_property_action(player, square)
        result = {"status": "success" if success else "failure", "message": f"Passed on buying {square.name}. Auction initiated by GC."}
        _log_agent_action(gc, player_id, "tool_pass_on_buying_property", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Asset Management (These tools might be called when pending_decision_type is None or "asset_management") ---
def tool_build_house(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to build a house/hotel on one of their properties."""
    try:
        # Asset management can happen when no other specific decision is pending.
        # gc.pending_decision_type might be None or a generic "manage_assets" phase.
        success = gc.build_house_on_property(player_id, property_id)
        status = "success" if success else "failure"
        # GameController method build_house_on_property already logs details.
        message = f"Build house on property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_build_house", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tool_sell_house(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to sell a house/hotel from one of their properties."""
    try:
        success = gc.sell_house_on_property(player_id, property_id)
        status = "success" if success else "failure"
        message = f"Sell house on property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_sell_house", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tool_mortgage_property(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to mortgage one of their properties."""
    try:
        success = gc.mortgage_property_for_player(player_id, property_id)
        status = "success" if success else "failure"
        message = f"Mortgage property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_mortgage_property", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tool_unmortgage_property(gc: Any, player_id: int, property_id: int) -> Dict[str, Any]:
    """Player attempts to unmortgage one of their properties."""
    try:
        success = gc.unmortgage_property_for_player(player_id, property_id)
        status = "success" if success else "failure"
        message = f"Unmortgage property {property_id}: {status}."
        result = {"status": status, "message": message}
        _log_agent_action(gc, player_id, "tool_unmortgage_property", {"property_id": property_id}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Jail Actions (Called when gc.pending_decision_type == "jail_options") ---
def tool_pay_bail(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        if not (player.in_jail and gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot pay bail: not in correct jail decision state."}
        # Call GC method with player_id and params (even if empty for this specific tool)
        action_outcome = gc._pay_to_get_out_of_jail(player_id, params) 
        result = {"status": action_outcome.get("status"), "message": action_outcome.get("message", "Pay bail attempt processed.")}
        _log_agent_action(gc, player_id, "tool_pay_bail", params, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_use_get_out_of_jail_card(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        if not (player.in_jail and gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot use GOOJ card: not in correct jail decision state."}
        if not (player.has_chance_gooj_card or player.has_community_gooj_card):
            return {"status": "failure", "message": "No GOOJ card to use."}
        # Call GC method with player_id and params
        action_outcome = gc._use_card_to_get_out_of_jail(player_id, params) 
        result = {"status": action_outcome.get("status"), "message": action_outcome.get("message", "Use GOOJ card attempt processed.")}
        _log_agent_action(gc, player_id, "tool_use_get_out_of_jail_card", params, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_roll_for_doubles_to_get_out_of_jail(gc: Any, player_id: int, params: Dict[str, Any] = None) -> Dict[str, Any]:
    player = gc.players[player_id]
    if params is None: params = {} # Ensure params is a dict
    try:
        if not (player.in_jail and gc.pending_decision_type == "jail_options" and gc.pending_decision_context.get("player_id") == player_id):
             return {"status": "failure", "message": "Cannot roll for jail: not in correct jail decision state."}
        # The check for player.jail_turns_remaining >=3 should ideally be handled by GC's _attempt_roll_out_of_jail or get_available_actions
        # However, keeping a preliminary check here can be useful.
        if player.jail_turns_remaining >=3 and not gc.pending_decision_context.get("max_rolls_attempted", False):
             # This condition is a bit redundant if _attempt_roll_out_of_jail handles it robustly by returning error
             # For safety, ensure agent doesn't try to roll if GC logic already determined max attempts.
             pass # Let GC method handle max attempts error
        
        # Call GC method with player_id and params
        action_outcome = gc._attempt_roll_out_of_jail(player_id, params)
        dice_rolled = action_outcome.get("dice_roll", gc.dice) 
        got_out = action_outcome.get("got_out", False)
        message = action_outcome.get("message", f"Roll for doubles (in jail): Dice {dice_rolled}, Got out: {got_out}.")
        
        result = {"status": action_outcome.get("status"), "message": message, "dice_roll": dice_rolled, "got_out": got_out}
        _log_agent_action(gc, player_id, "tool_roll_for_doubles_to_get_out_of_jail", params, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

# --- Bankruptcy Flow Tool ---
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

def tool_wait(gc: Any, player_id: int) -> Dict[str, Any]: # Typically used if not agent's turn but somehow asked
    try:
        result = {"status": "success", "message": "Player is waiting (e.g., not their active turn segment)."}
        _log_agent_action(gc, player_id, "tool_wait", {}, result)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
def tool_bid_on_auction(gc: Any, player_id: int, bid_amount: int) -> Dict[str, Any]:
    """Player places a bid in an ongoing auction."""
    player = gc.players[player_id]
    try:
        if not (gc.auction_in_progress and gc.pending_decision_type == "auction_bid" and gc.pending_decision_context.get("player_to_bid_id") == player_id):
            return {"status": "failure", "message": "Not player's turn to bid or auction not active."}
        gc._handle_auction_bid(player, bid_amount)
        message = f"{player.name} bids ${bid_amount}. GC logs actual acceptance."
        result = {"status": "success", "message": message}
        _log_agent_action(gc, player_id, "tool_bid_on_auction", {"bid_amount": bid_amount}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_pass_auction_bid(gc: Any, player_id: int) -> Dict[str, Any]:
    """Player passes their turn to bid in an ongoing auction."""
    player = gc.players[player_id]
    try:
        if not (gc.auction_in_progress and gc.pending_decision_type == "auction_bid" and gc.pending_decision_context.get("player_to_bid_id") == player_id):
            return {"status": "failure", "message": "Not player's turn to pass bid or auction not active."}
        gc._handle_auction_pass(player)
        result = {"status": "success", "message": f"{player.name} passed auction bid."}
        _log_agent_action(gc, player_id, "tool_pass_auction_bid", {}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

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
def tool_propose_trade(gc: Any, player_id: int, recipient_id: int,
                         offered_property_ids: Optional[List[int]] = None, offered_money: int = 0, offered_get_out_of_jail_free_cards: int = 0,
                         requested_property_ids: Optional[List[int]] = None, requested_money: int = 0, requested_get_out_of_jail_free_cards: int = 0,
                         message: Optional[str] = None) -> Dict[str, Any]:
    try:
        if player_id == recipient_id: return {"status": "failure", "message": "Cannot propose trade to oneself."}
        if not (0 <= recipient_id < len(gc.players)) or gc.players[recipient_id].is_bankrupt:
             return {"status": "failure", "message": f"Invalid or bankrupt recipient P{recipient_id}."}

        trade_id = gc.propose_trade_action(player_id, recipient_id, 
                                         offered_property_ids or [], offered_money or 0, offered_get_out_of_jail_free_cards or 0,
                                         requested_property_ids or [], requested_money or 0, requested_get_out_of_jail_free_cards or 0,
                                         message=message
                                         )
        status = "success" if trade_id is not None else "failure"
        log_message_str = f"Trade proposal to P{recipient_id} ({gc.players[recipient_id].name}): {status}."
        if trade_id is not None: log_message_str += f" Trade ID: {trade_id}"
        else: log_message_str += " (Proposal failed validation in GC - check logs)."
        
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

def tool_accept_trade(gc: Any, player_id: int, trade_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        tid = trade_id if trade_id is not None else gc.pending_decision_context.get("trade_id")
        if tid is None: return {"status": "failure", "message": "Trade ID missing for accept."}
        if not (gc.pending_decision_type == "respond_to_trade_offer" and gc.pending_decision_context.get("trade_id") == tid and gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": f"Not in state to accept trade {tid}. Pend: '{gc.pending_decision_type}', CtxP: {gc.pending_decision_context.get('player_id')}"}
        success = gc._respond_to_trade_offer_action(player_id, tid, "accept")
        log_message_str = f"Accepted trade {tid}: {'OK' if success else 'FAIL'}."
        if not success: log_message_str += " (Conditions may have changed or transfer failed - see GC logs)"
        result = {"status": "success" if success else "failure", "message": log_message_str}
        _log_agent_action(gc, player_id, "tool_accept_trade", {"trade_id": tid}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_reject_trade(gc: Any, player_id: int, trade_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        tid = trade_id if trade_id is not None else gc.pending_decision_context.get("trade_id")
        if tid is None: return {"status": "failure", "message": "Trade ID missing for reject."}
        if not (gc.pending_decision_type == "respond_to_trade_offer" and gc.pending_decision_context.get("trade_id") == tid and gc.pending_decision_context.get("player_id") == player_id):
            return {"status": "failure", "message": "Not in state to reject this trade."}
        success = gc._respond_to_trade_offer_action(player_id, tid, "reject")
        result = {"status": "success" if success else "failure", "message": f"Rejected trade {tid}: {'OK' if success else 'FAIL'}."}
        _log_agent_action(gc, player_id, "tool_reject_trade", {"trade_id": tid}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

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

        success = gc._respond_to_trade_offer_action(player_id, original_trade_id, "counter_offer",
                                                 counter_offered_prop_ids=offered_property_ids or [], 
                                                 counter_offered_money=offered_money or 0,
                                                 counter_offered_gooj_cards=offered_get_out_of_jail_free_cards or 0, 
                                                 requested_property_ids=requested_property_ids or [],
                                                 requested_money=requested_money or 0, 
                                                 requested_gooj_cards=requested_get_out_of_jail_free_cards or 0,
                                                 counter_message=counter_message
                                                 )
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
def tool_pay_mortgage_interest_fee(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player pays the 10% fee on a mortgaged property they received via trade."""
    try:
        target_property_id = property_id
        if target_property_id is None:
            if gc.pending_decision_type == "handle_received_mortgaged_property" and gc.pending_decision_context.get("property_id_to_handle"):
                target_property_id = gc.pending_decision_context["property_id_to_handle"]
            else: return {"status": "failure", "message": "Property ID missing or not in handle_mortgaged_property phase for 10% fee."}
        
        success = gc._handle_received_mortgaged_property_action(player_id, target_property_id, "pay_fee")
        message = f"Pay 10% fee for mortgaged prop {target_property_id}: {'OK' if success else 'Fail'}."
        if not success: message += " (Could not afford or other issue - see GC logs)"
        result = {"status": "success" if success else "failure", "message": message}
        _log_agent_action(gc, player_id, "tool_pay_mortgage_interest_fee", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)}

def tool_unmortgage_property_immediately(gc: Any, player_id: int, property_id: Optional[int] = None) -> Dict[str, Any]:
    """Player chooses to immediately unmortgage a property they received via trade (pays 1.1x mortgage value)."""
    try:
        target_property_id = property_id
        if target_property_id is None:
            if gc.pending_decision_type == "handle_received_mortgaged_property" and gc.pending_decision_context.get("property_id_to_handle"):
                target_property_id = gc.pending_decision_context["property_id_to_handle"]
            else: return {"status": "failure", "message": "Property ID missing or not in handle_mortgaged_property phase for unmortgage."}

        success = gc._handle_received_mortgaged_property_action(player_id, target_property_id, "unmortgage_now")
        message = f"Unmortgage prop {target_property_id} immediately: {'OK' if success else 'Fail'}."
        if not success: message += " (Could not afford or other issue - see GC logs)"
        result = {"status": "success" if success else "failure", "message": message}
        _log_agent_action(gc, player_id, "tool_unmortgage_property_immediately", {"property_id": target_property_id}, result)
        return result
    except Exception as e: return {"status": "error", "message": str(e)} 