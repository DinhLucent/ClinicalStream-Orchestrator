#!/usr/bin/env python3
"""
ClinicalStream Device Manager v2.0 - Main Entry Point
Advanced version với production-ready features
"""

import sys
import os
import logging
import argparse
from pathlib import Path
import traceback

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def setup_logging(log_level: str = "INFO", log_file: str = None):
    """Setup logging configuration"""
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Default log file
    if log_file is None:
        log_file = log_dir / "ClinicalStream_manager.log"
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set up Qt logging
    os.environ['QT_LOGGING_RULES'] = '*=false'  # Suppress Qt debug messages

def check_dependencies():
    """Kiểm tra dependencies"""
    required_modules = [
        'PySide6',
        'sqlite3'
    ]
    
    optional_modules = [
        ('matplotlib', 'Chart functionality'),
        ('pandas', 'Data export to Excel'),
        ('psutil', 'System monitoring')
    ]
    
    missing_required = []
    missing_optional = []
    
    # Check required modules
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_required.append(module)
    
    # Check optional modules
    for module, description in optional_modules:
        try:
            __import__(module)
        except ImportError:
            missing_optional.append((module, description))
    
    if missing_required:
        print(f"❌ Missing required dependencies: {', '.join(missing_required)}")
        print("Please install them with: pip install -r requirements.txt")
        return False
    
    if missing_optional:
        print("⚠️  Missing optional dependencies:")
        for module, description in missing_optional:
            print(f"   - {module}: {description}")
        print("Install with: pip install matplotlib pandas psutil")
    
    return True

def check_environment():
    """Kiểm tra environment"""
    issues = []
    
    # Check Python version
    if sys.version_info < (3, 8):
        issues.append(f"Python 3.8+ required, got {sys.version}")
    
    # Check write permissions
    test_dirs = ["logs", "data", "config"]
    for dir_name in test_dirs:
        test_dir = Path(dir_name)
        try:
            test_dir.mkdir(exist_ok=True)
            test_file = test_dir / "test_write.tmp"
            test_file.write_text("test")
            test_file.unlink()
        except Exception as e:
            issues.append(f"Cannot write to {dir_name}: {e}")
    
    # Check reference database
    ref_db_locations = [
        Path("ClinicalStream_reference.db"),
        Path("../ClinicalStream_reference.db"),
        Path("../../ClinicalStream_reference.db")
    ]
    
    ref_db_found = False
    for ref_db in ref_db_locations:
        if ref_db.exists():
            ref_db_found = True
            break
    
    if not ref_db_found:
        issues.append(f"Reference database not found in any of: {[str(p) for p in ref_db_locations]}")
    
    return issues

def run_gui_app():
    """Chạy GUI application"""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        
        # Create QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("ClinicalStream Device Manager")
        app.setApplicationVersion("2.0")
        app.setApplicationDisplayName("ClinicalStream Device Manager v2.0")
        
        # Set application properties  
        # Note: AA_EnableHighDpiScaling is deprecated in Qt6, but kept for compatibility
        try:
            app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        except AttributeError:
            pass  # Attribute doesn't exist in newer Qt versions
        app.setStyle("Fusion")
        
        # Initialize config manager
        from core.config_manager import init_config_manager
        config_manager = init_config_manager()
        
        # Create main window
        from gui.advanced_main_window import AdvancedMainWindow
        window = AdvancedMainWindow()
        window.show()
        
        logging.info("GUI application started")
        
        # Run application
        exit_code = app.exec()
        
        logging.info(f"GUI application exited with code: {exit_code}")
        return exit_code
        
    except Exception as e:
        logging.error(f"Error running GUI application: {e}")
        logging.error(traceback.format_exc())
        return 1



def run_tests():
    """Chạy unit tests"""
    try:
        import unittest
        
        # Discover and run tests
        loader = unittest.TestLoader()
        start_dir = Path(__file__).parent / "tests"
        
        if start_dir.exists():
            suite = loader.discover(str(start_dir))
            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(suite)
            
            return 0 if result.wasSuccessful() else 1
        else:
            print("No tests directory found")
            return 1
            
    except Exception as e:
        logging.error(f"Error running tests: {e}")
        return 1

def run_config_tool(args):
    """Chạy config management tool"""
    try:
        from core.config_manager import ConfigManager
        
        config_manager = ConfigManager()
        
        if args.config_action == "validate":
            errors = config_manager.validate_config()
            if errors:
                print("❌ Configuration errors:")
                for error in errors:
                    print(f"   - {error}")
                return 1
            else:
                print("✅ Configuration is valid")
                return 0
        
        elif args.config_action == "backup":
            backup_path = config_manager.backup_configs()
            if backup_path:
                print(f"✅ Configuration backed up to: {backup_path}")
                return 0
            else:
                print("❌ Backup failed")
                return 1
        
        elif args.config_action == "reset":
            if input("Are you sure you want to reset configuration to defaults? (y/N): ").lower() == 'y':
                config_manager.reset_to_defaults()
                print("✅ Configuration reset to defaults")
                return 0
            else:
                print("Cancelled")
                return 0
        
        elif args.config_action == "export":
            if args.export_file:
                config_manager.export_config(args.export_file)
                print(f"✅ Configuration exported to: {args.export_file}")
                return 0
            else:
                print("❌ Export file not specified")
                return 1
        
        elif args.config_action == "import":
            if args.import_file:
                config_manager.import_config(args.import_file)
                print(f"✅ Configuration imported from: {args.import_file}")
                return 0
            else:
                print("❌ Import file not specified")
                return 1
                
    except Exception as e:
        logging.error(f"Error in config tool: {e}")
        return 1

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="ClinicalStream Device Manager v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Start GUI application
  %(prog)s --tests                  # Run unit tests
  %(prog)s --config validate        # Validate configuration
  %(prog)s --config backup          # Backup configuration
        """
    )
    
    # General options
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='Log level')
    parser.add_argument('--log-file', help='Log file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--tests', action='store_true', help='Run unit tests')
    mode_group.add_argument('--config', choices=['validate', 'backup', 'reset', 'export', 'import'],
                           help='Configuration management')
    
    # Config options
    parser.add_argument('--export-file', help='Export config to file')
    parser.add_argument('--import-file', help='Import config from file')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level, args.log_file)
    
    logger = logging.getLogger(__name__)
    logger.info("ClinicalStream Device Manager v2.0 starting...")
    
    # Check dependencies
    if not check_dependencies():
        return 1
    
    # Check environment
    issues = check_environment()
    if issues:
        logger.warning("Environment issues detected:")
        for issue in issues:
            logger.warning(f"  - {issue}")
        
        if any("Reference database" in issue for issue in issues):
            logger.error("Critical: Reference database missing")
            return 1
    
    try:
        # Route to appropriate function
        if args.tests:
            return run_tests()
        elif args.config:
            return run_config_tool(args)
        else:
            # Default: run GUI
            return run_gui_app()
            
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
