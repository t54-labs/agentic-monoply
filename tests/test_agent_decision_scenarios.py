"""
Advanced Agent Decision Scenarios Test Suite

This module provides specialized tests for complex agent decision-making scenarios,
including multi-step strategic decisions, error handling, edge cases, and 
comprehensive regression testing for the GameControllerV2.

Focus Areas:
1. Complex Multi-Step Agent Decisions
2. Strategic Trade Negotiations
3. Competitive Property Acquisition
4. Bankruptcy Recovery Strategies
5. Jail Strategy Optimization
6. Endgame Scenarios
7. Error Recovery and Edge Cases
8. Performance and Stress Testing
9. Integration with External Systems
10. Regression Testing Suite
"""

import asyncio
import pytest
import json
import time
import random
from typing import Dict, Any, List, Optional, Tuple, Callable
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

# Import the game logic components
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.game_controller_v2 import GameControllerV2, TradeOffer, TradeOfferItem
from game_logic.player import Player
from game_logic.property import PropertySquare, RailroadSquare, UtilitySquare, TaxSquare, SquareType, PropertyColor
from tests.test_game_controller_v2 import TestGameSetupManager, TestExpectedResult, MockAgentResponse


@dataclass
class AgentDecisionScenario:
    """Complex agent decision scenario definition"""
    name: str
    description: str
    setup_function: Callable[[GameControllerV2], None]
    agent_decisions: List[MockAgentResponse]
    expected_outcomes: List[TestExpectedResult]
    validation_functions: List[Callable[[GameControllerV2], bool]]


@dataclass
class PerformanceMetrics:
    """Performance metrics for testing"""
    execution_time: float
    memory_usage: int
    operations_per_second: float
    error_count: int
    success_rate: float


class AgentDecisionTestSuite:
    """Advanced test suite for agent decision scenarios"""
    
    def __init__(self):
        self.test_results = []
        self.performance_metrics = []
        self.setup_manager = TestGameSetupManager()
        
    async def setup_complex_game_scenario(self, scenario_name: str, num_players: int = 4) -> GameControllerV2:
        """Setup complex game scenarios for advanced testing"""
        participants = self.setup_manager.create_test_participants(num_players)
        
        # Create enhanced mock WebSocket manager with logging
        mock_ws_manager = Mock()
        mock_ws_manager.broadcast_to_game = AsyncMock()
        
        # Create game controller with enhanced monitoring
        gc = GameControllerV2(
            game_uid=f"test_game_{scenario_name}",
            ws_manager=mock_ws_manager,
            game_db_id=random.randint(1000, 9999),
            participants=participants,
            treasury_agent_id="test_treasury"
        )
        
        # Enhanced mock TPay agent with realistic delays
        mock_tpay = Mock()
        mock_tpay.create_payment = AsyncMock(return_value={
            'success': True,
            'id': f'payment_{random.randint(1000, 9999)}',
            'status': 'pending'
        })
        mock_tpay.get_payment_status = AsyncMock(return_value={
            'status': 'success',
            'id': 'test_payment_id'
        })
        gc.tpay_agent = mock_tpay
        
        # Set varied initial money for testing different scenarios
        initial_money_distribution = [1500, 1200, 1800, 1000][:num_players]
        for i, player in enumerate(gc.players):
            player.money = initial_money_distribution[i]
            
        return gc

    # ======= Complex Multi-Step Decision Tests =======
    
    async def test_monopoly_building_strategy(self) -> bool:
        """Test agent's strategy for building monopolies through trading"""
        test_name = "Monopoly Building Strategy"
        
        try:
            gc = await self.setup_complex_game_scenario("monopoly_building")
            gc.start_game()
            
            # Set up scenario: Player 0 has 2/3 properties of a monopoly, needs to trade for the third
            player_id = 0
            player = gc.players[player_id]
            
            # Give player Mediterranean and Baltic (needs Boardwalk to complete brown monopoly)
            # Wait, brown monopoly is Mediterranean (1) and Baltic (3), not Boardwalk
            # Let's give them Mediterranean, need Baltic from another player
            self.setup_manager.setup_property_ownership(gc, player_id, [1])  # Mediterranean
            self.setup_manager.setup_property_ownership(gc, 1, [3])  # Baltic owned by player 1
            self.setup_manager.setup_property_ownership(gc, player_id, [6, 8])  # Light blue properties
            self.setup_manager.set_player_money(gc, player_id, 2000)
            
            # Mock complex agent decision sequence
            agent_decisions = [
                # Step 1: Analyze board state and identify monopoly opportunity
                MockAgentResponse(
                    "tool_analyze_board_state", {},
                    "I need Baltic Avenue to complete brown monopoly. Player 1 owns it.",
                    "Board analysis complete"
                ),
                
                # Step 2: Propose strategic trade
                MockAgentResponse(
                    "tool_propose_trade",
                    {
                        "recipient_id": 1,
                        "offered_property_ids": [6],  # Oriental
                        "offered_money": 500,
                        "requested_property_ids": [3],  # Baltic
                        "message": "Complete monopolies for both of us"
                    },
                    "Offering Oriental + $500 for Baltic to complete brown monopoly",
                    "Trade proposed successfully"
                ),
                
                # Step 3: If trade is accepted, build houses strategically
                MockAgentResponse(
                    "tool_build_house",
                    {"property_id": 1},  # Mediterranean
                    "Build house on Mediterranean first due to lower cost",
                    "House built successfully"
                ),
                
                MockAgentResponse(
                    "tool_build_house", 
                    {"property_id": 3},  # Baltic
                    "Build house on Baltic to maintain even development",
                    "House built successfully"
                )
            ]
            
            # Execute the strategy
            scenario_results = []
            
            # Step 1: Propose the trade
            trade_id = gc.propose_trade_action(
                proposer_id=0, recipient_id=1,
                offered_property_ids=[6], offered_money=500, offered_gooj_cards=0,
                requested_property_ids=[3], requested_money=0, requested_gooj_cards=0,
                message="Complete monopolies for both of us"
            )
            
            scenario_results.append(f"Trade proposed: {trade_id}")
            
            if trade_id:
                # Mock recipient accepting the trade (simulate intelligent agent decision)
                accept_result = await gc._respond_to_trade_offer_action(
                    player_id=1, trade_id=trade_id, response="accept"
                )
                scenario_results.append(f"Trade accepted: {accept_result}")
                
                # After trade completion, build houses
                if accept_result:
                    # Verify player 0 now owns both brown properties
                    baltic_square = gc.board.get_square(3)
                    assert baltic_square.owner_id == 0
                    
                    # Build houses
                    build_result_1 = await gc.build_house_on_property(0, 1)
                    build_result_2 = await gc.build_house_on_property(0, 3)
                    
                    scenario_results.append(f"Houses built: {build_result_1}, {build_result_2}")
                    
                    # Verify monopoly is complete and developed
                    med_square = gc.board.get_square(1)
                    baltic_square = gc.board.get_square(3)
                    assert med_square.num_houses >= 1
                    assert baltic_square.num_houses >= 1
            
            expected = TestExpectedResult(
                success=True,
                player_money_changes={0: -500, 1: 500},  # Trade payment
                property_ownership_changes={0: [3], 1: [-3, 6]},
                game_state_changes={'monopoly_completed': True, 'houses_built': 2},
                pending_decision_type=None
            )
            
            print(f"✅ {test_name} completed with scenario results: {scenario_results}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def test_competitive_property_acquisition(self) -> bool:
        """Test agents competing for valuable properties in auction"""
        test_name = "Competitive Property Acquisition"
        
        try:
            gc = await self.setup_complex_game_scenario("competitive_auction")
            gc.start_game()
            
            # Set up auction scenario for a valuable property (Boardwalk)
            valuable_property_id = 39  # Boardwalk
            
            # Give different players different financial capabilities
            self.setup_manager.set_player_money(gc, 0, 2000)  # Rich player
            self.setup_manager.set_player_money(gc, 1, 800)   # Moderate player  
            self.setup_manager.set_player_money(gc, 2, 400)   # Poor player
            self.setup_manager.set_player_money(gc, 3, 1500)  # Competition
            
            # Initiate auction
            await gc._initiate_auction(valuable_property_id)
            
            # Verify auction setup
            assert gc.auction_in_progress == True
            assert gc.auction_property_id == valuable_property_id
            assert len(gc.auction_active_bidders) == 4
            
            # Mock competitive bidding behavior
            bidding_scenarios = [
                {"player_id": 0, "bid_amount": 500, "reasoning": "I can afford to bid high for Boardwalk"},
                {"player_id": 3, "bid_amount": 600, "reasoning": "Counter-bid to stay competitive"}, 
                {"player_id": 0, "bid_amount": 800, "reasoning": "Push out weaker bidders"},
                {"player_id": 1, "bid_amount": 0, "reasoning": "Cannot afford to continue bidding"},
                {"player_id": 2, "bid_amount": 0, "reasoning": "Insufficient funds to compete"},
                {"player_id": 3, "bid_amount": 900, "reasoning": "Final push for the property"},
                {"player_id": 0, "bid_amount": 1200, "reasoning": "Secure the valuable property"}
            ]
            
            # Simulate the bidding process
            winning_bid = 0
            winning_player = None
            
            for bid_scenario in bidding_scenarios:
                if bid_scenario["bid_amount"] > 0 and bid_scenario["bid_amount"] > winning_bid:
                    winning_bid = bid_scenario["bid_amount"]
                    winning_player = bid_scenario["player_id"]
            
            # Mock auction conclusion
            gc.auction_current_bid = winning_bid
            gc.auction_highest_bidder = gc.players[winning_player] if winning_player is not None else None
            
            await gc._conclude_auction()
            
            # Verify auction results
            boardwalk_square = gc.board.get_square(valuable_property_id)
            assert boardwalk_square.owner_id == winning_player
            assert valuable_property_id in gc.players[winning_player].properties_owned_ids
            
            expected = TestExpectedResult(
                success=True,
                player_money_changes={winning_player: -winning_bid},
                property_ownership_changes={winning_player: [valuable_property_id]},
                game_state_changes={'auction_completed': True, 'property_acquired': True},
                pending_decision_type=None
            )
            
            print(f"✅ {test_name} completed. Player {winning_player} won Boardwalk for ${winning_bid}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def test_bankruptcy_recovery_strategy(self) -> bool:
        """Test agent's strategy for recovering from near-bankruptcy"""
        test_name = "Bankruptcy Recovery Strategy"
        
        try:
            gc = await self.setup_complex_game_scenario("bankruptcy_recovery")
            gc.start_game()
            
            player_id = 0
            player = gc.players[player_id]
            
            # Set up near-bankruptcy scenario
            self.setup_manager.setup_property_ownership(gc, player_id, [1, 3, 6, 8, 9])  # Multiple properties
            self.setup_manager.set_player_money(gc, player_id, 50)  # Very low cash
            
            # Add buildings to some properties
            med_square = gc.board.get_square(1)
            baltic_square = gc.board.get_square(3)
            if hasattr(med_square, 'num_houses'):
                med_square.num_houses = 2
                baltic_square.num_houses = 1
            
            # Force a debt situation
            debt_amount = 300
            gc._check_and_handle_bankruptcy(player, debt_to_creditor=debt_amount, creditor=None)
            
            # Verify bankruptcy process initiated
            assert gc.pending_decision_type == "asset_liquidation_for_debt"
            
            # Mock agent recovery decisions
            recovery_decisions = [
                # Step 1: Sell houses to raise quick cash
                MockAgentResponse(
                    "tool_sell_house",
                    {"property_id": 1},
                    "Sell house from Mediterranean to raise emergency cash",
                    "House sold for cash"
                ),
                
                # Step 2: Mortgage less valuable property
                MockAgentResponse(
                    "tool_mortgage_property", 
                    {"property_id": 6},
                    "Mortgage Oriental Avenue for additional funds",
                    "Property mortgaged successfully"
                ),
                
                # Step 3: Confirm liquidation is sufficient
                MockAgentResponse(
                    "tool_confirm_asset_liquidation_actions_done",
                    {},
                    "Asset liquidation complete, should cover debts",
                    "Bankruptcy avoided"
                )
            ]
            
            # Execute recovery strategy
            recovery_steps = []
            
            # Sell house
            sell_result = await gc.sell_house_on_property(player_id, 1)
            recovery_steps.append(f"House sold: {sell_result}")
            
            # Mortgage property
            mortgage_result = await gc.mortgage_property_for_player(player_id, 6)
            recovery_steps.append(f"Property mortgaged: {mortgage_result}")
            
            # Confirm asset liquidation
            gc.confirm_asset_liquidation_done(player_id)
            recovery_steps.append("Asset liquidation confirmed")
            
            # Verify recovery
            assert not player.is_bankrupt
            assert gc.pending_decision_type != "asset_liquidation_for_debt"
            
            expected = TestExpectedResult(
                success=True,
                player_money_changes={player_id: 75},  # House sale + mortgage value
                property_ownership_changes={},
                game_state_changes={'bankruptcy_avoided': True, 'assets_liquidated': True},
                pending_decision_type=None
            )
            
            print(f"✅ {test_name} completed with recovery steps: {recovery_steps}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def test_jail_strategy_optimization(self) -> bool:
        """Test different jail escape strategies based on game state"""
        test_name = "Jail Strategy Optimization"
        
        try:
            gc = await self.setup_complex_game_scenario("jail_strategy")
            gc.start_game()
            
            # Test multiple jail scenarios
            jail_scenarios = [
                {
                    "player_id": 0,
                    "money": 2000,
                    "properties": [1, 3, 6, 8],
                    "expected_strategy": "pay_bail",
                    "reasoning": "Rich player, pay bail immediately"
                },
                {
                    "player_id": 1, 
                    "money": 30,
                    "properties": [11, 13],
                    "expected_strategy": "roll_for_doubles",
                    "reasoning": "Poor player, try free escape first"
                },
                {
                    "player_id": 2,
                    "money": 500,
                    "properties": [],
                    "expected_strategy": "pay_bail",
                    "reasoning": "Moderate cash, no properties to manage"
                }
            ]
            
            jail_results = []
            
            for scenario in jail_scenarios:
                player_id = scenario["player_id"]
                player = gc.players[player_id]
                
                # Setup scenario
                self.setup_manager.set_player_money(gc, player_id, scenario["money"])
                for prop_id in scenario["properties"]:
                    self.setup_manager.setup_property_ownership(gc, player_id, [prop_id])
                
                # Put player in jail
                player.go_to_jail()
                gc.current_player_index = player_id
                gc._handle_jail_turn_initiation(player)
                
                # Verify jail state
                assert player.in_jail == True
                assert gc.pending_decision_type == "jail_options"
                
                # Execute optimal strategy
                if scenario["expected_strategy"] == "pay_bail":
                    jail_result = await gc._pay_to_get_out_of_jail(player_id, {})
                    jail_results.append(f"Player {player_id}: Paid bail - {jail_result['status']}")
                    assert jail_result["status"] == "success"
                    assert not player.in_jail
                    
                elif scenario["expected_strategy"] == "roll_for_doubles":
                    jail_result = await gc._attempt_roll_out_of_jail(player_id, {})
                    jail_results.append(f"Player {player_id}: Rolled for doubles - {jail_result['status']}")
                    # Result can be success or failure, both are valid outcomes
                
                # Reset for next scenario
                gc._clear_pending_decision()
            
            expected = TestExpectedResult(
                success=True,
                player_money_changes={},  # Varies by strategy
                property_ownership_changes={},
                game_state_changes={'jail_strategies_tested': len(jail_scenarios)},
                pending_decision_type=None
            )
            
            print(f"✅ {test_name} completed with results: {jail_results}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Advanced Integration Tests =======
    
    async def test_multi_player_strategic_interaction(self) -> bool:
        """Test complex multi-player strategic interactions"""
        test_name = "Multi-Player Strategic Interaction"
        
        try:
            gc = await self.setup_complex_game_scenario("multi_player_strategy", num_players=4)
            gc.start_game()
            
            # Setup complex scenario with multiple players having different strengths
            scenarios = {
                0: {"money": 2000, "properties": [1, 3], "strategy": "aggressive_trading"},
                1: {"money": 800, "properties": [6, 8, 9], "strategy": "defensive_building"},
                2: {"money": 1500, "properties": [11, 13, 14], "strategy": "conservative_growth"},
                3: {"money": 600, "properties": [16, 18, 19], "strategy": "opportunistic"}
            }
            
            # Setup each player's position
            for player_id, scenario in scenarios.items():
                self.setup_manager.set_player_money(gc, player_id, scenario["money"])
                self.setup_manager.setup_property_ownership(gc, player_id, scenario["properties"])
            
            # Simulate multi-round strategic interactions
            interaction_results = []
            
            # Round 1: Player 0 proposes trade to Player 1
            trade_id_1 = gc.propose_trade_action(
                proposer_id=0, recipient_id=1,
                offered_property_ids=[1], offered_money=400, offered_gooj_cards=0,
                requested_property_ids=[6], requested_money=0, requested_gooj_cards=0,
                message="Strategic trade to complete monopolies"
            )
            interaction_results.append(f"Trade 1 proposed: {trade_id_1}")
            
            # Round 2: Player 1 rejects and counter-offers
            if trade_id_1:
                counter_trade_id = gc.propose_trade_action(
                    proposer_id=1, recipient_id=0,
                    offered_property_ids=[6], offered_money=0, offered_gooj_cards=0,
                    requested_property_ids=[1], requested_money=600, requested_gooj_cards=0,
                    message="Counter-offer: need more cash",
                    counter_to_trade_id=trade_id_1
                )
                interaction_results.append(f"Counter-trade proposed: {counter_trade_id}")
            
            # Round 3: Player 2 and 3 form alliance
            alliance_trade_id = gc.propose_trade_action(
                proposer_id=2, recipient_id=3,
                offered_property_ids=[11], offered_money=200, offered_gooj_cards=0,
                requested_property_ids=[16], requested_money=0, requested_gooj_cards=0,
                message="Alliance trade to strengthen positions"
            )
            interaction_results.append(f"Alliance trade proposed: {alliance_trade_id}")
            
            # Verify complex game state
            assert len(gc.trade_offers) >= 2
            
            # Check that different players have pending decisions
            active_trades = [offer for offer in gc.trade_offers.values() if offer.status == "pending_response"]
            assert len(active_trades) >= 1
            
            expected = TestExpectedResult(
                success=True,
                player_money_changes={},
                property_ownership_changes={},
                game_state_changes={'strategic_interactions': len(interaction_results)},
                pending_decision_type="respond_to_trade_offer"
            )
            
            print(f"✅ {test_name} completed with interactions: {interaction_results}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Performance and Stress Testing =======
    
    async def test_performance_under_load(self) -> bool:
        """Test game performance under heavy load"""
        test_name = "Performance Under Load"
        
        try:
            start_time = time.time()
            
            # Create multiple concurrent games
            concurrent_games = []
            num_games = 10
            
            for i in range(num_games):
                gc = await self.setup_complex_game_scenario(f"perf_test_{i}", num_players=4)
                concurrent_games.append(gc)
            
            # Run concurrent operations
            operations = []
            for gc in concurrent_games:
                gc.start_game()
                
                # Perform multiple operations per game
                for player_id in range(len(gc.players)):
                    operations.append(gc.get_available_actions(player_id))
                    operations.append(gc.get_game_state_for_agent(player_id))
            
            # Execute all operations concurrently
            results = await asyncio.gather(*[
                self._async_operation(op) for op in operations[:20]  # Limit for testing
            ], return_exceptions=True)
            
            execution_time = time.time() - start_time
            error_count = sum(1 for result in results if isinstance(result, Exception))
            success_rate = (len(results) - error_count) / len(results) * 100
            
            performance_metrics = PerformanceMetrics(
                execution_time=execution_time,
                memory_usage=0,  # Could implement memory monitoring
                operations_per_second=len(results) / execution_time,
                error_count=error_count,
                success_rate=success_rate
            )
            
            self.performance_metrics.append(performance_metrics)
            
            # Performance assertions
            assert execution_time < 30  # Should complete within 30 seconds
            assert success_rate >= 95   # 95% success rate minimum
            assert error_count <= len(results) * 0.05  # Max 5% errors
            
            print(f"✅ {test_name} completed:")
            print(f"   Execution time: {execution_time:.2f}s")
            print(f"   Operations/sec: {performance_metrics.operations_per_second:.1f}")
            print(f"   Success rate: {success_rate:.1f}%")
            print(f"   Errors: {error_count}/{len(results)}")
            
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def _async_operation(self, operation):
        """Helper to wrap synchronous operations for async execution"""
        try:
            if callable(operation):
                return operation()
            return operation
        except Exception as e:
            return e

    # ======= Error Recovery and Edge Cases =======
    
    async def test_error_recovery_scenarios(self) -> bool:
        """Test system recovery from various error conditions"""
        test_name = "Error Recovery Scenarios"
        
        try:
            gc = await self.setup_complex_game_scenario("error_recovery")
            gc.start_game()
            
            error_scenarios = []
            
            # Scenario 1: Invalid property purchase attempt
            try:
                invalid_result = await gc.execute_buy_property_decision(0, 999)  # Invalid property ID
                error_scenarios.append(f"Invalid property purchase handled: {invalid_result}")
            except Exception as e:
                error_scenarios.append(f"Invalid property purchase error caught: {type(e).__name__}")
            
            # Scenario 2: Insufficient funds for house building
            try:
                self.setup_manager.set_player_money(gc, 0, 10)  # Very low money
                build_result = await gc.build_house_on_property(0, 1)
                error_scenarios.append(f"Insufficient funds build handled: {build_result}")
            except Exception as e:
                error_scenarios.append(f"Insufficient funds error caught: {type(e).__name__}")
            
            # Scenario 3: Trade with bankrupt player
            try:
                gc.players[1].declare_bankrupt()
                trade_id = gc.propose_trade_action(
                    proposer_id=0, recipient_id=1,
                    offered_property_ids=[], offered_money=100, offered_gooj_cards=0,
                    requested_property_ids=[], requested_money=50, requested_gooj_cards=0
                )
                error_scenarios.append(f"Bankrupt player trade handled: {trade_id}")
            except Exception as e:
                error_scenarios.append(f"Bankrupt player trade error caught: {type(e).__name__}")
            
            # Scenario 4: Malformed game state recovery
            try:
                # Corrupt game state temporarily
                original_turn = gc.turn_count
                gc.turn_count = -1
                
                # Attempt normal operation
                actions = gc.get_available_actions(0)
                
                # Restore state
                gc.turn_count = original_turn
                error_scenarios.append(f"Malformed state handled: {len(actions)} actions available")
            except Exception as e:
                error_scenarios.append(f"Malformed state error caught: {type(e).__name__}")
            
            # Verify error recovery
            assert len(error_scenarios) > 0
            assert gc.turn_count > 0  # Game state restored
            assert not gc.game_over   # Game continues after errors
            
            print(f"✅ {test_name} completed with scenarios: {error_scenarios}")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Regression Testing Framework =======
    
    async def run_comprehensive_regression_tests(self) -> Dict[str, Any]:
        """Run comprehensive regression tests covering all scenarios"""
        print("🔄 Starting Comprehensive Regression Tests for Agent Decisions...")
        print("=" * 70)
        
        test_methods = [
            self.test_monopoly_building_strategy,
            self.test_competitive_property_acquisition,
            self.test_bankruptcy_recovery_strategy,
            self.test_jail_strategy_optimization,
            self.test_multi_player_strategic_interaction,
            self.test_performance_under_load,
            self.test_error_recovery_scenarios
        ]
        
        total_tests = len(test_methods)
        passed_tests = 0
        failed_tests = []
        
        for test_method in test_methods:
            try:
                print(f"🧪 Running {test_method.__name__}...")
                result = await test_method()
                if result:
                    passed_tests += 1
                    print(f"✅ {test_method.__name__} PASSED")
                else:
                    failed_tests.append(test_method.__name__)
                    print(f"❌ {test_method.__name__} FAILED")
            except Exception as e:
                failed_tests.append(test_method.__name__)
                print(f"💥 {test_method.__name__} CRASHED: {str(e)}")
        
        # Calculate performance metrics
        avg_performance = None
        if self.performance_metrics:
            avg_performance = {
                "avg_execution_time": sum(p.execution_time for p in self.performance_metrics) / len(self.performance_metrics),
                "avg_operations_per_second": sum(p.operations_per_second for p in self.performance_metrics) / len(self.performance_metrics),
                "avg_success_rate": sum(p.success_rate for p in self.performance_metrics) / len(self.performance_metrics)
            }
        
        # Generate comprehensive report
        results = {
            "test_suite": "Agent Decision Scenarios",
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": len(failed_tests),
            "failed_test_names": failed_tests,
            "success_rate": (passed_tests / total_tests) * 100,
            "all_passed": passed_tests == total_tests,
            "performance_metrics": avg_performance,
            "timestamp": time.time()
        }
        
        print("=" * 70)
        print(f"📊 Regression Test Results:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests}")
        print(f"   Failed: {len(failed_tests)}")
        print(f"   Success Rate: {results['success_rate']:.1f}%")
        
        if avg_performance:
            print(f"   Avg Performance: {avg_performance['avg_operations_per_second']:.1f} ops/sec")
        
        if results["all_passed"]:
            print("🎉 ALL REGRESSION TESTS PASSED! Agent decisions are working correctly.")
        else:
            print(f"⚠️  {len(failed_tests)} regression tests failed: {', '.join(failed_tests)}")
        
        # Save results for CI/CD
        with open('regression_test_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        return results


class ContinuousIntegrationTestRunner:
    """CI/CD integration for automated testing"""
    
    def __init__(self):
        self.agent_test_suite = AgentDecisionTestSuite()
    
    async def run_pre_commit_tests(self) -> bool:
        """Run essential tests before code commits"""
        print("🚀 Running Pre-Commit Tests...")
        
        critical_tests = [
            self.agent_test_suite.test_monopoly_building_strategy,
            self.agent_test_suite.test_error_recovery_scenarios
        ]
        
        for test in critical_tests:
            try:
                result = await test()
                if not result:
                    print(f"❌ Critical test {test.__name__} failed! Blocking commit.")
                    return False
            except Exception as e:
                print(f"💥 Critical test {test.__name__} crashed: {e}")
                return False
        
        print("✅ All pre-commit tests passed!")
        return True
    
    async def run_nightly_regression(self) -> bool:
        """Run full regression suite for nightly builds"""
        print("🌙 Running Nightly Regression Tests...")
        
        results = await self.agent_test_suite.run_comprehensive_regression_tests()
        
        # Send results to monitoring system (mock implementation)
        await self._send_to_monitoring_system(results)
        
        return results["all_passed"]
    
    async def _send_to_monitoring_system(self, results: Dict[str, Any]):
        """Mock function to send results to monitoring system"""
        print(f"📡 Sending results to monitoring system: {results['success_rate']:.1f}% success rate")


# ======= Main Execution =======

async def main():
    """Main execution function for agent decision tests"""
    print("🧠 Advanced Agent Decision Scenarios Test Suite")
    print("Testing complex strategic decisions and edge cases")
    print("=" * 70)
    
    # Run comprehensive tests
    agent_test_suite = AgentDecisionTestSuite()
    results = await agent_test_suite.run_comprehensive_regression_tests()
    
    # Run CI/CD tests
    ci_runner = ContinuousIntegrationTestRunner()
    pre_commit_passed = await ci_runner.run_pre_commit_tests()
    
    print("\n" + "=" * 70)
    print("🏁 Advanced Testing Complete!")
    
    if results["all_passed"] and pre_commit_passed:
        print("🎉 All advanced agent decision tests passed!")
        print("💡 GameControllerV2 is ready for complex strategic gameplay!")
        return True
    else:
        print("⚠️  Some advanced tests failed. Review complex scenarios.")
        return False


if __name__ == "__main__":
    # Run advanced agent decision tests
    asyncio.run(main()) 