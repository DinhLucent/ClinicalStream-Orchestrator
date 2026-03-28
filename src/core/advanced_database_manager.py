#!/usr/bin/env python3
"""
Advanced Database Manager for ClinicalStream Orchestrator
SQLite management with connection pooling, batch operations, and thread safety
"""

import sqlite3
import threading
import queue
import time
import json
import uuid
import hashlib
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

@dataclass
class DeviceConfig:
    """Cấu hình thiết bị"""
    name: str
    ip: str
    port: int = 3002
    enabled: bool = True
    auto_start: bool = False

@dataclass
class SessionMetadata:
    """Metadata cho một session điều trị"""
    session_uuid: str
    device_name: str
    patient_id: Optional[str] = None
    therapy_type: Optional[str] = None
    therapy_type_id: Optional[int] = None
    sw_rev: Optional[str] = None
    machine_id: Optional[int] = None
    status: str = 'RUNNING'
    start_time_utc: str = None
    raw_data_dir: str = None
    
    def __post_init__(self):
        if self.start_time_utc is None:
            self.start_time_utc = datetime.now(timezone.utc).isoformat()

@dataclass
class SegmentInfo:
    """Thông tin segment data file"""
    session_id: int
    segment_index: int
    file_path: str
    begin_utc: str
    connection_status: str = 'CONNECTED'
    
class DatabaseManager:
    """Advanced database manager với thread safety và batch operations"""
    
    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = Path(db_path)
        self.max_connections = max_connections
        self._connection_pool = queue.Queue(maxsize=max_connections)
        self._pool_lock = threading.Lock()
        self._init_pool()
        self._ensure_schema()
        
        # Background writer thread
        self._write_queue = queue.Queue()
        self._writer_thread = None
        self._shutdown_event = threading.Event()
        self._start_writer_thread()
        
    def _init_pool(self):
        """Khởi tạo connection pool"""
        for _ in range(self.max_connections):
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            
            # Tối ưu performance
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -8000")  # 8MB per connection
            conn.execute("PRAGMA temp_store = MEMORY")
            
            self._connection_pool.put(conn)
    
    def _ensure_schema(self):
        """Đảm bảo database schema được tạo"""
        schema_file = Path(__file__).parent / "database_schema.sql"
        if schema_file.exists():
            with self.get_connection() as conn:
                conn.executescript(schema_file.read_text(encoding='utf-8'))
                conn.commit()
        else:
            logger.warning(f"Schema file không tìm thấy: {schema_file}")
    
    @contextmanager
    def get_connection(self):
        """Context manager để lấy connection từ pool"""
        conn = None
        try:
            conn = self._connection_pool.get(timeout=10.0)
            yield conn
        except queue.Empty:
            logger.error("Không thể lấy connection từ pool")
            raise RuntimeError("Database connection pool exhausted")
        finally:
            if conn:
                self._connection_pool.put(conn)
    
    def _start_writer_thread(self):
        """Bắt đầu background writer thread"""
        self._writer_thread = threading.Thread(
            target=self._writer_worker,
            name="DatabaseWriter",
            daemon=True
        )
        self._writer_thread.start()
        logger.info("Database writer thread started")
    
    def _writer_worker(self):
        """Background worker xử lý batch writes"""
        batch = []
        last_flush = time.time()
        
        while not self._shutdown_event.is_set():
            try:
                # Collect writes trong 1 giây hoặc cho đến khi có 100 items
                timeout = max(0.1, 1.0 - (time.time() - last_flush))
                
                try:
                    item = self._write_queue.get(timeout=timeout)
                    batch.append(item)
                    
                    # Flush khi batch đầy hoặc timeout
                    if len(batch) >= 100 or (time.time() - last_flush) >= 1.0:
                        self._flush_batch(batch)
                        batch = []
                        last_flush = time.time()
                        
                except queue.Empty:
                    if batch:
                        self._flush_batch(batch)
                        batch = []
                        last_flush = time.time()
                        
            except Exception as e:
                logger.error(f"Lỗi trong database writer: {e}")
                time.sleep(0.1)
        
        # Flush remaining batch before shutdown
        if batch:
            self._flush_batch(batch)
    
    def _flush_batch(self, batch: List[Tuple]):
        """Flush một batch các operations"""
        if not batch:
            return
            
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                for operation, query, params in batch:
                    if operation == 'execute':
                        cursor.execute(query, params)
                    elif operation == 'executemany':
                        cursor.executemany(query[0], query[1])
                
                conn.commit()
                logger.debug(f"Flushed batch of {len(batch)} operations")
                
        except Exception as e:
            logger.error(f"Lỗi flush batch: {e}")
    
    def queue_write(self, query: str, params: Tuple = ()):
        """Queue một write operation"""
        self._write_queue.put(('execute', query, params))
    
    def queue_write_many(self, query: str, params_list: List[Tuple]):
        """Queue một batch write operation"""
        self._write_queue.put(('executemany', (query, params_list), None))
    
    # Device Management
    def get_devices(self) -> List[DeviceConfig]:
        """Lấy danh sách tất cả thiết bị"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name, ip, port, enabled, auto_start FROM devices ORDER BY name"
            )
            return [DeviceConfig(**row) for row in cursor.fetchall()]
    
    def add_device(self, device: DeviceConfig) -> bool:
        """Thêm thiết bị mới"""
        try:
            with self.get_connection() as conn:
                conn.execute(
                    """INSERT INTO devices (name, ip, port, enabled, auto_start) 
                       VALUES (?, ?, ?, ?, ?)""",
                    (device.name, device.ip, device.port, device.enabled, device.auto_start)
                )
                conn.commit()
                logger.info(f"Added device: {device.name}")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Device already exists: {device.name}")
            return False
    
    def update_device(self, device: DeviceConfig) -> bool:
        """Cập nhật thiết bị"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """UPDATE devices 
                   SET ip=?, port=?, enabled=?, auto_start=? 
                   WHERE name=?""",
                (device.ip, device.port, device.enabled, device.auto_start, device.name)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_device(self, device_name: str) -> bool:
        """Xóa thiết bị"""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM devices WHERE name=?", (device_name,))
            conn.commit()
            return cursor.rowcount > 0
    
    # Session Management
    def create_session(self, metadata: SessionMetadata) -> int:
        """Tạo session mới và trả về session ID"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO sessions 
                   (session_uuid, device_name, patient_id, therapy_type, therapy_type_id,
                    sw_rev, machine_id, status, start_time_utc, raw_data_dir, last_update_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    metadata.session_uuid,
                    metadata.device_name,
                    metadata.patient_id,
                    metadata.therapy_type,
                    metadata.therapy_type_id,
                    metadata.sw_rev,
                    metadata.machine_id,
                    metadata.status,
                    metadata.start_time_utc,
                    metadata.raw_data_dir,
                    datetime.now(timezone.utc).isoformat()
                )
            )
            conn.commit()
            session_id = cursor.lastrowid
            
            # Log system event
            self.log_system_event(
                'SESSION_STARTED',
                metadata.device_name,
                session_id,
                f"Started session {metadata.session_uuid}"
            )
            
            return session_id
    
    def update_session(self, session_id: int, **kwargs):
        """Cập nhật session (async queue)"""
        # Auto update last_update_utc
        kwargs['last_update_utc'] = datetime.now(timezone.utc).isoformat()
        
        set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
        query = f"UPDATE sessions SET {set_clause} WHERE id=?"
        params = tuple(kwargs.values()) + (session_id,)
        
        self.queue_write(query, params)
    
    def end_session(self, session_id: int, end_time_utc: str = None):
        """Kết thúc session"""
        if end_time_utc is None:
            end_time_utc = datetime.now(timezone.utc).isoformat()
        
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET status='ENDED', end_time_utc=?, last_update_utc=? WHERE id=?",
                (end_time_utc, datetime.now(timezone.utc).isoformat(), session_id)
            )
            conn.commit()
    
    def get_active_sessions(self) -> List[Dict]:
        """Lấy các session đang active"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT s.*, d.ip, d.port,
                   (julianday('now') - julianday(s.start_time_utc)) * 86400 as duration_live
                   FROM sessions s
                   JOIN devices d ON s.device_name = d.name
                   WHERE s.status = 'RUNNING'
                   ORDER BY s.start_time_utc DESC"""
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def find_active_session(self, device_name: str, patient_id: str = None) -> Optional[Dict]:
        """Tìm session active để ghép nối sau reconnect"""
        with self.get_connection() as conn:
            if patient_id:
                cursor = conn.execute(
                    """SELECT * FROM sessions 
                       WHERE device_name=? AND patient_id=? AND status='RUNNING'
                       ORDER BY start_time_utc DESC LIMIT 1""",
                    (device_name, patient_id)
                )
            else:
                cursor = conn.execute(
                    """SELECT * FROM sessions 
                       WHERE device_name=? AND status='RUNNING'
                       ORDER BY start_time_utc DESC LIMIT 1""",
                    (device_name,)
                )
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Segment Management
    def add_segment(self, segment: SegmentInfo) -> int:
        """Thêm segment mới"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO session_segments 
                   (session_id, segment_index, begin_utc, file_path, connection_status)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    segment.session_id,
                    segment.segment_index,
                    segment.begin_utc,
                    segment.file_path,
                    segment.connection_status
                )
            )
            conn.commit()
            return cursor.lastrowid
    
    def update_segment(self, segment_id: int, **kwargs):
        """Cập nhật segment (async)"""
        set_clause = ", ".join([f"{k}=?" for k in kwargs.keys()])
        query = f"UPDATE session_segments SET {set_clause} WHERE id=?"
        params = tuple(kwargs.values()) + (segment_id,)
        
        self.queue_write(query, params)
    
    # Gap tracking
    def add_connection_gap(self, session_id: int, gap_start_utc: str, reason: str = "NETWORK_ERROR"):
        """Ghi nhận mất kết nối"""
        self.queue_write(
            """INSERT INTO connection_gaps (session_id, gap_start_utc, reason)
               VALUES (?, ?, ?)""",
            (session_id, gap_start_utc, reason)
        )
    
    def close_connection_gap(self, session_id: int, gap_end_utc: str = None):
        """Đóng gap khi khôi phục kết nối"""
        if gap_end_utc is None:
            gap_end_utc = datetime.now(timezone.utc).isoformat()
        
        self.queue_write(
            """UPDATE connection_gaps 
               SET gap_end_utc=?, duration_seconds=CAST((julianday(?) - julianday(gap_start_utc)) * 86400 AS INTEGER)
               WHERE session_id=? AND gap_end_utc IS NULL""",
            (gap_end_utc, gap_end_utc, session_id)
        )
    
    # System events
    def log_system_event(self, event_type: str, device_name: str = None, 
                        session_id: int = None, message: str = "", 
                        details: Dict = None, severity: str = 'INFO'):
        """Log system event"""
        details_json = json.dumps(details) if details else None
        
        self.queue_write(
            """INSERT INTO system_events 
               (event_type, device_name, session_id, message, details, severity)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_type, device_name, session_id, message, details_json, severity)
        )
    
    # History queries
    def get_session_history(self, device_name: str = None, days: int = 30) -> List[Dict]:
        """Lấy lịch sử sessions"""
        with self.get_connection() as conn:
            if device_name:
                cursor = conn.execute(
                    """SELECT s.*, 
                       COUNT(DISTINCT seg.id) as segment_count,
                       COUNT(DISTINCT g.id) as gap_count
                       FROM sessions s
                       LEFT JOIN session_segments seg ON s.id = seg.session_id
                       LEFT JOIN connection_gaps g ON s.id = g.session_id
                       WHERE s.device_name = ? 
                       AND julianday('now') - julianday(s.start_time_utc) <= ?
                       GROUP BY s.id
                       ORDER BY s.start_time_utc DESC""",
                    (device_name, days)
                )
            else:
                cursor = conn.execute(
                    """SELECT s.*, 
                       COUNT(DISTINCT seg.id) as segment_count,
                       COUNT(DISTINCT g.id) as gap_count
                       FROM sessions s
                       LEFT JOIN session_segments seg ON s.id = seg.session_id
                       LEFT JOIN connection_gaps g ON s.id = g.session_id
                       WHERE julianday('now') - julianday(s.start_time_utc) <= ?
                       GROUP BY s.id
                       ORDER BY s.start_time_utc DESC""",
                    (days,)
                )
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_session_details(self, session_id: int) -> Optional[Dict]:
        """Lấy chi tiết session với segments và gaps"""
        with self.get_connection() as conn:
            # Session info
            cursor = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
            session = cursor.fetchone()
            if not session:
                return None
            
            session = dict(session)
            
            # Segments
            cursor = conn.execute(
                "SELECT * FROM session_segments WHERE session_id=? ORDER BY segment_index",
                (session_id,)
            )
            session['segments'] = [dict(row) for row in cursor.fetchall()]
            
            # Gaps
            cursor = conn.execute(
                "SELECT * FROM connection_gaps WHERE session_id=? ORDER BY gap_start_utc",
                (session_id,)
            )
            session['gaps'] = [dict(row) for row in cursor.fetchall()]
            
            return session
    
    def shutdown(self):
        """Shutdown database manager"""
        logger.info("Shutting down database manager")
        self._shutdown_event.set()
        
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=5.0)
        
        # Close all connections
        while not self._connection_pool.empty():
            try:
                conn = self._connection_pool.get_nowait()
                conn.close()
            except queue.Empty:
                break

# Utility functions
def hash_patient_id(patient_id: str, salt: str = "ClinicalStream_salt") -> str:
    """Hash patient ID để bảo mật"""
    if not patient_id:
        return None
    
    return hashlib.sha256(f"{patient_id}{salt}".encode()).hexdigest()[:16]

def generate_session_uuid() -> str:
    """Tạo UUID cho session"""
    return str(uuid.uuid4())

def sanitize_filename(filename: str) -> str:
    """Làm sạch filename để safe cho filesystem"""
    import re
    # Chỉ giữ alphanumeric, dash, underscore, dot
    return re.sub(r'[^\w\-_.]', '_', filename)
