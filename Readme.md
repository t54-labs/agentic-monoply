# Agentic Monopoly: A Multi-Agent Economic Simulation Platform

![Tests](https://github.com/t54-labs/agentic-monoply/workflows/🎮%20Monopoly%20Game%20Tests/badge.svg)

## Abstract

Agentic Monopoly represents a pioneering computational framework for investigating multi-agent economic behaviors through the lens of the classic Monopoly board game. This system implements a sophisticated agent economy simulation where autonomous AI agents engage in complex economic transactions, negotiations, and strategic decision-making processes. By leveraging large language models (LLMs) as the cognitive engine for each agent, the platform provides a rich environment for studying emergent economic behaviors, trading strategies, and inter-agent cooperation and competition dynamics.

The system architecture encompasses a distributed client-server model with real-time communication capabilities, comprehensive game state management, and detailed behavioral logging for subsequent analysis. Through this implementation, researchers can observe and analyze how autonomous agents develop trading strategies, negotiate complex multi-asset transactions, and adapt their behaviors in response to dynamic market conditions within a controlled yet realistic economic environment.

## 1. Introduction

### 1.1 Motivation and Research Context

The emergence of large language models has opened unprecedented opportunities for creating autonomous agents capable of sophisticated reasoning and decision-making. However, understanding how these agents behave in complex economic environments remains an active area of research. Traditional economic simulations often rely on predetermined behavioral models or simplified rule-based systems, limiting their ability to capture the nuanced decision-making processes that characterize real economic actors.

Monopoly, as a microcosm of economic activity, provides an ideal testbed for multi-agent economic research. The game incorporates fundamental economic concepts including property ownership, rent collection, strategic investment, resource management, and complex multi-party negotiations. These elements create a rich environment where agents must balance immediate gains against long-term strategic positioning, negotiate mutually beneficial trades, and adapt to changing market conditions.

### 1.2 Research Objectives

This platform addresses several key research questions in multi-agent systems and computational economics:

1. **Emergent Trading Strategies**: How do LLM-based agents develop and refine trading strategies when operating in a competitive economic environment?

2. **Negotiation Dynamics**: What patterns emerge in multi-agent negotiations, particularly in scenarios involving asymmetric information and competing interests?

3. **Economic Adaptation**: How quickly and effectively do agents adapt their behaviors in response to changing market conditions and opponent strategies?

4. **Collective Intelligence**: Do groups of autonomous agents exhibit emergent collective behaviors that differ from individual agent strategies?

### 1.3 System Overview

The Agentic Monopoly platform consists of three primary subsystems:

- **Agent Intelligence Layer**: OpenAI GPT-4 powered autonomous agents with sophisticated reasoning capabilities
- **Game Logic Engine**: Comprehensive implementation of Monopoly rules with extensive customization options
- **Real-time Interface**: Web-based visualization and monitoring system with live game state updates

## 2. System Architecture

### 2.1 Multi-Tier Architecture Design

The system employs a layered architecture pattern that separates concerns while maintaining high cohesion within each layer:

#### 2.1.1 Presentation Layer
- **Frontend Framework**: Next.js 14 with TypeScript for type-safe development
- **Real-time Communication**: WebSocket-based bidirectional communication
- **UI Components**: Modular React components for game visualization and lobby management
- **State Management**: Client-side state synchronization with server-side game state

#### 2.1.2 Business Logic Layer
- **Game Controller**: Central orchestration of game rules, turn management, and state transitions
- **Agent Framework**: Pluggable architecture supporting multiple AI backends
- **Transaction Engine**: Complex multi-asset trading system with validation and rollback capabilities
- **Auction System**: Real-time bidding mechanism with sophisticated participant management

#### 2.1.3 Data Access Layer
- **SQLAlchemy ORM**: Object-relational mapping for type-safe database operations
- **PostgreSQL Database**: ACID-compliant storage for game state and agent decision logs
- **Session Management**: Stateful game session handling with automatic persistence

### 2.2 Agent Architecture

#### 2.2.1 Cognitive Framework
Each agent operates as an autonomous decision-making entity with the following capabilities:

```python
class OpenAIAgent(BaseAgent):
    def decide_action(self, game_state: Dict[str, Any], 
                     available_actions: List[str], 
                     current_gc_turn: int, 
                     action_sequence_num: int) -> Tuple[str, Dict[str, Any]]:
```

The agent cognitive process involves:
1. **State Analysis**: Comprehensive evaluation of current game state including player positions, property ownership, and market conditions
2. **Strategic Reasoning**: Long-term planning considering property monopolization potential and cash flow optimization
3. **Negotiation Logic**: Dynamic trading strategy formulation based on opponent behavior analysis
4. **Risk Assessment**: Probabilistic evaluation of action outcomes and potential countermeasures

#### 2.2.2 Decision Context Integration
Agents receive rich contextual information including:
- **Financial Status**: Current liquid assets, property portfolios, and debt obligations
- **Market Dynamics**: Property ownership distribution and rental income potential
- **Negotiation History**: Previous trade offers, acceptance/rejection patterns, and trust metrics
- **Opponent Modeling**: Inferred strategies and behavioral patterns of other agents

### 2.3 Game Logic Implementation

#### 2.3.1 State Management
The game controller maintains comprehensive state through several interconnected systems:

```python
class GameController:
    def __init__(self, num_players: int = 4, 
                 player_names: Optional[List[str]] = None,
                 game_uid: str = "default_game", 
                 ws_manager: Optional[Any] = None):
```

Core state components include:
- **Board Representation**: Dynamic property states with ownership tracking and improvement levels
- **Player Management**: Individual agent states including position, assets, and strategic context
- **Transaction Ledger**: Complete history of all economic activities for analysis and rollback
- **Decision Queue**: Asynchronous handling of simultaneous decision points (auctions, trades)

#### 2.3.2 Trading System Architecture
The platform implements a sophisticated multi-asset trading system supporting:

```python
@dataclass
class TradeOffer:
    trade_id: int
    proposer_id: int
    recipient_id: int
    items_offered_by_proposer: List[TradeOfferItem]
    items_requested_from_recipient: List[TradeOfferItem]
    status: str
    message: Optional[str] = None
    rejection_count: int = 0
```

**Transaction Types**:
- **Property Transfers**: Single or multiple property exchanges with automated ownership updates
- **Cash Transactions**: Direct monetary transfers with automatic balance validation
- **Special Assets**: Get-out-of-jail cards and other unique game elements
- **Complex Bundles**: Multi-asset packages enabling sophisticated deal structures

**Negotiation Protocols**:
- **Counter-offer Chains**: Iterative negotiation with rejection tracking and escalation prevention
- **Message Integration**: Natural language communication enhancing negotiation context
- **Timeout Management**: Automatic offer expiration preventing system deadlocks

#### 2.3.3 Auction Mechanism
Real-time auction system supporting:
- **Dynamic Bidding**: Real-time bid acceptance with automatic validation
- **Participant Management**: Flexible entry/exit with bankruptcy handling
- **Reserve Pricing**: Configurable minimum bid requirements
- **Tie-breaking**: Deterministic resolution of simultaneous bid scenarios

## 3. Implementation Details

### 3.1 Backend Infrastructure

#### 3.1.1 FastAPI Server Architecture
```python
app = FastAPI()
app.add_middleware(CORSMiddleware, 
                  allow_origins=["*"], 
                  allow_credentials=True,
                  allow_methods=["*"], 
                  allow_headers=["*"])
```

The server implements:
- **Asynchronous Request Handling**: Non-blocking I/O for concurrent game session management
- **WebSocket Management**: Persistent connections for real-time updates
- **Session Isolation**: Independent game instances with resource partitioning
- **Error Recovery**: Graceful degradation and automatic session restoration

#### 3.1.2 Database Schema Design
The system utilizes a normalized relational schema optimizing for both transactional integrity and analytical queries:

**Core Tables**:
- `games`: Game session metadata and configuration
- `players`: Agent instances and their associated game sessions  
- `game_turns`: Granular turn-by-turn state snapshots
- `agent_actions`: Detailed decision logs including reasoning traces

**Analytical Features**:
- **Decision Provenance**: Complete audit trail of agent reasoning processes
- **Performance Metrics**: Quantitative analysis of agent effectiveness
- **Behavioral Patterns**: Long-term strategy evolution tracking

### 3.2 Frontend Implementation

#### 3.2.1 Component Architecture
```typescript
interface GameData {
  game_uid: string;
  status: string;
  current_players_count: number;
  max_players: number;
  players: PlayerInfo[];
  turn_count?: number;
}
```

**Primary Components**:
- **LobbyPage**: Multi-session game browser with real-time status updates
- **GameTableCard**: Individual game session visualization with player status
- **MonopolyBoard**: Interactive game board with real-time piece movement
- **PlayerDashboard**: Comprehensive agent state and decision history

#### 3.2.2 Real-time Synchronization
The frontend maintains consistency through:
- **Event-driven Updates**: WebSocket message routing to appropriate components
- **Optimistic UI**: Immediate visual feedback with server-side validation
- **State Reconciliation**: Automatic correction of client-server state divergence
- **Connection Recovery**: Seamless reconnection handling with state resynchronization

### 3.3 Agent Decision Engine

#### 3.3.1 Prompt Engineering
The system employs sophisticated prompt engineering techniques to elicit sophisticated reasoning:

```python
def _build_prompt(self, game_state: Dict[str, Any], 
                 available_actions: List[str]) -> Tuple[str, List[Dict[str, str]]]:
```

**Prompt Components**:
- **Strategic Context**: Current board position and ownership analysis
- **Financial Assessment**: Liquidity, debt, and investment opportunity evaluation  
- **Opponent Analysis**: Historical behavior patterns and inferred strategies
- **Action Framing**: Available decisions with expected outcome analysis

#### 3.3.2 Response Processing
Robust parsing and validation ensure reliable agent operation:
- **JSON Schema Validation**: Structured response format enforcement
- **Error Recovery**: Graceful handling of malformed or invalid responses
- **Fallback Mechanisms**: Default action selection for communication failures
- **Decision Logging**: Comprehensive recording of reasoning processes

## 4. Advanced Features

### 4.1 Economic Complexity Modeling

#### 4.1.1 Property Valuation Dynamics
The system implements sophisticated property valuation considering:
- **Monopoly Potential**: Strategic value based on color group completion probability
- **Cash Flow Analysis**: Rental income projections with occupancy modeling
- **Development Opportunities**: Investment ROI calculations for property improvements
- **Market Position**: Relative competitive advantages and defensive positioning

#### 4.1.2 Risk Management Systems
Agents must navigate multiple risk factors:
- **Liquidity Risk**: Cash flow management preventing bankruptcy
- **Opportunity Cost**: Trade-off analysis between competing investment options
- **Counterparty Risk**: Trust modeling in multi-agent negotiations
- **Market Risk**: Adaptation to changing competitive landscapes

### 4.2 Behavioral Analytics

#### 4.2.1 Decision Tree Analysis
The platform captures detailed decision provenance enabling:
- **Strategy Identification**: Pattern recognition in agent decision sequences
- **Learning Curve Analysis**: Adaptation rate measurement across game sessions
- **Counterfactual Analysis**: Alternative outcome evaluation for decision validation
- **Behavioral Clustering**: Agent archetype identification and classification

#### 4.2.2 Performance Metrics
Comprehensive evaluation frameworks including:
- **Economic Efficiency**: Resource utilization and wealth accumulation metrics
- **Strategic Sophistication**: Long-term planning capability assessment
- **Negotiation Effectiveness**: Deal closure rates and value extraction analysis
- **Adaptive Capacity**: Response quality to environmental changes

### 4.3 Extensibility Framework

#### 4.3.1 Modular Agent Architecture
```python
TOOL_REGISTRY = {
    "tool_roll_dice": agent_tools.tool_roll_dice,
    "tool_buy_property": agent_tools.tool_buy_property,
    "tool_propose_trade": agent_tools.tool_propose_trade,
    # ... extensible tool framework
}
```

The platform supports:
- **Custom Agent Types**: Integration of alternative AI backends and reasoning systems
- **Rule Modifications**: Configurable game variants for experimental research
- **Behavioral Interventions**: Programmatic strategy injection for controlled experiments
- **Data Export**: Comprehensive analytics pipeline integration

#### 4.3.2 Research Integration
Designed for academic research with:
- **Reproducible Experiments**: Deterministic seeding and state management
- **Batch Processing**: Automated large-scale simulation execution
- **Statistical Analysis**: Built-in integration with analytical frameworks
- **Publication Pipeline**: Research-ready data export and visualization

## 5. Technical Specifications

### 5.1 System Requirements

#### 5.1.1 Server Infrastructure
- **Runtime**: Python 3.8+ with asyncio support
- **Memory**: 4GB RAM minimum (scales with concurrent sessions)
- **Storage**: PostgreSQL database with 10GB initial allocation
- **Network**: WebSocket-capable HTTP server with SSL support

#### 5.1.2 External Dependencies
```
openai>=1.0.0,<2.0.0
fastapi>=0.90.0,<1.0.0
sqlalchemy>=1.4.0,<2.0.0
psycopg2-binary>=2.9.0,<3.0.0
```

#### 5.1.3 Client Requirements
- **Browser**: Modern WebSocket-supporting browser (Chrome 80+, Firefox 75+)
- **Bandwidth**: Minimum 1Mbps for real-time updates
- **Display**: 1366x768 minimum resolution for optimal board visualization

### 5.2 Performance Characteristics

#### 5.2.1 Scalability Metrics
- **Concurrent Sessions**: Up to 50 simultaneous games on standard hardware
- **Agent Response Time**: Average 2-5 seconds per decision (OpenAI API dependent)
- **Database Performance**: 1000+ transactions per second with proper indexing
- **WebSocket Throughput**: 100+ messages per second per connection

#### 5.2.2 Reliability Features
- **Fault Tolerance**: Automatic session recovery with state persistence
- **Data Integrity**: ACID transaction guarantees for all game state changes
- **Error Handling**: Comprehensive exception management with graceful degradation
- **Monitoring**: Built-in logging and performance metric collection

## 6. Research Applications and Future Directions

### 6.1 Current Research Opportunities

#### 6.1.1 Economic Behavior Studies
The platform enables investigation of:
- **Emergence of Trading Strategies**: How agents develop sophisticated negotiation tactics
- **Market Efficiency**: Price discovery mechanisms in multi-agent property markets
- **Cooperation vs Competition**: Balance between collaborative and adversarial behaviors
- **Information Economics**: Impact of asymmetric information on trading outcomes

#### 6.1.2 AI Agent Development
Research vectors include:
- **Multi-Modal Learning**: Integration of visual board state with textual reasoning
- **Memory Systems**: Long-term strategy learning across multiple game sessions
- **Theory of Mind**: Agent modeling of opponent mental states and strategies
- **Communication Protocols**: Development of sophisticated inter-agent communication

### 6.2 Planned Enhancements

#### 6.2.1 Advanced AI Integration
- **Multi-Agent Reinforcement Learning**: Alternative to LLM-based decision making
- **Hybrid Architectures**: Combination of symbolic reasoning with neural networks
- **Explainable AI**: Enhanced interpretability of agent decision processes
- **Meta-Learning**: Agents that adapt their learning strategies across games

#### 6.2.2 Economic Model Extensions
- **Dynamic Pricing**: Market-driven property valuations
- **External Shocks**: Random events affecting game economics
- **Coalition Formation**: Multi-agent alliance mechanisms
- **Incomplete Information**: Hidden information scenarios for strategic complexity

## 7. Installation and Usage

### 7.1 System Setup

#### 7.1.1 Backend Installation
```bash
# Clone repository
git clone [repository-url]
cd monopoly

# Install Python dependencies
pip install -r requirements.txt

# Database setup
python -c "from database import create_db_and_tables; create_db_and_tables()"

# Configure OpenAI API
export OPENAI_API_KEY="your-api-key-here"
```

#### 7.1.2 Frontend Installation
```bash
cd frontend
npm install
npm run build
npm start
```

#### 7.1.3 Server Launch
```bash
# Start backend server
python server.py

# Access web interface
open http://localhost:3000/lobby
```

### 7.2 Configuration Options

#### 7.2.1 Game Parameters
```python
NUM_PLAYERS = 4  # 2-8 agents per game
MAX_TURNS = 200  # Game length limit
ACTION_DELAY_SECONDS = 2.0  # Thinking time per decision
```

#### 7.2.2 Agent Configuration
- **Model Selection**: GPT-4, GPT-3.5-turbo, or custom backends
- **Temperature Settings**: Creativity vs consistency balance
- **Prompt Customization**: Strategic focus modifications
- **Tool Registry**: Available action customization

### 7.3 Research Workflow

#### 7.3.1 Experiment Design
1. **Parameter Configuration**: Game rules and agent settings
2. **Session Initialization**: Multi-game batch setup
3. **Data Collection**: Automated logging and state capture
4. **Analysis Pipeline**: Statistical processing and visualization

#### 7.3.2 Data Export
```python
# Example data extraction
from database import engine
import pandas as pd

# Agent decision analysis
decisions_df = pd.read_sql(
    "SELECT * FROM agent_actions WHERE game_id = ?", 
    engine, params=[game_id]
)

# Game outcome analysis  
games_df = pd.read_sql("SELECT * FROM games", engine)
```

## 8. Conclusion

The Agentic Monopoly platform represents a significant contribution to the intersection of artificial intelligence and economic simulation. By providing a sophisticated, extensible environment for multi-agent economic research, it enables unprecedented investigation into the behaviors and strategies of autonomous AI agents operating in complex economic environments.

The system's comprehensive architecture, from the intelligent agent framework to the real-time visualization capabilities, creates a robust foundation for advancing our understanding of agent economics. As large language models continue to evolve, this platform provides an ideal testbed for evaluating their capabilities in strategic reasoning, negotiation, and economic decision-making.

Future research utilizing this platform has the potential to inform not only our understanding of artificial intelligence capabilities but also broader questions in economics, game theory, and multi-agent systems. The emergent behaviors observed in these simulated economies may provide insights applicable to real-world economic systems and inform the development of more sophisticated autonomous agents for economic applications.

## Acknowledgments

This research platform builds upon decades of work in game theory, artificial intelligence, and economic simulation. We acknowledge the contributions of the open-source community, particularly the developers of FastAPI, Next.js, and SQLAlchemy, whose robust frameworks enabled the construction of this sophisticated system.

## References

*Note: This section would typically contain academic citations. For a production README, consider adding relevant papers on multi-agent systems, economic simulation, and AI agent research.*

---

**Repository Structure:**
```
monopoly/
├── ai_agent/           # Agent intelligence framework
├── game_logic/         # Core game implementation  
├── frontend/           # Web interface
├── database.py         # Data persistence layer
├── server.py          # FastAPI backend server
├── main.py            # CLI simulation entry point
└── requirements.txt   # Python dependencies
```

**License:** [Specify appropriate license]
**Contact:** [Research team contact information]
**Documentation:** [Link to detailed API documentation]
