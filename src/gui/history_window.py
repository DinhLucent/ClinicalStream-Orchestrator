#!/usr/bin/env python3
"""
Advanced History Window cho ClinicalStream Device Manager
- Timeline visualization
- Offline decoding
- Export capabilities  
- Advanced filtering
"""

import os
import gzip
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QComboBox, QDateEdit, QLineEdit, QGroupBox, QTabWidget,
    QWidget, QSplitter, QTextEdit, QProgressBar, QCheckBox,
    QSpinBox, QFileDialog, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QDate, QTimer
from PySide6.QtGui import QFont, QColor, QBrush

try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from core.advanced_database_manager import DatabaseManager
from core.message_decoder import MessageDecoder

logger = logging.getLogger(__name__)

# Constants
STX_MARKER = b'\x02\x00'
HEADER_SIZE = 124
S_RECORD_SIZE = 12
MBL_OFFSET_IN_HEADER = 120

class OfflineDecodeWorker(QThread):
    """Worker thread để decode offline session data"""
    
    progress_updated = Signal(int)  # Percentage
    data_decoded = Signal(list)     # Decoded data points
    error_occurred = Signal(str)    # Error message
    finished_decoding = Signal()    # Finished
    
    def __init__(self, session_details: Dict, decoder: MessageDecoder, 
                 selected_params: List[str] = None, max_points: int = 10000):
        super().__init__()
        self.session_details = session_details
        self.decoder = decoder
        self.selected_params = selected_params or []
        self.max_points = max_points
        self._should_stop = False
        
    def run(self):
        """Main decode process"""
        try:
            data_points = []
            total_bytes = self.session_details.get('total_bytes', 0)
            processed_bytes = 0
            
            # Get all segment files
            segments = self.session_details.get('segments', [])
            if not segments:
                self.error_occurred.emit("Không tìm thấy segment files")
                return
            
            # Session start time
            start_time_str = self.session_details.get('start_time_utc', '')
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            except:
                start_time = datetime.now(timezone.utc)
            
            # Process each segment
            for segment in segments:
                if self._should_stop:
                    break
                
                file_path = segment.get('file_path', '')
                if not file_path or not os.path.exists(file_path):
                    continue
                
                # Decode segment
                segment_data = self._decode_segment_file(file_path, start_time)
                data_points.extend(segment_data)
                
                # Update progress
                processed_bytes += segment.get('bytes', 0)
                if total_bytes > 0:
                    progress = min(100, int(processed_bytes * 100 / total_bytes))
                    self.progress_updated.emit(progress)
                
                # Limit points để tránh memory issues
                if len(data_points) > self.max_points:
                    # Downsample data
                    step = len(data_points) // self.max_points
                    data_points = data_points[::step]
            
            # Filter by selected parameters
            if self.selected_params:
                filtered_data = []
                for point in data_points:
                    if point.get('param_name') in self.selected_params:
                        filtered_data.append(point)
                data_points = filtered_data
            
            # Sort by timestamp
            data_points.sort(key=lambda x: x.get('timestamp', 0))
            
            self.data_decoded.emit(data_points)
            self.finished_decoding.emit()
            
        except Exception as e:
            self.error_occurred.emit(f"Decode error: {e}")
    
    def _decode_segment_file(self, file_path: str, start_time: datetime) -> List[Dict]:
        """Decode một segment file"""
        data_points = []
        
        try:
            # Check if compressed
            if file_path.endswith('.gz'):
                with gzip.open(file_path, 'rb') as f:
                    file_data = f.read()
            else:
                with open(file_path, 'rb') as f:
                    file_data = f.read()
            
            # Parse packets từ raw data
            offset = 0
            packet_index = 0
            
            while offset < len(file_data) - HEADER_SIZE:
                if self._should_stop:
                    break
                
                # Find STX marker
                stx_pos = file_data.find(STX_MARKER, offset)
                if stx_pos == -1:
                    break
                
                offset = stx_pos
                
                # Check header
                if offset + HEADER_SIZE > len(file_data):
                    break
                
                # Read body length
                try:
                    mbl_bytes = file_data[offset + MBL_OFFSET_IN_HEADER : offset + MBL_OFFSET_IN_HEADER + 4]
                    body_length = struct.unpack('<I', mbl_bytes)[0]
                except:
                    offset += 1
                    continue
                
                total_length = HEADER_SIZE + body_length
                
                if offset + total_length > len(file_data):
                    break
                
                # Extract packet
                packet_data = file_data[offset:offset + total_length]
                
                # Decode packet
                try:
                    decoded_text, monitor_dict, header_dict = self.decoder.decode_packet_with_monitor_and_header(packet_data)
                    
                    # Calculate timestamp offset
                    packet_time = start_time + datetime.timedelta(seconds=packet_index)
                    
                    # Extract data points
                    for param_name, (value, unit) in monitor_dict.items():
                        try:
                            # Convert value to float if possible
                            if isinstance(value, str):
                                try:
                                    numeric_value = float(value)
                                except:
                                    numeric_value = None
                            else:
                                numeric_value = float(value) if value is not None else None
                            
                            data_point = {
                                'timestamp': packet_time.timestamp(),
                                'param_name': param_name,
                                'value': value,
                                'numeric_value': numeric_value,
                                'unit': unit,
                                'packet_index': packet_index
                            }
                            data_points.append(data_point)
                        except:
                            continue
                    
                    packet_index += 1
                    
                except Exception as e:
                    # Skip invalid packets
                    pass
                
                offset += total_length
                
                # Limit memory usage
                if len(data_points) > 50000:  # 50k points per segment
                    break
        
        except Exception as e:
            logger.error(f"Error decoding segment {file_path}: {e}")
        
        return data_points
    
    def stop(self):
        """Stop decode process"""
        self._should_stop = True

class TimelineChart(QWidget):
    """Chart widget cho timeline visualization"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_points = []
        self.selected_params = []
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        if MATPLOTLIB_AVAILABLE:
            # Chart controls
            controls_layout = QHBoxLayout()
            
            self.param_combo = QComboBox()
            self.param_combo.currentTextChanged.connect(self.update_chart)
            controls_layout.addWidget(QLabel("Parameter:"))
            controls_layout.addWidget(self.param_combo)
            
            self.chart_type_combo = QComboBox()
            self.chart_type_combo.addItems(["Line", "Scatter", "Bar"])
            self.chart_type_combo.currentTextChanged.connect(self.update_chart)
            controls_layout.addWidget(QLabel("Type:"))
            controls_layout.addWidget(self.chart_type_combo)
            
            controls_layout.addStretch()
            layout.addLayout(controls_layout)
            
            # Matplotlib canvas
            self.figure = Figure(figsize=(12, 6))
            self.canvas = FigureCanvas(self.figure)
            layout.addWidget(self.canvas)
            
        else:
            # Fallback text display
            layout.addWidget(QLabel("📊 Chart view requires matplotlib"))
            self.data_display = QTextEdit()
            self.data_display.setReadOnly(True)
            layout.addWidget(self.data_display)
    
    def set_data(self, data_points: List[Dict]):
        """Set data để visualize"""
        self.data_points = data_points
        
        if MATPLOTLIB_AVAILABLE:
            # Update parameter list
            param_names = sorted(set(p.get('param_name', '') for p in data_points))
            param_names = [p for p in param_names if p and not p.startswith('🚨')]  # Skip alarms
            
            self.param_combo.clear()
            self.param_combo.addItems(param_names)
            
            if param_names:
                self.update_chart()
        else:
            # Fallback text display
            summary = f"📊 Decoded {len(data_points)} data points\n\n"
            
            # Parameter summary
            param_counts = {}
            for point in data_points:
                param_name = point.get('param_name', '')
                param_counts[param_name] = param_counts.get(param_name, 0) + 1
            
            summary += "Parameters:\n"
            for param, count in sorted(param_counts.items())[:20]:  # Top 20
                summary += f"  {param}: {count} points\n"
            
            self.data_display.setText(summary)
    
    def update_chart(self):
        """Update matplotlib chart"""
        if not MATPLOTLIB_AVAILABLE or not self.data_points:
            return
        
        param_name = self.param_combo.currentText()
        chart_type = self.chart_type_combo.currentText()
        
        if not param_name:
            return
        
        # Filter data for selected parameter
        param_data = [p for p in self.data_points if p.get('param_name') == param_name]
        if not param_data:
            return
        
        # Extract timestamps và values
        timestamps = []
        values = []
        
        for point in param_data:
            timestamp = point.get('timestamp')
            numeric_value = point.get('numeric_value')
            
            if timestamp is not None and numeric_value is not None:
                timestamps.append(datetime.fromtimestamp(timestamp))
                values.append(numeric_value)
        
        if not timestamps:
            return
        
        # Clear figure
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # Plot data
        if chart_type == "Line":
            ax.plot(timestamps, values, linewidth=1)
        elif chart_type == "Scatter":
            ax.scatter(timestamps, values, s=2, alpha=0.7)
        elif chart_type == "Bar":
            ax.bar(timestamps, values, width=0.0001)  # Very thin bars
        
        # Format chart
        ax.set_title(f"{param_name} - {len(values)} points")
        ax.set_xlabel("Time")
        ax.set_ylabel(f"Value ({param_data[0].get('unit', '')})")
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
        self.figure.autofmt_xdate()
        
        # Grid
        ax.grid(True, alpha=0.3)
        
        # Tight layout
        self.figure.tight_layout()
        
        # Refresh canvas
        self.canvas.draw()

class SessionListWidget(QWidget):
    """Widget hiển thị danh sách sessions"""
    
    session_selected = Signal(dict)  # Emit selected session details
    
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.sessions = []
        self.setup_ui()
        self.load_sessions()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Filters
        filter_group = QGroupBox("🔍 Filters")
        filter_layout = QGridLayout(filter_group)
        
        # Device filter
        filter_layout.addWidget(QLabel("Device:"), 0, 0)
        self.device_combo = QComboBox()
        self.device_combo.addItem("All Devices")
        self.device_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.device_combo, 0, 1)
        
        # Status filter
        filter_layout.addWidget(QLabel("Status:"), 0, 2)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "RUNNING", "ENDED", "INTERRUPTED"])
        self.status_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_combo, 0, 3)
        
        # Date range
        filter_layout.addWidget(QLabel("From:"), 1, 0)
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.dateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.date_from, 1, 1)
        
        filter_layout.addWidget(QLabel("To:"), 1, 2)
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.dateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.date_to, 1, 3)
        
        layout.addWidget(filter_group)
        
        # Sessions table
        self.sessions_table = QTableWidget()
        self.sessions_table.setColumnCount(8)
        self.sessions_table.setHorizontalHeaderLabels([
            "Device", "Patient ID", "Status", "Start Time", 
            "Duration", "Packets", "Size", "Segments"
        ])
        
        # Table properties
        header = self.sessions_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        
        self.sessions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sessions_table.setAlternatingRowColors(True)
        self.sessions_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        layout.addWidget(self.sessions_table)
        
        # Refresh button
        refresh_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.load_sessions)
        refresh_layout.addWidget(self.refresh_btn)
        refresh_layout.addStretch()
        layout.addLayout(refresh_layout)
    
    def load_sessions(self):
        """Load sessions từ database"""
        try:
            self.sessions = self.db_manager.get_session_history(days=30)
            
            # Update device combo
            devices = sorted(set(s.get('device_name', '') for s in self.sessions))
            self.device_combo.clear()
            self.device_combo.addItem("All Devices")
            self.device_combo.addItems(devices)
            
            self.apply_filters()
            
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
    
    def apply_filters(self):
        """Áp dụng filters và update table"""
        device_filter = self.device_combo.currentText()
        status_filter = self.status_combo.currentText()
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        
        # Filter sessions
        filtered_sessions = []
        for session in self.sessions:
            # Device filter
            if device_filter != "All Devices" and session.get('device_name') != device_filter:
                continue
            
            # Status filter
            if status_filter != "All" and session.get('status') != status_filter:
                continue
            
            # Date filter
            try:
                start_time_str = session.get('start_time_utc', '')
                start_date = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).date()
                if start_date < date_from or start_date > date_to:
                    continue
            except:
                continue
            
            filtered_sessions.append(session)
        
        # Update table
        self.update_table(filtered_sessions)
    
    def update_table(self, sessions: List[Dict]):
        """Update sessions table"""
        self.sessions_table.setRowCount(len(sessions))
        
        for row, session in enumerate(sessions):
            # Device
            device_item = QTableWidgetItem(session.get('device_name', ''))
            self.sessions_table.setItem(row, 0, device_item)
            
            # Patient ID
            patient_id = session.get('patient_id', '') or 'Unknown'
            patient_item = QTableWidgetItem(patient_id)
            self.sessions_table.setItem(row, 1, patient_item)
            
            # Status
            status = session.get('status', '')
            status_item = QTableWidgetItem(status)
            if status == 'RUNNING':
                status_item.setForeground(QBrush(QColor("red")))
            elif status == 'ENDED':
                status_item.setForeground(QBrush(QColor("green")))
            else:
                status_item.setForeground(QBrush(QColor("orange")))
            self.sessions_table.setItem(row, 2, status_item)
            
            # Start time
            start_time_str = session.get('start_time_utc', '')
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                start_item = QTableWidgetItem(start_time.strftime('%Y-%m-%d %H:%M:%S'))
            except:
                start_item = QTableWidgetItem(start_time_str)
            self.sessions_table.setItem(row, 3, start_item)
            
            # Duration
            duration = session.get('duration_seconds', 0) or session.get('effective_duration', 0)
            if duration:
                hours = int(duration // 3600)
                minutes = int((duration % 3600) // 60)
                duration_str = f"{hours:02d}:{minutes:02d}"
            else:
                duration_str = "---"
            duration_item = QTableWidgetItem(duration_str)
            self.sessions_table.setItem(row, 4, duration_item)
            
            # Packets
            packets = session.get('total_packets', 0)
            packets_item = QTableWidgetItem(f"{packets:,}")
            self.sessions_table.setItem(row, 5, packets_item)
            
            # Size
            size_bytes = session.get('total_bytes', 0)
            if size_bytes > 1024**3:
                size_str = f"{size_bytes/1024**3:.1f} GB"
            elif size_bytes > 1024**2:
                size_str = f"{size_bytes/1024**2:.1f} MB"
            elif size_bytes > 1024:
                size_str = f"{size_bytes/1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"
            size_item = QTableWidgetItem(size_str)
            self.sessions_table.setItem(row, 6, size_item)
            
            # Segments
            segments = session.get('segment_count', 0)
            segments_item = QTableWidgetItem(str(segments))
            self.sessions_table.setItem(row, 7, segments_item)
        
        # Store filtered sessions for selection
        self.filtered_sessions = sessions
    
    def on_selection_changed(self):
        """Handle selection change"""
        current_row = self.sessions_table.currentRow()
        if 0 <= current_row < len(getattr(self, 'filtered_sessions', [])):
            session = self.filtered_sessions[current_row]
            # Get full session details including segments
            session_id = session.get('id')
            if session_id:
                try:
                    details = self.db_manager.get_session_details(session_id)
                    if details:
                        self.session_selected.emit(details)
                except Exception as e:
                    logger.error(f"Error getting session details: {e}")

class DataExportWidget(QWidget):
    """Widget cho data export"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_data = []
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Export options
        export_group = QGroupBox("📤 Export Options")
        export_layout = QGridLayout(export_group)
        
        # Format
        export_layout.addWidget(QLabel("Format:"), 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["CSV", "JSON", "Excel"])
        export_layout.addWidget(self.format_combo, 0, 1)
        
        # Parameters selection
        export_layout.addWidget(QLabel("Parameters:"), 1, 0)
        self.params_combo = QComboBox()
        self.params_combo.addItem("All Parameters")
        export_layout.addWidget(self.params_combo, 1, 1)
        
        # Export button
        self.export_btn = QPushButton("💾 Export Data")
        self.export_btn.clicked.connect(self.export_data)
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn, 2, 0, 1, 2)
        
        layout.addWidget(export_group)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
    
    def set_data(self, data_points: List[Dict]):
        """Set data cho export"""
        self.current_data = data_points
        
        # Update parameters
        param_names = sorted(set(p.get('param_name', '') for p in data_points))
        self.params_combo.clear()
        self.params_combo.addItem("All Parameters")
        self.params_combo.addItems(param_names)
        
        self.export_btn.setEnabled(len(data_points) > 0)
    
    def export_data(self):
        """Export data"""
        if not self.current_data:
            return
        
        format_type = self.format_combo.currentText()
        selected_param = self.params_combo.currentText()
        
        # File dialog
        file_filter = {
            "CSV": "CSV files (*.csv)",
            "JSON": "JSON files (*.json)",
            "Excel": "Excel files (*.xlsx)"
        }.get(format_type, "All files (*)")
        
        filename, _ = QFileDialog.getSaveFileName(
            self, f"Export {format_type}", f"ClinicalStream_data.{format_type.lower()}", file_filter
        )
        
        if not filename:
            return
        
        try:
            # Filter data if specific parameter selected
            export_data = self.current_data
            if selected_param != "All Parameters":
                export_data = [d for d in self.current_data if d.get('param_name') == selected_param]
            
            if format_type == "CSV":
                self._export_csv(filename, export_data)
            elif format_type == "JSON":
                self._export_json(filename, export_data)
            elif format_type == "Excel":
                self._export_excel(filename, export_data)
            
            QMessageBox.information(self, "Export Complete", f"Data exported to:\n{filename}")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Error exporting data:\n{e}")
    
    def _export_csv(self, filename: str, data: List[Dict]):
        """Export CSV"""
        import csv
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            if not data:
                return
            
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
    
    def _export_json(self, filename: str, data: List[Dict]):
        """Export JSON"""
        import json
        
        # Convert timestamps to ISO format
        export_data = []
        for item in data:
            new_item = item.copy()
            if 'timestamp' in new_item:
                new_item['timestamp_iso'] = datetime.fromtimestamp(new_item['timestamp']).isoformat()
            export_data.append(new_item)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    def _export_excel(self, filename: str, data: List[Dict]):
        """Export Excel"""
        try:
            import pandas as pd
            
            df = pd.DataFrame(data)
            if 'timestamp' in df.columns:
                df['timestamp_formatted'] = pd.to_datetime(df['timestamp'], unit='s')
            
            df.to_excel(filename, index=False)
        except ImportError:
            # Fallback to CSV if pandas not available
            self._export_csv(filename.replace('.xlsx', '.csv'), data)

class AdvancedHistoryWindow(QDialog):
    """Advanced History Window"""
    
    def __init__(self, db_manager: DatabaseManager, decoder: MessageDecoder, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.decoder = decoder
        self.current_session_details = None
        self.decode_worker = None
        
        self.setWindowTitle("ClinicalStream Treatment History")
        self.setMinimumSize(1400, 900)
        
        self.setup_ui()
        
        logger.info("History window opened")
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Sessions list
        self.session_list = SessionListWidget(self.db_manager)
        self.session_list.session_selected.connect(self.on_session_selected)
        main_splitter.addWidget(self.session_list)
        
        # Right panel - Session details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Session info
        self.session_info_label = QLabel("📋 Select a session to view details")
        self.session_info_label.setStyleSheet("font-weight: bold; padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        right_layout.addWidget(self.session_info_label)
        
        # Tabs for different views
        self.tab_widget = QTabWidget()
        
        # Timeline tab
        timeline_tab = QWidget()
        timeline_layout = QVBoxLayout(timeline_tab)
        
        # Decode controls
        decode_group = QGroupBox("🔄 Offline Decode")
        decode_layout = QHBoxLayout(decode_group)
        
        self.decode_btn = QPushButton("📊 Decode Session")
        self.decode_btn.clicked.connect(self.start_decode)
        self.decode_btn.setEnabled(False)
        
        self.decode_progress = QProgressBar()
        self.decode_progress.setVisible(False)
        
        self.max_points_spin = QSpinBox()
        self.max_points_spin.setRange(1000, 100000)
        self.max_points_spin.setValue(10000)
        self.max_points_spin.setSuffix(" points")
        
        decode_layout.addWidget(self.decode_btn)
        decode_layout.addWidget(QLabel("Max points:"))
        decode_layout.addWidget(self.max_points_spin)
        decode_layout.addWidget(self.decode_progress)
        decode_layout.addStretch()
        
        timeline_layout.addWidget(decode_group)
        
        # Chart
        self.timeline_chart = TimelineChart()
        timeline_layout.addWidget(self.timeline_chart)
        
        self.tab_widget.addTab(timeline_tab, "📈 Timeline")
        
        # Export tab
        self.export_widget = DataExportWidget()
        self.tab_widget.addTab(self.export_widget, "📤 Export")
        
        right_layout.addWidget(self.tab_widget)
        
        main_splitter.addWidget(right_panel)
        
        # Set splitter sizes
        main_splitter.setSizes([500, 900])
        
        layout.addWidget(main_splitter)
    
    @Slot(dict)
    def on_session_selected(self, session_details: Dict):
        """Handle session selection"""
        self.current_session_details = session_details
        
        # Update session info
        device_name = session_details.get('device_name', 'Unknown')
        patient_id = session_details.get('patient_id', 'Unknown')
        start_time = session_details.get('start_time_utc', '')
        status = session_details.get('status', 'Unknown')
        
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            start_formatted = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            start_formatted = start_time
        
        info_text = (
            f"📱 Device: {device_name} | "
            f"👤 Patient: {patient_id} | "
            f"🕐 Start: {start_formatted} | "
            f"📊 Status: {status}"
        )
        
        self.session_info_label.setText(info_text)
        
        # Enable decode button
        self.decode_btn.setEnabled(True)
        self.decode_btn.setText(f"📊 Decode Session ({len(session_details.get('segments', []))} segments)")
    
    def start_decode(self):
        """Bắt đầu decode session"""
        if not self.current_session_details:
            return
        
        # Stop previous decode if running
        if self.decode_worker and self.decode_worker.isRunning():
            self.decode_worker.stop()
            self.decode_worker.wait()
        
        # Show progress
        self.decode_progress.setVisible(True)
        self.decode_progress.setValue(0)
        self.decode_btn.setEnabled(False)
        
        # Start decode worker
        max_points = self.max_points_spin.value()
        self.decode_worker = OfflineDecodeWorker(
            self.current_session_details,
            self.decoder,
            max_points=max_points
        )
        
        # Connect signals
        self.decode_worker.progress_updated.connect(self.decode_progress.setValue)
        self.decode_worker.data_decoded.connect(self.on_data_decoded)
        self.decode_worker.error_occurred.connect(self.on_decode_error)
        self.decode_worker.finished_decoding.connect(self.on_decode_finished)
        
        self.decode_worker.start()
    
    @Slot(list)
    def on_data_decoded(self, data_points: List[Dict]):
        """Handle decoded data"""
        # Update timeline chart
        self.timeline_chart.set_data(data_points)
        
        # Update export widget
        self.export_widget.set_data(data_points)
    
    @Slot(str)
    def on_decode_error(self, error_message: str):
        """Handle decode error"""
        QMessageBox.critical(self, "Decode Error", f"Error decoding session:\n{error_message}")
        self.on_decode_finished()
    
    @Slot()
    def on_decode_finished(self):
        """Handle decode finished"""
        self.decode_progress.setVisible(False)
        self.decode_btn.setEnabled(True)
    
    def closeEvent(self, event):
        """Handle window close"""
        # Stop decode worker if running
        if self.decode_worker and self.decode_worker.isRunning():
            self.decode_worker.stop()
            self.decode_worker.wait(5000)
        
        event.accept()
        logger.info("History window closed")
