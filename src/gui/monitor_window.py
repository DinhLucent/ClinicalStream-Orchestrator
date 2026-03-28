#!/usr/bin/env python3
"""
Advanced Monitor Window cho ClinicalStream Device Manager
- S-Header panel với device info
- S-Body panel với parameter grid
- Adjustable refresh rate
- Advanced filtering và searching
- Favorites management
"""

import time
import json
import logging
from pathlib import Path
from typing import Dict, Set, Optional, Any, Tuple, List
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QSpinBox, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QGroupBox, QScrollArea, QWidget, QSplitter, QFrame,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QSlider, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QColor, QBrush

from core.advanced_database_manager import DeviceConfig
from core.advanced_device_worker import AdvancedDeviceWorker

class ParameterWidget(QWidget):
    """Widget cho một parameter trong S-Body"""
    
    def __init__(self, param_name: str, parent=None):
        super().__init__(parent)
        self.param_name = param_name
        self.last_update = 0
        self.is_favorite = False
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        
        # Parameter name
        self.name_label = QLabel(self.param_name)
        self.name_label.setMinimumWidth(200)
        self.name_label.setWordWrap(True)
        font = self.name_label.font()
        font.setPointSize(9)
        self.name_label.setFont(font)
        
        # Value
        self.value_label = QLabel("---")
        self.value_label.setMinimumWidth(80)
        self.value_label.setAlignment(Qt.AlignCenter)
        
        # Unit
        self.unit_label = QLabel("")
        self.unit_label.setMinimumWidth(60)
        self.unit_label.setAlignment(Qt.AlignCenter)
        
        # Favorite star
        self.favorite_btn = QPushButton("☆")
        self.favorite_btn.setMaximumSize(25, 25)
        self.favorite_btn.clicked.connect(self.toggle_favorite)
        
        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.unit_label)
        layout.addWidget(self.favorite_btn)
    
    def update_value(self, value: Any, unit: str):
        """Cập nhật giá trị parameter"""
        self.value_label.setText(str(value))
        self.unit_label.setText(unit)
        self.last_update = time.time()
        
        # Style cho ALARM
        if self.param_name.startswith('🚨 ALARM_'):
            self.set_alarm_style()
        else:
            self.set_normal_style()
    
    def set_alarm_style(self):
        """Style cho alarm parameters"""
        self.name_label.setStyleSheet(
            "color: #fff; font-weight: bold; padding: 4px; "
            "background-color: #d32f2f; border-radius: 3px;"
        )
        self.value_label.setStyleSheet(
            "color: #fff; background-color: #b71c1c; padding: 4px; "
            "border: 2px solid #d32f2f; border-radius: 3px; font-weight: bold;"
        )
        self.unit_label.setStyleSheet(
            "color: #fff; background-color: #b71c1c; padding: 4px; "
            "border: 2px solid #d32f2f; border-radius: 3px; font-weight: bold;"
        )
    
    def set_normal_style(self):
        """Style cho normal parameters"""
        self.name_label.setStyleSheet("color: #333; font-weight: bold;")
        self.value_label.setStyleSheet(
            "color: #000; background-color: #e8f5e8; padding: 2px; "
            "border: 1px solid #ccc; border-radius: 2px;"
        )
        self.unit_label.setStyleSheet(
            "color: #666; background-color: #f0f0f0; padding: 2px; "
            "border: 1px solid #ccc; border-radius: 2px;"
        )
    
    def set_inactive_style(self):
        """Style cho parameters không còn update"""
        self.name_label.setStyleSheet("color: #999; font-weight: normal;")
        self.value_label.setStyleSheet(
            "color: #999; background-color: #f5f5f5; padding: 2px; "
            "border: 1px solid #ddd; border-radius: 2px;"
        )
        self.unit_label.setStyleSheet(
            "color: #999; background-color: #f5f5f5; padding: 2px; "
            "border: 1px solid #ddd; border-radius: 2px;"
        )
    
    def toggle_favorite(self):
        """Toggle favorite status"""
        self.is_favorite = not self.is_favorite
        self.favorite_btn.setText("★" if self.is_favorite else "☆")
        self.favorite_btn.setStyleSheet(
            "color: gold; font-weight: bold;" if self.is_favorite else ""
        )

class HeaderPanel(QWidget):
    """Panel hiển thị S-Header information"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.header_data = {}
    
    def setup_ui(self):
        layout = QGridLayout(self)
        
        # Title
        title = QLabel("📋 S-Header Information")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50;")
        layout.addWidget(title, 0, 0, 1, 4)
        
        # Header fields
        self.machine_id_label = QLabel("---")
        self.sw_rev_label = QLabel("---")
        self.patient_id_label = QLabel("---")
        self.therapy_type_label = QLabel("---")
        self.therapy_status_label = QLabel("---")
        self.flags_label = QLabel("---")
        self.body_length_label = QLabel("---")
        self.msg_info_label = QLabel("---")
        
        # Layout fields
        row = 1
        layout.addWidget(QLabel("Machine ID:"), row, 0)
        layout.addWidget(self.machine_id_label, row, 1)
        layout.addWidget(QLabel("SW Rev:"), row, 2)
        layout.addWidget(self.sw_rev_label, row, 3)
        
        row += 1
        layout.addWidget(QLabel("Patient ID:"), row, 0)
        layout.addWidget(self.patient_id_label, row, 1)
        layout.addWidget(QLabel("Therapy Type:"), row, 2)
        layout.addWidget(self.therapy_type_label, row, 3)
        
        row += 1
        layout.addWidget(QLabel("Therapy Status:"), row, 0)
        layout.addWidget(self.therapy_status_label, row, 1)
        layout.addWidget(QLabel("Flags:"), row, 2)
        layout.addWidget(self.flags_label, row, 3)
        
        row += 1
        layout.addWidget(QLabel("Body Length:"), row, 0)
        layout.addWidget(self.body_length_label, row, 1)
        layout.addWidget(QLabel("Message Info:"), row, 2)
        layout.addWidget(self.msg_info_label, row, 3)
    
    def update_header(self, header_dict: Dict[str, Any]):
        """Cập nhật header information"""
        self.header_data = header_dict
        
        self.machine_id_label.setText(str(header_dict.get('machine_id', '---')))
        self.sw_rev_label.setText(str(header_dict.get('sw_rev', '---')))
        self.patient_id_label.setText(str(header_dict.get('patient_id', '---')))
        self.therapy_type_label.setText(str(header_dict.get('therapy_type', '---')))
        
        # Therapy status với màu sắc
        therapy_status = header_dict.get('therapy_status', '---')
        self.therapy_status_label.setText(str(therapy_status))
        
        if 'RUN' in str(therapy_status).upper():
            self.therapy_status_label.setStyleSheet("color: red; font-weight: bold;")
        elif 'END' in str(therapy_status).upper():
            self.therapy_status_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.therapy_status_label.setStyleSheet("color: black;")
        
        self.flags_label.setText(f"0x{header_dict.get('flags', 0):04X}")
        self.body_length_label.setText(str(header_dict.get('body_length', 0)))
        self.msg_info_label.setText(str(header_dict.get('msg_info', 0)))

class BodyPanel(QWidget):
    """Panel hiển thị S-Body parameters với advanced filtering"""
    
    # Main Parameters - các thông số chính quan trọng
    MAIN_PARAMETER_IDS = {
        1, 2, 3, 4, 6,  # Pressures
        17, 18, 19, 20, 21, 22, 23, 24, 26,  # Flows & Therapy
        36, 37, 38,  # Bolus & Heparin
        47,  # Pre HCT
        59,  # Run time
        94, 95, 97, 98, 99, 100,  # I/O History
        407,  # Syringe total
        410,  # Effluent dose
        412, 413, 414, 415, 416, 417,  # I/O History chart
        422, 425, 428, 431, 434, 437,  # I/O History doses
        443,  # Current filter time
        454,  # Total plasma
        457, 458, 459, 460, 461, 462, 463  # Additional parameters
    }
    
    def __init__(self, specific_ids: List[int] = None, parent=None):
        super().__init__(parent)
        self.parameters: Dict[str, ParameterWidget] = {}
        self.monitor_data: Dict[str, Tuple] = {}
        self.favorites: Set[str] = set()
        self.specific_ids = specific_ids  # Filter to show only these parameter IDs
        self.setup_ui()
        self.load_favorites()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Controls panel
        controls_group = QGroupBox("📊 S-Body Controls")
        controls_layout = QGridLayout(controls_group)
        
        # Refresh rate
        controls_layout.addWidget(QLabel("Refresh (ms):"), 0, 0)
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(200, 5000)
        self.refresh_spin.setValue(1000)
        self.refresh_spin.setSuffix(" ms")
        controls_layout.addWidget(self.refresh_spin, 0, 1)
        
        # Columns
        controls_layout.addWidget(QLabel("Columns:"), 0, 2)
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 6)
        self.columns_spin.setValue(3)
        self.columns_spin.valueChanged.connect(self.rebuild_layout)
        controls_layout.addWidget(self.columns_spin, 0, 3)
        
        # Search
        controls_layout.addWidget(QLabel("Search:"), 1, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter parameters...")
        self.search_edit.textChanged.connect(self.apply_filters)
        controls_layout.addWidget(self.search_edit, 1, 1, 1, 2)
        
        # Filter type
        self.filter_combo = QComboBox()
        filter_items = ["All", "Active Only", "Favorites Only", "Alarms Only", "Main Parameters"]
        if self.specific_ids:
            filter_items.append("Specific IDs Only")
        self.filter_combo.addItems(filter_items)
        
        # Set default filter to "Specific IDs Only" if specific_ids provided
        if self.specific_ids:
            self.filter_combo.setCurrentText("Specific IDs Only")
            
        self.filter_combo.currentTextChanged.connect(self.apply_filters)
        controls_layout.addWidget(self.filter_combo, 1, 3)
        
        # Parameter type filter
        controls_layout.addWidget(QLabel("Type:"), 2, 0)
        self.type_filter_combo = QComboBox()
        self.type_filter_combo.addItems(["All Types", "Actual", "Set", "Alarm"])
        self.type_filter_combo.currentTextChanged.connect(self.apply_filters)
        controls_layout.addWidget(self.type_filter_combo, 2, 1)
        
        # Quick presets
        presets_layout = QHBoxLayout()
        
        self.preset_pressure_btn = QPushButton("🔴 Pressure")
        self.preset_pressure_btn.clicked.connect(lambda: self.apply_preset("pressure"))
        
        self.preset_flow_btn = QPushButton("🔵 Flow")
        self.preset_flow_btn.clicked.connect(lambda: self.apply_preset("flow"))
        
        self.preset_pump_btn = QPushButton("🟢 Pump")
        self.preset_pump_btn.clicked.connect(lambda: self.apply_preset("pump"))
        
        self.preset_all_btn = QPushButton("⚪ All")
        self.preset_all_btn.clicked.connect(lambda: self.apply_preset("all"))
        
        self.preset_main_btn = QPushButton("🎯 Main")
        self.preset_main_btn.clicked.connect(lambda: self.apply_preset("main"))
        
        presets_layout.addWidget(self.preset_pressure_btn)
        presets_layout.addWidget(self.preset_flow_btn)
        presets_layout.addWidget(self.preset_pump_btn)
        presets_layout.addWidget(self.preset_all_btn)
        presets_layout.addWidget(self.preset_main_btn)
        
        self.custom_ids_btn = QPushButton("🔧 Custom IDs")
        self.custom_ids_btn.clicked.connect(self.show_custom_ids_dialog)
        presets_layout.addWidget(self.custom_ids_btn)
        
        presets_layout.addStretch()
        
        controls_layout.addLayout(presets_layout, 2, 2, 1, 2)
        
        main_layout.addWidget(controls_group)
        
        # Scroll area for parameters
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Container widget for parameters
        self.params_container = QWidget()
        self.params_layout = QGridLayout(self.params_container)
        self.params_layout.setSpacing(2)
        
        self.scroll_area.setWidget(self.params_container)
        main_layout.addWidget(self.scroll_area)
    
    def update_monitor_data(self, monitor_dict: Dict[str, Tuple]):
        """Cập nhật monitor data - now supports (value, unit, param_id)"""
        self.monitor_data.update(monitor_dict)
        
        # Add new parameters
        for param_name in monitor_dict.keys():
            if param_name not in self.parameters:
                self.add_parameter(param_name)
        
        # Update existing parameters
        current_time = time.time()
        for param_name, widget in self.parameters.items():
            if param_name in monitor_dict:
                data_tuple = monitor_dict[param_name]
                if len(data_tuple) >= 3:
                    value, unit, param_id = data_tuple[:3]
                else:
                    # Backward compatibility
                    value, unit = data_tuple[:2]
                    param_id = None
                widget.update_value(value, unit)
            else:
                # Mark as inactive if not updated for 30s
                if current_time - widget.last_update > 30:
                    widget.set_inactive_style()
        
        # Apply current filters
        self.apply_filters()
    
    def add_parameter(self, param_name: str):
        """Thêm parameter widget mới"""
        widget = ParameterWidget(param_name)
        widget.is_favorite = param_name in self.favorites
        widget.favorite_btn.setText("★" if widget.is_favorite else "☆")
        widget.favorite_btn.clicked.connect(lambda: self.toggle_favorite(param_name))
        
        self.parameters[param_name] = widget
        self.rebuild_layout()
    
    def toggle_favorite(self, param_name: str):
        """Toggle favorite status"""
        if param_name in self.favorites:
            self.favorites.remove(param_name)
        else:
            self.favorites.add(param_name)
        
        # Update widget
        if param_name in self.parameters:
            widget = self.parameters[param_name]
            widget.is_favorite = param_name in self.favorites
            widget.favorite_btn.setText("★" if widget.is_favorite else "☆")
        
        self.save_favorites()
        self.apply_filters()
    
    def apply_filters(self):
        """Áp dụng các filters"""
        search_text = self.search_edit.text().lower()
        filter_type = self.filter_combo.currentText()
        type_filter = self.type_filter_combo.currentText()
        
        visible_params = []
        
        for param_name, widget in self.parameters.items():
            # Search filter
            if search_text and search_text not in param_name.lower():
                continue
            
            # Type filter
            if type_filter != "All Types":
                if type_filter == "Actual" and (param_name.startswith('🚨') or 'Set' in param_name):
                    continue
                elif type_filter == "Set" and 'Set' not in param_name:
                    continue
                elif type_filter == "Alarm" and not param_name.startswith('🚨'):
                    continue
            
            # Main filter
            if filter_type == "Active Only" and time.time() - widget.last_update > 30:
                continue
            elif filter_type == "Favorites Only" and param_name not in self.favorites:
                continue
            elif filter_type == "Alarms Only" and not param_name.startswith('🚨'):
                continue
            elif filter_type == "Main Parameters":
                # Filter chỉ hiển thị main parameters
                if param_name in self.monitor_data:
                    data_tuple = self.monitor_data[param_name]
                    if len(data_tuple) >= 3:
                        _, _, param_id = data_tuple[:3]
                        if param_id is not None and param_id not in self.MAIN_PARAMETER_IDS:
                            continue
                    else:
                        # Fallback: try to extract ID from param_name
                        try:
                            if "ID " in param_name:
                                id_part = param_name.split("ID ")[1].split(":")[0].strip()
                                param_id = int(id_part)
                                if param_id not in self.MAIN_PARAMETER_IDS:
                                    continue
                            else:
                                continue  # Skip parameters without ID
                        except (ValueError, IndexError):
                            continue  # Skip if can't parse ID
                else:
                    continue  # Skip if no monitor data
            elif filter_type == "Specific IDs Only" and self.specific_ids:
                # Use actual param_id from monitor data
                if param_name in self.monitor_data:
                    data_tuple = self.monitor_data[param_name]
                    if len(data_tuple) >= 3:
                        _, _, param_id = data_tuple[:3]
                        if param_id is not None and param_id not in self.specific_ids:
                            continue
                    else:
                        # Fallback: try to extract ID from param_name for backward compatibility
                        try:
                            if "ID " in param_name:
                                id_part = param_name.split("ID ")[1].split(":")[0].strip()
                                param_id = int(id_part)
                                if param_id not in self.specific_ids:
                                    continue
                            else:
                                continue  # Skip parameters without ID
                        except (ValueError, IndexError):
                            continue  # Skip if can't parse ID
                else:
                    continue  # Skip if no monitor data
            
            visible_params.append(param_name)
        
        # Sort parameters: Alarms first, then favorites, then alphabetical
        def sort_key(param_name):
            if param_name.startswith('🚨'):
                return (0, param_name)
            elif param_name in self.favorites:
                return (1, param_name)
            else:
                return (2, param_name)
        
        visible_params.sort(key=sort_key)
        
        # Update layout
        self.update_layout(visible_params)
    
    def apply_preset(self, preset_type: str):
        """Áp dụng preset filter"""
        if preset_type == "main":
            # Set filter to Main Parameters
            self.filter_combo.setCurrentText("Main Parameters")
            return
        
        preset_keywords = {
            "pressure": ["pressure", "press", "pres", "mmhg"],
            "flow": ["flow", "rate", "ml/min", "l/min"],
            "pump": ["pump", "rpm", "speed", "motor"],
            "all": []
        }
        
        keywords = preset_keywords.get(preset_type, [])
        
        if preset_type == "all":
            self.search_edit.clear()
        else:
            # Find matching parameters
            matches = []
            for param_name in self.parameters.keys():
                for keyword in keywords:
                    if keyword.lower() in param_name.lower():
                        matches.append(param_name)
                        break
            
            if matches:
                # Set search to match first keyword
                self.search_edit.setText(keywords[0] if keywords else "")
    
    def show_custom_ids_dialog(self):
        """Hiển thị dialog để nhập custom IDs"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        
        # Get current IDs if any
        current_ids = []
        if hasattr(self, 'custom_ids') and self.custom_ids:
            current_ids = self.custom_ids
        
        # Show input dialog
        text, ok = QInputDialog.getText(
            self, 
            "Custom Parameter IDs", 
            "Nhập danh sách ID (cách nhau bằng dấu phẩy):\nVí dụ: 1,2,3,17,19,21",
            text=",".join(map(str, current_ids)) if current_ids else ""
        )
        
        if ok and text.strip():
            try:
                # Parse IDs
                ids = [int(x.strip()) for x in text.split(",") if x.strip()]
                if ids:
                    self.custom_ids = ids
                    # Set filter to Specific IDs Only
                    self.filter_combo.setCurrentText("Specific IDs Only")
                    # Update specific_ids for filtering
                    self.specific_ids = ids
                    # Apply filters
                    self.apply_filters()
                    
                    QMessageBox.information(
                        self, 
                        "Custom IDs Applied", 
                        f"Đã áp dụng {len(ids)} custom IDs: {ids}"
                    )
                else:
                    QMessageBox.warning(self, "Invalid Input", "Không có ID hợp lệ nào được nhập")
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Vui lòng nhập các số nguyên cách nhau bằng dấu phẩy")
    
    def get_main_parameters_info(self) -> str:
        """Lấy thông tin về main parameters"""
        return f"Main Parameters ({len(self.MAIN_PARAMETER_IDS)} IDs):\n" + \
               f"Pressures: {sorted([id for id in self.MAIN_PARAMETER_IDS if id <= 10])}\n" + \
               f"Flows: {sorted([id for id in self.MAIN_PARAMETER_IDS if 15 <= id <= 30])}\n" + \
               f"I/O History: {sorted([id for id in self.MAIN_PARAMETER_IDS if 90 <= id <= 120])}\n" + \
               f"Other: {sorted([id for id in self.MAIN_PARAMETER_IDS if id > 120])}"
    
    def rebuild_layout(self):
        """Rebuild toàn bộ layout"""
        visible_params = list(self.parameters.keys())
        self.apply_filters()
    
    def update_layout(self, visible_params: List[str]):
        """Update layout với danh sách parameters visible"""
        # Clear existing layout
        for i in reversed(range(self.params_layout.count())):
            item = self.params_layout.takeAt(i)
            if item.widget():
                item.widget().setParent(None)
        
        # Add visible parameters
        columns = self.columns_spin.value()
        
        for i, param_name in enumerate(visible_params):
            if param_name in self.parameters:
                widget = self.parameters[param_name]
                row = i // columns
                col = i % columns
                self.params_layout.addWidget(widget, row, col)
    
    def load_favorites(self):
        """Load favorites từ file"""
        try:
            favorites_file = Path("monitor_favorites.json")
            if favorites_file.exists():
                with open(favorites_file, 'r') as f:
                    data = json.load(f)
                    self.favorites = set(data.get('favorites', []))
        except Exception as e:
            logger.warning(f"Error loading favorites: {e}")
    
    def save_favorites(self):
        """Save favorites ra file"""
        try:
            favorites_file = Path("monitor_favorites.json")
            with open(favorites_file, 'w') as f:
                json.dump({'favorites': list(self.favorites)}, f, indent=2)
        except Exception as e:
            logger.warning(f"Error saving favorites: {e}")

class AdvancedMonitorWindow(QDialog):
    """Advanced Monitor Window cho một thiết bị"""
    
    def __init__(self, device: DeviceConfig, worker: AdvancedDeviceWorker, specific_ids: List[int] = None, parent=None):
        super().__init__(parent)
        self.device = device
        self.worker = worker
        self.specific_ids = specific_ids  # List of specific parameter IDs to show
        
        # Set window title with ID filter info
        title = f"Monitor - {device.name} ({device.ip}:{device.port})"
        if specific_ids:
            title += f" - IDs: {specific_ids}"
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 700)
        
        # Setup UI
        self.setup_ui()
        
        # Check if device is running
        self.device_running = hasattr(worker, '_is_running') and worker._is_running
        
        # Connect worker signals only if device is running
        if self.device_running:
            self.connect_worker_signals()
        else:
            # Show offline status
            self.connection_label.setText("🔴 Offline (Device not running)")
            self.connection_label.setStyleSheet("color: red; font-weight: bold;")
            self.treatment_label.setText("⚪ Offline")
            self.stats_label.setText("📊 No data")
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(1000)  # Default 1s
        
        # Connect refresh rate change
        self.body_panel.refresh_spin.valueChanged.connect(self.update_refresh_rate)
        
        # If device not running, show demo data
        if not self.device_running:
            self.show_demo_data()
        
        logger.info(f"Monitor window opened for {device.name}")
    
    def connect_worker_signals(self):
        """Kết nối worker signals"""
        try:
            self.worker.monitor_data.connect(self.body_panel.update_monitor_data)
            self.worker.header_data.connect(self.header_panel.update_header)
            self.worker.stats_updated.connect(self.update_stats)
        except Exception as e:
            logger.warning(f"Could not connect worker signals: {e}")
    
    def update_refresh_rate(self, rate: int):
        """Update refresh rate"""
        if self.update_timer:
            self.update_timer.setInterval(rate * 1000)
    
    def update_stats(self, stats: dict):
        """Update stats display"""
        if stats and isinstance(stats, dict):
            self.stats_label.setText(f"📊 {stats.get('packets_received', 0)} packets")
    
    def show_demo_data(self):
        """Hiển thị demo data khi device không chạy"""
        # Demo header data
        demo_header = {
            'device_id': 'DEMO',
            'treatment_id': 'TREATMENT_001',
            'patient_id': 'PATIENT_001',
            'start_time': '2024-01-01 10:00:00',
            'status': 'IDLE'
        }
        self.header_panel.update_header(demo_header)
        
        # Demo monitor data với main parameters
        demo_monitor = {}
        for param_id in self.body_panel.MAIN_PARAMETER_IDS:
            param_name = f"ID {param_id:3d}: DEMO_PARAM_{param_id}"
            if param_id <= 10:  # Pressures
                demo_monitor[param_name] = (120.5, "mmHg", param_id)
            elif 15 <= param_id <= 30:  # Flows
                demo_monitor[param_name] = (250.0, "ml/min", param_id)
            elif 30 <= param_id <= 50:  # Therapy
                demo_monitor[param_name] = ("ACTIVE", "", param_id)
            else:  # Other
                demo_monitor[param_name] = (0, "", param_id)
        
        self.body_panel.update_monitor_data(demo_monitor)
        
        # Update status
        self.connection_label.setText("🔴 Demo Mode (Device not running)")
        self.connection_label.setStyleSheet("color: orange; font-weight: bold;")
        self.treatment_label.setText("⚪ Demo")
        self.stats_label.setText("📊 Demo data")
    
    def update_display(self):
        """Update display data"""
        if not self.device_running:
            return  # Don't update if device not running
        
        # Update stats if available
        if hasattr(self.worker, 'get_stats'):
            stats = self.worker.get_stats()
            if stats:
                self.stats_label.setText(f"📊 {stats.get('packets_received', 0)} packets")
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Top info bar
        info_bar = QFrame()
        info_bar.setFrameStyle(QFrame.StyledPanel)
        info_layout = QHBoxLayout(info_bar)
        
        self.device_label = QLabel(f"📱 {self.device.name}")
        self.device_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.connection_label = QLabel("🔴 Connecting...")
        self.treatment_label = QLabel("⚪ Idle")
        self.stats_label = QLabel("📊 0 packets")
        
        info_layout.addWidget(self.device_label)
        info_layout.addStretch()
        info_layout.addWidget(self.connection_label)
        info_layout.addWidget(self.treatment_label)
        info_layout.addWidget(self.stats_label)
        
        layout.addWidget(info_bar)
        
        # Main content splitter
        splitter = QSplitter(Qt.Vertical)
        
        # Header panel
        self.header_panel = HeaderPanel()
        splitter.addWidget(self.header_panel)
        
        # Body panel
        self.body_panel = BodyPanel(specific_ids=self.specific_ids)
        splitter.addWidget(self.body_panel)
        
        # Set splitter sizes (header smaller)
        splitter.setSizes([200, 500])
        
        layout.addWidget(splitter)
        
        # Bottom controls
        bottom_layout = QHBoxLayout()
        
        self.force_flush_btn = QPushButton("💾 Force Flush")
        self.force_flush_btn.clicked.connect(self.force_flush)
        
        self.reset_stats_btn = QPushButton("📊 Reset Stats")
        self.reset_stats_btn.clicked.connect(self.reset_stats)
        
        bottom_layout.addWidget(self.force_flush_btn)
        bottom_layout.addWidget(self.reset_stats_btn)
        bottom_layout.addStretch()
        
        layout.addLayout(bottom_layout)
    
    def connect_worker_signals(self):
        """Kết nối signals từ worker"""
        self.worker.connection_state_changed.connect(self.update_connection_status)
        self.worker.monitor_data.connect(self.body_panel.update_monitor_data)
        self.worker.header_data.connect(self.header_panel.update_header)
        self.worker.stats_updated.connect(self.update_stats)
    
    @Slot(str, QColor)
    def update_connection_status(self, message: str, color: QColor):
        """Cập nhật connection status"""
        self.connection_label.setText(message)
        self.connection_label.setStyleSheet(f"color: {color.name()}; font-weight: bold;")
    
    @Slot(dict)
    def update_stats(self, stats: Dict):
        """Cập nhật statistics"""
        packets = stats.get('packets_received', 0)
        bytes_val = stats.get('bytes_received', 0)
        treatment_state = stats.get('treatment_state', 'IDLE')
        
        # Format bytes
        if bytes_val < 1024:
            bytes_str = f"{bytes_val} B"
        elif bytes_val < 1024**2:
            bytes_str = f"{bytes_val/1024:.1f} KB"
        else:
            bytes_str = f"{bytes_val/1024**2:.1f} MB"
        
        self.stats_label.setText(f"📊 {packets:,} packets, {bytes_str}")
        
        # Treatment status
        treatment_colors = {
            'IDLE': ('⚪ Chờ ca', 'gray'),
            'RUNNING': ('🔴 Đang ghi', 'red'),
            'ENDING': ('🟡 Kết thúc', 'orange'),
            'ENDED': ('⚫ Hoàn thành', 'black')
        }
        
        treatment_text, treatment_color = treatment_colors.get(treatment_state, ('❓ Unknown', 'gray'))
        self.treatment_label.setText(treatment_text)
        self.treatment_label.setStyleSheet(f"color: {treatment_color}; font-weight: bold;")
    
    def update_display(self):
        """Update display định kỳ (nếu cần)"""
        # Most updates are handled by signals
        pass
    
    def update_refresh_rate(self, value: int):
        """Cập nhật refresh rate"""
        self.update_timer.setInterval(value)
    
    def force_flush(self):
        """Force flush session data"""
        if self.worker:
            self.worker.force_flush()
            self.stats_label.setText(self.stats_label.text() + " (Flushed)")
    
    def reset_stats(self):
        """Reset statistics"""
        # This would need to be implemented in worker
        pass
    
    def closeEvent(self, event):
        """Handle window close"""
        # Save favorites
        self.body_panel.save_favorites()
        
        # Stop timer
        self.update_timer.stop()
        
        event.accept()
        logger.info(f"Monitor window closed for {self.device.name}")

import logging
logger = logging.getLogger(__name__)
