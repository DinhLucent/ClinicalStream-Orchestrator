import os
import threading
import sqlite3
import uuid
import json
import time
from collections import deque
from core.advanced_database_manager import DatabaseManager

RAW_BLOCK_SIZE = 64 * 1024  # 64KB
RAW_BLOCK_INTERVAL = 60     # 60s (giảm tần suất flush vì 10s sampling)

class StorageEngine:
    """
    2-Layer Storage Manager for ClinicalStream:
    - Raw segment (compressed block, binary file)
    - SQLite (metadata, samples, alarms, headers, gaps)
    """
    def __init__(self, base_dir, sqlite_path, sample_period_s=10, adaptive_thresholds=None):
        self.base_dir = base_dir
        self.sqlite_path = sqlite_path
        self.sample_period_s = sample_period_s
        self.adaptive_thresholds = adaptive_thresholds or {}
        self.conn = None
        self._init_db()
        self.lock = threading.Lock()
        self.raw_buffer = bytearray()
        self.samples_queue = deque()
        self.current_treatment = None
        self.current_segment = None
        self.current_alarm = None
        self.last_header = None
        self.writer_thread = None
        self.stop_writer = False
        self.last_raw_flush_ts = 0
        self.segment_file = None
        self.segment_path = None
        self.segment_index = 0
        self._start_writer()
        self.last_sample_values = {}
        self.last_sample_ts = 0

    def _init_db(self):
        self.conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        cur = self.conn.cursor()
        # Tạo bảng nếu chưa có
        cur.execute('''CREATE TABLE IF NOT EXISTS treatments (
            treatment_id   TEXT PRIMARY KEY,
            device_name    TEXT,
            serial_number  TEXT,
            patient_id     TEXT,
            therapy_type   INTEGER,
            start_ts       INTEGER,
            end_ts         INTEGER,
            status         TEXT,
            segments_count INTEGER DEFAULT 0,
            notes          TEXT
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS segments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            treatment_id  TEXT,
            part_index    INTEGER,
            file_path     TEXT,
            start_ts      INTEGER,
            end_ts        INTEGER,
            bytes         INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS headers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            treatment_id  TEXT,
            ts            INTEGER,
            machine_id    INTEGER,
            sw_rev        TEXT,
            therapy       TEXT,
            status        TEXT,
            patient_id    TEXT,
            flags_hex     TEXT,
            msg_info      INTEGER,
            body_length   INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS samples (
            treatment_id  TEXT,
            ts            INTEGER,
            param_id      INTEGER,
            name          TEXT,
            value_num     REAL,
            value_text    TEXT,
            unit          TEXT,
            kind          TEXT,
            PRIMARY KEY (treatment_id, ts, param_id)
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS alarms (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            treatment_id  TEXT,
            alarm_id      INTEGER,
            alarm_name    TEXT,
            priority      INTEGER,
            start_ts      INTEGER,
            end_ts        INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS gaps (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            treatment_id  TEXT,
            start_ts      INTEGER,
            end_ts        INTEGER
        )''')
        self.conn.commit()

    def _start_writer(self):
        def writer():
            while not self.stop_writer:
                self._flush_samples()
                time.sleep(5.0)  # 5s interval thay vì 0.5s (vì data ít hơn 10x)
        self.writer_thread = threading.Thread(target=writer, daemon=True)
        self.writer_thread.start()

    def _flush_samples(self):
        """Ghi samples batch vào DB."""
        batch = []
        with self.lock:
            while self.samples_queue:
                batch.append(self.samples_queue.popleft())
        if not batch:
            return
        cur = self.conn.cursor()
        rows = []
        for treatment_id, ts, monitor_dict, param_id_map in batch:
            for name, (value, unit) in monitor_dict.items():
                # Xác định loại value
                if isinstance(value, (int, float)):
                    value_num = value
                    value_text = None
                else:
                    value_num = None
                    value_text = str(value)
                kind = 'ALARM' if name.startswith('🚨 ALARM_') else 'Actual'
                param_id = None
                if param_id_map and name in param_id_map:
                    param_id = param_id_map[name]
                rows.append((treatment_id, ts, param_id, name, value_num, value_text, unit, kind))
        if rows:
            cur.executemany('''INSERT OR REPLACE INTO samples
                (treatment_id, ts, param_id, name, value_num, value_text, unit, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            self.conn.commit()

    def start_treatment(self, header_dict):
        """Bắt đầu ca chạy mới, tạo TreatmentUUID, mở segment mới."""
        self.current_treatment = str(uuid.uuid4())
        self.segment_index = 0
        now = time.localtime()
        device = header_dict.get('machine_id', 'unknown')
        serial_number = header_dict.get('machine_id', None)
        patient_id = header_dict.get('patient_id', None)
        therapy_type = header_dict.get('therapy', None)
        start_ts = int(time.time() * 1000)
        folder = os.path.join(self.base_dir, str(device),
                              f"{now.tm_year:04d}", f"{now.tm_mon:02d}", f"{now.tm_mday:02d}",
                              self.current_treatment)
        os.makedirs(folder, exist_ok=True)
        self.segment_path = os.path.join(folder, "treatment_data.sbin")
        self.segment_file = open(self.segment_path, 'ab')
        self.last_raw_flush_ts = time.time()
        self.raw_buffer = bytearray()
        self.last_header = None
        # Ghi treatment vào DB
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO treatments (treatment_id, device_name, serial_number, patient_id, therapy_type, start_ts, status) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (self.current_treatment, str(device), serial_number, patient_id, therapy_type, start_ts, 'RUN'))
        # Ghi segment vào DB (single file per treatment)
        cur.execute('''INSERT INTO segments (treatment_id, part_index, file_path, start_ts) VALUES (?, ?, ?, ?)''',
            (self.current_treatment, 0, self.segment_path, start_ts))
        self.conn.commit()
        self.current_segment = {'id': cur.lastrowid, 'start_ts': start_ts, 'file_path': self.segment_path}

    def append_raw(self, packet_bytes, recv_ts):
        """Gom raw vào buffer, ghi ra file segment khi đủ block hoặc đủ thời gian.
        
        Args:
            packet_bytes: Raw packet data
            recv_ts: Local timestamp (ms) khi nhận packet - KHÔNG phải thời gian từ thiết bị
        """
        if not self.segment_file:
            return
        # Định dạng: | u32 len | i64 recv_unix_ms | bytes[len] |
        plen = len(packet_bytes)
        entry = plen.to_bytes(4, 'little') + int(recv_ts).to_bytes(8, 'little') + packet_bytes
        self.raw_buffer.extend(entry)
        now = time.time()
        if len(self.raw_buffer) >= RAW_BLOCK_SIZE or (now - self.last_raw_flush_ts) >= RAW_BLOCK_INTERVAL:
            self.segment_file.write(self.raw_buffer)
            self.segment_file.flush()
            self.raw_buffer = bytearray()
            self.last_raw_flush_ts = now
            # print(f"[StorageEngine] Đã ghi block raw {self.segment_path}")

    def feed_monitor(self, monitor_dict, ts, param_id_map=None):
        """Nhận monitor_dict mỗi gói, gom vào aggregator, batch ghi samples (adaptive).
        
        Args:
            monitor_dict: Dict chứa thông số monitor
            ts: Local timestamp (ms) - thời gian máy chứa phần mềm, KHÔNG phải thời gian thiết bị
            param_id_map: Optional mapping parameters
        """
        if not self.current_treatment:
            return
        push = False
        # Đẩy theo chu kỳ cố định (simplified for 10s sampling)
        if (ts - self.last_sample_ts) >= self.sample_period_s * 1000:
            # Push toàn bộ monitor_dict một lần
            with self.lock:
                self.samples_queue.append((self.current_treatment, ts, monitor_dict, param_id_map))
            self.last_sample_ts = ts
            # Update cache
            for name, (value, unit) in monitor_dict.items():
                self.last_sample_values[name] = value

    def snapshot_header(self, header_dict, ts):
        """Lưu header vào DB nếu khác lần trước.
        
        Args:
            header_dict: Dictionary chứa thông tin header  
            ts: Local timestamp (ms) - thời gian máy chứa phần mềm
        """
        if not self.current_treatment or not header_dict:
            return
        # So sánh các trường chính
        fields = ['machine_id', 'sw_rev', 'therapy', 'status', 'patient_id', 'flags', 'msg_info', 'body_length']
        changed = False
        if self.last_header is None:
            changed = True
        else:
            for f in fields:
                if str(header_dict.get(f)) != str(self.last_header.get(f)):
                    changed = True
                    break
        if changed:
            cur = self.conn.cursor()
            cur.execute('''INSERT INTO headers (treatment_id, ts, machine_id, sw_rev, therapy, status, patient_id, flags_hex, msg_info, body_length)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                self.current_treatment, ts,
                header_dict.get('machine_id'),
                header_dict.get('sw_rev'),
                header_dict.get('therapy'),
                header_dict.get('status'),
                header_dict.get('patient_id'),
                header_dict.get('flags'),
                header_dict.get('msg_info'),
                int(str(header_dict.get('body_length', '0')).split()[0]) if header_dict.get('body_length') else None
            ))
            self.conn.commit()
            self.last_header = dict(header_dict)

    def handle_alarm(self, alarm, ts):
        """Ghép alarm thành khoảng thời gian, ghi vào DB khi có thay đổi.
        
        Args:
            alarm: Tuple (alarm_name, (state, kind))
            ts: Local timestamp (ms) - thời gian máy chứa phần mềm
        """
        if not self.current_treatment or not alarm:
            return
        alarm_name, (state, kind) = alarm
        alarm_id = None  # Nếu có thể map id thì bổ sung
        cur = self.conn.cursor()
        # Nếu có alarm mới PRESENT
        if state == 'PRESENT':
            if self.current_alarm is None or self.current_alarm['alarm_name'] != alarm_name:
                # Đóng alarm cũ nếu có
                if self.current_alarm:
                    cur.execute('''UPDATE alarms SET end_ts=? WHERE id=?''', (ts, self.current_alarm['id']))
                # Mở alarm mới
                cur.execute('''INSERT INTO alarms (treatment_id, alarm_id, alarm_name, priority, start_ts, end_ts) VALUES (?, ?, ?, ?, ?, NULL)''',
                    (self.current_treatment, alarm_id, alarm_name, None, ts))
                alarm_rowid = cur.lastrowid
                self.current_alarm = {'id': alarm_rowid, 'alarm_name': alarm_name, 'start_ts': ts}
                self.conn.commit()
        else:  # OVERRIDDEN hoặc không còn alarm
            if self.current_alarm:
                cur.execute('''UPDATE alarms SET end_ts=? WHERE id=?''', (ts, self.current_alarm['id']))
                self.conn.commit()
                self.current_alarm = None

    def rotate_segment_if_needed(self, ts):
        """DISABLED: Không xoay vòng segment - giữ nguyên 1 file cho cả ca chạy."""
        # File rotation bị tắt - tất cả dữ liệu binary của 1 ca chạy sẽ ở trong 1 file
        pass

    def mark_gap(self, start_ts, end_ts):
        if not self.current_treatment:
            return
        cur = self.conn.cursor()
        cur.execute('''INSERT INTO gaps (treatment_id, start_ts, end_ts) VALUES (?, ?, ?)''',
            (self.current_treatment, start_ts, end_ts))
        self.conn.commit()

    def end_treatment(self, ts):
        if self.segment_file:
            if self.raw_buffer:
                self.segment_file.write(self.raw_buffer)
                self.segment_file.flush()
                self.raw_buffer = bytearray()
            self.segment_file.close()
            self.segment_file = None
        # Cập nhật end_ts cho treatment và segment
        cur = self.conn.cursor()
        cur.execute('''UPDATE treatments SET end_ts=?, status=? WHERE treatment_id=?''', (ts, 'ENDED', self.current_treatment))
        if self.current_segment:
            cur.execute('''UPDATE segments SET end_ts=? WHERE id=?''', (ts, self.current_segment['id']))
        self.conn.commit()
        # Ghi metadata.json
        meta = {
            'treatment_id': self.current_treatment,
            'device_name': self.current_segment.get('file_path', ''),
            'start_ts': self.current_segment.get('start_ts', None),
            'end_ts': ts,
            'status': 'ENDED',
        }
        meta_path = os.path.join(os.path.dirname(self.segment_path), 'metadata.json')
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        # Move tmp -> final (nếu cần, ở đây giả sử đã ở đúng thư mục)
        # Nếu cần move, dùng os.replace(tmp_folder, final_folder)
        self.current_treatment = None
        self.current_segment = None
        self.last_header = None
        self.current_alarm = None
