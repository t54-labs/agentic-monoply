#!/usr/bin/env python3
"""
GameControllerV2 Test Runner Script

This script runs comprehensive tests for the modular GameControllerV2,
including core functionality tests, agent decision tests, and regression tests.

Usage:
    python run_tests.py --all                    # Run all tests
    python run_tests.py --core                   # Run core functionality tests
    python run_tests.py --agent-decisions        # Run agent decision tests
    python run_tests.py --regression             # Run regression tests only
    python run_tests.py --smoke                  # Run smoke tests
    python run_tests.py --performance            # Run performance tests
"""

import asyncio
import argparse
import sys
import os
import json
import time
from typing import Dict, Any, List

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import test suites
from tests.test_game_controller_v2 import GameControllerV2TestSuite, RegressionTestRunner


class TestOrchestrator:
    """Orchestrates all test suites and provides comprehensive reporting"""
    
    def __init__(self):
        self.core_test_suite = GameControllerV2TestSuite()
        self.regression_runner = RegressionTestRunner()
        self.test_results = {}
        
    async def run_core_tests(self) -> Dict[str, Any]:
        """Run core GameControllerV2 functionality tests"""
        print("🧪 Running Core GameControllerV2 Tests...")
        print("=" * 50)
        
        results = await self.core_test_suite.run_all_tests()
        self.test_results['core_tests'] = results
        
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
        overall_rate = sum(
            suite.get('success_rate', 0) for suite in self.test_results.values() 
            if 'success_rate' in suite
        ) / len([s for s in self.test_results.values() if 'success_rate' in s])
        
        if overall_rate >= 98:
            recommendations.append("🎉 Excellent test coverage and stability!")
        elif overall_rate >= 90:
            recommendations.append("👍 Good test stability, minor issues to address")
        elif overall_rate >= 80:
            recommendations.append("⚠️  Multiple test failures - significant issues to resolve")
        else:
            recommendations.append("🚨 Major stability issues - extensive debugging required")
        
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
    parser.add_argument('--output', default='test_results.json', help='Output file for results')
    
    args = parser.parse_args()
    
    # If no specific test type is specified, run all tests
    if not any([args.core, args.smoke, args.regression, args.performance]):
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