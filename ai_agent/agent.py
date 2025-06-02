import os
from typing import Tuple, Dict, List, Any, Optional
from abc import ABC, abstractmethod
import json # Ensure json is imported
import re   # For potential cleanup of JSON string if needed

from dotenv import load_dotenv

# Conditional import for openai, handle if not installed
try:
    import openai
except ImportError:
    openai = None
    print("OpenAI library not found. Please install it via pip: pip install openai")

class BaseAgent(ABC):
    def __init__(self, player_id: int, name: str):
        self.player_id = player_id
        self.name = name

    @abstractmethod
    def decide_action(self, game_state: Dict[str, Any], available_actions: List[str]) -> Tuple[str, Dict[str, Any]]:
        """
        Decides which action/tool to use based on the game state and available actions.

        Args:
            game_state: A dictionary representing the current state of the game.
            available_actions: A list of strings representing the names of tools the agent can currently use.

        Returns:
            A tuple containing the chosen tool name (str) and a dictionary of its parameters (Dict[str, Any]).
        """
        pass

    def get_player_thought_process(self) -> str:
        """Returns the agent's thought process for the last decision (optional)."""
        return "No detailed thought process recorded."

class OpenAIAgent(BaseAgent):
    def __init__(self, player_id: int, name: str, model_name: str = "gpt-4", api_key: str = None):
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

    def _build_prompt(self, game_state: Dict[str, Any], available_actions: List[str]) -> str:
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

        # Call to Action
        prompt += "\n--- Your Action Required ---\n"
        if game_state.get('current_player_id') != self.player_id:
             prompt += "Warning: It appears it is NOT my turn. I should 'wait'.\n"
        
        prompt += f"Current pending decision: {game_state.get('pending_decision_type', 'None')}\n"
        if game_state.get('pending_decision_context'): prompt += f"Decision context: {json.dumps(game_state.get('pending_decision_context'))}\n"
        prompt += f"Dice roll outcome processed: {game_state.get('dice_roll_outcome_processed')}\n"
        prompt += "\nAvailable actions for you now are:\n"
        for i, action_name in enumerate(available_actions):
            prompt += f"{i+1}. {action_name}\n"
        
        prompt += "\nINSTRUCTIONS FOR YOUR RESPONSE:\n"
        prompt += "1. First, briefly write your step-by-step thinking process or strategy TO YOURSELF (this part will be logged but not parsed by the game)."
        prompt += "2. After your thoughts, on A NEW LINE, provide your chosen action as a single JSON object."
        prompt += "3. The JSON object MUST have a key 'tool_name' with the exact name of the chosen action from the list above."
        prompt += "4. If the action requires parameters (e.g., property_id, bid_amount, recipient_player_id), include a 'parameters' key in the JSON object. The value of 'parameters' should be another JSON object containing these parameters."
        prompt += "5. If an action takes no parameters (e.g., 'tool_roll_dice', 'tool_end_turn'), the 'parameters' key should be an empty JSON object ({})."
        prompt += "Example for 'tool_buy_property' (assuming property_id is 12 based on game state):"
        prompt += "Thought: This property completes my set, I should buy it.\n"
        prompt += "{\"tool_name\": \"tool_buy_property\", \"parameters\": {\"property_id\": 12}}\n"
        prompt += "Example for 'tool_roll_dice':"
        prompt += "Thought: I need to move."
        prompt += "{\"tool_name\": \"tool_roll_dice\", \"parameters\": {}}\n"
        prompt += "Respond ONLY with your thoughts (optional) followed by the JSON object on a new line. Ensure the JSON is valid."

        self.last_prompt = prompt
        return prompt

    def _clean_llm_json_str(self, json_str: str) -> str:
        """Cleans common LLM mistakes from a string that should be JSON."""
        # Remove markdown code block fences if present
        if json_str.startswith("```json"): json_str = json_str[len("```json"):]
        if json_str.endswith("```"): json_str = json_str[:-len("```")]
        json_str = json_str.strip()
        
        # Attempt to fix common issues like trailing commas or unquoted keys (simple cases)
        # This is heuristic. Complex repairs are beyond this scope.
        # For example, remove trailing comma before closing brace/bracket
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        return json_str

    def _extract_json_from_response(self, llm_response_content: str) -> Optional[Dict[str, Any]]:
        self.last_thought_process = ""
        self.last_parsed_action_json_str = ""
        json_action_obj = None

        lines = llm_response_content.strip().split('\n')
        thought_lines = []
        json_candidate_lines = []

        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("{") and stripped_line.endswith("}"):
                json_candidate_lines.append(stripped_line)
            elif json_candidate_lines: # If we started collecting JSON lines and hit a non-JSON line
                thought_lines.append(line) # Assume it might be trailing thoughts or errors
            else:
                thought_lines.append(line) # Assume it's part of the thought process

        if json_candidate_lines:
            # Try to parse the last JSON candidate found, as per prompt instruction
            potential_json_str = self._clean_llm_json_str(json_candidate_lines[-1])
            try:
                json_action_obj = json.loads(potential_json_str)
                self.last_parsed_action_json_str = potential_json_str
                # If successfully parsed the last JSON-like line, assume preceding lines were thoughts.
                # Reconstruct thoughts from lines *not* part of the successfully parsed JSON string line.
                # This is a bit tricky if JSON was multi-line and extracted by regex later.
                # For now, if last line parse works, preceding lines are thoughts.
                self.last_thought_process = "\n".join(thought_lines + json_candidate_lines[:-1]).strip()
            except json.JSONDecodeError:
                self.last_thought_process = llm_response_content # Could not parse, keep all as thoughts
                json_action_obj = None # Ensure it's None
        
        # Fallback: if no line-wise JSON found, try regex for a JSON blob anywhere (more desperate)
        if json_action_obj is None:
            # Regex to find a string that starts with { and ends with }, being as non-greedy as possible for internal {} 
            # and allowing for nested structures.
            # This regex is hard to get perfect for all edge cases of malformed LLM JSON.
            match = re.search(r'(\{\s*\"tool_name\".*\})\s*$', llm_response_content, re.DOTALL | re.MULTILINE)
            if match:
                potential_json_str = self._clean_llm_json_str(match.group(1))
                try:
                    json_action_obj = json.loads(potential_json_str)
                    self.last_parsed_action_json_str = potential_json_str
                    # Attempt to get thoughts before this regex match
                    match_start_index = match.start(1)
                    self.last_thought_process = llm_response_content[:match_start_index].strip()
                except json.JSONDecodeError:
                    json_action_obj = None # Failed again
        
        if json_action_obj is None and not self.last_thought_process: # If no JSON and no thoughts captured yet
             self.last_thought_process = llm_response_content # Treat all of it as thoughts if no JSON

        return json_action_obj

    def decide_action(self, game_state: Dict[str, Any], available_actions: List[str]) -> Tuple[str, Dict[str, Any]]:
        if not available_actions:
            self.last_thought_process = "No actions available, deciding to 'wait'."
            return "wait", {}

        prompt_text = self._build_prompt(game_state, available_actions)
        # For debugging the prompt:
        # print(f"--- PROMPT for {self.name} ---\n{prompt_text}\n-------------------------")
        self.last_thought_process = f"LLM Prompting. Available actions: {', '.join(available_actions)}"
        
        action_name = available_actions[0] # Default fallback
        params = {}

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a highly intelligent and strategic Monopoly AI player. Your goal is to win. Follow the JSON response format precisely."},
                    {"role": "user", "content": prompt_text}
                ],
                temperature=0.5, 
                max_tokens=250 
            )
            self.last_raw_llm_response_content = response.choices[0].message.content.strip()
            # print(f"--- RAW LLM RESPONSE for {self.name} ---\n{self.last_raw_llm_response_content}\n-------------------------")

            parsed_json = self._extract_json_from_response(self.last_raw_llm_response_content)

            if parsed_json and isinstance(parsed_json.get("tool_name"), str):
                potential_action_name = parsed_json["tool_name"]
                if potential_action_name in available_actions:
                    action_name = potential_action_name
                    # Parameters should be a dict, default to empty if not present or not a dict
                    potential_params = parsed_json.get("parameters")
                    if isinstance(potential_params, dict):
                        params = potential_params
                    elif potential_params is not None:
                         self.last_thought_process += f"\n[Warning] LLM 'parameters' was not a dict: {potential_params}. Using empty params."
                    # else: params remains {}
                    self.last_thought_process += f"\nLLM Valid Action Parsed: '{action_name}', Params: {params}."
                else:
                    self.last_thought_process += f"\n[Warning] LLM chose action '{potential_action_name}' which is NOT in available actions: {available_actions}. Falling back to '{action_name}'."
            else:
                self.last_thought_process += f"\n[Warning] LLM response did not contain a valid JSON with 'tool_name'. Raw: '{self.last_raw_llm_response_content}'. Falling back to '{action_name}'."

        except Exception as e:
            self.last_thought_process += f"\n[Error] OpenAI API call or JSON parsing failed: {e}. Raw response: '{self.last_raw_llm_response_content if self.last_raw_llm_response_content else 'N/A'}'. Falling back to '{action_name}'."
        
        # Final validation
        if action_name not in available_actions:
            self.last_thought_process += f"\nCritical Fallback: Derived action '{action_name}' is invalid. Defaulting to first available: {available_actions[0] if available_actions else 'wait'}."
            action_name = available_actions[0] if available_actions else "wait"
            params = {}
            
        self.last_response_text = f"Chosen: {action_name}, Params: {params}. Thought: {self.last_thought_process}"
        return action_name, params

    def get_player_thought_process(self) -> str:
        # Return a more structured thought process including prompt if desired for debugging.
        # return f"Last Prompt:\n{self.last_prompt}\n\nLast Thought Process Log:\n{self.last_thought_process}"
        return self.last_thought_process


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
            action_s1, params_s1 = agent.decide_action(dummy_game_state, available_actions_s1)
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
            action_s2, params_s2 = agent.decide_action(dummy_game_state_s2, available_actions_s2)
            print(f"Chosen action: {action_s2}, Params: {params_s2}")
            # print(f"Thought process:\n{agent.get_player_thought_process()}")


    except ValueError as e:
        print(f"ValueError during test: {e}")
    except ImportError as e:
        print(f"ImportError during test: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during test: {e}") 