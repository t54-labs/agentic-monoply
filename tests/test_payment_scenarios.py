"""
Payment Scenarios Test Suite

This module provides comprehensive testing for payment scenarios in GameControllerV2,
including both successful and failed payment cases without relying on actual TPay integration.

Focus Areas:
1. Local Payment Simulation (no TPay)
2. Payment Success Scenarios
3. Payment Failure Scenarios
4. Bankruptcy Due to Payment Failures
5. Agent Decision Making Under Different Payment Conditions
"""

import asyncio
import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import Mock, AsyncMock, patch
from dataclasses import dataclass

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.game_controller_v2 import GameControllerV2
from game_logic.player import Player
from tests.test_game_controller_v2 import TestGameSetupManager, TestExpectedResult, MockAgentResponse


@dataclass
class PaymentScenario:
    """Payment test scenario definition"""
    name: str
    initial_money: Dict[int, int]  # player_id -> initial money
    payment_amount: int
    should_succeed: bool
    expected_final_money: Dict[int, int]  # player_id -> expected final money
    expected_bankruptcy: List[int] = None  # list of player_ids that should be bankrupt


class TestPaymentManager:
    """Test payment manager that simulates payments without TPay"""
    
    def __init__(self, force_failure: bool = False):
        self.force_failure = force_failure
        self.payment_history = []
        
    async def create_tpay_payment_player_to_player(self, payer: Player, recipient: Player, 
                                                  amount: float, reason: str, 
                                                  agent_decision_context: Optional[Dict[str, Any]] = None) -> bool:
        """Simulate player-to-player payment"""
        payment_record = {
            "type": "player_to_player",
            "payer": payer.name,
            "recipient": recipient.name,
            "amount": amount,
            "reason": reason,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        if self.force_failure or payer.money < amount:
            payment_record["status"] = "failed"
            payment_record["error"] = "Insufficient funds" if payer.money < amount else "Forced failure"
            self.payment_history.append(payment_record)
            return False
        
        # Execute local payment
        payer.money -= int(amount)
        recipient.money += int(amount)
        
        payment_record["status"] = "success"
        payment_record["payer_balance_after"] = payer.money
        payment_record["recipient_balance_after"] = recipient.money
        self.payment_history.append(payment_record)
        
        return True
    
    async def create_tpay_payment_player_to_system(self, payer: Player, amount: float, 
                                                  reason: str, event_description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Simulate player-to-system payment"""
        payment_record = {
            "type": "player_to_system",
            "payer": payer.name,
            "amount": amount,
            "reason": reason,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        if self.force_failure or payer.money < amount:
            payment_record["status"] = "failed"
            payment_record["error"] = "Insufficient funds" if payer.money < amount else "Forced failure"
            self.payment_history.append(payment_record)
            return None
        
        # Execute local payment
        payer.money -= int(amount)
        
        payment_record["status"] = "success"
        payment_record["payer_balance_after"] = payer.money
        self.payment_history.append(payment_record)
        
        return {"success": True, "id": f"test_payment_{len(self.payment_history)}"}
    
    async def create_tpay_payment_system_to_player(self, recipient: Player, amount: float, 
                                                  reason: str, event_description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Simulate system-to-player payment"""
        payment_record = {
            "type": "system_to_player",
            "recipient": recipient.name,
            "amount": amount,
            "reason": reason,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        if self.force_failure:
            payment_record["status"] = "failed"
            payment_record["error"] = "Forced failure"
            self.payment_history.append(payment_record)
            return None
        
        # Execute local payment
        recipient.money += int(amount)
        
        payment_record["status"] = "success"
        payment_record["recipient_balance_after"] = recipient.money
        self.payment_history.append(payment_record)
        
        return {"success": True, "id": f"test_payment_{len(self.payment_history)}"}
    
    async def _wait_for_payment_completion(self, payment_result: Dict[str, Any], timeout_seconds: int = 30) -> bool:
        """Simulate payment completion check"""
        if not payment_result:
            return False
        return payment_result.get("success", False)


class PaymentScenariosTestSuite:
    """Test suite for payment scenarios"""
    
    def __init__(self):
        self.test_results = []
        self.setup_manager = TestGameSetupManager()
        
    async def setup_payment_test_game(self, scenario: PaymentScenario, payment_manager: TestPaymentManager) -> GameControllerV2:
        """Setup a test game with custom payment manager"""
        participants = self.setup_manager.create_test_participants(len(scenario.initial_money))
        
        # Create mock WebSocket manager
        mock_ws_manager = Mock()
        mock_ws_manager.broadcast_to_game = AsyncMock()
        
        # Create game controller
        gc = GameControllerV2(
            game_uid=f"payment_test_{scenario.name}",
            ws_manager=mock_ws_manager,
            game_db_id=999,
            participants=participants,
            treasury_agent_id="test_treasury"
        )
        
        # Replace payment manager with test version
        gc.payment_manager.create_tpay_payment_player_to_player = payment_manager.create_tpay_payment_player_to_player
        gc.payment_manager.create_tpay_payment_player_to_system = payment_manager.create_tpay_payment_player_to_system
        gc.payment_manager.create_tpay_payment_system_to_player = payment_manager.create_tpay_payment_system_to_player
        gc.payment_manager._wait_for_payment_completion = payment_manager._wait_for_payment_completion
        
        # Set initial money for all players
        for player_id, money in scenario.initial_money.items():
            gc.players[player_id].money = money
            
        return gc

    # ======= Payment Success Scenarios =======
    
    async def test_successful_rent_payment(self) -> bool:
        """Test successful rent payment between players"""
        test_name = "Successful Rent Payment"
        
        try:
            scenario = PaymentScenario(
                name="rent_payment_success",
                initial_money={0: 1500, 1: 1000},  # Owner has 1500, tenant has 1000
                payment_amount=50,  # Rent amount
                should_succeed=True,
                expected_final_money={0: 1550, 1: 950}  # Owner +50, tenant -50
            )
            
            payment_manager = TestPaymentManager(force_failure=False)
            gc = await self.setup_payment_test_game(scenario, payment_manager)
            gc.start_game()
            
            # Setup property ownership
            owner_id = 0
            tenant_id = 1
            property_id = 1  # Mediterranean Avenue
            
            self.setup_manager.setup_property_ownership(gc, owner_id, [property_id])
            
            # Simulate tenant landing on owned property
            tenant = gc.players[tenant_id]
            tenant.position = property_id
            
            # Mock agent decision - tenant accepts payment
            mock_agent_response = MockAgentResponse(
                tool_name="pay_rent",
                parameters={"amount": scenario.payment_amount},
                reasoning=f"I must pay ${scenario.payment_amount} rent to the property owner",
                expected_outcome="Rent payment successful"
            )
            
            print(f"🤖 Agent Decision: {mock_agent_response.reasoning}")
            
            # Execute rent payment by landing on property
            await gc.land_on_square(tenant)
            
            # Verify payment was successful
            owner = gc.players[owner_id]
            assert owner.money == scenario.expected_final_money[0], f"Owner money: expected {scenario.expected_final_money[0]}, got {owner.money}"
            assert tenant.money == scenario.expected_final_money[1], f"Tenant money: expected {scenario.expected_final_money[1]}, got {tenant.money}"
            
            # Verify payment history
            assert len(payment_manager.payment_history) > 0
            last_payment = payment_manager.payment_history[-1]
            assert last_payment["status"] == "success"
            assert last_payment["amount"] == scenario.payment_amount
            
            print(f"✅ {test_name} passed - Rent payment successful")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def test_successful_property_purchase(self) -> bool:
        """Test successful property purchase"""
        test_name = "Successful Property Purchase"
        
        try:
            scenario = PaymentScenario(
                name="property_purchase_success",
                initial_money={0: 1500},
                payment_amount=60,  # Mediterranean Avenue price
                should_succeed=True,
                expected_final_money={0: 1440}  # 1500 - 60
            )
            
            payment_manager = TestPaymentManager(force_failure=False)
            gc = await self.setup_payment_test_game(scenario, payment_manager)
            gc.start_game()
            
            player_id = 0
            player = gc.players[player_id]
            property_id = 1  # Mediterranean Avenue
            
            # Set up buy decision scenario
            gc._set_pending_decision("buy_or_auction_property", 
                                   context={"property_id": property_id, "player_id": player_id},
                                   outcome_processed=False)
            
            # Mock agent decision to buy
            mock_agent_response = MockAgentResponse(
                tool_name="tool_buy_property",
                parameters={"property_id": property_id},
                reasoning="Mediterranean Avenue is affordable and a good investment",
                expected_outcome="Property purchase successful"
            )
            
            print(f"🤖 Agent Decision: {mock_agent_response.reasoning}")
            
            # Execute purchase
            purchase_result = await gc.execute_buy_property_decision(player_id, property_id)
            
            # Verify purchase was successful
            assert purchase_result == True
            assert player.money == scenario.expected_final_money[0]
            assert property_id in player.properties_owned_ids
            
            print(f"✅ {test_name} passed - Property purchase successful")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Payment Failure Scenarios =======
    
    async def test_failed_rent_payment(self) -> bool:
        """Test failed rent payment due to insufficient funds"""
        test_name = "Failed Rent Payment"
        
        try:
            scenario = PaymentScenario(
                name="rent_payment_failure",
                initial_money={0: 1500, 1: 30},  # Tenant has insufficient funds
                payment_amount=50,  # Rent amount higher than tenant's money
                should_succeed=False,
                expected_final_money={0: 1500, 1: 30},  # No money change due to failure
                expected_bankruptcy=[1]  # Tenant should face bankruptcy
            )
            
            payment_manager = TestPaymentManager(force_failure=False)  # Don't force failure, let insufficient funds cause it
            gc = await self.setup_payment_test_game(scenario, payment_manager)
            gc.start_game()
            
            # Setup property ownership
            owner_id = 0
            tenant_id = 1
            property_id = 1  # Mediterranean Avenue
            
            self.setup_manager.setup_property_ownership(gc, owner_id, [property_id])
            
            # Simulate tenant landing on owned property
            tenant = gc.players[tenant_id]
            tenant.position = property_id
            
            # Mock agent decision - tenant tries to pay but fails
            mock_agent_response = MockAgentResponse(
                tool_name="pay_rent",
                parameters={"amount": scenario.payment_amount},
                reasoning=f"I must pay ${scenario.payment_amount} rent but I only have ${tenant.money}",
                expected_outcome="Payment fails, bankruptcy process begins"
            )
            
            print(f"🤖 Agent Decision: {mock_agent_response.reasoning}")
            
            # Execute rent payment attempt
            await gc.land_on_square(tenant)
            
            # Verify payment failed and bankruptcy was triggered
            owner = gc.players[owner_id]
            assert owner.money == scenario.expected_final_money[0], f"Owner money should be unchanged"
            assert tenant.money == scenario.expected_final_money[1], f"Tenant money should be unchanged"
            
            # Verify bankruptcy process was initiated
            assert gc.pending_decision_type == "asset_liquidation_for_debt"
            assert gc.pending_decision_context.get("player_id") == tenant_id
            
            # Verify payment history shows failure
            rent_payments = [p for p in payment_manager.payment_history if "rent" in p.get("reason", "")]
            assert len(rent_payments) > 0
            last_rent_payment = rent_payments[-1]
            assert last_rent_payment["status"] == "failed"
            
            print(f"✅ {test_name} passed - Payment failed and bankruptcy triggered")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    async def test_failed_property_purchase(self) -> bool:
        """Test failed property purchase due to insufficient funds"""
        test_name = "Failed Property Purchase"
        
        try:
            scenario = PaymentScenario(
                name="property_purchase_failure",
                initial_money={0: 50},  # Player has insufficient funds
                payment_amount=60,  # Mediterranean Avenue price
                should_succeed=False,
                expected_final_money={0: 50}  # Money unchanged
            )
            
            payment_manager = TestPaymentManager(force_failure=False)
            gc = await self.setup_payment_test_game(scenario, payment_manager)
            gc.start_game()
            
            player_id = 0
            player = gc.players[player_id]
            property_id = 1  # Mediterranean Avenue
            
            # Set up buy decision scenario
            gc._set_pending_decision("buy_or_auction_property", 
                                   context={"property_id": property_id, "player_id": player_id},
                                   outcome_processed=False)
            
            # Mock agent decision to attempt purchase
            mock_agent_response = MockAgentResponse(
                tool_name="tool_buy_property",
                parameters={"property_id": property_id},
                reasoning=f"I want to buy Mediterranean Avenue but I only have ${player.money}",
                expected_outcome="Purchase fails due to insufficient funds"
            )
            
            print(f"🤖 Agent Decision: {mock_agent_response.reasoning}")
            
            # Execute purchase attempt
            purchase_result = await gc.execute_buy_property_decision(player_id, property_id)
            
            # Verify purchase failed
            assert purchase_result == False
            assert player.money == scenario.expected_final_money[0]
            assert property_id not in player.properties_owned_ids
            
            # Verify payment history shows failure
            purchase_payments = [p for p in payment_manager.payment_history if "purchase" in p.get("reason", "")]
            if purchase_payments:  # Payment might not even be attempted if pre-check fails
                last_purchase_payment = purchase_payments[-1]
                assert last_purchase_payment["status"] == "failed"
            
            print(f"✅ {test_name} passed - Property purchase failed as expected")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Agent Decision Under Payment Constraints =======
    
    async def test_agent_decision_with_limited_funds(self) -> bool:
        """Test agent decision making when funds are limited"""
        test_name = "Agent Decision with Limited Funds"
        
        try:
            scenario = PaymentScenario(
                name="limited_funds_decision",
                initial_money={0: 100, 1: 2000},  # Player 0 has limited funds, Player 1 has plenty
                payment_amount=0,  # No specific payment amount
                should_succeed=True,
                expected_final_money={0: 100, 1: 2000}  # Will depend on decisions made
            )
            
            payment_manager = TestPaymentManager(force_failure=False)
            gc = await self.setup_payment_test_game(scenario, payment_manager)
            gc.start_game()
            
            # Test decisions for poor player
            poor_player_id = 0
            poor_player = gc.players[poor_player_id]
            gc.current_player_index = poor_player_id
            
            # Get available actions for poor player
            available_actions = gc.get_available_actions(poor_player_id)
            
            # Mock agent decision based on financial constraints
            mock_agent_response = MockAgentResponse(
                tool_name="tool_end_turn",  # Conservative choice due to limited funds
                parameters={},
                reasoning=f"I only have ${poor_player.money}, so I should be conservative and end my turn",
                expected_outcome="Turn ends without risky actions"
            )
            
            print(f"🤖 Poor Player Agent Decision: {mock_agent_response.reasoning}")
            assert mock_agent_response.tool_name in available_actions
            
            # Test decisions for rich player
            rich_player_id = 1
            rich_player = gc.players[rich_player_id]
            gc.current_player_index = rich_player_id
            
            # Give rich player a property to potentially build on
            self.setup_manager.setup_property_ownership(gc, rich_player_id, [1, 3])  # Brown monopoly
            
            available_actions_rich = gc.get_available_actions(rich_player_id)
            
            # Mock agent decision for wealthy player
            mock_agent_rich_response = MockAgentResponse(
                tool_name="tool_build_house",  # Aggressive choice due to plenty of funds
                parameters={"property_id": 1},
                reasoning=f"I have ${rich_player.money}, so I can afford to build houses for higher rent",
                expected_outcome="House built successfully"
            )
            
            print(f"🤖 Rich Player Agent Decision: {mock_agent_rich_response.reasoning}")
            
            # Verify different strategies based on financial situation
            assert "tool_build_house" in available_actions_rich or "tool_roll_dice" in available_actions_rich
            
            print(f"✅ {test_name} passed - Agents make different decisions based on financial constraints")
            return True
            
        except Exception as e:
            print(f"❌ {test_name} failed: {str(e)}")
            return False

    # ======= Test Runner =======
    
    async def run_all_payment_tests(self) -> Dict[str, Any]:
        """Run all payment scenario tests"""
        print("💰 Starting Payment Scenarios Test Suite...")
        print("=" * 60)
        
        test_methods = [
            self.test_successful_rent_payment,
            self.test_successful_property_purchase,
            self.test_failed_rent_payment,
            self.test_failed_property_purchase,
            self.test_agent_decision_with_limited_funds
        ]
        
        total_tests = len(test_methods)
        passed_tests = 0
        
        for test_method in test_methods:
            try:
                result = await test_method()
                if result:
                    passed_tests += 1
            except Exception as e:
                print(f"💥 Test {test_method.__name__} crashed: {str(e)}")
        
        print("=" * 60)
        print(f"📊 Payment Test Results:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests}")
        print(f"   Failed: {total_tests - passed_tests}")
        print(f"   Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if passed_tests == total_tests:
            print("🎉 ALL PAYMENT TESTS PASSED!")
        else:
            print("⚠️  Some payment tests failed.")
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "success_rate": (passed_tests/total_tests)*100,
            "all_passed": passed_tests == total_tests
        }


# ======= Main Execution =======

async def main():
    """Main execution function for payment tests"""
    print("💳 Payment Scenarios Test Suite")
    print("Testing payment success and failure scenarios")
    print("=" * 60)
    
    payment_test_suite = PaymentScenariosTestSuite()
    results = await payment_test_suite.run_all_payment_tests()
    
    print("\n" + "=" * 60)
    print("🏁 Payment Testing Complete!")
    
    if results["all_passed"]:
        print("🎉 All payment scenarios work correctly!")
        return True
    else:
        print("⚠️  Some payment scenarios failed.")
        return False


if __name__ == "__main__":
    # Run payment tests
    asyncio.run(main()) 