# Detailed Report on Monopoly Game Runtime Logic

## Overview

This report provides a detailed description of the core runtime logic of the Monopoly game server, including all key parameters, states, steps, and code implementations.

## Core Architecture

### 1. Server Architecture

* **File**: `server.py`
* **Main Classes**: `ThreadSafeGameInstance`, `ConnectionManager`, `AgentManager`
* **Game Controller**: `GameControllerV2` (located in `game_logic/game_controller_v2.py`)

### 2. Key State Parameters

#### Game Controller State (`GameControllerV2`)

```python
class GameControllerV2:
    # Basic game state
    self.game_uid: str                    # Unique game identifier
    self.turn_count: int                  # Current turn number
    self.current_player_index: int       # Current player index (0–3)
    self.dice: Tuple[int, int]           # Current dice roll result
    self.doubles_streak: int             # Consecutive doubles count
    self.game_over: bool                 # Game over flag
    
    # Decision state
    self.pending_decision_type: Optional[str]     # Pending decision type
    self.pending_decision_context: Dict[str, Any] # Decision context
    self.dice_roll_outcome_processed: bool       # Dice outcome processed flag
    
    # Turn phase
    self.turn_phase: str                 # "pre_roll" | "post_roll"
    
    # Trade state
    self.trade_offers: Dict[int, TradeOffer]     # All trade offers
    self.next_trade_id: int                      # Next trade ID
    
    # Auction state
    self.auction_in_progress: bool               # Is an auction in progress
    self.auction_property_id: Optional[int]     # Property ID under auction
    self.auction_current_bid: int               # Current bid
    self.auction_highest_bidder: Optional[Player] # Highest bidder
```

## Game Flow Detailed Analysis

### 1. Game Initialization (`start_monopoly_game_instance`)

#### Step 1: Create Game Instance

```python
# File: server.py, Line: ~1027
gc = GameControllerV2(
    game_uid=game_uid,
    ws_manager=None,
    game_db_id=game_db_id,
    participants=available_agents,
    treasury_agent_id=treasury_agent_id
)
```

#### Step 2: Start Game

```python
# File: game_logic/game_controller_v2.py, Line: 1077
def start_game(self):
    self.current_player_index = random.randrange(len(self.players))
    self.turn_count = 1
    self.game_over = False
    self.turn_phase = "pre_roll"
    self.dice = (0, 0)
    self.dice_roll_outcome_processed = False
```

### 2. Main Game Loop

#### Loop Structure

```python
# File: server.py, Line: ~1174
while not gc.game_over and loop_turn_count < MAX_TURNS:
    loop_turn_count += 1
    
    # Determine active player
    active_player_id = determine_active_player(gc)
    current_acting_player = gc.players[active_player_id]
    
    # Player action segment
    while player_turn_segment_active and action_this_segment_count < MAX_ACTIONS_PER_SEGMENT:
        # Process async landing effects
        # Get available actions
        # Player decision
        # Execute action
```

#### Key Parameters

* `MAX_TURNS = 500` - Max number of turns
* `MAX_ACTIONS_PER_SEGMENT = 10` - Max actions per segment
* `ACTION_DELAY = 2.0` - Action delay in seconds

### 3. Player Turn Handling

#### Turn Phase Management

```python
# Pre-roll phase: player must roll dice
if self.turn_phase == "pre_roll":
    # Auto roll dice
    dice_roll = self.roll_dice()
    # Handle movement
    # Set turn_phase = "post_roll"
    
# Post-roll phase: player may manage assets
elif self.turn_phase == "post_roll":
    # Build, mortgage, trade, etc.
```

#### Dice Roll Logic

```python
# File: game_logic/game_controller_v2.py, Line: 936
def roll_dice(self) -> Tuple[int, int]:
    self.dice = (random.randint(1, 6), random.randint(1, 6))
    self.dice_roll_outcome_processed = False
    
    if self.is_double_roll():
        self.doubles_streak += 1
        if self.doubles_streak == 3:
            self._handle_go_to_jail_landing(player)
    else:
        self.doubles_streak = 0
```

### 4. Decision Type Handling

#### Main Decision Types

1. `"jail_options"` – Jail choices
2. `"respond_to_trade_offer"` – Respond to trade
3. `"buy_or_auction_property"` – Buy or auction property
4. `"asset_liquidation_for_debt"` – Asset liquidation
5. `"auction_bid"` – Auction bidding
6. `"action_card_draw"` – Action card draw
7. `"handle_received_mortgaged_properties"` – Handle received mortgaged properties

#### Set Decision State

```python
# File: game_logic/game_controller_v2.py, Line: 227
def _set_pending_decision(self, decision_type: str, context: Dict[str, Any], outcome_processed: bool = False):
    self.pending_decision_type = decision_type
    self.pending_decision_context = context
    self.dice_roll_outcome_processed = outcome_processed
```

### 5. Trade System

#### Trade Data Structure

```python
@dataclass
class TradeOffer:
    trade_id: int
    proposer_id: int
    recipient_id: int
    items_offered_by_proposer: List[TradeOfferItem]
    items_requested_from_recipient: List[TradeOfferItem]
    status: str  # "pending_response", "accepted", "rejected", "countered", "withdrawn"
    rejection_count: int
```

#### Trade Process

1. **Propose Trade**: `propose_trade_action()`
2. **Respond to Trade**: `_respond_to_trade_offer_action()`
3. **Execute Trade**: Automatically transfer assets and funds
4. **Notify System**: Telegram pushes trade status

### 6. Asynchronous Processing System

#### Trigger Condition

```python
# File: server.py, Line: ~1300
should_process_normal_async = (
    not gc.dice_roll_outcome_processed and 
    getattr(gc, 'turn_phase', None) == "post_roll" and 
    active_player_id == current_main_turn_player_id and
    not is_trade_negotiation
)
```

#### Processing Tasks

* GO reward handling
* Tile landing effects
* Card draw effects
* Rent payments

### 7. Turn Advancement Logic

#### Check for Turn Advancement

```python
# File: server.py, Line: ~2050
# Check whether to proceed to next turn
call_next_turn_flag = determine_turn_advance(gc)

if call_next_turn_flag:
    previous_turn_number = gc.turn_count
    current_main_turn_player_id = gc.current_player_index
    gc.next_turn()  # Move to next player
```

#### Doubles Bonus Logic

```python
# Check for valid doubles bonus
is_doubles = (gc.dice[0] == gc.dice[1])
valid_doubles_bonus = (
    is_doubles and 
    gc.dice != (0, 0) and 
    not current_acting_player.in_jail and 
    0 < gc.doubles_streak < 3
)
```

### 8. Payment System (TPay Integration)

#### Payment Types

1. **Player to Player**: `_create_tpay_payment_player_to_player()`
2. **Player to System**: `_create_tpay_payment_player_to_system()`
3. **System to Player**: `_create_tpay_payment_system_to_player()`

#### Payment Example

```python
# GO salary
await self._create_tpay_payment_system_to_player(
    recipient=player,
    amount=200.0,
    reason="GO salary"
)

# Rent payment
await self._create_tpay_payment_player_to_player(
    payer=current_player,
    recipient=property_owner,
    amount=rent_amount,
    reason=f"rent for {property_name}"
)
```

### 9. Notification System

#### Telegram Notifications

* Game start/end
* Turn end
* Trade status
* Special events (jail, property purchase, etc.)

#### WebSocket Notifications

* Player status updates
* Board state changes
* Real-time game events

## Key File Structure

### Main Files

1. `server.py` – Server logic and main loop
2. `game_logic/game_controller_v2.py` – Core game logic
3. `game_logic/managers/` – Modular managers

   * `trade_manager.py` – Trade logic
   * `payment_manager.py` – Payment logic
   * `property_manager.py` – Property management
   * `auction_manager.py` – Auction logic
   * `jail_manager.py` – Jail logic
4. `admin/game_event_handler.py` – Event handling and notifications
5. `admin/telegram_notifier.py` – Telegram push

### Configuration Parameters

```python
# server.py configuration
MAX_TURNS = 500
MAX_ACTIONS_PER_SEGMENT = 10  
ACTION_DELAY = 2.0
MAX_TRADE_REJECTIONS = 3

# Game settings
MONOPOLY_BOARD_SIZE = 40
GO_SALARY = 200
JAIL_POSITION = 10
```

## State Sync Mechanism

### Database Sync

* Game state periodically saved to DB
* Player actions recorded in `game_turns_table`
* Trade and financial state tracking

### Frontend Sync

* WebSocket pushes real-time player status
* Dynamic board layout updates
* Instant action feedback

## Error Handling and Recovery

### Exception Handling

* Network recovery
* Payment rollback
* Game state consistency checks

### Logging System

* Detailed game event logs
* Tiered debug output
* Error tracing and reporting

## Performance Optimization

### Concurrent Execution

* Multiple game instances in parallel
* Thread-safe message queue
* Async I/O operations

### Resource Management

* Dynamic agent pool allocation
* Connection pool reuse
* Memory usage optimization

This report covers all core runtime logic of the Monopoly game. The system adopts a modular design with clearly defined responsibilities, ensuring the stability and maintainability of the game logic.
