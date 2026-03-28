#!/usr/bin/env python3
"""
Advanced Clinical Device Worker with FSM lifecycle
IDLE → RUNNING → ENDING → ENDED
Optimized for stability and performance
"""

import socket
import time
import threading
import struct
import logging
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtGui import QColor

from core.advanced_database_manager import DatabaseManager
from core.session_writer import SessionWriter, SessionConfig
from core.message_decoder import MessageDecoder

logger = logging.getLogger(__name__)

# Protocol Interface Constants (Generalized for Portfolio)
STX_MARKER = b'\x00\x00'      # Placeholder for proprietary marker
HEADER_SIZE = 124             # Standard frame header length
S_RECORD_SIZE = 12           # Standard record length
MBL_OFFSET_IN_HEADER = 0      # Generalized offset

# Therapy Status Constants
STATUS_IDLE = 0
STATUS_CUSTOM = 1
STATUS_PREPARE = 2
STATUS_TEST = 3
STATUS_READY = 4
STATUS_RUNNING = 5          # Start data acquisition
STATUS_ACTION_REQUIRED = 6
STATUS_STOPPED = 7
STATUS_FINALIZE = 8         # End data acquisition
STATUS_COMPLETE = 9
STATUS_MAINTENANCE = 10
STATUS_POST_PROC = 11

class TreatmentState(Enum):
    """FSM states cho treatment lifecycle"""
    IDLE = auto()           # Không có treatment active
    RUNNING = auto()        # Treatment đang chạy, đang ghi data
    ENDING = auto()         # Treatment kết thúc, finalize data
    ENDED = auto()          # Treatment đã hoàn thành

class ConnectionState(Enum):
    """Connection states"""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()

class AdvancedDeviceWorker(QObject):
    """
    Advanced worker to connect and process data from clinical devices
    With FSM lifecycle and robust connection management
    """
    
    # Signals
    status_changed = Signal(str, QColor)
    connection_state_changed = Signal(str, QColor)
    monitor_data = Signal(dict)  # Real-time monitoring data
    header_data = Signal(dict)   # Header information
    stats_updated = Signal(dict) # Performance stats
    error_occurred = Signal(str, str)  # Error type, message
    finished = Signal()  # Signal when worker is finished
    
    def __init__(self, device_name: str, ip: str, port: int,
                 db_manager: DatabaseManager, 
                 message_decoder: MessageDecoder,
                 session_config: SessionConfig = None):
        super().__init__()
        
        self.device_name = device_name
        self.ip = ip
        self.port = port
        self.db_manager = db_manager
        self.message_decoder = message_decoder
        self.session_config = session_config or SessionConfig()
        
        # Connection management
        self.connection: Optional[socket.socket] = None
        self.connection_state = ConnectionState.DISCONNECTED
        self._is_running = False
        self._should_reconnect = True
        
        # Buffer and processing
        self.stream_buffer = bytearray()
        self.packet_count = 0
        self.bytes_received = 0
        self.last_packet_time = 0
        
        # Treatment FSM
        self.treatment_state = TreatmentState.IDLE
        self.current_therapy_status = None
        self.current_patient_id = None
        self.run_time_stable_count = 0  # Counter for RUN_TIME stability
        self.last_run_time = 0
        self.run_time_timeout_start = None
        
        # Session management
        self.session_writer: Optional[SessionWriter] = None
        
        # Monitoring
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._emit_stats)
        self.stats_timer.start(5000)  # 5s stats update
        
        # Logger
        self.logger = logging.getLogger(f"DeviceWorker.{device_name}")
        
        self.logger.info(f"Advanced DeviceWorker initialized: {device_name}@{ip}:{port}")
    
    @Slot()
    def start(self):
        """Bắt đầu worker"""
        if self._is_running:
            return
        
        self._is_running = True
        self._should_reconnect = True
        
        # Khởi tạo session writer
        self.session_writer = SessionWriter(
            self.device_name,
            self.db_manager,
            self.session_config
        )
        self.session_writer.set_stats_callback(self._on_session_stats)
        
        # Bắt đầu connection thread
        self.connection_thread = threading.Thread(
            target=self._connection_worker,
            name=f"Connection-{self.device_name}",
            daemon=True
        )
        self.connection_thread.start()
        
        self.logger.info(f"Started device worker for {self.device_name}")
    
    @Slot()
    def stop(self):
        """Dừng worker"""
        if not self._is_running:
            return
        
        self.logger.info(f"Stopping device worker for {self.device_name}")
        
        self._is_running = False
        self._should_reconnect = False
        
        # Kết thúc session nếu đang chạy
        if self.treatment_state == TreatmentState.RUNNING:
            self._end_treatment("MANUAL_STOP")
        
        # Đóng connection
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
        
        # Dừng session writer
        if self.session_writer:
            self.session_writer.end_session("WORKER_STOPPED")
            self.session_writer = None
        
        # Dừng stats timer
        if hasattr(self, 'stats_timer'):
            self.stats_timer.stop()
        
        # Update status
        self.status_changed.emit("⏹️ Đã dừng", QColor("gray"))
        self.connection_state_changed.emit("Đã ngắt kết nối", QColor("gray"))
        
        # Set connection state
        self._set_connection_state(ConnectionState.DISCONNECTED)
        
        self.logger.info(f"Stopped device worker for {self.device_name}")
        
        # Emit finished signal để cleanup thread
        self.finished.emit()
    
    def _connection_worker(self):
        """Main connection worker thread"""
        reconnect_delay = 2.0
        last_packet_time = None
        
        while self._is_running and self._should_reconnect:
            try:
                self._set_connection_state(ConnectionState.CONNECTING)
                
                # Tạo connection
                self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.connection.settimeout(5.0)
                self.connection.connect((self.ip, self.port))
                
                self._set_connection_state(ConnectionState.CONNECTED)
                reconnect_delay = 2.0  # Reset delay
                last_packet_time = time.time()
                
                # Main receive loop
                while self._is_running:
                    try:
                        data = self.connection.recv(8192)
                        if not data:
                            break
                        
                        self.bytes_received += len(data)
                        self.stream_buffer.extend(data)
                        last_packet_time = time.time()
                        
                        # Process packets
                        self._process_stream_buffer()
                        
                    except socket.timeout:
                        # Check if we should stop
                        if not self._is_running:
                            break
                        
                        # Check for connection health
                        if time.time() - last_packet_time > 30:  # 30s no data
                            self.logger.warning("No data received for 30s, reconnecting")
                            break
                        continue
                    
                    except Exception as e:
                        if self._is_running:  # Only log if not intentionally stopped
                            self.logger.error(f"Receive error: {e}")
                        break
                
            except Exception as e:
                self.logger.warning(f"Connection error: {e}")
                
            finally:
                # Connection lost
                if self.connection:
                    try:
                        self.connection.close()
                    except:
                        pass
                    self.connection = None
                
                # Mark connection lost
                if self.session_writer:
                    self.session_writer.mark_connection_lost()
                
                self._set_connection_state(ConnectionState.DISCONNECTED)
            
            # Reconnect delay with backoff
            if self._is_running and self._should_reconnect:
                self._set_connection_state(ConnectionState.RECONNECTING)
                
                for i in range(int(reconnect_delay), 0, -1):
                    if not self._is_running:
                        break
                    self.status_changed.emit(f"Kết nối lại sau {i}s...", QColor("orange"))
                    time.sleep(1.0)
                
                reconnect_delay = min(reconnect_delay * 1.5, 60.0)  # Max 60s delay
    
    def _set_connection_state(self, state: ConnectionState):
        """Cập nhật connection state"""
        self.connection_state = state
        
        state_colors = {
            ConnectionState.DISCONNECTED: ("❌ Mất kết nối", QColor("red")),
            ConnectionState.CONNECTING: ("🔄 Đang kết nối...", QColor("orange")),
            ConnectionState.CONNECTED: ("✅ Đã kết nối", QColor("green")),
            ConnectionState.RECONNECTING: ("🔄 Đang kết nối lại...", QColor("orange"))
        }
        
        text, color = state_colors[state]
        self.connection_state_changed.emit(text, color)
        
        if state == ConnectionState.CONNECTED:
            self.status_changed.emit("🟢 Hoạt động", QColor("green"))
        elif state == ConnectionState.DISCONNECTED:
            self.status_changed.emit("🔴 Mất kết nối", QColor("red"))
    
    def _process_stream_buffer(self):
        """Xử lý stream buffer để extract packets"""
        while len(self.stream_buffer) >= HEADER_SIZE:
            # Tìm STX marker
            stx_pos = self.stream_buffer.find(STX_MARKER)
            if stx_pos == -1:
                self.stream_buffer.clear()
                return
            
            if stx_pos > 0:
                # Remove garbage before STX
                self.stream_buffer = self.stream_buffer[stx_pos:]
            
            # Check if we have enough data for header
            if len(self.stream_buffer) < HEADER_SIZE:
                return
            
            # Read body length from header
            try:
                mbl_bytes = self.stream_buffer[MBL_OFFSET_IN_HEADER : MBL_OFFSET_IN_HEADER + 4]
                body_length = struct.unpack('<I', mbl_bytes)[0]
            except struct.error:
                # Invalid header, skip
                self.stream_buffer = self.stream_buffer[1:]
                continue
            
            total_message_length = HEADER_SIZE + body_length
            
            # Check if we have complete packet
            if len(self.stream_buffer) < total_message_length:
                return
            
            # Extract complete packet
            packet_data = bytes(self.stream_buffer[:total_message_length])
            self.stream_buffer = self.stream_buffer[total_message_length:]
            
            # Process packet
            self._process_packet(packet_data)
    
    def _process_packet(self, packet_data: bytes):
        """Xử lý một packet hoàn chỉnh"""
        try:
            self.packet_count += 1
            self.last_packet_time = time.time()
            
            # Decode packet
            decoded_text, monitor_dict, header_dict = self.message_decoder.decode_packet_with_monitor_and_header(packet_data)
            
            # Emit monitoring data
            self.monitor_data.emit(monitor_dict)
            self.header_data.emit(header_dict)
            
            # Extract therapy info
            therapy_status = header_dict.get('therapy_status_id')
            patient_id = header_dict.get('patient_id')
            
            # FSM treatment lifecycle
            self._update_treatment_fsm(therapy_status, patient_id, monitor_dict, header_dict)
            
            # Ghi packet nếu treatment active
            if (self.treatment_state == TreatmentState.RUNNING and 
                self.session_writer and self.session_writer.is_active):
                self.session_writer.append_packet(packet_data)
            
        except Exception as e:
            self.logger.error(f"Error processing packet: {e}")
            self.error_occurred.emit("PACKET_DECODE_ERROR", str(e))
    
    def _update_treatment_fsm(self, therapy_status: int, patient_id: str,
                             monitor_dict: Dict, header_dict: Dict):
        """Cập nhật FSM treatment lifecycle"""
        current_run_time = monitor_dict.get('RUN_TIME', (0, ''))[0]
        
        if self.treatment_state == TreatmentState.IDLE:
            # Transition IDLE → RUNNING when therapy status = RUNNING
            if therapy_status == STATUS_RUNNING:
                self._start_treatment(header_dict, patient_id)
                
        elif self.treatment_state == TreatmentState.RUNNING:
            # Check for treatment end conditions
            if therapy_status == STATUS_FINALIZE:
                # Explicit END signal
                self._end_treatment("THERAPY_END")
                
            elif self._check_run_time_timeout(current_run_time):
                # RUN_TIME timeout (no increase in 180s)
                self._end_treatment("RUN_TIME_TIMEOUT")
                
            elif patient_id != self.current_patient_id and patient_id:
                # Patient ID changed = new session
                self._end_treatment("PATIENT_CHANGED")
                # Start new session
                if therapy_status == STATUS_RUNNING:
                    self._start_treatment(header_dict, patient_id)
        
        # Update current state
        self.current_therapy_status = therapy_status
        self.last_run_time = current_run_time
    
    def _check_run_time_timeout(self, current_run_time: float) -> bool:
        """Kiểm tra RUN_TIME timeout (180s không tăng)"""
        if current_run_time <= self.last_run_time:
            # RUN_TIME không tăng
            if self.run_time_timeout_start is None:
                self.run_time_timeout_start = time.time()
            elif time.time() - self.run_time_timeout_start > 180:  # 3 phút
                return True
        else:
            # RUN_TIME tăng = reset timeout
            self.run_time_timeout_start = None
        
        return False
    
    def _start_treatment(self, header_dict: Dict, patient_id: str):
        """Bắt đầu treatment mới"""
        if self.treatment_state == TreatmentState.RUNNING:
            # Kết thúc treatment hiện tại trước
            self._end_treatment("NEW_TREATMENT")
        
        self.treatment_state = TreatmentState.RUNNING
        self.current_patient_id = patient_id
        self.run_time_timeout_start = None
        
        # Bắt đầu session
        if self.session_writer:
            is_new_session = self.session_writer.start_session(header_dict, patient_id)
            
            if is_new_session:
                self.status_changed.emit("🔴 Ghi dữ liệu - Ca mới", QColor("red"))
                self.logger.info(f"Started new treatment for patient: {patient_id}")
            else:
                self.status_changed.emit("🔴 Ghi dữ liệu - Tiếp tục", QColor("red"))
                self.logger.info(f"Resumed treatment for patient: {patient_id}")
        
        # Log event
        self.db_manager.log_system_event(
            'SESSION_STARTED',
            self.device_name,
            None,
            f"Treatment started for patient {patient_id}"
        )
    
    def _end_treatment(self, reason: str):
        """Kết thúc treatment hiện tại"""
        if self.treatment_state != TreatmentState.RUNNING:
            return
        
        self.treatment_state = TreatmentState.ENDING
        
        if self.session_writer:
            self.session_writer.end_session(reason)
        
        self.treatment_state = TreatmentState.ENDED
        self.current_patient_id = None
        self.run_time_timeout_start = None
        
        # Update status
        if self.connection_state == ConnectionState.CONNECTED:
            self.status_changed.emit("🟢 Kết nối - Chờ ca mới", QColor("green"))
        
        self.logger.info(f"Treatment ended: {reason}")
        
        # Reset to IDLE để sẵn sàng cho ca mới
        self.treatment_state = TreatmentState.IDLE
    
    def _on_session_stats(self, stats: Dict):
        """Callback từ SessionWriter"""
        # Forward stats to UI
        combined_stats = self.get_stats()
        combined_stats.update(stats)
        self.stats_updated.emit(combined_stats)
    
    def _emit_stats(self):
        """Emit stats định kỳ"""
        if self._is_running:
            self.stats_updated.emit(self.get_stats())
    
    def get_stats(self) -> Dict[str, Any]:
        """Lấy stats hiện tại"""
        stats = {
            'device_name': self.device_name,
            'connection_state': self.connection_state.name,
            'treatment_state': self.treatment_state.name,
            'packets_received': self.packet_count,
            'bytes_received': self.bytes_received,
            'buffer_size': len(self.stream_buffer),
            'last_packet_time': self.last_packet_time,
            'current_patient_id': self.current_patient_id,
            'uptime': time.time() - (self.last_packet_time or time.time()) if self._is_running else 0
        }
        
        # Add session stats if available
        if self.session_writer:
            session_stats = self.session_writer.get_stats()
            stats.update({f"session_{k}": v for k, v in session_stats.items()})
        
        return stats
    
    def force_flush(self):
        """Force flush session writer"""
        if self.session_writer and self.session_writer.is_active:
            self.session_writer._flush_now()
    
    def get_session_info(self) -> Optional[Dict]:
        """Lấy thông tin session hiện tại"""
        if self.session_writer and self.session_writer.session_id:
            return self.db_manager.get_session_details(self.session_writer.session_id)
        return None
