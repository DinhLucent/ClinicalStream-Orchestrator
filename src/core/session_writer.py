#!/usr/bin/env python3
"""
SessionWriter - Manages session data recording with 12s flush buffer
Optimized for multi-device parallel execution, memory efficient
"""

import os
import threading
import time
import zlib
import gzip
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone
import logging
import queue
from dataclasses import dataclass

from advanced_database_manager import DatabaseManager, SessionMetadata, SegmentInfo

logger = logging.getLogger(__name__)

@dataclass
class SessionConfig:
    """Cấu hình cho SessionWriter"""
    flush_interval: float = 12.0      # 12 giây flush
    max_buffer_size: int = 16 * 1024 * 1024  # 16MB buffer max
    max_segment_size: int = 2 * 1024 * 1024 * 1024  # 2GB per segment
    backup_enabled: bool = True
    compression_enabled: bool = True
    compression_level: int = 6
    data_root: str = "data"

class SessionWriter:
    """
    Manages session data recording with:
    - 12s flush buffer
    - Segment management on reconnection
    - Thread-safe operations
    - Automatic backup on completion
    """
    
    def __init__(self, device_name: str, db_manager: DatabaseManager, 
                 config: SessionConfig = None):
        self.device_name = device_name
        self.db_manager = db_manager
        self.config = config or SessionConfig()
        
        # Session state
        self.session_id: Optional[int] = None
        self.session_uuid: Optional[str] = None
        self.session_metadata: Optional[SessionMetadata] = None
        self.session_dir: Optional[Path] = None
        
        # Current segment state
        self.current_segment_id: Optional[int] = None
        self.current_segment_index: int = 0
        self.current_segment_file: Optional[Path] = None
        self.current_file_handle = None
        
        # Buffer management
        self.write_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.total_bytes = 0
        self.total_packets = 0
        self.segment_bytes = 0
        self.segment_packets = 0
        
        # Timing
        self.last_flush_time = 0
        self.session_start_time = None
        
        # Flush timer
        self.flush_timer: Optional[threading.Timer] = None
        self.is_active = False
        
        # Stats callback
        self.stats_callback: Optional[Callable] = None
        
        logger.info(f"SessionWriter initialized for device: {device_name}")
    
    def set_stats_callback(self, callback: Callable[[Dict], None]):
        """Đặt callback để báo cáo stats"""
        self.stats_callback = callback
    
    def start_session(self, header_dict: Dict[str, Any], 
                     patient_id: str = None) -> bool:
        """
        Bắt đầu session mới hoặc resume session hiện tại
        Returns True nếu tạo session mới, False nếu resume
        """
        try:
            # Kiểm tra session hiện tại đang active
            existing_session = self.db_manager.find_active_session(
                self.device_name, patient_id
            )
            
            if existing_session and self._should_resume_session(existing_session, header_dict):
                # Resume session hiện tại
                self._resume_session(existing_session)
                return False
            else:
                # Tạo session mới
                self._create_new_session(header_dict, patient_id)
                return True
                
        except Exception as e:
            logger.error(f"Lỗi start session: {e}")
            return False
    
    def _should_resume_session(self, session: Dict, header_dict: Dict) -> bool:
        """Kiểm tra có nên resume session không"""
        # Resume nếu:
        # 1. Cùng device
        # 2. Cùng patient_id (nếu có)
        # 3. Session bắt đầu trong vòng 24h
        # 4. Cùng therapy type (nếu có)
        
        if session['device_name'] != self.device_name:
            return False
        
        # Kiểm tra thời gian
        start_time = datetime.fromisoformat(session['start_time_utc'].replace('Z', '+00:00'))
        time_diff = datetime.now(timezone.utc) - start_time
        if time_diff.total_seconds() > 24 * 3600:  # > 24h
            return False
        
        # Kiểm tra therapy type nếu có
        if (session.get('therapy_type_id') and 
            header_dict.get('therapy_type_id') and
            session['therapy_type_id'] != header_dict.get('therapy_type_id')):
            return False
        
        return True
    
    def _create_new_session(self, header_dict: Dict, patient_id: str = None):
        """Tạo session mới"""
        from advanced_database_manager import generate_session_uuid, sanitize_filename
        
        # Tạo metadata
        self.session_uuid = generate_session_uuid()
        self.session_start_time = datetime.now(timezone.utc)
        
        # Tạo thư mục session
        session_dir_name = self._generate_session_dir_name(patient_id)
        self.session_dir = Path(self.config.data_root) / self.device_name / session_dir_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Tạo metadata
        self.session_metadata = SessionMetadata(
            session_uuid=self.session_uuid,
            device_name=self.device_name,
            patient_id=patient_id,
            therapy_type=header_dict.get('therapy'),
            therapy_type_id=header_dict.get('therapy_type_id'),
            sw_rev=header_dict.get('sw_rev'),
            machine_id=header_dict.get('machine_id'),
            start_time_utc=self.session_start_time.isoformat(),
            raw_data_dir=str(self.session_dir)
        )
        
        # Lưu vào database
        self.session_id = self.db_manager.create_session(self.session_metadata)
        
        # Bắt đầu segment đầu tiên
        self._start_new_segment("CONNECTED")
        
        # Bắt đầu flush timer
        self._start_flush_timer()
        self.is_active = True
        
        logger.info(f"Created new session {self.session_uuid} for {self.device_name}")
    
    def _resume_session(self, session: Dict):
        """Resume session hiện tại"""
        self.session_id = session['id']
        self.session_uuid = session['session_uuid']
        self.session_dir = Path(session['raw_data_dir'])
        self.session_start_time = datetime.fromisoformat(
            session['start_time_utc'].replace('Z', '+00:00')
        )
        
        # Lấy segment cuối cùng để tính index
        segments = self.db_manager.get_session_details(self.session_id)['segments']
        if segments:
            self.current_segment_index = max(s['segment_index'] for s in segments) + 1
        else:
            self.current_segment_index = 0
        
        # Bắt đầu segment mới cho reconnection
        self._start_new_segment("RESUMED")
        
        # Đóng gap nếu có
        self.db_manager.close_connection_gap(self.session_id)
        
        # Bắt đầu flush timer
        self._start_flush_timer()
        self.is_active = True
        
        logger.info(f"Resumed session {self.session_uuid} for {self.device_name}")
    
    def _generate_session_dir_name(self, patient_id: str = None) -> str:
        """Tạo tên thư mục session"""
        from advanced_database_manager import sanitize_filename
        
        timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%SZ")
        
        if patient_id:
            patient_clean = sanitize_filename(patient_id)
            return f"{timestamp}__{patient_clean}__RUN"
        else:
            return f"{timestamp}__UNKNOWN__RUN"
    
    def _start_new_segment(self, connection_status: str = "CONNECTED"):
        """Bắt đầu segment file mới"""
        if self.current_file_handle:
            self._close_current_segment()
        
        # Tạo file segment mới
        segment_filename = f"segment_{self.current_segment_index:03d}.praw"
        self.current_segment_file = self.session_dir / segment_filename
        
        # Mở file để ghi
        self.current_file_handle = open(self.current_segment_file, 'ab')
        
        # Ghi vào database
        segment_info = SegmentInfo(
            session_id=self.session_id,
            segment_index=self.current_segment_index,
            file_path=str(self.current_segment_file),
            begin_utc=datetime.now(timezone.utc).isoformat(),
            connection_status=connection_status
        )
        
        self.current_segment_id = self.db_manager.add_segment(segment_info)
        
        # Reset counters
        self.segment_bytes = 0
        self.segment_packets = 0
        
        logger.info(f"Started segment {self.current_segment_index} for session {self.session_uuid}")
    
    def append_packet(self, packet_bytes: bytes):
        """Thêm packet vào buffer"""
        if not self.is_active:
            return
        
        with self.buffer_lock:
            self.write_buffer.extend(packet_bytes)
            self.total_packets += 1
            self.segment_packets += 1
            
            # Kiểm tra buffer size limit
            if len(self.write_buffer) >= self.config.max_buffer_size:
                logger.warning(f"Buffer full for {self.device_name}, forcing flush")
                self._flush_now()
    
    def _start_flush_timer(self):
        """Bắt đầu timer flush định kỳ"""
        if self.flush_timer:
            self.flush_timer.cancel()
        
        self.flush_timer = threading.Timer(self.config.flush_interval, self._scheduled_flush)
        self.flush_timer.daemon = True
        self.flush_timer.start()
    
    def _scheduled_flush(self):
        """Flush theo lịch"""
        if self.is_active:
            self._flush_now()
            # Schedule next flush
            self._start_flush_timer()
    
    def _flush_now(self):
        """Flush buffer ngay lập tức"""
        if not self.is_active or not self.current_file_handle:
            return
        
        start_time = time.time()
        
        with self.buffer_lock:
            if not self.write_buffer:
                return
                
            try:
                # Ghi buffer vào file
                self.current_file_handle.write(self.write_buffer)
                self.current_file_handle.flush()
                os.fsync(self.current_file_handle.fileno())  # Force disk write
                
                # Update counters
                bytes_written = len(self.write_buffer)
                self.total_bytes += bytes_written
                self.segment_bytes += bytes_written
                
                # Clear buffer
                self.write_buffer.clear()
                self.last_flush_time = time.time()
                
                # Update database stats
                self.db_manager.update_session(
                    self.session_id,
                    total_bytes=self.total_bytes,
                    total_packets=self.total_packets
                )
                
                if self.current_segment_id:
                    self.db_manager.update_segment(
                        self.current_segment_id,
                        bytes=self.segment_bytes,
                        packets=self.segment_packets
                    )
                
                # Callback stats
                if self.stats_callback:
                    self.stats_callback({
                        'total_bytes': self.total_bytes,
                        'total_packets': self.total_packets,
                        'flush_time_ms': (time.time() - start_time) * 1000
                    })
                
                logger.debug(f"Flushed {bytes_written} bytes for {self.device_name}")
                
                # Kiểm tra segment rotation
                if self.segment_bytes >= self.config.max_segment_size:
                    self._rotate_segment()
                    
            except Exception as e:
                logger.error(f"Lỗi flush buffer: {e}")
    
    def _rotate_segment(self):
        """Xoay segment khi đạt size limit"""
        self._close_current_segment()
        self.current_segment_index += 1
        self._start_new_segment("CONNECTED")
        
        logger.info(f"Rotated to segment {self.current_segment_index}")
    
    def _close_current_segment(self):
        """Đóng segment hiện tại"""
        if self.current_file_handle:
            try:
                self.current_file_handle.close()
                
                # Update segment end time
                if self.current_segment_id:
                    self.db_manager.update_segment(
                        self.current_segment_id,
                        end_utc=datetime.now(timezone.utc).isoformat(),
                        bytes=self.segment_bytes,
                        packets=self.segment_packets
                    )
                
            except Exception as e:
                logger.error(f"Lỗi đóng segment: {e}")
            finally:
                self.current_file_handle = None
    
    def mark_connection_lost(self):
        """Đánh dấu mất kết nối"""
        if self.session_id:
            self.db_manager.add_connection_gap(
                self.session_id,
                datetime.now(timezone.utc).isoformat(),
                "NETWORK_ERROR"
            )
        
        # Flush buffer cuối cùng
        if self.is_active:
            self._flush_now()
            
        logger.warning(f"Connection lost for session {self.session_uuid}")
    
    def end_session(self, reason: str = "NORMAL"):
        """Kết thúc session"""
        if not self.is_active:
            return
        
        self.is_active = False
        
        # Cancel flush timer
        if self.flush_timer:
            self.flush_timer.cancel()
            self.flush_timer = None
        
        # Final flush
        self._flush_now()
        
        # Close current segment
        self._close_current_segment()
        
        # Update session status
        end_time = datetime.now(timezone.utc).isoformat()
        self.db_manager.end_session(self.session_id, end_time)
        
        # Rename session directory to __END
        if self.session_dir:
            end_dir = Path(str(self.session_dir).replace("__RUN", "__END"))
            if self.session_dir.exists() and not end_dir.exists():
                self.session_dir.rename(end_dir)
                self.session_dir = end_dir
        
        # Create session metadata file
        self._create_session_metadata_file()
        
        # Backup if enabled
        if self.config.backup_enabled:
            self._backup_session()
        
        # Compress segments if enabled
        if self.config.compression_enabled:
            self._compress_segments()
        
        logger.info(f"Ended session {self.session_uuid} for {self.device_name}")
    
    def _create_session_metadata_file(self):
        """Tạo file session.meta.json"""
        if not self.session_dir:
            return
        
        try:
            metadata = {
                'session_uuid': self.session_uuid,
                'device_name': self.device_name,
                'start_time_utc': self.session_start_time.isoformat(),
                'end_time_utc': datetime.now(timezone.utc).isoformat(),
                'total_bytes': self.total_bytes,
                'total_packets': self.total_packets,
                'segments_count': self.current_segment_index + 1,
                'session_dir': str(self.session_dir)
            }
            
            metadata_file = self.session_dir / "session.meta.json"
            import json
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
                
        except Exception as e:
            logger.error(f"Lỗi tạo metadata file: {e}")
    
    def _backup_session(self):
        """Backup session directory"""
        if not self.session_dir or not self.session_dir.exists():
            return
        
        try:
            backup_root = Path(self.config.data_root) / "backup"
            backup_root.mkdir(exist_ok=True)
            
            backup_name = f"{self.device_name}_{self.session_uuid}.tar.gz"
            backup_path = backup_root / backup_name
            
            import tarfile
            with tarfile.open(backup_path, 'w:gz') as tar:
                tar.add(self.session_dir, arcname=self.session_dir.name)
            
            # Update database
            self.db_manager.update_session(
                self.session_id,
                backup_status='COMPLETED',
                backup_path=str(backup_path)
            )
            
            logger.info(f"Backup completed: {backup_path}")
            
        except Exception as e:
            logger.error(f"Lỗi backup session: {e}")
            self.db_manager.update_session(
                self.session_id,
                backup_status='FAILED'
            )
    
    def _compress_segments(self):
        """Nén các segment files"""
        if not self.session_dir:
            return
        
        try:
            for segment_file in self.session_dir.glob("segment_*.praw"):
                compressed_file = segment_file.with_suffix('.praw.gz')
                
                with open(segment_file, 'rb') as f_in:
                    with gzip.open(compressed_file, 'wb', 
                                 compresslevel=self.config.compression_level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Calculate compression ratio
                original_size = segment_file.stat().st_size
                compressed_size = compressed_file.stat().st_size
                ratio = compressed_size / original_size if original_size > 0 else 1.0
                
                # Remove original file
                segment_file.unlink()
                
                logger.info(f"Compressed {segment_file.name}: {ratio:.2%}")
                
        except Exception as e:
            logger.error(f"Lỗi nén segments: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Lấy stats hiện tại"""
        return {
            'session_uuid': self.session_uuid,
            'is_active': self.is_active,
            'total_bytes': self.total_bytes,
            'total_packets': self.total_packets,
            'buffer_size': len(self.write_buffer),
            'current_segment': self.current_segment_index,
            'last_flush': self.last_flush_time,
            'session_duration': (
                (datetime.now(timezone.utc) - self.session_start_time).total_seconds()
                if self.session_start_time else 0
            )
        }
