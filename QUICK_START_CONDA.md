# 🚀 Quick Start with Conda Environment

## 📋 Rapid Setup Guide

### Step 1: Environment Setup (One-time)

```bash
# Run automated setup script
setup_conda.bat

# Or manual setup:
conda create -n clinicalstream python=3.9 -y
conda activate clinicalstream  
pip install PySide6 matplotlib pandas psutil pytest
```

### Step 2: Running the Application

```bash
# Option 1: Using the launcher (Recommended)
run_ClinicalStream.bat

# Option 2: Manual execution
conda activate clinicalstream
python src/main.py
```

## 🎯 Execution Modes

### GUI Mode (Default)
```bash
run_ClinicalStream.bat
# or
run_ClinicalStream.bat gui
```

### Simulator Mode
```bash
# Single device simulator
run_ClinicalStream.bat simulator

# Multi-device simulator  
run_ClinicalStream.bat simulator multi

# Custom simulator
run_ClinicalStream.bat simulator custom
```

### Test Mode
```bash
run_ClinicalStream.bat test
```

### Configuration Management
```bash
# Validate configuration
run_ClinicalStream.bat config validate

# Backup configuration
run_ClinicalStream.bat config backup
```

## 🔧 Troubleshooting

### "Reference database not found"
```bash
# Copy file from reference directory
copy ..\ClinicalStream_reference.db .

# Or test using the built-in simulator
run_ClinicalStream.bat simulator
```

### "Conda environment not found"
```bash
# Re-run the setup script
setup_conda.bat
```

### "Import errors"
```bash
# Reinstall dependencies
conda activate clinicalstream
pip install --upgrade PySide6 matplotlib pandas psutil
```

### Debug Mode
```bash
# Run with debug logging enabled
conda activate clinicalstream
python src/main.py --log-level DEBUG
```

## 📁 Project Structure

```
src/
├── core/             # Core orchestration logic
├── gui/              # UI components
└── main.py           # Main application entry
configs/              # JSON configurations
schema/               # Database SQL schemas
tests/                # Unit & Integration tests
```

## 🏥 Production Usage

1. **Setup environment**: `setup_conda.bat`
2. **Daily operation**: `run_ClinicalStream.bat`
3. **Monitor activity**: Check `logs/` directory
4. **Data preservation**: `run_ClinicalStream.bat config backup`

## 💡 Engineering Tips

- Create a desktop shortcut for `run_ClinicalStream.bat` for quick access.
- Deploy in startup folder for automatic clinical monitoring.
- Use Task Scheduler for automated production maintenance.
- Monitor system resources using the integrated performance tracker.
