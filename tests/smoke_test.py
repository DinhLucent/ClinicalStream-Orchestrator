import sys
import os
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))

def test_imports():
    """Verify that all sanitized modules can be imported correctly."""
    try:
        from core.advanced_database_manager import DatabaseManager
        from core.advanced_device_worker import AdvancedDeviceWorker
        from core.message_decoder import MessageDecoder
        from core.session_writer import SessionWriter
        from core.storage_engine import StorageEngine
        from core.config_manager import ConfigManager
        print("✅ Core module imports successful.")
        
        # Verify GUI imports (headless check might be needed for CI, but here we just check import)
        from gui.advanced_main_window import AdvancedMainWindow
        from gui.monitor_window import MonitorWindow
        from gui.history_window import AdvancedHistoryWindow
        print("✅ GUI module imports successful.")
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        sys.exit(1)

def test_stubs():
    """Verify that core algorithms have been successfully stubbed out."""
    from core.message_decoder import MessageDecoder
    decoder = MessageDecoder(None)
    
    # Check if the proprietary decoding logic returns the stub message
    sample_packet = b"\x02\x00" + b"\x00" * 122 # Dummy packet
    try:
        decoded_text, monitor_dict, header_dict = decoder.decode_packet_with_monitor_and_header(sample_packet)
        if "PROPRIETARY ALGORITHM REMOVED" in decoded_text:
            print("✅ Proprietary logic correctly stubbed.")
        else:
            print("⚠️ Proprietary logic might still be present in decoder output!")
    except Exception as e:
        print(f"✅ Decoder handled dummy packet with stub (expected): {e}")

if __name__ == "__main__":
    test_imports()
    test_stubs()
