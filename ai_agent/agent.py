import os
from typing import Tuple, Dict, List, Any, Optional
from abc import ABC, abstractmethod
import json # Ensure json is imported
import re   # For potential cleanup of JSON string if needed
import time # Added for time measurement

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
        from game_logic.game_controller import MAX_TRADE_REJECTIONS as MTR_GC
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
    def __init__(self, player_id: int, name: str, model_name: str = "gpt-4o-mini", api_key: str = None):
        super().__init__(player_id, name)

        load_dotenv()

        if openai is None:
            raise ImportError("OpenAI library is required for OpenAIAgent but not installed.")
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided or found in OPENAI_API_KEY environment variable.")
        
        self.client = openai.OpenAI(api_key=self.api_key)
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

    def _build_prompt(self, game_state: Dict[str, Any], available_actions: List[str]) -> Tuple[str, List[Dict[str, str]]]:
        # Prompt for the AI agent in a Monopoly game
        
        # Introduction and Goal
        prompt = f"You are an AI player named {self.name} (Player ID: {self.player_id}) in a game of Monopoly.\n"
        prompt += "Your primary goal is to maximize your wealth and bankrupt other players. Make strategic decisions to achieve this.\n"

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
            for prop_id in game_state.get('my_properties_owned_ids', []):
                prop = next((sq for sq in game_state.get('board_squares',[]) if sq['id'] == prop_id), None)
                if prop:
                    mortgaged_status = " (Mortgaged)" if prop.get('is_mortgaged') else ""
                    houses_str = ""
                    if prop.get('type') == 'PROPERTY' and prop.get('num_houses', 0) > 0:
                        houses_str = f", {prop['num_houses']} houses" if prop['num_houses'] < 5 else ", HOTEL"
                    prompt += f"  - {prop['name']} (ID: {prop_id}){houses_str}{mortgaged_status}\n"
        
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
        prompt += "\n--- Opponent Status (Summary) ---\n"
        if not game_state.get('other_players', []):
            prompt += "  (No other active players)\n"
        else:
            for p_info in game_state.get('other_players', []):
                if p_info.get('is_bankrupt', False):
                    prompt += f"{p_info['name']} (ID: {p_info['player_id']}): BANKRUPT\n"
                else:
                    prompt += f"{p_info['name']} (ID: {p_info['player_id']}): Pos {p_info.get('position')}, Props {p_info.get('num_properties')}, Jail: {p_info.get('in_jail')}\n"
        
        # Recent Game Events
        prompt += "\n--- Recent Game Events (Last 5) ---\n"
        if not game_state.get('game_log_tail', []):
            prompt += "  (No recent events)\n"
        else:
            for log_entry in game_state.get('game_log_tail', [])[-5:]:
                prompt += f"- {log_entry}\n"

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
                prompt += "Review the offer details (usually logged or in game state if fully detailed) and choose to accept, reject, or propose a counter-offer (tool_propose_counter_offer, you can add a 'counter_message').\n"
            
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
                else:
                    prompt += f"You have reached the maximum number of rejections for this negotiation. You must choose to end the negotiation (tool_end_trade_negotiation).\n"
            
            elif current_pending_decision == "jail_options":
                # ... (existing jail options prompt enhancement)
                if decision_context.get("max_rolls_attempted"): 
                     prompt += "You have used all your roll attempts to get out of jail this time. You must now pay, use a card, or end your turn if no other options.\n"
                elif decision_context.get("roll_failed"): 
                     prompt += f"Your last roll to get out of jail ({decision_context.get('last_roll_dice')}) failed. You have {3 - decision_context.get('jail_turns_attempted_this_incarceration',0)} roll attempts left this incarceration.\n"

        prompt += f"Dice roll outcome processed by game logic: {game_state.get('dice_roll_outcome_processed')}\n"
        prompt += "\nAvailable actions for you now are:\n"
        for i, action_name in enumerate(available_actions):
            prompt += f"{i+1}. {action_name}\n"
        
        prompt += "\nINSTRUCTIONS FOR YOUR RESPONSE:\n"
        prompt += "1. First, briefly write your step-by-step thinking process or strategy TO YOURSELF (this part will be logged but not parsed by the game)."
        prompt += "2. After your thoughts, on A NEW LINE, provide your chosen action as a single JSON object."
        prompt += "3. The JSON object MUST have a key 'tool_name' with the exact name of the chosen action from the list above."
        prompt += "4. If the action requires parameters (e.g., property_id, bid_amount, recipient_player_id, offered_money, requested_money, message, counter_message), include a 'parameters' key in the JSON object. The value of 'parameters' should be another JSON object containing these parameters."
        prompt += "5. If an action takes no parameters (e.g., 'tool_roll_dice', 'tool_end_turn'), the 'parameters' key should be an empty JSON object ({})."
        prompt += "Example for 'tool_propose_trade' with a message:"
        prompt += "Thought: I want Baltic Avenue. Maybe Player B will accept this offer if I explain my reasoning.\n"
        prompt += "{\"tool_name\": \"tool_propose_trade\", \"parameters\": {\"recipient_player_id\": 1, \"offered_property_ids\": [1], \"offered_money\": 50, \"requested_property_ids\": [3], \"message\": \"Baltic would complete my set! How about this deal?\"}}\n"
        prompt += "Example for 'tool_propose_counter_offer' with a message:"
        prompt += "Thought: Their offer is okay, but I want a bit more money and will explain why.\n"
        prompt += "{\"tool_name\": \"tool_propose_counter_offer\", \"parameters\": {\"trade_id\": 123, \"offered_money\": 100, \"counter_message\": \"I need a bit more cash for repairs, how about this?\"}}\n"
        prompt += "Example for 'tool_roll_dice':"
        prompt += "Thought: I need to move."
        prompt += "{\"tool_name\": \"tool_roll_dice\", \"parameters\": {}}\n"
        prompt += "Respond ONLY with your thoughts (optional) followed by the JSON object on a new line. Ensure the JSON is valid."

        self.last_prompt = prompt

        # For brevity, assuming this method is correctly implemented and returns system_prompt, messages
        # It's crucial this produces a valid prompt for the LLM.
        # Simplified example:
        system_prompt = (
            "You are an expert Monopoly player. You are playing a game of Monopoly. "
            "Your goal is to bankrupt all other players while avoiding bankruptcy yourself. "
            "Analyze the provided game state and choose the best action from the list of available actions. "
            "You MUST respond with a JSON object containing two keys: \"tool_name\" and \"parameters\". "
            "The \"tool_name\" must be one of the available_actions. "
            "The \"parameters\" must be an object containing the parameters for that tool, or an empty object if no parameters are needed. "
            "Include your thought process and reasoning in a key named \"thoughts\" within the JSON response, before tool_name and parameters."
        )
        
        prompt = f"""Current Game State:
        {json.dumps(game_state, indent=2)}

        Available Actions:
        {json.dumps(available_actions, indent=2)}

        Choose your action based on the rules and your strategy. Format your response as a JSON object with 'thoughts', 'tool_name', and 'parameters' keys."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        return system_prompt, messages # Returning system_prompt for potential logging, though not used by client.chat.completions.create directly

    def _clean_llm_json_str(self, json_str: str) -> str:
        cleaned_str = json_str
        if cleaned_str.startswith("```json"): cleaned_str = cleaned_str[len("```json"):]
        if cleaned_str.endswith("```"): cleaned_str = cleaned_str[:-len("```")]
        cleaned_str = cleaned_str.strip()
        return cleaned_str

    def _extract_json_from_response(self, llm_response_content: str) -> Optional[Dict[str, Any]]:
        agent_name_logging = f"Agent {self.name} (P{self.player_id})"
        # print(f"{agent_name_logging}: Attempting to extract JSON. Raw LLM response content (len: {len(llm_response_content)}):\n--BEGIN LLM RAW--\n{llm_response_content}\n--END LLM RAW--")
        
        self.last_agent_thoughts = ""
        self.last_parsed_action_json_str = ""
        json_action_obj = None

        cleaned_content = self._clean_llm_json_str(llm_response_content)
        # print(f"{agent_name_logging}: Cleaned content for JSON parsing (len: {len(cleaned_content)}):\n--BEGIN CLEANED--\n{cleaned_content}\n--END CLEANED--")

        # Attempt 1: Parse the entire cleaned content as JSON
        try:
            json_action_obj = json.loads(cleaned_content)
            self.last_parsed_action_json_str = cleaned_content
            # print(f"{agent_name_logging}: Successfully parsed entire cleaned content as JSON directly.")
        except json.JSONDecodeError as e_full:
            # print(f"{agent_name_logging}: Failed to parse entire cleaned content directly. Error: {e_full}. Content was: '{cleaned_content[:500]}...'")
            
            # Attempt 2: Try to find the first '{' and last '}' and parse that substring
            try:
                first_brace = cleaned_content.find('{')
                last_brace = cleaned_content.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    potential_json_str = cleaned_content[first_brace : last_brace + 1]
                    print(f"{agent_name_logging}: Fallback Attempt 2: Trying to parse substring from first {{ to last }}: '{potential_json_str[:500]}...'")
                    json_action_obj = json.loads(potential_json_str)
                    self.last_parsed_action_json_str = potential_json_str
                    # If this succeeds, text outside this substring might be thoughts.
                    pre_json_text = cleaned_content[:first_brace].strip()
                    post_json_text = cleaned_content[last_brace+1:].strip()
                    if pre_json_text or post_json_text:
                        self.last_agent_thoughts = f"Pre-JSON: {pre_json_text} | Post-JSON: {post_json_text}".strip(" | ")
                    print(f"{agent_name_logging}: Successfully parsed substring as JSON.")
                else:
                    print(f"{agent_name_logging}: Fallback Attempt 2: Could not find valid {{...}} block.")
                    self.last_agent_thoughts = llm_response_content # Treat all as thoughts if no JSON found
            except json.JSONDecodeError as e_substring:
                print(f"{agent_name_logging}: Fallback Attempt 2: Failed to parse substring as JSON. Error: {e_substring}. Substring was: '{potential_json_str[:500]}...'")
                self.last_agent_thoughts = llm_response_content # Treat all as thoughts
            except Exception as e_general_fallback:
                print(f"{agent_name_logging}: Unexpected error during fallback JSON extraction: {e_general_fallback}")
                self.last_agent_thoughts = llm_response_content
        except Exception as e_outer:
             print(f"{agent_name_logging}: Unexpected error before or during primary JSON parsing: {e_outer}")
             self.last_agent_thoughts = llm_response_content
        
        if json_action_obj and isinstance(json_action_obj, dict) and 'thoughts' in json_action_obj and isinstance(json_action_obj['thoughts'], str):
            # If thoughts are successfully parsed from within the JSON, prioritize them.
            # Concatenate if there were also pre/post thoughts from substring parsing.
            json_thoughts = json_action_obj['thoughts']
            if self.last_agent_thoughts and self.last_agent_thoughts != llm_response_content:
                self.last_agent_thoughts = f"Pre/Post Text: {self.last_agent_thoughts} | JSON Thoughts: {json_thoughts}"
            else:
                self.last_agent_thoughts = json_thoughts
            # print(f"{agent_name_logging}: Extracted/Combined thoughts: '{self.last_agent_thoughts}'")
        elif json_action_obj and not self.last_agent_thoughts: # JSON parsed but no specific thoughts field or pre/post text
             self.last_agent_thoughts = "JSON action parsed, no separate \"thoughts\" field found or pre/post text."
        elif not json_action_obj and not self.last_agent_thoughts: # Complete failure to parse and no thoughts otherwise
            self.last_agent_thoughts = llm_response_content # Default to full response if nothing else
        
        # print(f"{agent_name_logging}: Final extracted JSON object for action: {json.dumps(json_action_obj) if json_action_obj else 'None'}")
        # print(f"{agent_name_logging}: Final agent thoughts for DB: '{self.last_agent_thoughts[:500]}...'") # Log truncated thoughts
        return json_action_obj

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