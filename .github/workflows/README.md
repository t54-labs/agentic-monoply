# 🚀 GitHub Actions Automated Testing

This directory contains GitHub Actions workflow configurations for the **Monopoly** project.

## 📁 Workflow Files

### 1. `monopoly-tests.yml` – Core Testing Workflow ⭐ **Recommended**

* **Purpose**: Dedicated to running the GameControllerV2 test suite
* **Triggers**: On push to `main`, `master`, or `develop` branches, or on Pull Request creation
* **Tests Included**:

     * ✅ Full GameControllerV2 test suite (17 test cases)
   * ✅ Trade negotiation tests (includes reject → renegotiate → accept flow)
   * ✅ Local tpay SDK installation from `dist/tpay-0.1.1.tar.gz`
   * ✅ Additional validation using `pytest`
* **Benefits**: Fast, focused, and easy to understand

### 2. `test.yml` – Full Workflow

* **Purpose**: Comprehensive code quality checks and tests
* **Includes**:

  * 🧪 Multi-version Python testing (3.9, 3.10, 3.11)
  * 🎨 Code formatting checks (Black, isort)
  * 🔍 Code linting (flake8)
  * 🔒 Security scanning (Bandit, Safety)
* **Benefits**: Thorough, professional, production-grade

## 🚀 How to Enable

1. **Commit files to GitHub**:

   ```bash
   git add .github/
   git commit -m "Add GitHub Actions workflows for automated testing"
   git push origin main
   ```

2. **View results**:

   * Go to your GitHub repository
   * Click the **Actions** tab
   * View the status of workflow runs

## 📊 Test Results

### Example: All Tests Passed

```
🎉 ALL TESTS PASSED! GameControllerV2 is ready for production.
📊 Test Results Summary:
   Total Tests: 17
   Passed: 17
   Failed: 0
   Success Rate: 100.0%
```

### If Tests Fail

* Click the failed workflow to view detailed logs
* Identify which specific test failed
* Fix the code and push again

## 📦 Local Dependencies

This project uses a local **tpay SDK** that is not available on PyPI:

* **Package**: `dist/tpay-0.1.1.tar.gz`
* **Installation**: Automatically handled by GitHub Actions
* **Local Development**: Run `pip install dist/tpay-0.1.1.tar.gz` after installing requirements.txt

### Important Notes
* The `dist/` directory is **included in the repository** (not gitignored)
* GitHub Actions will automatically install the local tpay package after standard dependencies
* If you update the tpay package, commit the new `.tar.gz` file to the `dist/` directory

## 🔧 Custom Configuration

### Modify Trigger Branches

In the `.yml` file:

```yaml
on:
  push:
    branches: [ main, your-branch-name ]
```

### Add Environment Variables

```yaml
- name: Set environment variables
  run: |
    export YOUR_VAR=value
```

### Change Python Version

```yaml
- name: Set up Python
  uses: actions/setup-python@v4
  with:
    python-version: "3.11"  # Change to your desired version
```

## 🎯 Recommended Workflow Usage

1. **Development Phase**: Use `monopoly-tests.yml` (for quick feedback)
2. **Pre-Release Checks**: Use `test.yml` (for full validation)
3. **Hotfixes**: You can just run the core tests

## 📈 GitHub Actions Features

* ✅ **Auto-triggered**: Runs on every push and PR
* ✅ **Parallel execution**: Tests can run simultaneously
* ✅ **Result notifications**: Failures show up directly in PRs
* ✅ **History tracking**: View full workflow run history
* ✅ **Status badges**: Display test status in your README

## 🏷️ Add a Status Badge

Add this to your `README.md`:

```markdown
![Tests](https://github.com/your-username/monopoly/workflows/🎮%20Monopoly%20Game%20Tests/badge.svg)
```

## 🛠️ Troubleshooting

### Common Issues

1. **Dependency install failure**: Check if `requirements.txt` is correct
2. **Test timeout**: Consider increasing timeout duration
3. **Permission errors**: Ensure Actions are enabled in repo settings

### Debug Tips

* Add `echo` statements in your test steps for debug info
* Use `if: always()` to run specific steps even after failure
* Check detailed output in Actions logs
