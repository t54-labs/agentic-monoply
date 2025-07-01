import random
import time # For potential delays to make game watchable
from typing import Optional, Dict, Any, List, Tuple # Added Dict, Any, List, Tuple
import json # For pretty printing dicts
import datetime

from game_logic.game_controller_v2 import GameControllerV2
from game_logic.property import PurchasableSquare, SquareType, PropertySquare # Ensure PropertySquare is imported if used explicitly
from ai_agent.agent import OpenAIAgent # Assuming OpenAIAgent is the one we use
from ai_agent import tools as agent_tools # Import the tools module
from database import engine, agent_actions_table # Add agent_actions_table
from sqlalchemy import insert
from sqlalchemy.orm import Session # For DB operations if preferred

# --- Game Configuration ---
NUM_PLAYERS = 4 # As per requirement, 4 AI agents
PLAYER_NAMES = ["Player A", "Player B", "Player C", "Player D"] # Optional, will use defaults if None or not enough
MAX_TURNS = 500  # Max turns before game ends automatically
ACTION_DELAY_SECONDS = 2.0 # Delay between agent actions - Increased from 0.5
MAX_ACTIONS_PER_SEGMENT = 10 # Max actions an agent can take in a single turn segment before yielding/ending

# Global Fore, Style for colorama - defined here for potential import by server.py
class Fore: CYAN=YELLOW=GREEN=RED=MAGENTA=WHITE=BLACK=BLUE=""; LIGHTBLACK_EX=LIGHTBLUE_EX=LIGHTCYAN_EX=LIGHTGREEN_EX=LIGHTMAGENTA_EX=LIGHTRED_EX=LIGHTWHITE_EX=LIGHTYELLOW_EX=""
class Style: RESET_ALL=BRIGHT=DIM=NORMAL="";

# A simple registry to map tool names to functions
# This will need to be populated with all tools from ai_agent.tools
TOOL_REGISTRY = {
    # Basic Turn Actions
    "tool_roll_dice": agent_tools.tool_roll_dice,
    "tool_end_turn": agent_tools.tool_end_turn,
    # Property Actions
    "tool_buy_property": agent_tools.tool_buy_property,
    "tool_pass_on_buying_property": agent_tools.tool_pass_on_buying_property,
    # Asset Management
    "tool_build_house": agent_tools.tool_build_house,
    "tool_sell_house": agent_tools.tool_sell_house,
    "tool_mortgage_property": agent_tools.tool_mortgage_property,
    "tool_unmortgage_property": agent_tools.tool_unmortgage_property,
    # Jail Actions
    "tool_pay_bail": agent_tools.tool_pay_bail,
    "tool_use_get_out_of_jail_card": agent_tools.tool_use_get_out_of_jail_card,
    "tool_roll_for_doubles_to_get_out_of_jail": agent_tools.tool_roll_for_doubles_to_get_out_of_jail,
    # Placeholder/Fallback Actions
    "tool_do_nothing": agent_tools.tool_do_nothing,
    "tool_wait": agent_tools.tool_wait,
    "tool_resign_game": getattr(agent_tools, 'tool_resign_game', lambda gc, pid, **k: {"status":"failure", "message":"resign tool not implemented"}),
    "tool_confirm_asset_liquidation_actions_done": getattr(agent_tools, 'tool_confirm_asset_liquidation_actions_done', lambda gc, pid, **k: {"status":"failure", "message":"confirm liquidation tool not implemented"}),
    # Auction placeholders
    "tool_bid_on_auction": getattr(agent_tools, 'tool_bid_on_auction', lambda gc, pid, **k: {"status":"failure", "message":"auction_bid tool not implemented"}),
    "tool_pass_auction_bid": getattr(agent_tools, 'tool_pass_auction_bid', lambda gc, pid, **k: {"status":"failure", "message":"auction_pass tool not implemented"}),
    "tool_withdraw_from_auction": getattr(agent_tools, 'tool_withdraw_from_auction', lambda gc, pid, **k: {"status":"failure", "message":"auction_withdraw tool not implemented"}),
    # Trade Tools
    "tool_propose_trade": getattr(agent_tools, 'tool_propose_trade'),
    "tool_accept_trade": getattr(agent_tools, 'tool_accept_trade'),
    "tool_reject_trade": getattr(agent_tools, 'tool_reject_trade'),
    "tool_propose_counter_offer": getattr(agent_tools, 'tool_propose_counter_offer'),
    "tool_end_trade_negotiation": getattr(agent_tools, 'tool_end_trade_negotiation', lambda gc, player_id, **k: {"status":"failure", "message":"tool_end_trade_negotiation not implemented"}),
    # Handling received mortgaged property tools
    "tool_pay_mortgage_interest_fee": getattr(agent_tools, 'tool_pay_mortgage_interest_fee', lambda gc, pid, **k: {"status":"failure", "message":"pay_mortgage_fee tool not implemented"}),
    "tool_unmortgage_property_immediately": getattr(agent_tools, 'tool_unmortgage_property_immediately', lambda gc, pid, **k: {"status":"failure", "message":"unmortgage_immediately tool not implemented"}),
}

def _setup_tool_placeholders(gc_instance=None):
    """Ensures critical placeholder tools call GC methods if not fully defined in tools.py."""
    # This function might need a GC instance if placeholders directly call GC methods during setup,
    # but for now, assume they are generic enough or take GC as param during execution.

    if TOOL_REGISTRY["tool_resign_game"].__name__ == '<lambda>':
        def _resign_placeholder(gc: GameControllerV2, player_id: int) -> dict:
            player = gc.players[player_id]
            gc.log_event(f"Agent {player.name} resigns (placeholder tool).")
            gc._check_and_handle_bankruptcy(player, 0, None)
            return {"status": "success", "message": "Resignation placeholder processed."}
        TOOL_REGISTRY["tool_resign_game"] = _resign_placeholder

    if TOOL_REGISTRY["tool_confirm_asset_liquidation_actions_done"].__name__ == '<lambda>':
        def _confirm_liq_placeholder(gc: GameControllerV2, player_id: int) -> dict:
            gc.confirm_asset_liquidation_done(player_id)
            return {"status": "success", "message": "Asset liquidation confirm placeholder processed."}
        TOOL_REGISTRY["tool_confirm_asset_liquidation_actions_done"] = _confirm_liq_placeholder

    def _create_placeholder_tool_if_missing(tool_name_key, gc_for_placeholder_call: Optional[GameControllerV2] = None):
        is_lambda_placeholder = False
        try:
            if TOOL_REGISTRY.get(tool_name_key) and TOOL_REGISTRY[tool_name_key].__name__ == '<lambda>':
                is_lambda_placeholder = True
        except AttributeError: pass
        
        if is_lambda_placeholder:
            def placeholder_tool_impl(gc_inner: GameControllerV2, player_id_inner: int, **kwargs) -> dict:
                p_name = gc_inner.players[player_id_inner].name
                gc_inner.log_event(f"[Placeholder Tool] P{player_id_inner}({p_name}) uses '{tool_name_key}' with {kwargs}")
                if tool_name_key == "tool_bid_on_auction": gc_inner._handle_auction_bid(gc_inner.players[player_id_inner], kwargs.get('bid_amount', 1))
                elif tool_name_key == "tool_pass_auction_bid": gc_inner._handle_auction_pass(gc_inner.players[player_id_inner])
                elif tool_name_key == "tool_withdraw_from_auction": gc_inner._handle_auction_withdraw(gc_inner.players[player_id_inner])
                elif tool_name_key == "tool_accept_trade": gc_inner._respond_to_trade_offer_action(player_id_inner, kwargs.get('trade_id'), "accept")
                elif tool_name_key == "tool_reject_trade": gc_inner._respond_to_trade_offer_action(player_id_inner, kwargs.get('trade_id'), "reject")
                else: return {"status":"failure", "message":f"Tool '{tool_name_key}' default placeholder, no specific GC call."}
                return {"status":"success", "message": f"Placeholder for '{tool_name_key}' executed calling GC method."}
            TOOL_REGISTRY[tool_name_key] = placeholder_tool_impl

    for tn in TOOL_REGISTRY.keys(): 
        _create_placeholder_tool_if_missing(tn, gc_instance)

_setup_tool_placeholders() # Call at module level to ensure TOOL_REGISTRY is patched before use.

def execute_agent_action(gc: GameControllerV2, player_id: int, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Executes the chosen tool for the agent."""
    if tool_name in TOOL_REGISTRY:
        tool_function = TOOL_REGISTRY[tool_name]
        try:
            # Special handling for tool_propose_trade if params contain nested structure
            if tool_name == "tool_propose_trade" and params and "proposed_trade" in params:
                # Extract the nested parameters
                nested_params = params["proposed_trade"]
                return tool_function(gc, player_id, **nested_params)
            
            # Parameter name normalization for trade tools
            if tool_name in ["tool_propose_trade", "tool_propose_counter_offer"] and params:
                normalized_params = {}
                for key, value in params.items():
                    # Map various parameter name formats to the expected ones
                    if key == "target_player_id":
                        normalized_params["recipient_id"] = value
                    elif key == "offer_property_ids":
                        normalized_params["offered_property_ids"] = value
                    elif key == "request_property_ids":
                        normalized_params["requested_property_ids"] = value
                    elif key == "offer_money":
                        normalized_params["offered_money"] = value
                    elif key == "request_money":
                        normalized_params["requested_money"] = value
                    elif key == "offered_gooj_cards":
                        normalized_params["offered_get_out_of_jail_free_cards"] = value
                    elif key == "requested_gooj_cards":
                        normalized_params["requested_get_out_of_jail_free_cards"] = value
                    elif key == "proposer_id":
                        # Skip proposer_id since player_id already represents the proposer
                        continue
                    else:
                        normalized_params[key] = value
                return tool_function(gc, player_id, **normalized_params)
            
            # Ensure params are passed correctly if they exist
            if params is not None and params:
                return tool_function(gc, player_id, **params)
            else:
                return tool_function(gc, player_id) # Assumes tools handle missing optional params or have defaults
        except TypeError as te:
            gc.log_event(f"[E] TypeError tool '{tool_name}' P{player_id} {params}: {te}")
            return {"status": "error", "message": f"TypeError: {te}"}
        except Exception as e:
            gc.log_event(f"[E] Exception tool '{tool_name}' P{player_id}: {e}")
            return {"status": "error", "message": str(e)}
    else:
        gc.log_event(f"[E] Unknown tool '{tool_name}' P{player_id}.")
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

def print_game_summary(gc: GameControllerV2, return_string: bool = False) -> Optional[str]:
    summary_lines = []
    summary_lines.append("\n--- Game Summary ---")
    for player in gc.players:
        summary_lines.append(f"Player {player.player_id} ({player.name}): Money ${player.money}, Bankrupt: {player.is_bankrupt}")
        if not player.is_bankrupt:
            summary_lines.append(f"  Properties ({len(player.properties_owned_ids)}):")
            for prop_id in sorted(list(player.properties_owned_ids)):
                square = gc.board.get_square(prop_id)
                houses = f" ({square.num_houses}H)" if isinstance(square, PropertySquare) and square.num_houses > 0 and square.num_houses < 5 else " (HOTEL)" if isinstance(square, PropertySquare) and square.num_houses == 5 else ""
                mortgaged = " [M]" if isinstance(square, PurchasableSquare) and square.is_mortgaged else ""
                summary_lines.append(f"    - {square.name}{houses}{mortgaged}")
            gooj_cards = []
            if player.has_chance_gooj_card: gooj_cards.append("Chance")
            if player.has_community_gooj_card: gooj_cards.append("Community Chest")
            if gooj_cards: summary_lines.append(f"  GOOJ Cards: {', '.join(gooj_cards)}")
    summary_lines.append("--------------------")
    
    output_str = "\n".join(summary_lines)
    if return_string:
        return output_str
    else:
        print(output_str)
        return None

def get_user_input_for_action(gc: GameControllerV2, player: Any, game_state: Dict[str, Any], available_actions: List[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    print(f"\n{Fore.YELLOW}Player {player.name} (P{player.player_id}), it's your turn to act.{Style.RESET_ALL}")
    print(f"Current Money: ${player.money}, Position: {player.position} ({game_state.get('my_position_name', 'N/A')})")
    if gc.pending_decision_type:
        print(f"Pending Decision: {Fore.MAGENTA}{gc.pending_decision_type}{Style.RESET_ALL}")
        if gc.pending_decision_context:
            print(f"  Decision Context: {json.dumps(gc.pending_decision_context, indent=1)}")
    
    print("Available actions:")
    for i, action_name in enumerate(available_actions):
        print(f"  {i+1}. {action_name}")
    
    chosen_tool_name = None
    params = {}

    while True:
        try:
            choice = input(f"Choose action by number (1-{len(available_actions)}): ")
            if not choice.isdigit() or not (1 <= int(choice) <= len(available_actions)):
                print("Invalid choice. Please enter a number from the list.")
                continue
            chosen_tool_name = available_actions[int(choice)-1]
            break
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt: print("\nExiting game."); return None, {}
        except EOFError: print("\nExiting game (EOF)."); return None, {}

    # Dynamically ask for parameters based on common patterns in our tools
    # This is a simplified approach. A more robust system might have a schema for each tool's params.
    if chosen_tool_name == "tool_buy_property" or chosen_tool_name == "tool_pass_on_buying_property":
        if gc.pending_decision_type == "buy_or_auction_property" and gc.pending_decision_context.get("property_id") is not None:
            params["property_id"] = gc.pending_decision_context["property_id"]
            print(f"  (Auto-filled property_id: {params['property_id']}) for {chosen_tool_name}")
        else: # Should not happen if get_available_actions is correct for this phase
            prop_id_str = input("  Enter property_id to act on: ")
            if prop_id_str.isdigit(): params["property_id"] = int(prop_id_str)
            else: print("Invalid property_id, action might fail.")
    
    elif chosen_tool_name in ["tool_build_house", "tool_sell_house", "tool_mortgage_property", "tool_unmortgage_property"]:
        prop_id_str = input(f"  Enter property_id for {chosen_tool_name}: ")
        if prop_id_str.isdigit(): params["property_id"] = int(prop_id_str)
        else: print("Invalid property_id, action might fail.")

    elif chosen_tool_name == "tool_bid_on_auction":
        bid_amount_str = input("  Enter your bid amount: ")
        if bid_amount_str.isdigit(): params["bid_amount"] = int(bid_amount_str)
        else: print("Invalid bid amount, action might fail.")

    elif chosen_tool_name == "tool_propose_trade":
        try:
            params["recipient_id"] = int(input("  Enter recipient player ID for trade: "))
            params["offered_property_ids"] = [int(x) for x in input("  Enter YOUR property IDs to offer (comma-separated, e.g., 1,5 or leave blank): ").split(',') if x.strip().isdigit()]
            params["offered_money"] = int(input("  Enter YOUR money to offer (0 if none): ") or "0")
            params["offered_get_out_of_jail_free_cards"] = int(input("  Enter YOUR Get Out of Jail cards to offer (0-2): ") or "0")
            params["requested_property_ids"] = [int(x) for x in input(f"  Enter RECIPIENT's property IDs to request (comma-separated): ").split(',') if x.strip().isdigit()]
            params["requested_money"] = int(input(f"  Enter RECIPIENT's money to request (0 if none): ") or "0")
            params["requested_get_out_of_jail_free_cards"] = int(input(f"  Enter RECIPIENT's Get Out of Jail cards to request (0-2): ") or "0")
        except ValueError: print("Invalid input for trade parameters.")
    
    elif chosen_tool_name in ["tool_accept_trade", "tool_reject_trade", "tool_propose_counter_offer"]:
        params["trade_id"] = gc.pending_decision_context.get("trade_id") # Auto-filled
        print(f"  (Auto-filled trade_id: {params['trade_id']}) for {chosen_tool_name}")
        if chosen_tool_name == "tool_propose_counter_offer":
            print("  Enter details for your counter-offer:")
            try:
                params["offered_property_ids"] = [int(x) for x in input("    YOUR property IDs to offer now (comma-separated): ").split(',') if x.strip().isdigit()]
                params["offered_money"] = int(input("    YOUR money to offer now (0 if none): ") or "0")
                params["offered_get_out_of_jail_free_cards"] = int(input("    YOUR GOOJ cards to offer now (0-2): ") or "0")
                params["requested_property_ids"] = [int(x) for x in input(f"    ORIGINAL PROPOSER's property IDs to request now: ").split(',') if x.strip().isdigit()]
                params["requested_money"] = int(input(f"    ORIGINAL PROPOSER's money to request now (0 if none): ") or "0")
                params["requested_get_out_of_jail_free_cards"] = int(input(f"    ORIGINAL PROPOSER's GOOJ cards to request now (0-2): ") or "0")
            except ValueError: print("Invalid input for counter-offer parameters.")

    elif chosen_tool_name in ["tool_pay_mortgage_interest_fee", "tool_unmortgage_property_immediately"]:
        params["property_id"] = gc.pending_decision_context.get("property_id_to_handle") # Auto-filled
        print(f"  (Auto-filled property_id: {params['property_id']}) for {chosen_tool_name}")

    return chosen_tool_name, params

# New function to log agent actions to DB
def _log_agent_action_to_db(gc: GameControllerV2, player_id: int, agent: OpenAIAgent, action_result: Dict[str, Any], current_game_turn_db_id: Optional[int]):
    if gc.game_db_id is None: # Cannot log if no game_db_id
        return
    
    player_db_id = gc.players[player_id].db_id
    if player_db_id is None:
        gc.log_event(f"[DB Error] Player P{player_id} has no db_id. Cannot log agent action.")
        return

    decision_details = agent.get_last_decision_details_for_db()

    action_data_to_insert = {
        "game_id": gc.game_db_id,
        "game_turn_id": current_game_turn_db_id, # This needs to be the ID of the *current* game_turns entry
        "player_db_id": player_db_id,
        "player_game_index": player_id,
        "gc_turn_number": decision_details.get("gc_turn_number"),
        "action_sequence_in_gc_turn": decision_details.get("action_sequence_in_gc_turn"),
        "pending_decision_type_before": decision_details.get("pending_decision_type_before"),
        "pending_decision_context_json_before": decision_details.get("pending_decision_context_json_before"),
        "available_actions_json_before": decision_details.get("available_actions_json_before"),
        "agent_thoughts_text": decision_details.get("agent_thoughts_text"),
        "llm_raw_response_text": decision_details.get("llm_raw_response_text"),
        "parsed_action_json_str": decision_details.get("parsed_action_json_str"),
        "chosen_tool_name": decision_details.get("chosen_tool_name"),
        "tool_parameters_json": decision_details.get("tool_parameters_json"),
        "action_result_status": action_result.get("status"),
        "action_result_message": action_result.get("message"),
        "timestamp": datetime.datetime.now(datetime.timezone.utc) 
    }
    try:
        with Session(engine) as session: # Or use engine.connect() for Core
            stmt = insert(agent_actions_table).values(action_data_to_insert)
            session.execute(stmt)
            session.commit()
            # gc.log_event(f"[DB] Logged agent action for P{player_id}, Tool: {action_data_to_insert['chosen_tool_name']}")
    except Exception as e:
        gc.log_event(f"[DB Error] Failed to log agent action for P{player_id}: {e}")

def run_game_cli_simulation(interactive_mode=False, game_uid_for_server: Optional[str] = None, ws_manager_for_server: Optional[Any] = None):
    # This function will now be callable from server.py, or run directly.
    # If called from server, game_id_for_server and ws_manager_for_server will be provided.
    
    # Colorama setup should be at the very top of the script or handled by calling environment
    # For simplicity if this file is run directly:
    if __name__ == "__main__" or interactive_mode: # Only init colorama if running as main or explicitly interactive
        try: from colorama import init, Fore as ColoramaFore, Style as ColoramaStyle; init(); Fore=ColoramaFore; Style=ColoramaStyle
        except ImportError: print("Colorama not found, colors will be disabled.")

    game_id_to_use = game_uid_for_server if game_uid_for_server else "cli_game"
    
    print(f"Starting Monopoly CLI Simulation (Game ID: {game_id_to_use})...")
    gc = GameControllerV2(num_players=NUM_PLAYERS, player_names=PLAYER_NAMES, game_uid=game_id_to_use, ws_manager=ws_manager_for_server)
    agents = [OpenAIAgent(player_id=i, name=gc.players[i].name) for i in range(NUM_PLAYERS)]
    gc.log_event(f"Initialized {len(agents)} agents for game {game_id_to_use}.")
    gc.start_game()
    loop_turn_count = 0 
    effective_action_delay = ACTION_DELAY_SECONDS if not interactive_mode else 0.5
    current_game_turn_db_id: Optional[int] = None 

    while not gc.game_over and loop_turn_count < MAX_TURNS:
        loop_turn_count += 1; gc.turn_count = loop_turn_count
        active_player_id: Optional[int]; current_acting_player: Optional[Player]; log_turn_header_detail = ""
        roll_action_taken_this_main_turn_segment = False 
        current_main_turn_player_id = gc.current_player_index
        
        action_sequence_this_gc_turn = 0 # Reset for each new GameController turn_count
        if gc.turn_count != getattr(run_game_cli_simulation, '_last_gc_turn_for_action_seq', -1):
            run_game_cli_simulation._last_gc_turn_for_action_seq = gc.turn_count
        else:
            # This means it's still the same GC turn, but could be a different player acting (e.g. auction)
            # or same player making multiple decisions. We need a robust way to increment sequence.
            # For now, let's increment it inside the while player_turn_segment_active loop.
            pass 

        # Save game turn snapshot at the beginning of processing for this gc.turn_count if it's a new turn for the main player
        # or if a significant event like auction start makes sense for a snapshot.
        # This logic needs refinement: when is the best time to snapshot?
        if gc.current_player_index == getattr(run_game_cli_simulation, '_last_player_for_snapshot', -2) and \
           gc.turn_count == getattr(run_game_cli_simulation, '_last_turn_for_snapshot', -2):
            pass # Avoid redundant snapshot for the same player in the same turn if loop re-enters for sub-decisions
        else:
            current_game_turn_db_id = gc._save_game_turn_snapshot(gc.current_player_index) # Save for main turn player
            setattr(run_game_cli_simulation, '_last_player_for_snapshot', gc.current_player_index)
            setattr(run_game_cli_simulation, '_last_turn_for_snapshot', gc.turn_count)

        # Determine who is acting
        if gc.auction_in_progress and gc.pending_decision_type == "auction_bid":
            active_player_id = gc.pending_decision_context.get("player_to_bid_id")
            if active_player_id is None: gc.log_event(f"[E] MainL: Auction active but no bidder. Concluding."); gc._conclude_auction(no_winner=True); active_player_id = current_main_turn_player_id 
            current_acting_player = gc.players[active_player_id]
            auction_prop_name = gc.board.get_square(gc.auction_property_id).name if gc.auction_property_id is not None else "N/A"
            log_turn_header_detail = f"(Auction for {auction_prop_name} | Bidder: {current_acting_player.name} | Bid: ${gc.auction_current_bid})"
        elif gc.pending_decision_type in ["respond_to_trade_offer", "handle_received_mortgaged_property"]:
            active_player_id = gc.pending_decision_context.get("player_id")
            if active_player_id is None: gc.log_event(f"[E] MainL: Pending '{gc.pending_decision_type}' but no P_ID. Clearing."); gc._clear_pending_decision(); active_player_id = current_main_turn_player_id
            current_acting_player = gc.players[active_player_id]
            log_turn_header_detail = f"(Player {current_acting_player.name} deciding: {gc.pending_decision_type})"
        else: # Default to main turn player
            active_player_id = current_main_turn_player_id
            current_acting_player = gc.players[active_player_id]
            log_turn_header_detail = f"(Player {current_acting_player.name} (${current_acting_player.money}) Pos: {current_acting_player.position} - {gc.board.get_square(current_acting_player.position).name})"
        
        agent_to_act = agents[active_player_id]
        print(f"\n{ Fore.CYAN }--- Turn {loop_turn_count} {log_turn_header_detail} | GC Pend: '{gc.pending_decision_type}', DiceDone: {gc.dice_roll_outcome_processed} ---{ Style.RESET_ALL }")
        
        if current_acting_player.is_bankrupt: # ... (bankrupt handling) ...
             gc.log_event(f"P{active_player_id} ({current_acting_player.name}) is bankrupt.")
             if gc.auction_in_progress and current_acting_player in gc.auction_active_bidders: gc._handle_auction_pass(current_acting_player) 
             elif active_player_id == gc.current_player_index : gc.next_turn() 
             if gc.game_over: break; continue 
        
        player_turn_segment_active = True; action_this_segment_count = 0; MAX_ACTIONS_PER_SEGMENT = 15
        if active_player_id == current_main_turn_player_id and gc.pending_decision_type is None: roll_action_taken_this_main_turn_segment = False

        while player_turn_segment_active and not current_acting_player.is_bankrupt and not gc.game_over and action_this_segment_count < MAX_ACTIONS_PER_SEGMENT:
            action_this_segment_count += 1
            action_sequence_this_gc_turn += 1 # Increment sequence for each agent decision point
            
            available_actions = gc.get_available_actions(active_player_id)
            if not available_actions: 
                gc.log_event(f"[W] No available actions for P{active_player_id}({current_acting_player.name}). Pend:'{gc.pending_decision_type}',DD:{gc.dice_roll_outcome_processed}. EndSeg.")
                player_turn_segment_active = False; break
            
            game_state_for_agent = gc.get_game_state_for_agent(active_player_id)
            print(f"{Fore.YELLOW}Agent {agent_to_act.name} (P{active_player_id}) thinking...{Style.RESET_ALL}");
            if gc.pending_decision_context: print(f"  Ctx: {json.dumps(gc.pending_decision_context, indent=1)}")
            print(f"  Actions: {available_actions[:7]}{ '...' if len(available_actions) > 7 else ''}")
            
            chosen_tool_name, params = agent_to_act.decide_action(game_state_for_agent, available_actions, gc.turn_count, action_sequence_this_gc_turn)
            if hasattr(agent_to_act, 'get_player_thought_process'): thoughts = agent_to_act.get_player_thought_process(); print(f"{Fore.MAGENTA}  Thinks: {thoughts.split('LLM Valid Action Parsed:')[0].strip() if 'LLM Valid Action Parsed:' in thoughts else thoughts}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}  Player '{current_acting_player.name}' chose: '{chosen_tool_name}' with params: {params}{Style.RESET_ALL}")
            action_result = execute_agent_action(gc, active_player_id, chosen_tool_name, params)
            _log_agent_action_to_db(gc, active_player_id, agent_to_act, action_result, current_game_turn_db_id)
            print(f"  Tool Result: Status '{action_result.get('status', 'N/A' )}' - Msg: {action_result.get('message', 'No msg.')}")

            if action_result.get("status") == "error" or current_acting_player.is_bankrupt : player_turn_segment_active = False; break 

            # --- Player action segment termination logic --- 
            if chosen_tool_name == "tool_roll_dice":
                if action_result.get("status") == "success":
                    if active_player_id == current_main_turn_player_id: roll_action_taken_this_main_turn_segment = True 
                    if not action_result.get("went_to_jail", False):
                        dice_val = action_result.get("dice_roll", gc.dice) 
                        if dice_val and sum(dice_val) > 0: gc._move_player(current_acting_player, sum(dice_val))
                        else: gc.log_event(f"[E] Invalid dice from roll_dice: {dice_val}"); gc._resolve_current_action_segment()
                # After roll_dice and potential _move_player, GameController state is updated.
                # If a new pending_decision is set for the current_acting_player (e.g., buy_or_auction),
                # the loop should continue. If GC resolved the landing and no new decision for this player,
                # then pending_decision_type will be None and dice_roll_outcome_processed will be True.
                if gc.pending_decision_type is None and gc.dice_roll_outcome_processed:
                    player_turn_segment_active = False # Roll segment done, no immediate follow-up decision for THIS player.
                # else: A new pending decision (e.g. buy/auction) was set by GC for current_acting_player, so loop continues.
            
            elif chosen_tool_name == "tool_buy_property":
                if action_result.get("status") == "success": # Buy was successful and resolved
                    player_turn_segment_active = False
                # If buy failed (e.g. funds), GC keeps pending_decision="buy_or_auction_property", so loop continues.

            elif chosen_tool_name == "tool_pass_on_buying_property":
                # This sets pending_decision_type to "auction_bid" (for next auction bidder).
                # Current player's buy/pass decision segment is done.
                player_turn_segment_active = False 

            elif chosen_tool_name == "tool_end_turn" or chosen_tool_name == "tool_resign_game":
                player_turn_segment_active = False
            elif gc.pending_decision_type == "asset_liquidation_for_debt":
                if chosen_tool_name == "tool_confirm_asset_liquidation_actions_done" or current_acting_player.money >=0:
                    player_turn_segment_active = False 
            elif gc.pending_decision_type == "handle_received_mortgaged_property":
                if gc.pending_decision_type != "handle_received_mortgaged_property": 
                    player_turn_segment_active = False
            elif gc.auction_in_progress and gc.pending_decision_type == "auction_bid": 
                player_turn_segment_active = False 
            elif gc.pending_decision_type is None and gc.dice_roll_outcome_processed:
                # General actions phase. Agent can make multiple asset changes or propose trades.
                # Loop ends if they choose tool_end_turn (caught above) or no meaningful actions left.
                current_av_actions = gc.get_available_actions(active_player_id)
                if not current_av_actions or all(act in ["tool_end_turn", "tool_wait"] for act in current_av_actions):
                     player_turn_segment_active = False
            
            if action_this_segment_count >= MAX_ACTIONS_PER_SEGMENT:
                gc.log_event(f"[W] Max actions for P{active_player_id} ({current_acting_player.name}). End seg."); player_turn_segment_active = False
            
            if player_turn_segment_active and not gc.game_over and effective_action_delay > 0: time.sleep(effective_action_delay)
        
        # --- End of an active player's decision segment(s) --- 
        if gc.game_over: break
        main_turn_player = gc.players[gc.current_player_index]

        if not gc.auction_in_progress: 
            if main_turn_player.is_bankrupt:
                gc.log_event(f"Main turn P{main_turn_player.player_id} ({main_turn_player.name}) is bankrupt. Advancing."); gc.next_turn()
            elif active_player_id == main_turn_player.player_id and \
                 roll_action_taken_this_main_turn_segment and \
                 gc.dice[0] == gc.dice[1] and gc.dice[0] != 0 and \
                 not main_turn_player.in_jail and \
                 gc.doubles_streak < 3 and gc.doubles_streak > 0: 
                gc.log_event(f"{main_turn_player.name} (DS: {gc.doubles_streak}) gets another main turn segment (bonus)." )
                gc._clear_pending_decision(); gc.dice_roll_outcome_processed = True 
                roll_action_taken_this_main_turn_segment = False # Reset for the bonus segment
                if main_turn_player.pending_mortgaged_properties_to_handle: 
                    gc._handle_received_mortgaged_property_initiation(main_turn_player)
                # Loop continues with the same main_turn_player.
            else:
                if active_player_id == main_turn_player.player_id: 
                    gc.log_event(f"End of main turn for {main_turn_player.name} (DS: {gc.doubles_streak}). Advancing."); gc.next_turn()
                # Else: an out-of-turn action (auction bid, trade response) just finished. Main turn continues for main_turn_player or next auction bidder.
        elif gc.auction_in_progress : 
            gc.log_event(f"Auction for {gc.board.get_square(gc.auction_property_id).name if gc.auction_property_id is not None else 'prop'} continues...")
        
        if gc.game_over: break
        if loop_turn_count >= MAX_TURNS: gc.log_event(f"Max turns ({MAX_TURNS}) reached."); gc.game_over = True; break
            
    print_game_summary(gc)
    gc.log_event("Monopoly CLI Simulation Finished.")

if __name__ == "__main__":
    # Define Fore and Style globally for access within run_game_cli_simulation
    # This ensures they exist even if colorama import fails later in the function call.
    class Fore: CYAN=YELLOW=GREEN=RED=MAGENTA=WHITE=BLACK=BLUE=""; LIGHTBLACK_EX=LIGHTBLUE_EX=LIGHTCYAN_EX=LIGHTGREEN_EX=LIGHTMAGENTA_EX=LIGHTRED_EX=LIGHTWHITE_EX=LIGHTYELLOW_EX=""
    class Style: RESET_ALL=BRIGHT=DIM=NORMAL="";
    
    # Try to initialize colorama and overwrite placeholders if successful
    try: 
        from colorama import init, Fore as ColoramaFore, Style as ColoramaStyle
        init()
        Fore = ColoramaFore 
        Style = ColoramaStyle
        print(f"{Fore.GREEN}Colorama initialized successfully for CLI output.{Style.RESET_ALL}")
    except ImportError: 
        print("Colorama not found, CLI output will not be colored.")
        pass # Global placeholders will be used
    
    run_game_cli_simulation(interactive_mode=False) 