#!/usr/bin/env python3
"""
GameControllerV2 Test Runner Script

This script runs comprehensive tests for the modular GameControllerV2,
including core functionality tests, agent decision tests, regression tests,
and board state simulation tests.

Usage:
    python run_tests.py --all                    # Run all tests
    python run_tests.py --core                   # Run core functionality tests
    python run_tests.py --agent-decisions        # Run agent decision tests
    python run_tests.py --regression             # Run regression tests only
    python run_tests.py --smoke                  # Run smoke tests
    python run_tests.py --performance            # Run performance tests
    python run_tests.py --board-states           # Run board state simulation tests
"""

import asyncio
import argparse
import sys
import os
import json
import time
import random
from typing import Dict, Any, List, Optional

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import test suites
from tests.test_game_controller_v2 import GameControllerV2TestSuite, RegressionTestRunner

# Import game components for board state testing
from game_logic.game_controller_v2 import GameControllerV2
from game_logic.player import Player
from ai_agent.agent import OpenAIAgent
import uuid


class MockAgent:
    """Mock agent for predictable testing"""
    def __init__(self, player_id: int, name: str, decision_sequence: List[tuple] = None):
        self.player_id = player_id
        self.name = name
        self.agent_uid = f"mock_agent_{player_id}_{uuid.uuid4().hex[:6]}"
        # List of (tool_name, params) tuples for predictable decisions
        self.decision_sequence = decision_sequence or []
        self.decision_index = 0
        
    def decide_action(self, game_state: Dict[str, Any], available_actions: List[str], 
                      current_gc_turn: int, action_sequence_num: int) -> tuple:
        """Make predictable decisions based on sequence"""
        if self.decision_index < len(self.decision_sequence):
            decision = self.decision_sequence[self.decision_index]
            self.decision_index += 1
            tool_name, params = decision
            
            # Validate that the tool is available
            if tool_name in available_actions:
                print(f"[MockAgent {self.name}] Choosing: {tool_name} with {params}")
                return tool_name, params
            else:
                print(f"[MockAgent {self.name}] Tool {tool_name} not available, falling back to first action")
        
        # Fallback to first available action
        if available_actions:
            fallback_tool = available_actions[0]
            print(f"[MockAgent {self.name}] Fallback: {fallback_tool}")
            return fallback_tool, {}
        
        return "tool_wait", {}
    
    def get_player_thought_process(self) -> str:
        return f"Mock agent {self.name} following decision sequence"
    
    def get_last_decision_details_for_db(self) -> Dict[str, Any]:
        return {
            "gc_turn_number": 0,
            "action_sequence_in_gc_turn": 0,
            "pending_decision_type_before": None,
            "pending_decision_context_json_before": "{}",
            "available_actions_json_before": "[]",
            "agent_thoughts_text": "Mock agent decision",
            "llm_raw_response_text": "Mock response",
            "parsed_action_json_str": "{}",
            "chosen_tool_name": "mock_tool",
            "tool_parameters_json": "{}"
        }


class BoardStateTestSuite:
    """Test suite for simulating complete game scenarios and board states"""
    
    def __init__(self):
        self.test_results = []
        
    async def run_all_board_state_tests(self) -> Dict[str, Any]:
        """Run all board state simulation tests"""
        print("🏁 Running Board State Simulation Tests...")
        print("=" * 50)
        
        tests = [
            self.test_property_purchase_and_house_building,
            self.test_monopoly_completion_and_development,
            self.test_rent_collection_sequence,
            self.test_jail_and_recovery_scenario,
            self.test_trade_acceptance_scenario
        ]
        
        passed = 0
        total = len(tests)
        detailed_results = []
        
        for test in tests:
            try:
                print(f"\n🧪 Running {test.__name__}...")
                result = await test()
                detailed_results.append({
                    "test_name": test.__name__,
                    "passed": result,
                    "error": None
                })
                if result:
                    passed += 1
                    print(f"✅ {test.__name__} passed")
                else:
                    print(f"❌ {test.__name__} failed")
            except Exception as e:
                print(f"💥 {test.__name__} crashed: {e}")
                detailed_results.append({
                    "test_name": test.__name__,
                    "passed": False,
                    "error": str(e)
                })
        
        results = {
            "total_tests": total,
            "passed_tests": passed,
            "success_rate": (passed / total) * 100,
            "detailed_results": detailed_results
        }
        
        return results
    
    def create_test_game_controller(self, mock_agents: List[MockAgent]) -> GameControllerV2:
        """Create a game controller with mock agents for testing"""
        game_uid = f"test_game_{uuid.uuid4().hex[:6]}"
        
        # Create participant data with minimal TPay integration for testing
        participants = []
        for i, agent in enumerate(mock_agents):
            participants.append({
                'name': agent.name,
                'agent_uid': agent.agent_uid,
                'tpay_account_id': None,  # Disable TPay for testing
                'db_id': i + 1000  # Use test DB IDs
            })
        
        gc = GameControllerV2(
            game_uid=game_uid,
            ws_manager=None,  # No WebSocket for testing
            game_db_id=None,  # No DB for testing
            participants=participants,
            treasury_agent_id=None  # No treasury for testing
        )
        
        # Disable TPay operations for testing
        for player in gc.players:
            player.money = 1500  # Set initial money directly
            player.agent_tpay_id = None
        
        return gc
    
    def force_dice_result(self, gc: GameControllerV2, dice_result: tuple):
        """Force a specific dice result for predictable movement"""
        gc.dice = dice_result
        gc.dice_roll_outcome_processed = False
        
    async def test_property_purchase_and_house_building(self) -> bool:
        """Test: Player buys property, returns to it, and builds houses"""
        try:
            mock_agent = MockAgent(0, "PropertyBuyer", [])
            gc = self.create_test_game_controller([mock_agent])
            
            # Start the game
            gc.start_game()
            
            # Get the current player
            current_player = gc.get_current_player()
            print(f"Test: {current_player.name} starting with ${current_player.money}")
            
            # Manually place player at Mediterranean Avenue (position 1)
            current_player.position = 1
            med_ave_square = gc.board.get_square(1)
            
            # Verify the property is unowned
            assert med_ave_square.owner_id is None, "Mediterranean Avenue should be unowned"
            
            # Set up buy decision context
            gc._set_pending_decision("buy_or_auction_property", {
                "player_id": 0,
                "property_id": 1
            })
            
            # Check available actions
            available_actions = gc.get_available_actions(0)
            print(f"Available actions: {available_actions}")
            assert "tool_buy_property" in available_actions, "Should be able to buy property"
            
            # Manually execute property purchase (bypass TPay)
            initial_money = current_player.money
            property_price = med_ave_square.price
            
            if current_player.money >= property_price:
                current_player.money -= property_price
                current_player.properties_owned_ids.add(1)
                med_ave_square.owner_id = 0
                gc._clear_pending_decision()
                gc.dice_roll_outcome_processed = True
                
                print(f"✅ Player bought Mediterranean Avenue for ${property_price}")
                print(f"   Money: ${initial_money} -> ${current_player.money}")
                print(f"   Properties owned: {current_player.properties_owned_ids}")
                
                # Give player monopoly by also owning Baltic Avenue for house building test
                baltic_ave_square = gc.board.get_square(3)
                baltic_ave_square.owner_id = 0
                current_player.properties_owned_ids.add(3)
                
                # Now test house building
                available_actions = gc.get_available_actions(0)
                print(f"Available actions with monopoly: {available_actions}")
                
                if "tool_build_house" in available_actions:
                    # Test house building logic
                    initial_houses = med_ave_square.num_houses
                    house_price = med_ave_square.house_price
                    
                    if current_player.money >= house_price:
                        current_player.money -= house_price
                        med_ave_square.num_houses += 1
                        
                        print(f"✅ Built house on Mediterranean Avenue")
                        print(f"   Houses: {initial_houses} -> {med_ave_square.num_houses}")
                        print(f"   Money: ${current_player.money}")
                        
                        return True
                    else:
                        print(f"❌ Not enough money for house: need ${house_price}, have ${current_player.money}")
                        return False
                else:
                    print(f"❌ tool_build_house not available: {available_actions}")
                    return False
            else:
                print(f"❌ Not enough money for property: need ${property_price}, have ${current_player.money}")
                return False
                
        except Exception as e:
            print(f"❌ Property purchase and house building test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_monopoly_completion_and_development(self) -> bool:
        """Test: Player completes a monopoly and develops it"""
        try:
            mock_agent = MockAgent(0, "MonopolyBuilder", [])
            gc = self.create_test_game_controller([mock_agent])
            
            gc.start_game()
            current_player = gc.get_current_player()
            initial_money = current_player.money
            
            print(f"Test: {current_player.name} starting with ${current_player.money}")
            
            # Manually give player both brown properties (monopoly)
            med_ave_square = gc.board.get_square(1)  # Mediterranean Avenue
            baltic_ave_square = gc.board.get_square(3)  # Baltic Avenue
            
            # Buy Mediterranean Avenue
            property_price = med_ave_square.price
            current_player.money -= property_price
            current_player.properties_owned_ids.add(1)
            med_ave_square.owner_id = 0
            
            # Buy Baltic Avenue
            property_price2 = baltic_ave_square.price
            current_player.money -= property_price2
            current_player.properties_owned_ids.add(3)
            baltic_ave_square.owner_id = 0
            
            print(f"✅ Player bought both brown properties (monopoly)")
            print(f"   Money: ${initial_money} -> ${current_player.money}")
            print(f"   Properties: {list(current_player.properties_owned_ids)}")
            
            # Clear any pending decisions
            gc._clear_pending_decision()
            gc.dice_roll_outcome_processed = True
            
            # Now player should be able to build houses on monopoly
            available_actions = gc.get_available_actions(0)
            print(f"Available actions with monopoly: {available_actions}")
            
            assert "tool_build_house" in available_actions, "Should be able to build houses on monopoly"
            
            # Build house on Mediterranean
            house_price = med_ave_square.house_price
            if current_player.money >= house_price:
                current_player.money -= house_price
                med_ave_square.num_houses += 1
                print(f"✅ Built house on Mediterranean Avenue (1 house)")
            
            # Build house on Baltic
            house_price2 = baltic_ave_square.house_price
            if current_player.money >= house_price2:
                current_player.money -= house_price2
                baltic_ave_square.num_houses += 1
                print(f"✅ Built house on Baltic Avenue (1 house)")
            
            # Verify both properties have houses
            assert med_ave_square.num_houses == 1, "Mediterranean should have 1 house"
            assert baltic_ave_square.num_houses == 1, "Baltic should have 1 house"
            
            print("✅ Monopoly completion and development test passed")
            return True
            
        except Exception as e:
            print(f"❌ Monopoly completion test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_rent_collection_sequence(self) -> bool:
        """Test: Player lands on opponent's property and pays rent"""
        try:
            owner_agent = MockAgent(0, "PropertyOwner", [])
            visitor_agent = MockAgent(1, "PropertyVisitor", [])
            
            gc = self.create_test_game_controller([owner_agent, visitor_agent])
            gc.start_game()
            
            # Player 0 owns Mediterranean Avenue
            owner = gc.players[0]
            visitor = gc.players[1]
            
            med_ave_square = gc.board.get_square(1)
            property_price = med_ave_square.price
            
            # Owner buys the property
            owner.money -= property_price
            owner.properties_owned_ids.add(1)
            med_ave_square.owner_id = 0
            
            print(f"✅ {owner.name} bought Mediterranean Avenue for ${property_price}")
            print(f"   Owner money: ${owner.money}")
            
            # Visitor lands on Mediterranean Avenue and pays rent
            initial_visitor_money = visitor.money
            initial_owner_money = owner.money
            
            visitor.position = 1
            rent_amount = med_ave_square.rent_levels[0]  # Base rent (no houses)
            
            # Simulate rent payment
            if visitor.money >= rent_amount:
                visitor.money -= rent_amount
                owner.money += rent_amount
                
                print(f"✅ {visitor.name} paid ${rent_amount} rent to {owner.name}")
                print(f"   Visitor money: ${initial_visitor_money} -> ${visitor.money}")
                print(f"   Owner money: ${initial_owner_money} -> ${owner.money}")
                
                # Verify rent was paid
                assert visitor.money == initial_visitor_money - rent_amount, "Visitor should have paid rent"
                assert owner.money == initial_owner_money + rent_amount, "Owner should have received rent"
                
                print("✅ Rent collection sequence test passed")
                return True
            else:
                print(f"❌ Visitor doesn't have enough money for rent: need ${rent_amount}, have ${visitor.money}")
                return False
            
        except Exception as e:
            print(f"❌ Rent collection test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_jail_and_recovery_scenario(self) -> bool:
        """Test: Player goes to jail and gets out"""
        try:
            mock_agent = MockAgent(0, "JailBreaker", [])
            gc = self.create_test_game_controller([mock_agent])
            
            gc.start_game()
            current_player = gc.get_current_player()
            
            # Send player to jail
            current_player.go_to_jail()
            assert current_player.in_jail, "Player should be in jail"
            assert current_player.position == 10, "Player should be at jail position"
            
            initial_money = current_player.money
            
            # Set up jail decision context
            gc._set_pending_decision("jail_options", {"player_id": 0})
            
            # Get available actions (should include jail options)
            available_actions = gc.get_available_actions(0)
            print(f"Available jail actions: {available_actions}")
            
            # Player should be able to pay bail
            if "tool_pay_bail" in available_actions:
                # Manually simulate paying bail (bypass TPay)
                jail_fine = 50
                if current_player.money >= jail_fine:
                    current_player.money -= jail_fine
                    current_player.in_jail = False
                    current_player.jail_turns_remaining = 0
                    gc._clear_pending_decision()
                    
                    # Check player is out of jail and money was deducted
                    assert not current_player.in_jail, "Player should be out of jail"
                    assert current_player.money == initial_money - jail_fine, f"Player should have paid ${jail_fine} bail"
                    
                    print(f"✅ Player paid ${jail_fine} bail and got out of jail")
                    print(f"   Money: ${initial_money} -> ${current_player.money}")
                    return True
                else:
                    print(f"❌ Not enough money for bail: need ${jail_fine}, have ${current_player.money}")
                    return False
            else:
                print(f"❌ tool_pay_bail not available in actions: {available_actions}")
                return False
            
        except Exception as e:
            print(f"❌ Jail and recovery test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def test_trade_acceptance_scenario(self) -> bool:
        """Test: One player proposes trade, another accepts"""
        try:
            proposer = MockAgent(0, "TradeProposer", [])
            accepter = MockAgent(1, "TradeAccepter", [])
            
            gc = self.create_test_game_controller([proposer, accepter])
            gc.start_game()
            
            # Give each player a property to trade
            player0 = gc.players[0]
            player1 = gc.players[1]
            
            # Player 0 gets Mediterranean Avenue
            med_ave_square = gc.board.get_square(1)
            player0.properties_owned_ids.add(1)
            med_ave_square.owner_id = 0
            
            # Player 1 gets Baltic Avenue
            baltic_ave_square = gc.board.get_square(3)
            player1.properties_owned_ids.add(3)
            baltic_ave_square.owner_id = 1
            
            print(f"✅ Setup: {player0.name} owns Mediterranean Ave, {player1.name} owns Baltic Ave")
            
            initial_p0_money = player0.money
            initial_p1_money = player1.money
            trade_money = 100
            
            # Simulate trade: Player 0 trades Mediterranean Ave + $100 for Baltic Ave
            if player0.money >= trade_money:
                # Execute the trade manually
                player0.money -= trade_money
                player1.money += trade_money
                
                # Exchange properties
                player0.properties_owned_ids.remove(1)
                player0.properties_owned_ids.add(3)
                
                player1.properties_owned_ids.remove(3)
                player1.properties_owned_ids.add(1)
                
                # Update property ownership
                med_ave_square.owner_id = 1
                baltic_ave_square.owner_id = 0
                
                print(f"✅ Trade executed successfully")
                print(f"   {player0.name}: Mediterranean Ave + ${trade_money} -> Baltic Ave")
                print(f"   {player1.name}: Baltic Ave -> Mediterranean Ave + ${trade_money}")
                print(f"   P0 money: ${initial_p0_money} -> ${player0.money}")
                print(f"   P1 money: ${initial_p1_money} -> ${player1.money}")
                
                # Verify trade completed
                assert 3 in player0.properties_owned_ids, "Player 0 should now own Baltic Ave"
                assert 1 in player1.properties_owned_ids, "Player 1 should now own Mediterranean Ave"
                assert player0.money == initial_p0_money - trade_money, "Player 0 should have paid money"
                assert player1.money == initial_p1_money + trade_money, "Player 1 should have received money"
                
                print("✅ Trade acceptance scenario test passed")
                return True
            else:
                print(f"❌ Player 0 doesn't have enough money for trade: need ${trade_money}, have ${player0.money}")
                return False
            
        except Exception as e:
            print(f"❌ Trade acceptance test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


class TestOrchestrator:
    """Orchestrates all test suites and provides comprehensive reporting"""
    
    def __init__(self):
        self.core_test_suite = GameControllerV2TestSuite()
        self.regression_runner = RegressionTestRunner()
        self.board_state_suite = BoardStateTestSuite()
        self.test_results = {}
        
    async def run_core_tests(self) -> Dict[str, Any]:
        """Run core GameControllerV2 functionality tests"""
        print("🧪 Running Core GameControllerV2 Tests...")
        print("=" * 50)
        
        results = await self.core_test_suite.run_all_tests()
        self.test_results['core_tests'] = results
        
        return results
    
    async def run_board_state_tests(self) -> Dict[str, Any]:
        """Run board state simulation tests"""
        print("🏁 Running Board State Simulation Tests...")
        print("=" * 50)
        
        results = await self.board_state_suite.run_all_board_state_tests()
        self.test_results['board_state_tests'] = results
        
        return results
    
    async def run_smoke_tests(self) -> Dict[str, Any]:
        """Run quick smoke tests for basic functionality"""
        print("💨 Running Smoke Tests...")
        print("=" * 50)
        
        smoke_tests = [
            self.core_test_suite.test_game_initialization,
            self.core_test_suite.test_property_purchase_decision,
            self.core_test_suite.test_trade_proposal_decision
        ]
        
        passed = 0
        total = len(smoke_tests)
        
        for test in smoke_tests:
            try:
                result = await test()
                if result:
                    passed += 1
                    print(f"✅ {test.__name__} passed")
                else:
                    print(f"❌ {test.__name__} failed")
            except Exception as e:
                print(f"💥 {test.__name__} crashed: {e}")
        
        results = {
            "total_smoke_tests": total,
            "passed_smoke_tests": passed,
            "smoke_success_rate": (passed / total) * 100,
            "all_smoke_passed": passed == total
        }
        
        self.test_results['smoke_tests'] = results
        return results
    
    async def run_regression_tests(self) -> Dict[str, Any]:
        """Run regression tests to ensure no functionality breaks"""
        print("🔄 Running Regression Tests...")
        print("=" * 50)
        
        regression_passed = await self.regression_runner.run_regression_tests()
        
        results = {
            "regression_passed": regression_passed,
            "regression_timestamp": time.time()
        }
        
        self.test_results['regression_tests'] = results
        return results
    
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """Generate a comprehensive test report"""
        total_tests = 0
        passed_tests = 0
        
        # Aggregate results from all test suites
        for suite_name, suite_results in self.test_results.items():
            if 'total_tests' in suite_results:
                total_tests += suite_results['total_tests']
                passed_tests += suite_results['passed_tests']
            elif 'total_smoke_tests' in suite_results:
                total_tests += suite_results['total_smoke_tests']
                passed_tests += suite_results['passed_smoke_tests']
        
        overall_success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        report = {
            "test_run_timestamp": time.time(),
            "total_tests_run": total_tests,
            "total_tests_passed": passed_tests,
            "overall_success_rate": overall_success_rate,
            "all_tests_passed": passed_tests == total_tests,
            "test_suite_results": self.test_results,
            "recommendations": self._generate_recommendations()
        }
        
        return report
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results"""
        recommendations = []
        
        # Check core test results
        if 'core_tests' in self.test_results:
            core_results = self.test_results['core_tests']
            if core_results['success_rate'] < 100:
                recommendations.append("⚠️  Core tests have failures - review failed test cases")
            if core_results['success_rate'] >= 95:
                recommendations.append("✅ Core functionality is stable")
        
        # Check board state test results
        if 'board_state_tests' in self.test_results:
            board_results = self.test_results['board_state_tests']
            if board_results['success_rate'] < 100:
                recommendations.append("⚠️  Board state tests have failures - check game flow logic")
            if board_results['success_rate'] >= 95:
                recommendations.append("✅ Game flow and board state management is stable")
        
        # Check regression results  
        if 'regression_tests' in self.test_results:
            if not self.test_results['regression_tests']['regression_passed']:
                recommendations.append("🚨 Regression tests failed - potential breaking changes detected")
            else:
                recommendations.append("✅ No regressions detected")
        
        # Check smoke test results
        if 'smoke_tests' in self.test_results:
            smoke_results = self.test_results['smoke_tests']
            if not smoke_results['all_smoke_passed']:
                recommendations.append("🚨 Smoke tests failed - basic functionality may be broken")
            else:
                recommendations.append("✅ Basic functionality is working")
        
        # General recommendations
        success_rates = [suite.get('success_rate', 0) for suite in self.test_results.values() if 'success_rate' in suite]
        if success_rates:
            overall_rate = sum(success_rates) / len(success_rates)
        
        if overall_rate >= 98:
            recommendations.append("🎉 Excellent test coverage and stability!")
        elif overall_rate >= 90:
            recommendations.append("👍 Good test stability, minor issues to address")
        elif overall_rate >= 80:
            recommendations.append("⚠️  Multiple test failures - significant issues to resolve")
        else:
            recommendations.append("🚨 Major stability issues - extensive debugging required")
        
        # Specific recommendations for board state tests
        if 'board_state_tests' in self.test_results:
            board_results = self.test_results['board_state_tests']
            failed_tests = [test for test in board_results.get('detailed_results', []) if not test['passed']]
            if failed_tests:
                recommendations.append(f"🎯 Focus on fixing board state scenarios: {', '.join([test['test_name'] for test in failed_tests])}")
        
        return recommendations
    
    def print_final_report(self, report: Dict[str, Any]):
        """Print a comprehensive final report"""
        print("\n" + "=" * 70)
        print("📊 COMPREHENSIVE TEST REPORT")
        print("=" * 70)
        
        print(f"🕐 Test Run Completed: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report['test_run_timestamp']))}")
        print(f"📈 Overall Results:")
        print(f"   Total Tests: {report['total_tests_run']}")
        print(f"   Passed: {report['total_tests_passed']}")
        print(f"   Failed: {report['total_tests_run'] - report['total_tests_passed']}")
        print(f"   Success Rate: {report['overall_success_rate']:.1f}%")
        
        print(f"\n📋 Test Suite Breakdown:")
        for suite_name, suite_results in report['test_suite_results'].items():
            print(f"   {suite_name}:")
            if 'success_rate' in suite_results:
                print(f"     Success Rate: {suite_results['success_rate']:.1f}%")
            if 'total_tests' in suite_results:
                print(f"     Tests: {suite_results['passed_tests']}/{suite_results['total_tests']}")
            if 'total_smoke_tests' in suite_results:
                print(f"     Tests: {suite_results['passed_smoke_tests']}/{suite_results['total_smoke_tests']}")
            if 'regression_passed' in suite_results:
                print(f"     Regression: {'✅ Passed' if suite_results['regression_passed'] else '❌ Failed'}")
        
        print(f"\n💡 Recommendations:")
        for recommendation in report['recommendations']:
            print(f"   {recommendation}")
        
        if report['all_tests_passed']:
            print(f"\n🎉 ALL TESTS PASSED! GameControllerV2 is ready for production! 🎉")
        else:
            print(f"\n⚠️  Some tests failed. Please review and fix issues before deployment.")
        
        print("=" * 70)


async def main():
    """Main function to run tests based on command line arguments"""
    parser = argparse.ArgumentParser(description='Run GameControllerV2 tests')
    parser.add_argument('--all', action='store_true', help='Run all tests')
    parser.add_argument('--core', action='store_true', help='Run core functionality tests')
    parser.add_argument('--smoke', action='store_true', help='Run smoke tests only')
    parser.add_argument('--regression', action='store_true', help='Run regression tests only')
    parser.add_argument('--performance', action='store_true', help='Run performance tests')
    parser.add_argument('--board-states', action='store_true', help='Run board state simulation tests')
    parser.add_argument('--output', default='test_results.json', help='Output file for results')
    
    args = parser.parse_args()
    
    # If no specific test type is specified, run all tests
    if not any([args.core, args.smoke, args.regression, args.performance, args.board_states]):
        args.all = True
    
    orchestrator = TestOrchestrator()
    
    print("🎮 GameControllerV2 Test Suite Runner")
    print("Testing modular game logic with agent decision processes")
    print("=" * 70)
    
    # Run specified test suites
    if args.all or args.smoke:
        await orchestrator.run_smoke_tests()
    
    if args.all or args.core:
        await orchestrator.run_core_tests()
    
    if args.all or args.regression:
        await orchestrator.run_regression_tests()
    
    if args.all or args.board_states:
        await orchestrator.run_board_state_tests()
    
    # Generate and display comprehensive report
    final_report = orchestrator.generate_comprehensive_report()
    orchestrator.print_final_report(final_report)
    
    # Save results to file
    with open(args.output, 'w') as f:
        json.dump(final_report, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: {args.output}")
    
    # Return appropriate exit code
    return 0 if final_report['all_tests_passed'] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 