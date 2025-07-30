import os
from typing import Tuple, Dict, List, Any, Optional
from abc import ABC, abstractmethod
import json # Ensure json is imported
import re   # For potential cleanup of JSON string if needed
import time # Added for time measurement

from tpay.tools import taudit_verifier

from dotenv import load_dotenv

# Conditional import for openai, handle if not installed
try:
    import openai
except ImportError:
    openai = None
    print("OpenAI library not found. Please install it via pip: pip install openai")

# Attempt to import MAX_TRADE_REJECTIONS if defined in main.py or game_logic.game_controller
# This is for providing context to the AI in the prompt.
MAX_TRADE_REJECTIONS_FOR_PROMPT = 3 # Default value
try:
    from main import MAX_TRADE_REJECTIONS as MTR_MAIN
    MAX_TRADE_REJECTIONS_FOR_PROMPT = MTR_MAIN
except ImportError:
    try:
        from game_logic.game_controller_v2 import MAX_TRADE_REJECTIONS as MTR_GC
        MAX_TRADE_REJECTIONS_FOR_PROMPT = MTR_GC
    except ImportError:
        print("[Agent Prompt] MAX_TRADE_REJECTIONS constant not found, using default for prompt.")

class BaseAgent(ABC):
    def __init__(self, player_id: int, name: str):
        self.player_id = player_id
        self.name = name

    @abstractmethod
    def decide_action(self, game_state: Dict[str, Any], available_actions: List[str], 
                      current_gc_turn: int, action_sequence_num: int) -> Tuple[str, Dict[str, Any]]:
        """
        Decides which action/tool to use based on the game state and available actions.

        Args:
            game_state: A dictionary representing the current state of the game.
            available_actions: A list of strings representing the names of tools the agent can currently use.
            current_gc_turn: The current game turn number.
            action_sequence_num: The sequence number of the action within the current game turn.

        Returns:
            A tuple containing the chosen tool name (str) and a dictionary of its parameters (Dict[str, Any]).
        """
        pass

    def get_player_thought_process(self) -> str:
        """Returns the agent's thought process for the last decision (optional)."""
        return "No detailed thought process recorded."

    def get_last_decision_details_for_db(self) -> Dict[str, Any]:
        """Returns a dictionary of details from the last decision for DB logging."""
        return {}

class OpenAIAgent(BaseAgent):
    @taudit_verifier
    def __init__(self, agent_uid: str, player_id: int, name: str, personality: str = "", model_name: str = "gpt-4o", api_key: str = None):
        super().__init__(player_id, name)

        load_dotenv()

        if openai is None:
            raise ImportError("OpenAI library is required for OpenAIAgent but not installed.")
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided or found in OPENAI_API_KEY environment variable.")
        
        self.client = openai.OpenAI(api_key=self.api_key)

        self.agent_uid = agent_uid
        self.personality = personality

        self.model_name = model_name
        self.last_prompt: str = ""
        self.last_response_text: str = ""
        self.last_raw_llm_response_content: str = ""
        self.last_thought_process: str = ""
        self.last_parsed_action_json_str: str = "" # Store the string that was successfully parsed as JSON
        self.last_chosen_tool_name: Optional[str] = None
        self.last_tool_parameters: Optional[Dict[str, Any]] = None
        self.last_available_actions_json_before: str = ""
        self.last_pending_decision_type_before: Optional[str] = None
        self.last_pending_decision_context_json_before: str = ""
        self.last_gc_turn_number: int = 0
        self.last_action_sequence_in_gc_turn: int = 0
        self.last_agent_thoughts: str = ""
        self.last_llm_raw_response: str = ""
        self.last_tool_parameters_json: str = "{}"

    @taudit_verifier
    def _build_prompt(self, game_state: Dict[str, Any], available_actions: List[str]) -> Tuple[str, List[Dict[str, str]]]:
        # Prompt for the AI agent in a Monopoly game
        
        # Introduction and Goal
        prompt = f"You are an AI player named {self.name} (Player ID: {self.player_id}) in a game of Monopoly.\n"
        prompt += "Your primary goal is to maximize your wealth and bankrupt other players. Make strategic decisions to achieve this.\n"
        
        # Add personality if available
        if self.personality:
            prompt += f"\n--- Your Personality & Playing Style ---\n"
            prompt += f"{self.personality}\n"
            prompt += "Always stay true to your personality while making strategic decisions.\n"

        # Current Player's Status
        prompt += "\n--- My Current Status ---\n"
        my_pos = game_state.get('my_position')
        pos_name = game_state.get('my_position_name', "N/A")
        prompt += f"Money: ${game_state.get('my_money')}\n"
        prompt += f"Position: Square {my_pos} ({pos_name})\n"
        prompt += f"In Jail: {game_state.get('my_in_jail', False)}\n"
        if game_state.get('my_in_jail', False):
            prompt += f"Jail turns attempted: {game_state.get('my_jail_turns_remaining', 0)}\n"

        prompt += f"Properties Owned ({len(game_state.get('my_properties_owned_ids', []))}):\n"
        if not game_state.get('my_properties_owned_ids', []):
            prompt += "  (None)\n"
        else:
            # 🎯 ENHANCED: Group properties by mortgage status for clarity
            mortgaged_properties = []
            unmortgaged_properties = []
            
            for prop_id in game_state.get('my_properties_owned_ids', []):
                prop = next((sq for sq in game_state.get('board_squares',[]) if sq['id'] == prop_id), None)
                if prop:
                    houses_str = ""
                    if prop.get('type') == 'PROPERTY' and prop.get('num_houses', 0) > 0:
                        houses_str = f", {prop['num_houses']} houses" if prop['num_houses'] < 5 else ", HOTEL"
                    
                    property_line = f"  - {prop['name']} (ID: {prop_id}){houses_str}"
                    
                    if prop.get('is_mortgaged'):
                        mortgaged_properties.append(property_line + " [MORTGAGED]")
                    else:
                        unmortgaged_properties.append(property_line + " [UNMORTGAGED]")
            
            # Display unmortgaged properties first, then mortgaged
            if unmortgaged_properties:
                prompt += "  💰 UNMORTGAGED (can be mortgaged for cash):\n"
                for line in unmortgaged_properties:
                    prompt += line + "\n"
            
            if mortgaged_properties:
                prompt += "  🏦 MORTGAGED (already mortgaged, cannot mortgage again):\n"
                for line in mortgaged_properties:
                    prompt += line + "\n"
        
        gooj_cards = game_state.get('my_get_out_of_jail_cards', {})
        prompt += f"Get Out of Jail Cards: Chance: {gooj_cards.get('chance')}, Community Chest: {gooj_cards.get('community_chest')}\n"

        # Current Square Details
        if my_pos is not None and game_state.get('board_squares') and 0 <= my_pos < len(game_state['board_squares']):
            current_square_details = game_state['board_squares'][my_pos]
            prompt += f"\n--- Details of Current Square ({current_square_details['name']}) ---\n"
            prompt += f"Type: {current_square_details['type']}\n"
            if current_square_details.get('owner_id') is None and 'price' in current_square_details:
                prompt += f"This property is unowned. Price: ${current_square_details.get('price')}\n"
            elif current_square_details.get('owner_id') == self.player_id:
                prompt += "You own this property.\n"
            elif current_square_details.get('owner_id') is not None:
                owner_id = current_square_details.get('owner_id')
                owner_name = "Another Player"
                for p_info in game_state.get('other_players', []):
                    if p_info['player_id'] == owner_id:
                        owner_name = p_info['name']
                        break
                prompt += f"This property is owned by {owner_name}. Mortgaged: {current_square_details.get('is_mortgaged')}\n"
        
        # Other Players' Status
        prompt += "\n--- Opponent Status (Detailed) ---\n"
        if not game_state.get('other_players', []):
            prompt += "  (No other active players)\n"
        else:
            for p_info in game_state.get('other_players', []):
                if p_info.get('is_bankrupt', False):
                    prompt += f"{p_info['name']} (ID: {p_info['player_id']}): BANKRUPT\n"
                else:
                    prompt += f"{p_info['name']} (ID: {p_info['player_id']}): Pos {p_info.get('position')}, Props {p_info.get('num_properties')}, Jail: {p_info.get('in_jail')}\n"
                    
                    # 🎯 CRITICAL: Show detailed property ownership for accurate trading
                    properties_owned = p_info.get('properties_owned', [])
                    if properties_owned:
                        prompt += f"\n  🏠 Properties owned by {p_info['name']} (use these IDs for requesting in trades):\n"
                        
                        # Group by mortgage status for clarity
                        unmortgaged_props = []
                        mortgaged_props = []
                        
                        for prop in properties_owned:
                            houses_str = ""
                            if prop.get('num_houses', 0) > 0:
                                houses_str = f", {prop['num_houses']} houses" if prop['num_houses'] < 5 else ", HOTEL"
                            color_group_str = f" [{prop.get('color_group', 'N/A')}]" if prop.get('color_group') else ""
                            
                            prop_line = f"    - {prop['name']} (ID: {prop['id']}){color_group_str}{houses_str}"
                            
                            if prop.get('is_mortgaged'):
                                mortgaged_props.append(prop_line + " [MORTGAGED]")
                            else:
                                unmortgaged_props.append(prop_line + " [AVAILABLE]")
                        
                        # Display available properties first (more likely to be tradeable)
                        if unmortgaged_props:
                            prompt += f"    💰 AVAILABLE for trade:\n"
                            for line in unmortgaged_props:
                                prompt += line + "\n"
                        
                        if mortgaged_props:
                            prompt += f"    🏦 MORTGAGED (may be less desirable):\n"
                            for line in mortgaged_props:
                                prompt += line + "\n"
                    else:
                        prompt += f"  ❌ {p_info['name']} owns no properties\n"
                prompt += "\n"  # Add spacing between players
        
        # Recent Game Events
        prompt += "\n--- Recent Game Events (Last 5) ---\n"
        if not game_state.get('game_log_tail', []):
            prompt += "  (No recent events)\n"
        else:
            # 🎯 ENHANCED: Highlight error/failure events for better AI awareness
            recent_events = game_state.get('game_log_tail', [])[-5:]
            
            # Separate successful events from error events
            error_events = []
            success_events = []
            
            for log_entry in recent_events:
                # Check for error/failure keywords
                error_keywords = ['failed', 'failure', 'error', 'cannot', 'invalid', 'already mortgaged', 'not owned', 'insufficient']
                if any(keyword.lower() in log_entry.lower() for keyword in error_keywords):
                    error_events.append(log_entry)
                else:
                    success_events.append(log_entry)
            
            # Display error events first with warning emoji
            if error_events:
                prompt += "  ⚠️ RECENT ERRORS/FAILURES (learn from these!):\n"
                for event in error_events:
                    prompt += f"    ❌ {event}\n"
            
            if success_events:
                if error_events:  # Add separator if there were errors
                    prompt += "\n  ✅ SUCCESSFUL EVENTS:\n"
                for event in success_events:
                    prompt += f"    • {event}\n"

        # Current Trade Information (if applicable)
        current_trade_info = game_state.get('current_trade_info')
        if current_trade_info:
            prompt += "\n--- Current Trade Details ---\n"
            prompt += f"Trade ID: {current_trade_info['trade_id']}\n"
            prompt += f"Proposer: P{current_trade_info['proposer_id']}\n"
            prompt += f"Recipient: P{current_trade_info['recipient_id']}\n"
            prompt += f"Status: {current_trade_info['status']}\n"
            if current_trade_info.get('message'):
                prompt += f"Message: \"{current_trade_info['message']}\"\n"
            
            prompt += "Items offered by proposer:\n"
            for item in current_trade_info['items_offered_by_proposer']:
                if item['item_type'] == 'money':
                    prompt += f"  - ${item['quantity']}\n"
                elif item['item_type'] == 'property':
                    prop_name = "Unknown Property"
                    for sq in game_state.get('board_squares', []):
                        if sq.get('id') == item['item_id']:
                            prop_name = sq.get('name', 'Unknown Property')
                            break
                    prompt += f"  - Property: {prop_name} (ID: {item['item_id']})\n"
                elif item['item_type'] == 'get_out_of_jail_card':
                    prompt += f"  - Get Out of Jail Free Card x{item['quantity']}\n"
            
            prompt += "Items requested from recipient:\n"
            for item in current_trade_info['items_requested_from_recipient']:
                if item['item_type'] == 'money':
                    prompt += f"  - ${item['quantity']}\n"
                elif item['item_type'] == 'property':
                    prop_name = "Unknown Property"
                    for sq in game_state.get('board_squares', []):
                        if sq.get('id') == item['item_id']:
                            prop_name = sq.get('name', 'Unknown Property')
                            break
                    prompt += f"  - Property: {prop_name} (ID: {item['item_id']})\n"
                elif item['item_type'] == 'get_out_of_jail_card':
                    prompt += f"  - Get Out of Jail Free Card x{item['quantity']}\n"

        # Recent Trade History
        recent_trades = game_state.get('recent_trade_offers', [])
        if recent_trades:
            prompt += "\n--- Recent Trade History ---\n"
            for trade in recent_trades:
                prompt += f"Trade {trade['trade_id']}: P{trade['proposer_id']} → P{trade['recipient_id']} ({trade['status']})\n"
                if trade.get('message'):
                    prompt += f"  Message: \"{trade['message']}\"\n"
                
                # Show money amounts for context
                money_offered = 0
                money_requested = 0
                for item in trade['items_offered_by_proposer']:
                    if item['item_type'] == 'money':
                        money_offered = item['quantity']
                for item in trade['items_requested_from_recipient']:
                    if item['item_type'] == 'money':
                        money_requested = item['quantity']
                
                if money_offered > 0 or money_requested > 0:
                    prompt += f"  Money: Offered ${money_offered}, Requested ${money_requested}\n"

        # Call to Action
        prompt += "\n--- Your Action Required ---\n"
        if game_state.get('current_turn_player_id') != self.player_id and game_state.get('pending_decision_type') not in ["respond_to_trade_offer", "auction_bid", "propose_new_trade_after_rejection"] :
             prompt += "Warning: It appears it is NOT my main turn. I should usually 'wait' unless I have a specific decision like responding to a trade or bidding in an auction.\n"

        # Building houses guidance (concise)
        if "tool_build_house" in available_actions:
            prompt += "\n🏠 IMPORTANT STRATEGY NOTE: Building houses is one of the most profitable actions in Monopoly!\n"
            prompt += "- Houses significantly increase rent income from properties\n"
            prompt += "- Building houses reduces the housing supply for other players\n"
            prompt += "- You should prioritize building houses when you can afford them\n"
            
            # 🎯 ADD CRITICAL BUILDING RULES
            prompt += "\n🚨 CRITICAL BUILDING RULES - READ CAREFULLY:\n"
            prompt += "1. ⭐ COLOR GROUP MONOPOLY REQUIRED: You can ONLY build houses if you own ALL properties in a color group\n"
            prompt += "   - Example: For BROWN group, you need BOTH Mediterranean AND Baltic Avenue\n"
            prompt += "   - Example: For LIGHT_BLUE group, you need ALL THREE: Oriental, Vermont, Connecticut\n"
            prompt += "   - If you only own 2 out of 3 properties in a group, you CANNOT build houses!\n"
            prompt += "2. 🏠 EVEN BUILDING RULE: Houses must be built evenly across the color group\n"
            prompt += "   - You cannot build a 2nd house on one property until ALL properties in the group have 1 house\n"
            prompt += "   - You cannot build a 3rd house until all have 2 houses, etc.\n"
            prompt += "3. 💰 MONEY REQUIREMENT: You need enough money to pay the house price\n"
            prompt += "4. 🚫 NO MORTGAGED PROPERTIES: All properties in the color group must be unmortgaged\n"
            
            prompt += "💡 BUILDING STRATEGY PRIORITY:\n"
            prompt += "- If tool_build_house is available, it means you CAN build (all requirements met)\n"
            prompt += "- Building houses should be your #1 priority when available\n"
            prompt += "- If you can't build houses, focus on completing color groups through trading\n\n"
        
        # Add clearer property information section in the prompt
        # 🎯 CRITICAL: Show detailed property ownership for accurate trading
        if "tool_propose_trade" in available_actions or "tool_propose_counter_offer" in available_actions:
            prompt += "\n" + "="*80 + "\n"
            prompt += "🎯 PROPERTY OWNERSHIP REFERENCE - FOR TRADE ACTIONS ONLY\n"
            prompt += "="*80 + "\n"
            
            # Show my properties in simple format
            prompt += f"📋 MY PROPERTIES (use these IDs for 'offered_property_ids'):\n"
            if not game_state.get('my_properties_owned_ids', []):
                prompt += "  (None - I own no properties)\n"
            else:
                for prop_id in sorted(game_state.get('my_properties_owned_ids', [])):
                    prop = next((sq for sq in game_state.get('board_squares',[]) if sq['id'] == prop_id), None)
                    if prop:
                        mortgage_status = "[MORTGAGED]" if prop.get('is_mortgaged') else "[AVAILABLE]"
                        houses_info = ""
                        if prop.get('type') == 'PROPERTY' and prop.get('num_houses', 0) > 0:
                            houses_info = f" +{prop['num_houses']}H" if prop['num_houses'] < 5 else " +HOTEL"
                        prompt += f"  ID:{prop_id} = {prop['name']}{houses_info} {mortgage_status}\n"
            
            # Show each other player's properties in simple format
            for other_player in game_state.get('other_players', []):
                if other_player.get('is_bankrupt', False):
                    continue
                    
                player_name = other_player['name']
                player_id = other_player['player_id']
                properties_owned = other_player.get('properties_owned', [])
                
                prompt += f"\n📋 {player_name.upper()} (P{player_id}) PROPERTIES (use these IDs for 'requested_property_ids' when trading with P{player_id}):\n"
                if not properties_owned:
                    prompt += "  (None - they own no properties)\n"
                else:
                    for prop in sorted(properties_owned, key=lambda x: x.get('id', 0)):
                        prop_id = prop.get('id')
                        prop_name = prop.get('name', 'Unknown')
                        mortgage_status = "[MORTGAGED]" if prop.get('is_mortgaged') else "[AVAILABLE]"
                        houses_info = ""
                        if prop.get('num_houses', 0) > 0:
                            houses_info = f" +{prop['num_houses']}H" if prop['num_houses'] < 5 else " +HOTEL"
                        prompt += f"  ID:{prop_id} = {prop_name}{houses_info} {mortgage_status}\n"
            
            prompt += "\n" + "="*80 + "\n"
            prompt += "🚨 CRITICAL TRADE RULES:\n"
            prompt += "1. ✅ offered_property_ids = property IDs from MY PROPERTIES section above\n"
            prompt += "2. ✅ requested_property_ids = property IDs from TARGET PLAYER's properties section above\n"
            prompt += "3. ❌ NEVER mix up property IDs between players\n"
            prompt += "4. ❌ NEVER guess property IDs - they are ALL listed above\n"
            prompt += "5. ✅ Double-check the property name matches the ID you're using\n"
            
            # Add special warning for counter offers
            current_pending_decision = game_state.get('pending_decision_type')
            if current_pending_decision == "respond_to_trade_offer" and "tool_propose_counter_offer" in available_actions:
                decision_context = game_state.get('pending_decision_context', {})
                proposer_id_ctx = decision_context.get("proposer_id")
                if proposer_id_ctx is not None:
                    # Find the proposer's name
                    proposer_name_ctx = "Unknown Player"
                    for p_info in game_state.get('other_players', []):
                        if p_info and p_info.get('player_id') == proposer_id_ctx:
                            proposer_name_ctx = p_info.get('name', 'Unknown')
                            break
                    
                    prompt += f"6. 🚨 COUNTER-OFFER SPECIAL RULE: You can ONLY request properties from P{proposer_id_ctx} ({proposer_name_ctx})!\n"
                    prompt += f"   ❌ Do NOT request properties from other players in a counter-offer!\n"
            
            prompt += "="*80 + "\n\n"
        
        # 🎯 CONDITIONAL: add strategy note for trading (only in later game stages)
        # 🚨 FIX: Define is_later_stage outside of conditions to avoid UnboundLocalError
        # Determine if we're in later game stage for trade emphasis
        total_properties_owned = len(game_state.get('my_properties_owned_ids', []))
        turn_count = game_state.get('turn_count', 1)
        other_players_have_properties = any(
            len(p.get('properties_owned', [])) > 2 
            for p in game_state.get('other_players', [])
        )
        
        # Only emphasize trading in later stages: turn 50+, or when players have 3+ properties
        is_later_stage = turn_count >= 30 or total_properties_owned >= 3 or other_players_have_properties
        
        if "tool_propose_trade" in available_actions:
            if is_later_stage:
                prompt += "\n🤝 TRADING FOCUS: Complete color groups to build houses and charge monopoly rent.\n"
            else:
                prompt += "\n💰 EARLY GAME: Focus on buying unowned properties first. Trade when beneficial.\n"
            
            # analyze current color group situation
            color_group_analysis = {}
            for prop_id in game_state.get('my_properties_owned_ids', []):
                prop = next((sq for sq in game_state.get('board_squares',[]) if sq['id'] == prop_id), None)
                if prop and prop.get('color_group'):
                    color_group = prop['color_group']
                    if color_group not in color_group_analysis:
                        color_group_analysis[color_group] = {'owned': [], 'total_in_group': 0, 'missing': []}
                    color_group_analysis[color_group]['owned'].append(prop)
            
            # calculate the completeness of each color group
            board_squares = game_state.get('board_squares', [])
            for color_group in color_group_analysis:
                total_props_in_group = [sq for sq in board_squares if sq.get('color_group') == color_group and sq.get('type') == 'PROPERTY']
                color_group_analysis[color_group]['total_in_group'] = len(total_props_in_group)
                
                owned_ids = [prop['id'] for prop in color_group_analysis[color_group]['owned']]
                missing_props = [sq for sq in total_props_in_group if sq['id'] not in owned_ids]
                color_group_analysis[color_group]['missing'] = missing_props
            
            # Trading analysis (concise)
            if color_group_analysis and is_later_stage:
                prompt += "\n--- Color Group Status ---\n"
                trade_targets = []
                
                for color_group, analysis in color_group_analysis.items():
                    owned_count = len(analysis['owned'])
                    total_count = analysis['total_in_group']
                    missing_count = len(analysis['missing'])
                    
                    prompt += f"• {color_group}: You own {owned_count}/{total_count} properties"
                    
                    if missing_count == 0:
                        prompt += f"• {color_group}: COMPLETE - Build houses!\n"
                    elif missing_count == 1:
                        missing_prop = analysis['missing'][0]
                        owner_id = missing_prop.get('owner_id')
                        if owner_id is not None and owner_id != game_state.get('my_player_id'):
                            owner_name = next((p['name'] for p in game_state.get('other_players', []) if p['player_id'] == owner_id), "Unknown")
                            prompt += f"• {color_group}: Need {missing_prop['name']} from P{owner_id} ({owner_name})\n"
                            trade_targets.append(f"P{owner_id} for {missing_prop['name']}")
                    else:
                        prompt += f"• {color_group}: Need {missing_count} more properties\n"
                
                if trade_targets:
                    prompt += f"Priority trades: {', '.join(trade_targets)}\n"
        
        # Other players analysis (simplified)
        if is_later_stage:
            monopoly_threats = []
            for other_player in game_state.get('other_players', []):
                if other_player.get('is_bankrupt', False):
                    continue
                player_name = other_player['name']
                other_properties = other_player.get('properties_owned', [])
                
                # Check for near-complete monopolies
                other_color_groups = {}
                for prop in other_properties:
                    color_group = prop.get('color_group')
                    if color_group and color_group != 'N/A':
                        other_color_groups[color_group] = other_color_groups.get(color_group, 0) + 1
                
                for color_group, count in other_color_groups.items():
                    total_in_group = len([sq for sq in game_state.get('board_squares', []) 
                                        if sq.get('color_group') == color_group and sq.get('type') == 'PROPERTY'])
                    if count == total_in_group:
                        monopoly_threats.append(f"{player_name} has {color_group} monopoly")
                    elif count == total_in_group - 1:
                        monopoly_threats.append(f"{player_name} needs 1 more for {color_group}")
            
            if monopoly_threats:
                prompt += f"\n--- Threats: {', '.join(monopoly_threats)}\n"
        

        
        current_pending_decision = game_state.get('pending_decision_type', 'None')
        prompt += f"Current pending decision: {current_pending_decision}\n"
        decision_context = game_state.get('pending_decision_context')
        if decision_context: 
            prompt += f"Decision context: {json.dumps(decision_context)}\n"
            if current_pending_decision == "respond_to_trade_offer":
                proposer_id_ctx = decision_context.get("proposer_id")
                proposer_name_ctx = "Unknown Player"
                # Search for proposer name in other_players or in my_name if I am the proposer (should not happen for respond_to_trade_offer)
                for p_info_list in [game_state.get('other_players', []), [{"player_id": game_state.get("my_player_id"), "name": game_state.get("my_name")}] ]:
                    for p_info in p_info_list:
                        if p_info and p_info.get('player_id') == proposer_id_ctx: proposer_name_ctx = p_info.get('name', 'Unknown'); break
                    if proposer_name_ctx != "Unknown Player": break
                
                message_from_proposer = decision_context.get("message_from_proposer")
                prompt += f"You have received a trade offer (ID: {decision_context.get('trade_id')}) from P{proposer_id_ctx} ({proposer_name_ctx}).\n"
                if message_from_proposer:
                    prompt += f"Message from P{proposer_name_ctx}: \"{message_from_proposer}\"\n"
                prompt += f"🚨 COUNTER-OFFER RULE: If you counter-offer, you can ONLY trade with P{proposer_id_ctx} ({proposer_name_ctx}) - NOT with other players!\n"
                prompt += f"This means requested_property_ids must be from P{proposer_id_ctx}'s property list ONLY.\n"
                prompt += "Review the offer details and choose to accept, reject, or propose a counter-offer (tool_propose_counter_offer).\n"
            
            elif current_pending_decision == "propose_new_trade_after_rejection":
                rejected_by_player_id = decision_context.get("rejected_by_player_id")
                rejected_by_player_name = "Unknown Player"
                for p_info_list in [game_state.get('other_players', []), [{"player_id": game_state.get("my_player_id"), "name": game_state.get("my_name")}] ]:
                    for p_info in p_info_list:
                         if p_info and p_info.get('player_id') == rejected_by_player_id: rejected_by_player_name = p_info.get('name', 'Unknown'); break
                    if rejected_by_player_name != "Unknown Player": break
                
                rejection_count = decision_context.get("negotiation_rejection_count", 0)
                last_offer_msg_from_context = decision_context.get("message_from_rejector", "(No specific rejection message was provided, assume general rejection of your last offer.)") # This context message is from GC
                prompt += f"Your previous trade offer (Original ID: {decision_context.get('original_trade_id_rejected')}) to P{rejected_by_player_id} ({rejected_by_player_name}) was REJECTED.\n"
                prompt += f"{last_offer_msg_from_context}\n" # Display the message from GC about rejection
                prompt += f"This negotiation has been rejected {rejection_count} time(s). Maximum allowed is {MAX_TRADE_REJECTIONS_FOR_PROMPT}.\n"
                
                # Add specific guidance for improving the offer
                if current_trade_info:
                    prompt += "\nTo improve your offer, you could:\n"
                    
                    # Analyze current money in the trade
                    current_money_offered = 0
                    for item in current_trade_info['items_offered_by_proposer']:
                        if item['item_type'] == 'money':
                            current_money_offered = item['quantity']
                            break
                    
                    if current_money_offered > 0:
                        prompt += f"- Increase money offer (currently ${current_money_offered})\n"
                    else:
                        prompt += f"- Add money to your offer (currently $0)\n"
                    
                    prompt += f"- Add additional properties to your offer\n"
                    prompt += f"- Request different items\n"
                    prompt += f"- Change your message to be more persuasive\n"
                    prompt += f"\nIMPORTANT: When you say 'add $X', make sure your 'offered_money' parameter is the TOTAL amount (current + additional), not just the additional amount.\n"
                
                if rejection_count < MAX_TRADE_REJECTIONS_FOR_PROMPT:
                    prompt += f"You can either propose a new trade (tool_propose_trade) to P{rejected_by_player_id} (include new terms and an optional 'message' parameter), or end this negotiation (tool_end_trade_negotiation).\n"
                    prompt += f"IMPORTANT: Check your turn trade limit before proposing - you may have reached the maximum trade attempts for this turn.\n"
                else:
                    prompt += f"You have reached the maximum number of rejections for this negotiation. You must choose to end the negotiation (tool_end_trade_negotiation).\n"
            
            elif current_pending_decision == "jail_options":
                # ... (existing jail options prompt enhancement)
                if decision_context.get("max_rolls_attempted"): 
                     prompt += "You have used all your roll attempts to get out of jail this time. You must now pay, use a card, or end your turn if no other options.\n"
                elif decision_context.get("roll_failed"): 
                     prompt += f"Your last roll to get out of jail ({decision_context.get('last_roll_dice')}) failed. You have {3 - decision_context.get('jail_turns_attempted_this_incarceration',0)} roll attempts left this incarceration.\n"


        
        prompt += "\nAvailable actions for you now are:\n"
        for i, action_name in enumerate(available_actions):
            if action_name == "tool_build_house":
                prompt += f"{i+1}. {action_name} ⭐ HIGH PRIORITY - BUILD HOUSES TO INCREASE RENT! (After rolling dice)\n"
            else:
                prompt += f"{i+1}. {action_name}\n"
        
        # Add detailed tool descriptions to prevent parameter confusion
        prompt += "\n--- Tool Parameter Specifications ---\n"
        prompt += "IMPORTANT: Use EXACT parameter names as specified below:\n\n"
        
        tool_descriptions = {
            "tool_end_turn": "Parameters: {} (no parameters needed)",
            "tool_buy_property": "Parameters: {\"property_id\": <integer>} (optional, auto-filled if pending)",
            "tool_pass_on_buying_property": "Parameters: {\"property_id\": <integer>} (optional, auto-filled if pending)",
            "tool_build_house": "Parameters: {\"property_id\": <integer>} (builds ONE house on the specified property)",
            "tool_sell_house": "Parameters: {\"property_id\": <integer>} (sells ONE house from the specified property)",
            "tool_mortgage_property": "Parameters: {\"property_id\": <integer>} - 🚨 ONLY for UNMORTGAGED properties!",
            "tool_unmortgage_property": "Parameters: {\"property_id\": <integer>} - 🚨 ONLY for MORTGAGED properties!",
            "tool_pay_bail": "Parameters: {} (no parameters needed)",
            "tool_use_get_out_of_jail_card": "Parameters: {} (no parameters needed)",
            "tool_roll_for_doubles_to_get_out_of_jail": "Parameters: {} (no parameters needed)",
            "tool_bid_on_auction": "Parameters: {\"bid_amount\": <integer>}",
            "tool_pass_auction_bid": "Parameters: {} (no parameters needed)",
            "tool_withdraw_from_auction": "Parameters: {} (no parameters needed)",
            "tool_propose_trade": "Parameters: {\"recipient_id\": <integer>, \"offered_property_ids\": [<list of integers>], \"offered_money\": <integer>, \"offered_get_out_of_jail_free_cards\": <integer>, \"requested_property_ids\": [<list of integers representing properties index id>], \"requested_money\": <integer>, \"requested_get_out_of_jail_free_cards\": <integer>, \"message\": \"<optional string>\"} ⚠️ CRITICAL: Look up property IDs from board_squares - do NOT guess!",
            "tool_accept_trade": "Parameters: {\"trade_id\": <integer>} (optional, auto-filled if pending)",
            "tool_reject_trade": "Parameters: {\"trade_id\": <integer>} (optional, auto-filled if pending)",
            "tool_propose_counter_offer": "Parameters: {\"trade_id\": <integer>, \"offered_property_ids\": [<list of integers>], \"offered_money\": <integer>, \"offered_get_out_of_jail_free_cards\": <integer>, \"requested_property_ids\": [<list of integers representing properties index id>], \"requested_money\": <integer>, \"requested_get_out_of_jail_free_cards\": <integer>, \"counter_message\": \"<optional string>\"} 🚨 CRITICAL COUNTER-OFFER RULE: You can ONLY request properties from the ORIGINAL trade proposer - NOT from other players!",
            "tool_end_trade_negotiation": "Parameters: {} (no parameters needed)",
            "tool_pay_mortgage_interest_fee": "Parameters: {\"property_id\": <integer>} (optional, auto-filled if pending)",
            "tool_unmortgage_property_immediately": "Parameters: {\"property_id\": <integer>} (optional, auto-filled if pending)",
            "tool_confirm_asset_liquidation_actions_done": "Parameters: {} (no parameters needed)",
            "tool_do_nothing": "Parameters: {\"reason\": \"<optional string>\"}",
            "tool_wait": "Parameters: {} (no parameters needed)",
            "tool_resign_game": "Parameters: {} (no parameters needed)"
        }
        
        for action_name in available_actions:
            if action_name in tool_descriptions:
                prompt += f"• {action_name}: {tool_descriptions[action_name]}\n"
            else:
                prompt += f"• {action_name}: Parameters: {{}} (unknown tool, use no parameters)\n"
        
        # 🚨 CRITICAL OPERATION VALIDATION - Add comprehensive guidance
        prompt += "\n🚨 CRITICAL OPERATION VALIDATION CHECKLIST:\n"
        prompt += "Before taking ANY action, you MUST verify:\n\n"
        
        # Mortgage-specific validation
        if "tool_mortgage_property" in available_actions:
            prompt += "💰 MORTGAGE PROPERTY VALIDATION:\n"
            prompt += "1. ✅ Check 'UNMORTGAGED' section above - property must be listed there\n"
            prompt += "2. ❌ NEVER mortgage properties listed in 'MORTGAGED' section\n"
            prompt += "3. ❌ If property shows '[MORTGAGED]' - it's ALREADY mortgaged!\n"
            prompt += "4. ❌ If you just mortgaged a property this turn - DON'T mortgage it again!\n"
            prompt += "5. ✅ Only use property_id from your own properties in UNMORTGAGED section\n\n"
        
        if "tool_unmortgage_property" in available_actions:
            prompt += "🏦 UNMORTGAGE PROPERTY VALIDATION:\n"
            prompt += "1. ✅ Check 'MORTGAGED' section above - property must be listed there\n"
            prompt += "2. ❌ NEVER unmortgage properties listed in 'UNMORTGAGED' section\n"
            prompt += "3. ❌ If property shows '[UNMORTGAGED]' - it's NOT mortgaged!\n"
            prompt += "4. ✅ Only use property_id from your own properties in MORTGAGED section\n\n"
        
        # Trade-specific validation
        if "tool_propose_trade" in available_actions or "tool_propose_counter_offer" in available_actions:
            prompt += "🤝 TRADE PROPOSAL VALIDATION:\n"
            prompt += "1. ✅ For offered_property_ids: Use ONLY properties from YOUR 'Properties Owned' section\n"
            prompt += "2. ✅ For requested_property_ids: Use ONLY properties from TARGET PLAYER's property list\n"
            prompt += "3. ❌ NEVER offer properties you don't own (not in your Properties Owned section)\n"
            prompt += "4. ❌ NEVER request properties the other player doesn't own\n"
            prompt += "5. ✅ Cross-reference 'Properties owned by [Player]' section for exact property IDs\n"
            prompt += "6. ✅ Double-check property ownership in 'Opponent Status' section above\n\n"
        
        # General validation
        prompt += "⚡ GENERAL ACTION VALIDATION:\n"
        prompt += "1. 🔄 READ recent game events - avoid repeating failed actions immediately\n"
        prompt += "2. 🎯 Check 'Available actions' - only use actions from this list\n"
        prompt += "3. 💡 If an action just failed - understand WHY before trying similar actions\n"
        prompt += "4. 🧠 THINK: Does this action make sense given current game state?\n"
        prompt += "5. 📋 Verify all parameters match the specifications above exactly\n\n"

        # 🚨 CRITICAL: Add property ID verification for trades AND counter offers
        if "tool_propose_trade" in available_actions or "tool_propose_counter_offer" in available_actions:
            prompt += "\n🔍 PROPERTY ID VERIFICATION - READ CAREFULLY!\n"
            prompt += "Before proposing any trade or you are responding to proposal with a counter-offer, you MUST verify property IDs using the detailed information provided.\n"
            
            prompt += "\n🎯 VERIFICATION CHECKLIST BEFORE SUBMITTING:\n"
            prompt += "1. ✅ Check 'Properties owned by [Player]' section above for exact property names and IDs\n"
            prompt += "2. ✅ Use the EXACT property IDs shown in the opponent's property list\n"
            prompt += "3. ✅ For your own properties, use the IDs from 'Properties Owned' section\n"
            prompt += "4. ✅ Cross-reference with board_squares if needed for additional details\n"
            prompt += "5. ❌ NEVER guess property IDs - all information is provided above\n"
            
            prompt += "\n💡 EXAMPLE WORKFLOW:\n"
            prompt += "1. 'I want to trade with Ricky for his Vermont Avenue'\n"
            prompt += "2. Look at 'Properties owned by Ricky' section above\n"
            prompt += "3. Find 'Vermont Avenue (ID: 8)' in his property list\n"
            prompt += "4. Use ID 8 in requested_property_ids parameter\n"
            prompt += "5. For offered properties, check my own 'Properties Owned' section\n"
            
            # 🎯 Add specific guidance for counter offers
            if "tool_propose_counter_offer" in available_actions:
                prompt += "\n🔄 COUNTER-OFFER SPECIAL INSTRUCTIONS:\n"
                prompt += "When responding to a trade offer with a counter-offer:\n"
                prompt += "1. ✅ Review the original trade details in 'Current Trade Details' section above\n"
                prompt += "2. ✅ Understand what the proposer offered and requested\n"
                prompt += "3. ✅ Your counter-offer offered_property_ids = properties YOU give to THEM\n"
                prompt += "4. ✅ Your counter-offer requested_property_ids = properties YOU want from THEM\n"
                prompt += "5. ✅ Use the detailed property ownership information to verify all IDs\n"
                prompt += "6. ✅ Include a counter_message explaining your counter-proposal\n\n"

        prompt += "\nINSTRUCTIONS FOR YOUR RESPONSE:\n"
        prompt += "You must respond with a single JSON object containing your action and thoughts.\n"
        prompt += "The JSON object MUST have these keys:\n"
        prompt += "1. 'thoughts': Your reasoning process"
        if self.personality:
            prompt += " - ALWAYS consider how your personality influences this decision"
        prompt += "\n2. 'tool_name': The exact name of the chosen action from the available actions list\n"
        prompt += "3. 'parameters': A JSON object containing the action parameters (use {} if no parameters needed)\n"        
        # Error handling
        prompt += "\n🚨 CRITICAL ERROR HANDLING AND STRATEGY ADJUSTMENT:\n"
        prompt += "If your previous action FAILED (you see error messages), you MUST:\n"
        prompt += "1. 📖 READ the error message carefully for specific failure reasons\n"
        prompt += "2. 🔍 UNDERSTAND what went wrong before attempting similar actions\n"
        prompt += "3. 🛠️ ADJUST your strategy based on the specific error type\n"
        prompt += "4. ❌ NEVER repeat the exact same action with same parameters immediately\n"
        prompt += "5. 🎯 Choose a completely different action or fix the parameters\n\n"
        
        # 🎯 ENHANCED: Add specific error pattern handling
        prompt += "📋 COMMON ERROR PATTERNS AND FIXES:\n"
        prompt += "• Property ownership errors → Check PROPERTY OWNERSHIP REFERENCE section above\n"
        prompt += "• Already mortgaged errors → Look for [MORTGAGED] status in property listings\n"
        prompt += "• Insufficient funds errors → Check current money vs. required amount\n"
        prompt += "• Invalid property ID errors → Use exact IDs from property lists above\n"
        prompt += "• Trade validation errors → Double-check offered vs. requested property owners\n"
        prompt += "• House building errors → Verify monopoly ownership and even development rule\n\n"
        
        # 🎯 SPECIFIC: Counter-offer guidance
        if "tool_propose_counter_offer" in available_actions:
            prompt += "🔄 COUNTER-OFFER SPECIAL GUIDANCE:\n"
            prompt += "• Remember: YOU are now the proposer, THEY are the recipient\n"
            prompt += "• offered_property_ids = properties YOU give to THEM (from YOUR properties)\n"
            prompt += "• requested_property_ids = properties YOU want from THEM (from THEIR properties)\n"
            prompt += "• Review the original trade details above to understand what they offered/requested\n"
            prompt += "• Your counter should be a reasonable alternative to their proposal\n\n"
        
        prompt += "\nExamples:\n"
        if self.personality:
            prompt += '{"thoughts": "Based on my personality, I should [decision]. This aligns with my playing style of [behavior].", "tool_name": "tool_action", "parameters": {...}}\n'
        else:
            prompt += '{"thoughts": "My reasoning for this action...", "tool_name": "tool_action", "parameters": {...}}\n'
        prompt += "\nRespond ONLY with the JSON object. Ensure it contains all three required keys and is valid JSON."

        self.last_prompt = prompt

        # Concise system prompt
        system_prompt = (
            "You are an expert Monopoly AI player. Your goal: win by bankrupting opponents while avoiding bankruptcy. "
            "Respond with valid JSON: {'thoughts': 'reasoning', 'tool_name': 'action', 'parameters': {}}. "
            "Building houses and completing monopolies are highest priorities. "
            "Use exact property IDs from the provided information - never guess. "
            "CRITICAL: Always verify property states (mortgaged/unmortgaged) and ownership before acting. "
            "Never repeat failed actions immediately - learn from errors and adjust strategy. "
            "When mortgaging: only use UNMORTGAGED properties. When trading: only offer/request properties actually owned by the respective players."
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        return system_prompt, messages

    def _clean_llm_json_str(self, json_str: str) -> str:
        cleaned_str = json_str
        if cleaned_str.startswith("```json"): cleaned_str = cleaned_str[len("```json"):]
        if cleaned_str.endswith("```"): cleaned_str = cleaned_str[:-len("```")]
        cleaned_str = cleaned_str.strip()
        return cleaned_str

    @taudit_verifier
    def _extract_json_from_response(self, llm_response_content: str) -> Optional[Dict[str, Any]]:
        agent_name_logging = f"Agent {self.name} (P{self.player_id})"
        print(f"{agent_name_logging}: Attempting to extract JSON. Raw LLM response content (len: {len(llm_response_content)}):\n--BEGIN LLM RAW--\n{llm_response_content}\n--END LLM RAW--")
        
        self.last_agent_thoughts = ""
        self.last_parsed_action_json_str = ""
        json_action_obj = None

        cleaned_content = self._clean_llm_json_str(llm_response_content)

        # Attempt to parse the entire cleaned content as JSON (new format with thoughts inside)
        try:
            json_action_obj = json.loads(cleaned_content)
            self.last_parsed_action_json_str = cleaned_content
            
            # Extract thoughts from JSON if present
            if isinstance(json_action_obj, dict) and 'thoughts' in json_action_obj:
                self.last_agent_thoughts = json_action_obj.get('thoughts', '')
            else:
                self.last_agent_thoughts = "No thoughts field found in JSON response"
                            
        except json.JSONDecodeError as e_full:
            print(f"{agent_name_logging}: Failed to parse cleaned content as JSON. Error: {e_full}. Content was: '{cleaned_content[:500]}...'")
            
            # Fallback: Try to find JSON object and parse it (legacy format support)
            try:
                first_brace = cleaned_content.find('{')
                last_brace = cleaned_content.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    potential_json_str = cleaned_content[first_brace : last_brace + 1]
                    print(f"{agent_name_logging}: Fallback: Trying to parse substring from first {{ to last }}: '{potential_json_str[:500]}...'")
                    json_action_obj = json.loads(potential_json_str)
                    self.last_parsed_action_json_str = potential_json_str
                    
                    # Check for thoughts in JSON (new format)
                    if isinstance(json_action_obj, dict) and 'thoughts' in json_action_obj:
                        self.last_agent_thoughts = json_action_obj.get('thoughts', '')
                    else:
                        # Extract pre/post JSON text as thoughts (legacy format)
                        pre_json_text = cleaned_content[:first_brace].strip()
                        post_json_text = cleaned_content[last_brace+1:].strip()
                        if pre_json_text or post_json_text:
                            self.last_agent_thoughts = f"Pre-JSON: {pre_json_text} | Post-JSON: {post_json_text}".strip(" | ")
                        else:
                            self.last_agent_thoughts = "JSON parsed but no thoughts field or surrounding text found"
                    
                    print(f"{agent_name_logging}: Successfully parsed substring as JSON (fallback).")
                else:
                    print(f"{agent_name_logging}: Fallback: Could not find valid {{...}} block.")
                    self.last_agent_thoughts = llm_response_content # Treat all as thoughts if no JSON found
            except json.JSONDecodeError as e_substring:
                print(f"{agent_name_logging}: Fallback: Failed to parse substring as JSON. Error: {e_substring}. Substring was: '{potential_json_str[:500]}...'")
                self.last_agent_thoughts = llm_response_content # Treat all as thoughts
            except Exception as e_general_fallback:
                print(f"{agent_name_logging}: Unexpected error during fallback JSON extraction: {e_general_fallback}")
                self.last_agent_thoughts = llm_response_content
        except Exception as e_outer:
             print(f"{agent_name_logging}: Unexpected error before or during primary JSON parsing: {e_outer}")
             self.last_agent_thoughts = llm_response_content
        
        # Final validation and logging
        if json_action_obj and isinstance(json_action_obj, dict):
            if not self.last_agent_thoughts or self.last_agent_thoughts == llm_response_content:
                # If we still don't have thoughts, provide a default
                self.last_agent_thoughts = json_action_obj.get('thoughts', 'JSON action parsed, no thoughts provided')
        elif not json_action_obj and not self.last_agent_thoughts:
            # Complete failure to parse and no thoughts otherwise
            self.last_agent_thoughts = llm_response_content # Default to full response if nothing else
        
        print(f"{agent_name_logging}: Final extracted JSON object: {json.dumps(json_action_obj) if json_action_obj else 'None'}")
        print(f"{agent_name_logging}: Final agent thoughts: '{self.last_agent_thoughts[:200]}...'")
        return json_action_obj

    @taudit_verifier
    def decide_action(self, game_state: Dict[str, Any], available_actions: List[str], current_gc_turn: int, action_sequence_num: int) -> Tuple[str, Dict[str, Any]]:
        self.last_gc_turn_number = current_gc_turn
        self.last_action_sequence_in_gc_turn = action_sequence_num
        self.last_pending_decision_type_before = game_state.get("pending_decision_type")
        self.last_pending_decision_context_json_before = json.dumps(game_state.get("pending_decision_context"))
        self.last_available_actions_json_before = json.dumps(available_actions)
        self.last_agent_thoughts = ""
        self.last_llm_raw_response = ""
        self.last_parsed_action_json_str = ""
        self.last_chosen_tool_name = ""
        self.last_tool_parameters_json = "{}"

        if not available_actions:
            self.last_agent_thoughts = "No actions available, choosing to do nothing."
            self.last_chosen_tool_name = "tool_do_nothing"
            return "tool_do_nothing", {}

        _, messages_for_prompt = self._build_prompt(game_state, available_actions)
        
        self.last_agent_thoughts = f"Attempting to call reasoning for P{self.player_id}. Available actions: {available_actions}. Pending: {self.last_pending_decision_type_before}"
        start_time = time.time() # Import time if not already
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages_for_prompt,
                temperature=0.7, 
                response_format={"type": "json_object"} # Requires GPT-4 Turbo or newer for guaranteed JSON
            )
            self.last_llm_raw_response = response.choices[0].message.content if response.choices else ""
        except Exception as e:
            error_message = f"Agent {self.name} (P{self.player_id}): OpenAI API call EXCEPTION: {e}"
            print(error_message)
            self.last_agent_thoughts += f" | OpenAI API call failed: {e}"
            self.last_llm_raw_response = error_message
            self.last_chosen_tool_name = "tool_do_nothing" # Fallback action
            # Also log this error to the game log via GC if possible, or ensure server log catches it
            return "tool_do_nothing", {}

        end_time = time.time()
        print(f"Agent {self.name} (P{self.player_id}): reasoning completed in {end_time - start_time:.2f} seconds.")

        if not self.last_llm_raw_response:
            self.last_agent_thoughts += " | LLM returned an empty response."
            self.last_chosen_tool_name = "tool_do_nothing"
            return "tool_do_nothing", {}

        extracted_json = self._extract_json_from_response(self.last_llm_raw_response)
        self.last_parsed_action_json_str = json.dumps(extracted_json) if extracted_json else "{}"

        if extracted_json and "tool_name" in extracted_json:
            chosen_tool_name = extracted_json.get("tool_name")
            params = extracted_json.get("parameters", {})
            llm_thoughts = extracted_json.get("thoughts", "No thoughts provided by LLM.")
            self.last_agent_thoughts = llm_thoughts # Overwrite or append based on preference
            self.last_chosen_tool_name = chosen_tool_name
            self.last_tool_parameters_json = json.dumps(params)
            
            if chosen_tool_name in available_actions:
                self.last_agent_thoughts += f" | LLM Valid Action Parsed: {chosen_tool_name} with params {params}."
                print(f"Agent {self.name} (P{self.player_id}) parsed action: {chosen_tool_name}, Params: {params}")
                return chosen_tool_name, params
            else:
                self.last_agent_thoughts += f" | LLM chose an UNAVAILABLE action: '{chosen_tool_name}'. Fallback."
                print(f"Agent {self.name} (P{self.player_id}): LLM chose unavailable action '{chosen_tool_name}'. Available: {available_actions}. Fallback to tool_wait or tool_do_nothing.")
        else:
            self.last_agent_thoughts += " | Failed to parse valid JSON action from LLM response."
            print(f"Agent {self.name} (P{self.player_id}): Failed to parse JSON action. Raw: {self.last_llm_raw_response}... Fallback.")

        # Fallback if parsing failed or action was unavailable
        fallback_action = "tool_wait" if "tool_wait" in available_actions else "tool_do_nothing"
        self.last_chosen_tool_name = fallback_action
        self.last_agent_thoughts += f" | Fallback to {fallback_action}."
        return fallback_action, {}

    def get_player_thought_process(self) -> str:
        # Return a more structured thought process including prompt if desired for debugging.
        # return f"Last Prompt:\n{self.last_prompt}\n\nLast Thought Process Log:\n{self.last_thought_process}"
        return self.last_agent_thoughts

    def get_last_decision_details_for_db(self) -> Dict[str, Any]:
        return {
            "gc_turn_number": self.last_gc_turn_number,
            "action_sequence_in_gc_turn": self.last_action_sequence_in_gc_turn,
            "pending_decision_type_before": self.last_pending_decision_type_before,
            "pending_decision_context_json_before": self.last_pending_decision_context_json_before,
            "available_actions_json_before": self.last_available_actions_json_before,
            "agent_thoughts_text": self.last_agent_thoughts, # Thoughts extracted before JSON
            "llm_raw_response_text": self.last_llm_raw_response,
            "parsed_action_json_str": self.last_parsed_action_json_str,
            "chosen_tool_name": self.last_chosen_tool_name,
            "tool_parameters_json": self.last_tool_parameters_json
        }

if __name__ == '__main__':
    # This is a placeholder for where you'd set your API key
    # Ensure OPENAI_API_KEY is set in your environment variables
    # e.g., export OPENAI_API_KEY='your_actual_api_key' (on Linux/macOS)
    # or set OPENAI_API_KEY=your_actual_api_key (on Windows cmd)
    # or $env:OPENAI_API_KEY='your_actual_api_key' (on Windows PowerShell)

    print("Attempting to initialize OpenAIAgent...")
    try:
        if not os.getenv("OPENAI_API_KEY"):
            print("Skipping OpenAIAgent test: OPENAI_API_KEY environment variable not set.")
        else:
            agent = OpenAIAgent(player_id=0, name="TestAgentGPT")
            print(f"Agent {agent.name} initialized with model {agent.model_name}.")
            
            dummy_game_state = {
                "my_player_id": 0,
                "my_name": "TestAgentGPT",
                "my_money": 1500,
                "my_position": 1, # On Mediterranean Ave
                "my_properties_owned_ids": [],
                "my_in_jail": False,
                "my_jail_turns_remaining": 0,
                "my_get_out_of_jail_cards": {"community_chest": False, "chance": False},
                "current_player_id": 0,
                "dice_roll": None,
                "board_squares": [
                    {"id": 0, "name": "GO", "type": "GO"},
                    {"id": 1, "name": "Mediterranean Avenue", "type": "PROPERTY", "price": 60, "owner_id": None, "is_mortgaged": False, "color_group": "BROWN", "rent_levels": [2,10,30,90,160,250], "house_price": 50, "num_houses":0},
                    {"id": 2, "name": "Community Chest", "type": "COMMUNITY_CHEST"},
                    {"id": 3, "name": "Baltic Avenue", "type": "PROPERTY", "price": 60, "owner_id": 1, "is_mortgaged": False, "color_group": "BROWN", "rent_levels": [4,20,60,180,320,450], "house_price": 50, "num_houses":0},
                ],
                "other_players": [
                    {"player_id": 1, "name": "Opponent1", "money": 1440, "position": 3, "properties_owned_ids": [3], "in_jail": False}
                ],
                "game_log_tail": ["Game started.", "TestAgentGPT rolled 1.", "TestAgentGPT landed on Mediterranean Avenue."]
            }
            # Scenario 1: Landed on unowned property
            print("\n--- Scenario 1: Landed on unowned property ---")
            dummy_actions_s1 = ['buy_property {"property_id": 1}', 'auction_property {"property_id": 1}'] # Simplified action format for this test
            # Actual available_actions list would just be ["buy_property", "auction_property"]
            # The LLM needs to construct the params.
            # Let's use the tool names as available_actions, and LLM should format output.
            available_actions_s1 = ["buy_property", "auction_property"]

            prompt_s1 = agent._build_prompt(dummy_game_state, available_actions_s1)
            print("\n--- Built Prompt (Scenario 1) ---")
            # print(prompt_s1) # Usually too long for console
            
            print("\n--- Simulating decide_action (Scenario 1) ---")
            action_s1, params_s1 = agent.decide_action(dummy_game_state, available_actions_s1, 1, 1)
            print(f"Chosen action: {action_s1}, Params: {params_s1}")
            # print(f"Thought process:\n{agent.get_player_thought_process()}") # Also can be very long

            # Scenario 2: In Jail
            print("\n\n--- Scenario 2: In Jail ---")
            dummy_game_state_s2 = dummy_game_state.copy()
            dummy_game_state_s2["my_in_jail"] = True
            dummy_game_state_s2["my_jail_turns_remaining"] = 1
            dummy_game_state_s2["my_position"] = 10 # Jail square
            dummy_game_state_s2["board_squares"].append({"id": 10, "name": "Jail", "type": "JAIL_VISITING"}) # Add Jail square for prompt
            
            available_actions_s2 = ["pay_bail", "use_get_out_of_jail_card", "roll_for_doubles"]
            prompt_s2 = agent._build_prompt(dummy_game_state_s2, available_actions_s2)
            # print("\n--- Built Prompt (Scenario 2) ---")
            # print(prompt_s2)

            print("\n--- Simulating decide_action (Scenario 2) ---")
            action_s2, params_s2 = agent.decide_action(dummy_game_state_s2, available_actions_s2, 2, 1)
            print(f"Chosen action: {action_s2}, Params: {params_s2}")
            # print(f"Thought process:\n{agent.get_player_thought_process()}")


    except ValueError as e:
        print(f"ValueError during test: {e}")
    except ImportError as e:
        print(f"ImportError during test: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during test: {e}") 