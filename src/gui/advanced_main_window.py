#!/usr/bin/env python3
"""
Advanced Main Window cho ClinicalStream Device Manager
- Device management table
- Auto-connect functionality  
- Multi-threading per device
- Performance monitoring
"""

import sys
import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QHeaderView, QInputDialog, 
    QMessageBox, QSplitter, QLabel, QLineEdit, QCheckBox,
    QGroupBox, QSpinBox, QComboBox, QProgressBar, QTextEdit,
    QDialog, QGridLayout, QFrame, QTabWidget, QApplication
)
from PySide6.QtCore import QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QFont, QAction, QIcon, QPixmap

from core.advanced_database_manager import DatabaseManager, DeviceConfig
from core.advanced_device_worker import AdvancedDeviceWorker
from core.message_decoder import MessageDecoder, load_reference_data
from core.session_writer import SessionConfig
from gui.monitor_window import AdvancedMonitorWindow
from gui.history_window import AdvancedHistoryWindow

logger = logging.getLogger(__name__)

class QTextEditLogHandler(logging.Handler):
    """Custom logging handler để hiển thị logs trong QTextEdit"""
    
    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self.text_edit = text_edit
        self.setLevel(logging.INFO)
        
        # Format cho log messages
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.setFormatter(formatter)
    
    def emit(self, record):
        """Emit log record vào QTextEdit"""
        try:
            msg = self.format(record)
            
            # Màu sắc theo log level
            color_map = {
                logging.DEBUG: QColor("gray"),
                logging.INFO: QColor("black"),
                logging.WARNING: QColor("orange"),
                logging.ERROR: QColor("red"),
                logging.CRITICAL: QColor("darkred")
            }
            
            color = color_map.get(record.levelno, QColor("black"))
            
            # Append với màu sắc
            cursor = self.text_edit.textCursor()
            cursor.movePosition(cursor.End)
            self.text_edit.setTextCursor(cursor)
            
            # Format timestamp
            timestamp = datetime.now().strftime('%H:%M:%S')
            formatted_msg = f"{timestamp} - {record.levelname}: {record.getMessage()}"
            
            # Append message
            self.text_edit.append(formatted_msg)
            
            # Auto-scroll to bottom
            scrollbar = self.text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        except Exception as e:
            # Fallback nếu có lỗi
            print(f"Error in log handler: {e}")

class DeviceConfigDialog(QDialog):
    """Dialog để cấu hình thiết bị"""
    
    def __init__(self, device: DeviceConfig = None, parent=None):
        super().__init__(parent)
        self.device = device
        self.setWindowTitle("Cấu hình thiết bị" if device else "Thêm thiết bị mới")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Device info
        form_group = QGroupBox("Thông tin thiết bị")
        form_layout = QGridLayout(form_group)
        
        # Name
        form_layout.addWidget(QLabel("Tên thiết bị:"), 0, 0)
        self.name_edit = QLineEdit()
        form_layout.addWidget(self.name_edit, 0, 1)
        
        # IP
        form_layout.addWidget(QLabel("Địa chỉ IP:"), 1, 0)
        self.ip_edit = QLineEdit()
        form_layout.addWidget(self.ip_edit, 1, 1)
        
        # Port
        form_layout.addWidget(QLabel("Port:"), 2, 0)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(3002)
        form_layout.addWidget(self.port_spin, 2, 1)
        
        # Enabled
        self.enabled_check = QCheckBox("Kích hoạt thiết bị")
        self.enabled_check.setChecked(True)
        form_layout.addWidget(self.enabled_check, 3, 0, 1, 2)
        
        # Auto start
        self.auto_start_check = QCheckBox("Tự động kết nối khi khởi động")
        form_layout.addWidget(self.auto_start_check, 4, 0, 1, 2)
        
        layout.addWidget(form_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        
        self.cancel_button = QPushButton("Hủy")
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # Load existing device data
        if device:
            self.name_edit.setText(device.name)
            self.ip_edit.setText(device.ip)
            self.port_spin.setValue(device.port)
            self.enabled_check.setChecked(device.enabled)
            self.auto_start_check.setChecked(device.auto_start)
            self.name_edit.setReadOnly(True)  # Can't change name
    
    def get_device_config(self) -> DeviceConfig:
        """Lấy cấu hình thiết bị từ form"""
        return DeviceConfig(
            name=self.name_edit.text().strip(),
            ip=self.ip_edit.text().strip(),
            port=self.port_spin.value(),
            enabled=self.enabled_check.isChecked(),
            auto_start=self.auto_start_check.isChecked()
        )

class SystemStatsWidget(QWidget):
    """Widget hiển thị system stats"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_stats)
        self.update_timer.start(2000)  # 2s update
        
    def setup_ui(self):
        layout = QGridLayout(self)
        
        # CPU & Memory
        self.cpu_label = QLabel("CPU: ---%")
        self.memory_label = QLabel("Memory: --- MB")
        self.threads_label = QLabel("Threads: ---")
        
        # Database stats
        self.db_connections_label = QLabel("DB Conn: ---")
        self.active_sessions_label = QLabel("Active Sessions: ---")
        
        # Network stats
        self.total_packets_label = QLabel("Total Packets: ---")
        self.total_bytes_label = QLabel("Total Bytes: ---")
        
        layout.addWidget(QLabel("📊 System Stats"), 0, 0, 1, 2)
        layout.addWidget(self.cpu_label, 1, 0)
        layout.addWidget(self.memory_label, 1, 1)
        layout.addWidget(self.threads_label, 2, 0)
        layout.addWidget(self.db_connections_label, 2, 1)
        layout.addWidget(self.active_sessions_label, 3, 0)
        layout.addWidget(self.total_packets_label, 3, 1)
        
    def update_stats(self):
        """Cập nhật system stats"""
        try:
            import psutil
            import threading
            
            # CPU & Memory
            cpu_percent = psutil.cpu_percent()
            memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
            thread_count = threading.active_count()
            
            self.cpu_label.setText(f"CPU: {cpu_percent:.1f}%")
            self.memory_label.setText(f"Memory: {memory_mb:.1f} MB")
            self.threads_label.setText(f"Threads: {thread_count}")
            
        except ImportError:
            # psutil not available
            import threading
            thread_count = threading.active_count()
            self.threads_label.setText(f"Threads: {thread_count}")

class AdvancedMainWindow(QMainWindow):
    """Advanced Main Window cho ClinicalStream Device Manager"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ClinicalStream Device Manager v2.0")
        self.setMinimumSize(1200, 800)
        
        # Core components
        self.db_manager = None
        self.message_decoder = None
        self.session_config = SessionConfig()
        
        # Device management
        self.devices: List[DeviceConfig] = []
        self.workers: Dict[str, AdvancedDeviceWorker] = {}
        self.threads: Dict[str, QThread] = {}
        
        # Windows
        self.monitor_windows: Dict[str, AdvancedMonitorWindow] = {}
        self.history_window: Optional[AdvancedHistoryWindow] = None
        
        # Performance tracking
        self.total_packets = 0
        self.total_bytes = 0
        
        # Setup
        self._init_logging()
        self._init_database()
        self._init_decoder()
        self._load_config()
        self._setup_ui()
        self._load_devices()
        
        # Auto-start if configured
        QTimer.singleShot(1000, self._auto_start_devices)
        
        logger.info("AdvancedMainWindow initialized")
    
    def _init_logging(self):
        """Khởi tạo logging"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "ClinicalStream_manager.log"),
                logging.StreamHandler()
            ]
        )
    
    def _init_database(self):
        """Khởi tạo database manager"""
        try:
            db_path = "ClinicalStream_manager.db"
            self.db_manager = DatabaseManager(db_path)
            logger.info(f"Database initialized: {db_path}")
        except Exception as e:
            self._show_error("Database Error", f"Không thể khởi tạo database: {e}")
            sys.exit(1)
    
    def _init_decoder(self):
        """Khởi tạo message decoder"""
        try:
            # Tìm reference database
            ref_db_locations = [
                "ClinicalStream_reference.db",
                "../ClinicalStream_reference.db", 
                "../../ClinicalStream_reference.db"
            ]
            
            ref_db_path = None
            for path in ref_db_locations:
                if os.path.exists(path):
                    ref_db_path = path
                    break
            
            if ref_db_path is None:
                self._show_error("Reference Database Missing", 
                               f"Không tìm thấy file reference database trong các vị trí:\n{chr(10).join(ref_db_locations)}\n\n"
                               f"Vui lòng copy file ClinicalStream_reference.db vào thư mục app_code\n"
                               f"hoặc sử dụng simulator để test.")
                sys.exit(1)
            
            reference_data = load_reference_data(ref_db_path)
            self.message_decoder = MessageDecoder(reference_data)
            logger.info(f"Message decoder initialized with database: {ref_db_path}")
        except Exception as e:
            self._show_error("Decoder Error", f"Không thể khởi tạo decoder: {e}")
            sys.exit(1)
    
    def _load_config(self):
        """Load configuration"""
        config_file = Path("manager_config.json")
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                # Update session config
                session_cfg = config.get('session', {})
                self.session_config.flush_interval = session_cfg.get('flush_interval', 12.0)
                self.session_config.max_buffer_size = session_cfg.get('max_buffer_size', 16*1024*1024)
                self.session_config.backup_enabled = session_cfg.get('backup_enabled', True)
                self.session_config.compression_enabled = session_cfg.get('compression_enabled', True)
                
                logger.info("Configuration loaded")
            except Exception as e:
                logger.warning(f"Config load error: {e}")
    
    def _setup_ui(self):
        """Setup user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Top toolbar
        toolbar_layout = QHBoxLayout()
        
        self.add_device_btn = QPushButton("➕ Thêm thiết bị")
        self.add_device_btn.clicked.connect(self.add_device)
        
        self.delete_device_btn = QPushButton("🗑️ Xóa thiết bị")
        self.delete_device_btn.clicked.connect(self.delete_device)
        
        self.start_all_btn = QPushButton("▶️ Khởi động tất cả")
        self.start_all_btn.clicked.connect(self.start_all_devices)
        
        self.stop_all_btn = QPushButton("⏹️ Dừng tất cả")
        self.stop_all_btn.clicked.connect(self.stop_all_devices)
        
        self.history_btn = QPushButton("📋 Lịch sử")
        self.history_btn.clicked.connect(self.show_history)
        
        self.settings_btn = QPushButton("⚙️ Cài đặt")
        self.settings_btn.clicked.connect(self.show_settings)
        
        toolbar_layout.addWidget(self.add_device_btn)
        toolbar_layout.addWidget(self.delete_device_btn)
        toolbar_layout.addWidget(self.start_all_btn)
        toolbar_layout.addWidget(self.stop_all_btn)
        toolbar_layout.addWidget(self.history_btn)
        toolbar_layout.addWidget(self.settings_btn)
        toolbar_layout.addStretch()
        
        main_layout.addLayout(toolbar_layout)
        
        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Device table
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        left_layout.addWidget(QLabel("📱 Thiết bị"))
        
        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(8)
        self.device_table.setHorizontalHeaderLabels([
            "Tên", "IP:Port", "Trạng thái", "Kết nối", "Treatment", 
            "Packets", "Bytes", "Thao tác"
        ])
        
        # Table properties
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.setAlternatingRowColors(True)
        self.device_table.doubleClicked.connect(self.open_monitor_window)
        
        left_layout.addWidget(self.device_table)
        
        # Right panel - Stats & logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # System stats
        self.stats_widget = SystemStatsWidget()
        right_layout.addWidget(self.stats_widget)
        
        # Log viewer
        log_header_layout = QHBoxLayout()
        log_header_layout.addWidget(QLabel("📝 System Log"))
        
        # Log controls
        self.clear_log_btn = QPushButton("🗑️ Clear")
        self.clear_log_btn.clicked.connect(self.clear_log_viewer)
        self.clear_log_btn.setMaximumWidth(80)
        
        self.export_log_btn = QPushButton("💾 Export")
        self.export_log_btn.clicked.connect(self.export_log_viewer)
        self.export_log_btn.setMaximumWidth(80)
        
        # Log level filter
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["ALL", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("ERROR")
        self.log_level_combo.currentTextChanged.connect(self.filter_log_level)
        self.log_level_combo.setMaximumWidth(100)
        
        log_header_layout.addStretch()
        log_header_layout.addWidget(QLabel("Level:"))
        log_header_layout.addWidget(self.log_level_combo)
        log_header_layout.addWidget(self.clear_log_btn)
        log_header_layout.addWidget(self.export_log_btn)
        
        right_layout.addLayout(log_header_layout)
        
        self.log_viewer = QTextEdit()
        self.log_viewer.setMaximumHeight(200)
        self.log_viewer.setReadOnly(True)
        
        # Add custom log handler to QTextEdit
        log_handler = QTextEditLogHandler(self.log_viewer)
        logging.getLogger().addHandler(log_handler)
        
        right_layout.addWidget(self.log_viewer)
        
        # Load initial logs từ file
        self.load_initial_logs()
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([800, 400])
        
        main_layout.addWidget(splitter)
        
        # Status bar
        self.statusBar().showMessage("Sẵn sàng")
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_device_table)
        self.update_timer.start(1000)  # 1s update
    
    def _load_devices(self):
        """Load devices từ database"""
        try:
            self.devices = self.db_manager.get_devices()
            self.update_device_table()
            logger.info(f"Loaded {len(self.devices)} devices")
        except Exception as e:
            self._show_error("Load Devices Error", f"Lỗi load devices: {e}")
    
    def _auto_start_devices(self):
        """Auto-start devices có cấu hình auto_start"""
        auto_start_devices = [d for d in self.devices if d.auto_start and d.enabled]
        
        if auto_start_devices:
            logger.info(f"Auto-starting {len(auto_start_devices)} devices")
            for device in auto_start_devices:
                self.start_device(device)
    
    def update_device_table(self):
        """Cập nhật device table"""
        self.device_table.setRowCount(len(self.devices))
        
        for row, device in enumerate(self.devices):
            # Name
            name_item = QTableWidgetItem(device.name)
            if not device.enabled:
                name_item.setForeground(QBrush(QColor("gray")))
            self.device_table.setItem(row, 0, name_item)
            
            # IP:Port
            ip_port_item = QTableWidgetItem(f"{device.ip}:{device.port}")
            self.device_table.setItem(row, 1, ip_port_item)
            
            # Status & Connection
            worker = self.workers.get(device.name)
            if worker and worker._is_running:
                stats = worker.get_stats()
                
                # Status
                status_text = f"🟢 Đang chạy"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QBrush(QColor("green")))
                
                # Connection
                conn_state = stats.get('connection_state', 'DISCONNECTED')
                conn_colors = {
                    'CONNECTED': ('✅ Kết nối', QColor("green")),
                    'CONNECTING': ('🔄 Kết nối...', QColor("orange")),
                    'RECONNECTING': ('🔄 Kết nối lại...', QColor("orange")),
                    'DISCONNECTED': ('❌ Mất kết nối', QColor("red"))
                }
                conn_text, conn_color = conn_colors.get(conn_state, ('❓ Unknown', QColor("gray")))
                conn_item = QTableWidgetItem(conn_text)
                conn_item.setForeground(QBrush(conn_color))
                
                # Treatment
                treatment_state = stats.get('treatment_state', 'IDLE')
                treatment_colors = {
                    'IDLE': ('⚪ Chờ', QColor("gray")),
                    'RUNNING': ('🔴 Đang ghi', QColor("red")),
                    'ENDING': ('🟡 Kết thúc', QColor("orange")),
                    'ENDED': ('⚫ Hoàn thành', QColor("black"))
                }
                treatment_text, treatment_color = treatment_colors.get(treatment_state, ('❓', QColor("gray")))
                treatment_item = QTableWidgetItem(treatment_text)
                treatment_item.setForeground(QBrush(treatment_color))
                
                # Packets & Bytes
                packets = stats.get('packets_received', 0)
                bytes_received = stats.get('bytes_received', 0)
                
                packets_item = QTableWidgetItem(f"{packets:,}")
                bytes_item = QTableWidgetItem(self._format_bytes(bytes_received))
                
            else:
                # Device stopped
                status_item = QTableWidgetItem("⚫ Đã dừng")
                status_item.setForeground(QBrush(QColor("gray")))
                
                conn_item = QTableWidgetItem("➖ Không kết nối")
                treatment_item = QTableWidgetItem("➖ Không hoạt động")
                packets_item = QTableWidgetItem("0")
                bytes_item = QTableWidgetItem("0 B")
            
            self.device_table.setItem(row, 2, status_item)
            self.device_table.setItem(row, 3, conn_item)
            self.device_table.setItem(row, 4, treatment_item)
            self.device_table.setItem(row, 5, packets_item)
            self.device_table.setItem(row, 6, bytes_item)
            
            # Action buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            
            if worker and worker._is_running:
                stop_btn = QPushButton("⏹️")
                stop_btn.setToolTip("Dừng thiết bị")
                stop_btn.clicked.connect(lambda checked, d=device: self.stop_device(d))
                action_layout.addWidget(stop_btn)
            else:
                start_btn = QPushButton("▶️")
                start_btn.setToolTip("Khởi động thiết bị")
                start_btn.setEnabled(device.enabled)
                start_btn.clicked.connect(lambda checked, d=device: self.start_device(d))
                action_layout.addWidget(start_btn)
            
            monitor_btn = QPushButton("📊")
            monitor_btn.setToolTip("Mở cửa sổ monitor (có thể xem ngay cả khi device chưa chạy)")
            monitor_btn.setEnabled(True)  # Luôn enable để có thể xem monitor
            monitor_btn.clicked.connect(lambda checked, d=device: self.open_monitor_window_for_device(d))
            action_layout.addWidget(monitor_btn)
            
            edit_btn = QPushButton("✏️")
            edit_btn.setToolTip("Chỉnh sửa thiết bị")
            edit_btn.clicked.connect(lambda checked, d=device: self.edit_device(d))
            action_layout.addWidget(edit_btn)
            
            self.device_table.setCellWidget(row, 7, action_widget)
    
    def _format_bytes(self, bytes_value: int) -> str:
        """Format bytes thành human readable"""
        if bytes_value < 1024:
            return f"{bytes_value} B"
        elif bytes_value < 1024**2:
            return f"{bytes_value/1024:.1f} KB"
        elif bytes_value < 1024**3:
            return f"{bytes_value/1024**2:.1f} MB"
        else:
            return f"{bytes_value/1024**3:.1f} GB"
    
    def add_device(self):
        """Thêm thiết bị mới"""
        dialog = DeviceConfigDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            device = dialog.get_device_config()
            
            # Validate
            if not device.name or not device.ip:
                self._show_error("Lỗi nhập liệu", "Tên thiết bị và IP không được để trống")
                return
            
            # Check duplicate
            if any(d.name == device.name for d in self.devices):
                self._show_error("Lỗi trùng lặp", f"Thiết bị '{device.name}' đã tồn tại")
                return
            
            # Add to database
            if self.db_manager.add_device(device):
                self.devices.append(device)
                self.update_device_table()
                self.statusBar().showMessage(f"Đã thêm thiết bị: {device.name}")
                logger.info(f"Added device: {device.name}")
            else:
                self._show_error("Database Error", "Không thể thêm thiết bị vào database")
    
    def delete_device(self):
        """Xóa thiết bị đã chọn"""
        current_row = self.device_table.currentRow()
        if current_row < 0:
            self._show_error("Chưa chọn thiết bị", "Vui lòng chọn thiết bị cần xóa")
            return
        
        # Get selected device
        device_name = self.device_table.item(current_row, 0).text()
        device = next((d for d in self.devices if d.name == device_name), None)
        if not device:
            self._show_error("Lỗi", "Không tìm thấy thiết bị")
            return
        
        # Check if device is running
        worker = self.workers.get(device_name)
        if worker and worker._is_running:
            self._show_error("Thiết bị đang chạy", 
                           f"Không thể xóa thiết bị '{device_name}' khi đang chạy.\nVui lòng dừng thiết bị trước.")
            return
        
        # Confirm deletion
        reply = QMessageBox.question(
            self, "Xác nhận xóa", 
            f"Bạn có chắc chắn muốn xóa thiết bị '{device_name}'?\n\nHành động này không thể hoàn tác.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Delete from database
            if self.db_manager.delete_device(device_name):
                # Remove from memory
                self.devices = [d for d in self.devices if d.name != device_name]
                
                # Clean up worker if exists
                if device_name in self.workers:
                    del self.workers[device_name]
                if device_name in self.threads:
                    del self.threads[device_name]
                
                self.update_device_table()
                self.statusBar().showMessage(f"Đã xóa thiết bị: {device_name}")
                logger.info(f"Deleted device: {device_name}")
            else:
                self._show_error("Lỗi database", "Không thể xóa thiết bị khỏi database")
    
    def edit_device(self, device: DeviceConfig):
        """Chỉnh sửa thiết bị"""
        dialog = DeviceConfigDialog(device, parent=self)
        if dialog.exec() == QDialog.Accepted:
            updated_device = dialog.get_device_config()
            
            # Update in database
            if self.db_manager.update_device(updated_device):
                # Update local list
                for i, d in enumerate(self.devices):
                    if d.name == device.name:
                        self.devices[i] = updated_device
                        break
                
                self.update_device_table()
                self.statusBar().showMessage(f"Đã cập nhật thiết bị: {device.name}")
                logger.info(f"Updated device: {device.name}")
            else:
                self._show_error("Database Error", "Không thể cập nhật thiết bị")
    
    def start_device(self, device: DeviceConfig):
        """Khởi động thiết bị"""
        if device.name in self.workers:
            return  # Already running
        
        try:
            # Create worker
            worker = AdvancedDeviceWorker(
                device.name,
                device.ip,
                device.port,
                self.db_manager,
                self.message_decoder,
                self.session_config
            )
            
            # Create thread
            thread = QThread()
            worker.moveToThread(thread)
            
            # Connect signals
            worker.status_changed.connect(self._on_worker_status_changed)
            worker.connection_state_changed.connect(self._on_worker_connection_changed)
            worker.stats_updated.connect(self._on_worker_stats_updated)
            worker.error_occurred.connect(self._on_worker_error)
            
            # Thread lifecycle
            thread.started.connect(worker.start)
            worker.finished.connect(thread.quit)
            thread.finished.connect(lambda: self._cleanup_worker(device.name))
            
            # Store references
            self.workers[device.name] = worker
            self.threads[device.name] = thread
            
            # Start
            thread.start()
            
            self.statusBar().showMessage(f"Đã khởi động: {device.name}")
            logger.info(f"Started device worker: {device.name}")
            
        except Exception as e:
            self._show_error("Start Error", f"Không thể khởi động thiết bị {device.name}: {e}")
    
    def stop_device(self, device: DeviceConfig):
        """Dừng thiết bị"""
        if device.name not in self.workers:
            return
        
        try:
            worker = self.workers[device.name]
            
            # Set immediate status to show stopping
            self.statusBar().showMessage(f"Đang dừng: {device.name}")
            
            # Stop worker (this will emit finished signal)
            worker.stop()
            
            logger.info(f"Stop signal sent to device worker: {device.name}")
            
        except Exception as e:
            self._show_error("Stop Error", f"Lỗi dừng thiết bị {device.name}: {e}")
            # Force cleanup on error
            self._cleanup_worker(device.name)
    
    def start_all_devices(self):
        """Khởi động tất cả thiết bị enabled"""
        for device in self.devices:
            if device.enabled and device.name not in self.workers:
                self.start_device(device)
    
    def stop_all_devices(self):
        """Dừng tất cả thiết bị"""
        for device in self.devices:
            if device.name in self.workers:
                self.stop_device(device)
    
    def _cleanup_worker(self, device_name: str):
        """Cleanup worker sau khi thread kết thúc"""
        if device_name in self.workers:
            del self.workers[device_name]
        
        if device_name in self.threads:
            thread = self.threads[device_name]
            thread.quit()
            thread.wait(5000)  # Wait max 5s
            del self.threads[device_name]
        
        self.update_device_table()
        logger.info(f"Cleaned up worker: {device_name}")
    
    def open_monitor_window(self, index):
        """Mở monitor window bằng double-click"""
        row = index.row()
        if 0 <= row < len(self.devices):
            device = self.devices[row]
            self.open_monitor_window_for_device(device)
    
    def open_monitor_window_for_device(self, device: DeviceConfig):
        """Mở monitor window cho thiết bị (có thể xem ngay cả khi device chưa chạy)"""
        # Check if device has worker (running) or create dummy worker for viewing
        if device.name in self.workers:
            worker = self.workers[device.name]
        else:
            # Create dummy worker for viewing monitor structure
            from advanced_device_worker import AdvancedDeviceWorker
            worker = AdvancedDeviceWorker(
                device.name, 
                device.ip, 
                device.port, 
                self.db_manager, 
                self.message_decoder
            )
            worker._is_running = False  # Mark as not running
        
        # Create or show existing monitor window
        if device.name not in self.monitor_windows:
            monitor_window = AdvancedMonitorWindow(device, worker, parent=self)
            self.monitor_windows[device.name] = monitor_window
            
            # Cleanup khi đóng window
            monitor_window.finished.connect(lambda: self.monitor_windows.pop(device.name, None))
        
        self.monitor_windows[device.name].show()
        self.monitor_windows[device.name].raise_()
        self.monitor_windows[device.name].activateWindow()
    
    def open_monitor_window_with_ids(self, device: DeviceConfig, specific_ids: List[int]):
        """Mở monitor window cho thiết bị với specific parameter IDs (có thể xem ngay cả khi device chưa chạy)"""
        # Check if device has worker (running) or create dummy worker for viewing
        if device.name in self.workers:
            worker = self.workers[device.name]
        else:
            # Create dummy worker for viewing monitor structure
            from advanced_device_worker import AdvancedDeviceWorker
            worker = AdvancedDeviceWorker(
                device.name, 
                device.ip, 
                device.port, 
                self.db_manager, 
                self.message_decoder
            )
            worker._is_running = False  # Mark as not running
        
        # Create unique window key for this ID set
        window_key = f"{device.name}_ids_{'-'.join(map(str, specific_ids))}"
        
        # Create or show existing monitor window
        if window_key not in self.monitor_windows:
            monitor_window = AdvancedMonitorWindow(device, worker, specific_ids=specific_ids, parent=self)
            self.monitor_windows[window_key] = monitor_window
            
            # Cleanup khi đóng window
            monitor_window.finished.connect(lambda: self.monitor_windows.pop(window_key, None))
        
        self.monitor_windows[window_key].show()
        self.monitor_windows[window_key].raise_()
        self.monitor_windows[window_key].activateWindow()
    
    def show_history(self):
        """Hiển thị history window"""
        if not self.history_window:
            self.history_window = AdvancedHistoryWindow(self.db_manager, self.message_decoder, parent=self)
        
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()
    
    def show_settings(self):
        """Hiển thị settings dialog"""
        # TODO: Implement settings dialog
        QMessageBox.information(self, "Settings", "Settings dialog sẽ được implement sau")
    
    @Slot(str, QColor)
    def _on_worker_status_changed(self, message: str, color: QColor):
        """Handle worker status change"""
        # Update in table will be handled by update_device_table timer
        pass
    
    @Slot(str, QColor)
    def _on_worker_connection_changed(self, message: str, color: QColor):
        """Handle worker connection change"""
        pass
    
    @Slot(dict)
    def _on_worker_stats_updated(self, stats: Dict):
        """Handle worker stats update"""
        # Aggregate total stats
        self.total_packets += stats.get('packets_received', 0) - getattr(self, '_last_packets', {}).get(stats.get('device_name'), 0)
        self.total_bytes += stats.get('bytes_received', 0) - getattr(self, '_last_bytes', {}).get(stats.get('device_name'), 0)
        
        # Store last values
        if not hasattr(self, '_last_packets'):
            self._last_packets = {}
            self._last_bytes = {}
        
        device_name = stats.get('device_name')
        if device_name:
            self._last_packets[device_name] = stats.get('packets_received', 0)
            self._last_bytes[device_name] = stats.get('bytes_received', 0)
    
    @Slot(str, str)
    def _on_worker_error(self, error_type: str, message: str):
        """Handle worker error"""
        self.log_viewer.append(f"{datetime.now().strftime('%H:%M:%S')} - ERROR: {error_type}: {message}")
        
        # Auto-scroll to bottom
        scrollbar = self.log_viewer.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _show_error(self, title: str, message: str):
        """Hiển thị error dialog"""
        QMessageBox.critical(self, title, message)
        logger.error(f"{title}: {message}")
    
    def clear_log_viewer(self):
        """Xóa tất cả logs trong log viewer"""
        self.log_viewer.clear()
        logger.info("Log viewer cleared")
    
    def export_log_viewer(self):
        """Export logs từ log viewer ra file"""
        try:
            from pathlib import Path
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"system_logs_{timestamp}.txt"
            
            # Lấy nội dung từ log viewer
            log_content = self.log_viewer.toPlainText()
            
            # Tạo thư mục logs nếu chưa có
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            
            # Ghi file
            log_file = log_dir / filename
            log_file.write_text(log_content, encoding='utf-8')
            
            QMessageBox.information(self, "Export Success", f"Logs đã được export ra: {log_file}")
            logger.info(f"Logs exported to: {log_file}")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Lỗi khi export logs: {e}")
            logger.error(f"Export logs error: {e}")
    
    def filter_log_level(self, level: str):
        """Filter logs theo level được chọn"""
        try:
            # Lấy tất cả logs từ file log
            log_file = Path("logs/ClinicalStream_manager.log")
            if not log_file.exists():
                return
            
            # Đọc file log
            with open(log_file, 'r', encoding='utf-8') as f:
                all_logs = f.readlines()
            
            # Filter theo level
            if level == "ALL":
                filtered_logs = all_logs
            else:
                filtered_logs = [log for log in all_logs if f" - {level} - " in log]
            
            # Hiển thị logs đã filter (giới hạn 100 dòng cuối)
            filtered_logs = filtered_logs[-100:] if len(filtered_logs) > 100 else filtered_logs
            
            # Clear và hiển thị logs đã filter
            self.log_viewer.clear()
            for log in filtered_logs:
                self.log_viewer.append(log.strip())
            
            logger.info(f"Logs filtered by level: {level}")
            
            # Nếu chọn ERROR, hiển thị thông báo số lượng
            if level == "ERROR":
                error_count = len(filtered_logs)
                if error_count == 0:
                    self.log_viewer.append("✅ Không có ERROR logs nào")
                else:
                    self.log_viewer.append(f"⚠️  Tìm thấy {error_count} ERROR logs")
            
        except Exception as e:
            logger.error(f"Filter logs error: {e}")
    
    def load_initial_logs(self):
        """Load initial logs from the log file"""
        try:
            log_file = Path("logs/ClinicalStream_manager.log")
            if log_file.exists():
                # Mặc định chỉ load ERROR logs
                with open(log_file, 'r', encoding='utf-8') as f:
                    error_logs = [line.strip() for line in f if " - ERROR - " in line]
                    # Giới hạn 50 dòng ERROR logs cuối cùng
                    error_logs = error_logs[-50:] if len(error_logs) > 50 else error_logs
                    for log in error_logs:
                        self.log_viewer.append(log)
                logger.info(f"Loaded {len(error_logs)} ERROR logs from {log_file}")
        except Exception as e:
            logger.warning(f"Error loading initial logs: {e}")
    
    def closeEvent(self, event):
        """Handle window close"""
        # Stop all workers
        self.stop_all_devices()
        
        # Wait for workers to stop
        for thread in self.threads.values():
            thread.quit()
            thread.wait(5000)
        
        # Shutdown database
        if self.db_manager:
            self.db_manager.shutdown()
        
        event.accept()
        logger.info("Main window closed")

def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("ClinicalStream Device Manager")
    app.setApplicationVersion("2.0")
    
    # Set style
    app.setStyle("Fusion")
    
    # Create main window
    window = AdvancedMainWindow()
    window.show()
    
    sys.exit(app.exec())
