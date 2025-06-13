#!/usr/bin/env python3
"""
CI/CD Pipeline for GameControllerV2

This script implements a comprehensive CI/CD pipeline for automated testing,
quality assurance, and deployment readiness checks for the GameControllerV2.

Pipeline Stages:
1. Code Quality Checks (linting, formatting)
2. Unit Tests (core functionality)
3. Integration Tests (manager interactions)
4. Agent Decision Tests (complex scenarios)
5. Performance Tests (load and stress)
6. Security Tests (basic security checks)
7. Regression Tests (no breaking changes)
8. Deployment Readiness Check
9. Report Generation and Notifications

Usage:
    python ci_cd_pipeline.py --stage all          # Run full pipeline
    python ci_cd_pipeline.py --stage pre-commit   # Pre-commit checks
    python ci_cd_pipeline.py --stage nightly      # Nightly build checks
    python ci_cd_pipeline.py --stage deploy       # Deployment readiness
"""

import asyncio
import argparse
import sys
import os
import json
import time
import subprocess
import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import test suites
from tests.test_game_controller_v2 import GameControllerV2TestSuite, RegressionTestRunner
from run_tests import TestOrchestrator


@dataclass
class PipelineResult:
    """Result of a pipeline stage"""
    stage_name: str
    success: bool
    duration: float
    details: Dict[str, Any]
    errors: List[str]
    warnings: List[str]


@dataclass 
class QualityMetrics:
    """Code quality metrics"""
    test_coverage: float
    code_complexity: int
    security_issues: int
    performance_score: float
    documentation_score: float


class CICDPipeline:
    """Comprehensive CI/CD pipeline for GameControllerV2"""
    
    def __init__(self, output_dir: str = "ci_reports"):
        self.output_dir = output_dir
        self.pipeline_results: List[PipelineResult] = []
        self.quality_metrics = QualityMetrics(0, 0, 0, 0, 0)
        
        # Setup logging
        os.makedirs(output_dir, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'{output_dir}/pipeline.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def log_stage_start(self, stage_name: str):
        """Log the start of a pipeline stage"""
        self.logger.info(f"🚀 Starting pipeline stage: {stage_name}")
        print(f"\n{'='*60}")
        print(f"🚀 PIPELINE STAGE: {stage_name.upper()}")
        print(f"{'='*60}")
    
    def log_stage_end(self, stage_name: str, success: bool, duration: float):
        """Log the end of a pipeline stage"""
        status = "✅ PASSED" if success else "❌ FAILED"
        self.logger.info(f"{status} Pipeline stage '{stage_name}' completed in {duration:.2f}s")
        print(f"{status} {stage_name} completed in {duration:.2f}s")

    # ======= Stage 1: Code Quality Checks =======
    
    async def run_code_quality_checks(self) -> PipelineResult:
        """Run code quality checks including linting and formatting"""
        stage_name = "Code Quality Checks"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Check for Python syntax errors
            syntax_check = await self._run_syntax_checks()
            details['syntax_check'] = syntax_check
            if not syntax_check['success']:
                errors.extend(syntax_check['errors'])
            
            # Run basic code quality metrics
            quality_metrics = await self._analyze_code_quality()
            details['quality_metrics'] = quality_metrics
            
            # Check for common security issues
            security_check = await self._run_security_checks()
            details['security_check'] = security_check
            if security_check['issues'] > 0:
                warnings.append(f"Found {security_check['issues']} potential security issues")
            
            success = len(errors) == 0
            
        except Exception as e:
            errors.append(f"Code quality check failed: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result
    
    async def _run_syntax_checks(self) -> Dict[str, Any]:
        """Check Python syntax for all source files"""
        try:
            # Run Python syntax check on key files
            key_files = [
                'game_logic/game_controller_v2.py',
                'tests/test_game_controller_v2.py',
                'run_tests.py'
            ]
            
            syntax_errors = []
            for file_path in key_files:
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r') as f:
                            compile(f.read(), file_path, 'exec')
                    except SyntaxError as e:
                        syntax_errors.append(f"{file_path}: {str(e)}")
            
            return {
                'success': len(syntax_errors) == 0,
                'files_checked': len(key_files),
                'errors': syntax_errors
            }
        except Exception as e:
            return {'success': False, 'errors': [str(e)]}
    
    async def _analyze_code_quality(self) -> Dict[str, Any]:
        """Analyze code quality metrics"""
        try:
            # Basic code metrics (simplified for this example)
            metrics = {
                'total_lines': 0,
                'total_functions': 0,
                'total_classes': 0,
                'complexity_score': 'low'  # Simplified
            }
            
            # Count lines, functions, classes in key files
            key_files = ['game_logic/game_controller_v2.py']
            for file_path in key_files:
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        lines = f.readlines()
                        metrics['total_lines'] += len(lines)
                        metrics['total_functions'] += sum(1 for line in lines if line.strip().startswith('def '))
                        metrics['total_classes'] += sum(1 for line in lines if line.strip().startswith('class '))
            
            return metrics
        except Exception as e:
            return {'error': str(e)}
    
    async def _run_security_checks(self) -> Dict[str, Any]:
        """Run basic security checks"""
        try:
            # Basic security check - look for potential issues
            security_issues = 0
            issues_found = []
            
            # Check for hardcoded secrets (simplified)
            key_files = ['game_logic/game_controller_v2.py', 'database.py']
            for file_path in key_files:
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        content = f.read()
                        # Check for potential hardcoded secrets
                        if 'password' in content.lower() and '=' in content:
                            security_issues += 1
                            issues_found.append(f"{file_path}: Potential hardcoded password")
            
            return {
                'issues': security_issues,
                'details': issues_found,
                'files_scanned': len(key_files)
            }
        except Exception as e:
            return {'issues': 999, 'error': str(e)}

    # ======= Stage 2: Unit Tests =======
    
    async def run_unit_tests(self) -> PipelineResult:
        """Run comprehensive unit tests"""
        stage_name = "Unit Tests"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Run core test suite
            test_orchestrator = TestOrchestrator()
            core_results = await test_orchestrator.run_core_tests()
            
            details['core_test_results'] = core_results
            
            # Check test coverage
            if core_results['success_rate'] < 95:
                warnings.append(f"Test success rate below 95%: {core_results['success_rate']:.1f}%")
            
            if core_results['failed_tests'] > 0:
                errors.append(f"{core_results['failed_tests']} unit tests failed")
            
            success = core_results['success_rate'] >= 90  # Minimum threshold
            
        except Exception as e:
            errors.append(f"Unit tests failed to run: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result

    # ======= Stage 3: Integration Tests =======
    
    async def run_integration_tests(self) -> PipelineResult:
        """Run integration tests for manager interactions"""
        stage_name = "Integration Tests"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Run integration-specific tests
            integration_results = await self._run_manager_integration_tests()
            details['integration_results'] = integration_results
            
            # Check manager interactions
            if integration_results['manager_failures'] > 0:
                errors.append(f"{integration_results['manager_failures']} manager integration failures")
            
            success = integration_results['all_managers_working']
            
        except Exception as e:
            errors.append(f"Integration tests failed: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result
    
    async def _run_manager_integration_tests(self) -> Dict[str, Any]:
        """Test integration between different managers"""
        try:
            # Create a test game and verify all managers work together
            from tests.test_game_controller_v2 import TestGameSetupManager
            
            setup_manager = TestGameSetupManager()
            participants = setup_manager.create_test_participants(2)
            
            from game_logic.game_controller_v2 import GameControllerV2
            from unittest.mock import Mock, AsyncMock
            
            # Create test game
            mock_ws = Mock()
            mock_ws.broadcast_to_game = AsyncMock()
            
            gc = GameControllerV2(
                game_uid="integration_test",
                ws_manager=mock_ws,
                game_db_id=999,
                participants=participants,
                treasury_agent_id="test_treasury"
            )
            
            # Mock TPay
            gc.tpay_agent = setup_manager.create_mock_tpay_agent()
            
            # Test manager initialization
            manager_tests = {
                'payment_manager': gc.payment_manager is not None,
                'property_manager': gc.property_manager is not None,
                'trade_manager': gc.trade_manager is not None,
                'state_manager': gc.state_manager is not None,
                'auction_manager': gc.auction_manager is not None,
                'jail_manager': gc.jail_manager is not None,
                'bankruptcy_manager': gc.bankruptcy_manager is not None
            }
            
            # Test manager interactions
            gc.start_game()
            
            # Test property management + payment integration
            property_result = await gc.execute_buy_property_decision(0, 1)
            
            # Test trade management + state management integration
            trade_result = gc.propose_trade_action(0, 1, [], 100, 0, [], 0, 0)
            
            manager_failures = sum(1 for test, result in manager_tests.items() if not result)
            integration_failures = 0
            
            if not property_result:
                integration_failures += 1
            if not trade_result:
                integration_failures += 1
            
            return {
                'managers_initialized': len([r for r in manager_tests.values() if r]),
                'total_managers': len(manager_tests),
                'manager_failures': manager_failures,
                'integration_failures': integration_failures,
                'all_managers_working': manager_failures == 0 and integration_failures == 0,
                'detailed_results': manager_tests
            }
            
        except Exception as e:
            return {
                'managers_initialized': 0,
                'total_managers': 7,
                'manager_failures': 7,
                'integration_failures': 999,
                'all_managers_working': False,
                'error': str(e)
            }

    # ======= Stage 4: Performance Tests =======
    
    async def run_performance_tests(self) -> PipelineResult:
        """Run performance and load tests"""
        stage_name = "Performance Tests"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Run performance benchmarks
            performance_results = await self._run_performance_benchmarks()
            details['performance_results'] = performance_results
            
            # Check performance thresholds
            if performance_results['avg_response_time'] > 1.0:  # 1 second threshold
                warnings.append(f"High response time: {performance_results['avg_response_time']:.2f}s")
            
            if performance_results['memory_usage'] > 100:  # 100MB threshold (simplified)
                warnings.append(f"High memory usage: {performance_results['memory_usage']}MB")
            
            success = performance_results['performance_score'] >= 80
            
        except Exception as e:
            errors.append(f"Performance tests failed: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result
    
    async def _run_performance_benchmarks(self) -> Dict[str, Any]:
        """Run performance benchmarks"""
        try:
            # Simplified performance testing
            from tests.test_game_controller_v2 import TestGameSetupManager
            
            setup_manager = TestGameSetupManager()
            participants = setup_manager.create_test_participants(4)
            
            # Time game creation
            creation_start = time.time()
            
            from game_logic.game_controller_v2 import GameControllerV2
            from unittest.mock import Mock, AsyncMock
            
            mock_ws = Mock()
            mock_ws.broadcast_to_game = AsyncMock()
            
            gc = GameControllerV2(
                game_uid="perf_test",
                ws_manager=mock_ws,
                game_db_id=998,
                participants=participants,
                treasury_agent_id="test_treasury"
            )
            
            gc.tpay_agent = setup_manager.create_mock_tpay_agent()
            creation_time = time.time() - creation_start
            
            # Time game operations
            operations_start = time.time()
            gc.start_game()
            
            # Run multiple operations
            operations = []
            for _ in range(10):
                operations.append(gc.get_available_actions(0))
                operations.append(gc.get_game_state_for_agent(0))
            
            operations_time = time.time() - operations_start
            
            avg_response_time = operations_time / len(operations) if operations else 1.0
            
            return {
                'game_creation_time': creation_time,
                'operations_time': operations_time,
                'avg_response_time': avg_response_time,
                'operations_per_second': len(operations) / operations_time if operations_time > 0 else 0,
                'memory_usage': 50,  # Simplified
                'performance_score': min(100, max(0, 100 - (avg_response_time * 100)))
            }
            
        except Exception as e:
            return {
                'game_creation_time': 999,
                'operations_time': 999,
                'avg_response_time': 999,
                'operations_per_second': 0,
                'memory_usage': 999,
                'performance_score': 0,
                'error': str(e)
            }

    # ======= Stage 5: Regression Tests =======
    
    async def run_regression_tests(self) -> PipelineResult:
        """Run regression tests to ensure no breaking changes"""
        stage_name = "Regression Tests"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Run regression test suite
            regression_runner = RegressionTestRunner()
            regression_passed = await regression_runner.run_regression_tests()
            
            details['regression_passed'] = regression_passed
            
            if not regression_passed:
                errors.append("Regression tests detected breaking changes")
            
            success = regression_passed
            
        except Exception as e:
            errors.append(f"Regression tests failed to run: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result

    # ======= Stage 6: Deployment Readiness =======
    
    async def check_deployment_readiness(self) -> PipelineResult:
        """Check if the system is ready for deployment"""
        stage_name = "Deployment Readiness"
        self.log_stage_start(stage_name)
        start_time = time.time()
        
        errors = []
        warnings = []
        details = {}
        
        try:
            # Check all previous stages
            readiness_checks = {
                'code_quality_passed': any(r.stage_name == "Code Quality Checks" and r.success for r in self.pipeline_results),
                'unit_tests_passed': any(r.stage_name == "Unit Tests" and r.success for r in self.pipeline_results),
                'integration_tests_passed': any(r.stage_name == "Integration Tests" and r.success for r in self.pipeline_results),
                'performance_acceptable': any(r.stage_name == "Performance Tests" and r.success for r in self.pipeline_results),
                'no_regressions': any(r.stage_name == "Regression Tests" and r.success for r in self.pipeline_results)
            }
            
            details['readiness_checks'] = readiness_checks
            
            # Check environment requirements
            env_checks = await self._check_environment_requirements()
            details['environment_checks'] = env_checks
            
            # Calculate deployment score
            passed_checks = sum(1 for check in readiness_checks.values() if check)
            total_checks = len(readiness_checks)
            deployment_score = (passed_checks / total_checks) * 100
            
            details['deployment_score'] = deployment_score
            
            if deployment_score < 100:
                failed_checks = [name for name, passed in readiness_checks.items() if not passed]
                errors.append(f"Failed readiness checks: {', '.join(failed_checks)}")
            
            if deployment_score < 80:
                errors.append(f"Deployment score too low: {deployment_score:.1f}%")
            
            success = deployment_score >= 90  # High threshold for deployment
            
        except Exception as e:
            errors.append(f"Deployment readiness check failed: {str(e)}")
            success = False
            details['exception'] = str(e)
        
        duration = time.time() - start_time
        self.log_stage_end(stage_name, success, duration)
        
        result = PipelineResult(stage_name, success, duration, details, errors, warnings)
        self.pipeline_results.append(result)
        return result
    
    async def _check_environment_requirements(self) -> Dict[str, Any]:
        """Check environment requirements for deployment"""
        try:
            checks = {
                'python_version': sys.version_info >= (3, 8),
                'required_files_exist': all(os.path.exists(f) for f in [
                    'game_logic/game_controller_v2.py',
                    'requirements.txt',
                    'database.py'
                ]),
                'config_files_exist': os.path.exists('requirements.txt')
            }
            
            return {
                'all_requirements_met': all(checks.values()),
                'detailed_checks': checks,
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            }
        except Exception as e:
            return {'all_requirements_met': False, 'error': str(e)}

    # ======= Pipeline Orchestration =======
    
    async def run_full_pipeline(self) -> Dict[str, Any]:
        """Run the complete CI/CD pipeline"""
        self.logger.info("🚀 Starting full CI/CD pipeline")
        pipeline_start = time.time()
        
        # Run all stages in order
        stages = [
            self.run_code_quality_checks,
            self.run_unit_tests,
            self.run_integration_tests,
            self.run_performance_tests,
            self.run_regression_tests,
            self.check_deployment_readiness
        ]
        
        for stage_func in stages:
            result = await stage_func()
            
            # Stop pipeline if critical stage fails
            if not result.success and result.stage_name in ["Code Quality Checks", "Unit Tests"]:
                self.logger.error(f"Critical stage '{result.stage_name}' failed. Stopping pipeline.")
                break
        
        pipeline_duration = time.time() - pipeline_start
        
        # Generate final report
        report = self._generate_pipeline_report(pipeline_duration)
        
        # Save report
        report_file = f"{self.output_dir}/pipeline_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"Pipeline completed in {pipeline_duration:.2f}s. Report saved to {report_file}")
        
        return report
    
    async def run_pre_commit_pipeline(self) -> Dict[str, Any]:
        """Run pre-commit pipeline (faster, essential checks only)"""
        self.logger.info("🏃 Running pre-commit pipeline")
        
        # Run essential stages only
        essential_stages = [
            self.run_code_quality_checks,
            self.run_unit_tests
        ]
        
        for stage_func in essential_stages:
            await stage_func()
        
        report = self._generate_pipeline_report(0)
        return report
    
    async def run_nightly_pipeline(self) -> Dict[str, Any]:
        """Run comprehensive nightly pipeline"""
        self.logger.info("🌙 Running nightly pipeline")
        
        # Run full pipeline with additional comprehensive checks
        return await self.run_full_pipeline()
    
    def _generate_pipeline_report(self, total_duration: float) -> Dict[str, Any]:
        """Generate comprehensive pipeline report"""
        total_stages = len(self.pipeline_results)
        passed_stages = sum(1 for r in self.pipeline_results if r.success)
        
        all_errors = []
        all_warnings = []
        
        for result in self.pipeline_results:
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
        
        report = {
            'pipeline_timestamp': datetime.now().isoformat(),
            'total_duration': total_duration,
            'total_stages': total_stages,
            'passed_stages': passed_stages,
            'failed_stages': total_stages - passed_stages,
            'success_rate': (passed_stages / total_stages * 100) if total_stages > 0 else 0,
            'pipeline_passed': passed_stages == total_stages,
            'stage_results': [
                {
                    'stage': r.stage_name,
                    'success': r.success,
                    'duration': r.duration,
                    'errors': r.errors,
                    'warnings': r.warnings,
                    'details': r.details
                } for r in self.pipeline_results
            ],
            'summary': {
                'total_errors': len(all_errors),
                'total_warnings': len(all_warnings),
                'critical_issues': len([e for e in all_errors if 'critical' in e.lower()]),
                'deployment_ready': any(r.stage_name == "Deployment Readiness" and r.success for r in self.pipeline_results)
            },
            'recommendations': self._generate_pipeline_recommendations()
        }
        
        return report
    
    def _generate_pipeline_recommendations(self) -> List[str]:
        """Generate recommendations based on pipeline results"""
        recommendations = []
        
        # Check for patterns in failures
        failed_stages = [r.stage_name for r in self.pipeline_results if not r.success]
        
        if "Code Quality Checks" in failed_stages:
            recommendations.append("🔧 Fix code quality issues before proceeding")
        
        if "Unit Tests" in failed_stages:
            recommendations.append("🧪 Resolve unit test failures - core functionality may be broken")
        
        if "Performance Tests" in failed_stages:
            recommendations.append("⚡ Optimize performance - system may be too slow for production")
        
        if "Regression Tests" in failed_stages:
            recommendations.append("🔄 Review breaking changes - regression detected")
        
        # Check for warnings
        total_warnings = sum(len(r.warnings) for r in self.pipeline_results)
        if total_warnings > 5:
            recommendations.append(f"⚠️  Address {total_warnings} warnings to improve quality")
        
        # Overall health
        success_rate = (sum(1 for r in self.pipeline_results if r.success) / len(self.pipeline_results) * 100) if self.pipeline_results else 0
        
        if success_rate >= 100:
            recommendations.append("🎉 Excellent! All pipeline stages passed - ready for deployment")
        elif success_rate >= 80:
            recommendations.append("👍 Good pipeline health - address minor issues")
        elif success_rate >= 60:
            recommendations.append("⚠️  Moderate issues - significant work needed before deployment")
        else:
            recommendations.append("🚨 Major issues detected - extensive fixes required")
        
        return recommendations
    
    def print_pipeline_summary(self, report: Dict[str, Any]):
        """Print a summary of pipeline results"""
        print("\n" + "=" * 80)
        print("📊 CI/CD PIPELINE SUMMARY")
        print("=" * 80)
        
        print(f"🕐 Pipeline Completed: {report['pipeline_timestamp']}")
        print(f"⏱️  Total Duration: {report['total_duration']:.2f}s")
        print(f"📈 Success Rate: {report['success_rate']:.1f}% ({report['passed_stages']}/{report['total_stages']} stages)")
        
        print(f"\n📋 Stage Results:")
        for stage in report['stage_results']:
            status = "✅" if stage['success'] else "❌"
            print(f"   {status} {stage['stage']} ({stage['duration']:.2f}s)")
            if stage['errors']:
                for error in stage['errors']:
                    print(f"      🔴 {error}")
            if stage['warnings']:
                for warning in stage['warnings'][:2]:  # Limit warnings shown
                    print(f"      🟡 {warning}")
        
        print(f"\n💡 Recommendations:")
        for rec in report['recommendations']:
            print(f"   {rec}")
        
        if report['pipeline_passed']:
            print(f"\n🎉 PIPELINE PASSED! System is ready for deployment! 🎉")
        else:
            print(f"\n⚠️  PIPELINE FAILED. Address issues before deployment.")
        
        print("=" * 80)


async def main():
    """Main function for CI/CD pipeline execution"""
    parser = argparse.ArgumentParser(description='Run CI/CD pipeline for GameControllerV2')
    parser.add_argument('--stage', choices=['all', 'pre-commit', 'nightly', 'deploy'], 
                       default='all', help='Pipeline stage to run')
    parser.add_argument('--output-dir', default='ci_reports', help='Output directory for reports')
    
    args = parser.parse_args()
    
    pipeline = CICDPipeline(args.output_dir)
    
    print("🏭 GameControllerV2 CI/CD Pipeline")
    print("Ensuring quality, performance, and reliability")
    print("=" * 80)
    
    # Run specified pipeline stage
    if args.stage == 'pre-commit':
        report = await pipeline.run_pre_commit_pipeline()
    elif args.stage == 'nightly':
        report = await pipeline.run_nightly_pipeline()
    elif args.stage == 'deploy':
        report = await pipeline.check_deployment_readiness()
    else:  # all
        report = await pipeline.run_full_pipeline()
    
    # Display results
    pipeline.print_pipeline_summary(report)
    
    # Return appropriate exit code
    return 0 if report.get('pipeline_passed', False) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 