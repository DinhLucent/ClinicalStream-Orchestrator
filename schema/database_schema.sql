-- ClinicalStream Device Manager Database Schema
-- Phiên bản: 2.0 - Tối ưu cho production
-- Ngày tạo: 2025-01-15

-- Bảng thiết bị
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    ip TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 3002,
    enabled BOOLEAN DEFAULT 1,
    auto_start BOOLEAN DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- Bảng phiên điều trị (sessions)
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT UNIQUE NOT NULL,  -- UUID cho mỗi ca điều trị
    device_name TEXT NOT NULL,
    patient_id TEXT,                    -- Có thể NULL hoặc được hash
    therapy_type TEXT,                  -- Loại liệu pháp
    therapy_type_id INTEGER,            -- ID từ reference DB
    sw_rev TEXT,                        -- Software revision (a.bVcRd)
    machine_id INTEGER,                 -- ID máy từ header
    status TEXT CHECK(status IN ('RUNNING','ENDED','INTERRUPTED')) NOT NULL DEFAULT 'RUNNING',
    start_time_utc TEXT NOT NULL,       -- ISO8601 UTC timestamp
    end_time_utc TEXT,                  -- NULL khi đang chạy
    duration_seconds INTEGER,           -- Thời gian chạy tính toán
    raw_data_dir TEXT NOT NULL,         -- Đường dẫn thư mục chứa data
    total_bytes INTEGER DEFAULT 0,      -- Tổng bytes đã lưu
    total_packets INTEGER DEFAULT 0,    -- Tổng số gói tin
    last_update_utc TEXT NOT NULL,      -- Lần cập nhật cuối
    notes TEXT,                         -- Ghi chú
    backup_status TEXT DEFAULT 'PENDING' CHECK(backup_status IN ('PENDING','COMPLETED','FAILED')),
    backup_path TEXT,                   -- Đường dẫn file backup
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    
    FOREIGN KEY(device_name) REFERENCES devices(name) ON UPDATE CASCADE
);

-- Bảng segments cho mỗi session (khi reconnect)
CREATE TABLE IF NOT EXISTS session_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    segment_index INTEGER NOT NULL,     -- 0, 1, 2, ... theo thứ tự
    begin_utc TEXT NOT NULL,            -- Thời điểm bắt đầu segment
    end_utc TEXT,                       -- NULL nếu segment đang active
    file_path TEXT NOT NULL,            -- Đường dẫn file segment_<n>.praw
    bytes INTEGER DEFAULT 0,            -- Kích thước file
    packets INTEGER DEFAULT 0,          -- Số gói tin trong segment
    connection_status TEXT DEFAULT 'CONNECTED' CHECK(connection_status IN ('CONNECTED','DISCONNECTED','RESUMED')),
    crc32 TEXT,                         -- CRC32 checksum cho toàn vẹn
    compressed_path TEXT,               -- Đường dẫn file nén (sau khi kết thúc)
    compression_ratio REAL,             -- Tỷ lệ nén
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    UNIQUE(session_id, segment_index)
);

-- Bảng gaps (mất kết nối)
CREATE TABLE IF NOT EXISTS connection_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    gap_start_utc TEXT NOT NULL,        -- Thời điểm mất kết nối
    gap_end_utc TEXT,                   -- Thời điểm khôi phục (NULL nếu chưa)
    duration_seconds INTEGER,           -- Thời gian mất kết nối
    reason TEXT,                        -- Lý do: NETWORK_ERROR, TIMEOUT, etc.
    packets_lost_estimate INTEGER,      -- Ước tính số gói bị mất
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Bảng metadata headers (sample định kỳ)
CREATE TABLE IF NOT EXISTS session_headers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp_utc TEXT NOT NULL,        -- Thời điểm ghi header
    machine_id INTEGER,
    sw_rev TEXT,
    therapy_type_id INTEGER,
    therapy_status_id INTEGER,
    patient_id TEXT,
    flags INTEGER,
    msg_info INTEGER,
    body_length INTEGER,
    raw_header_hex TEXT,                -- Header hex để debug
    
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Bảng alarms (extracted từ packets)
CREATE TABLE IF NOT EXISTS session_alarms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    alarm_id INTEGER NOT NULL,          -- ID alarm từ reference DB
    alarm_name TEXT,                    -- Tên alarm từ reference DB
    priority INTEGER,                   -- Mức độ ưu tiên
    state TEXT CHECK(state IN ('PRESENT','OVERRIDDEN','CLEARED')),
    start_time_utc TEXT NOT NULL,       -- Thời điểm alarm xuất hiện
    end_time_utc TEXT,                  -- Thời điểm alarm biến mất
    duration_seconds INTEGER,           -- Thời gian alarm kéo dài
    
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- Bảng system events (hệ thống)
CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(event_type IN ('DEVICE_CONNECTED','DEVICE_DISCONNECTED','SESSION_STARTED','SESSION_ENDED','BACKUP_COMPLETED','ERROR','WARNING')),
    device_name TEXT,
    session_id INTEGER,
    message TEXT NOT NULL,
    details TEXT,                       -- JSON chi tiết
    severity TEXT DEFAULT 'INFO' CHECK(severity IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
    timestamp_utc TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    
    FOREIGN KEY(device_name) REFERENCES devices(name) ON UPDATE CASCADE,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- Indexes cho performance
CREATE INDEX IF NOT EXISTS idx_sessions_device_time ON sessions(device_name, start_time_utc);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status, device_name);
CREATE INDEX IF NOT EXISTS idx_segments_session ON session_segments(session_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_gaps_session ON connection_gaps(session_id, gap_start_utc);
CREATE INDEX IF NOT EXISTS idx_headers_session_time ON session_headers(session_id, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_alarms_session_time ON session_alarms(session_id, start_time_utc);
CREATE INDEX IF NOT EXISTS idx_events_time_type ON system_events(timestamp_utc, event_type);
CREATE INDEX IF NOT EXISTS idx_events_device ON system_events(device_name, timestamp_utc);

-- Views tiện ích
CREATE VIEW IF NOT EXISTS active_sessions AS
SELECT 
    s.*,
    d.ip,
    d.port,
    (julianday('now') - julianday(s.start_time_utc)) * 86400 as duration_seconds_live,
    COUNT(g.id) as gap_count
FROM sessions s
LEFT JOIN devices d ON s.device_name = d.name
LEFT JOIN connection_gaps g ON s.id = g.session_id
WHERE s.status = 'RUNNING'
GROUP BY s.id;

CREATE VIEW IF NOT EXISTS session_summary AS
SELECT 
    s.*,
    COUNT(DISTINCT seg.id) as segment_count,
    COUNT(DISTINCT g.id) as gap_count,
    COUNT(DISTINCT a.id) as alarm_count,
    CASE 
        WHEN s.status = 'RUNNING' THEN (julianday('now') - julianday(s.start_time_utc)) * 86400
        ELSE s.duration_seconds
    END as effective_duration
FROM sessions s
LEFT JOIN session_segments seg ON s.id = seg.session_id
LEFT JOIN connection_gaps g ON s.id = g.session_id  
LEFT JOIN session_alarms a ON s.id = a.session_id
GROUP BY s.id;

-- Triggers để tự động update timestamps
CREATE TRIGGER IF NOT EXISTS devices_updated_at 
AFTER UPDATE ON devices
BEGIN
    UPDATE devices SET updated_at = datetime('now', 'utc') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS sessions_update_duration
AFTER UPDATE OF end_time_utc ON sessions
WHEN NEW.end_time_utc IS NOT NULL AND OLD.end_time_utc IS NULL
BEGIN
    UPDATE sessions 
    SET duration_seconds = CAST((julianday(NEW.end_time_utc) - julianday(NEW.start_time_utc)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

-- Insert default devices nếu bảng trống
INSERT OR IGNORE INTO devices (name, ip, port, enabled, auto_start) VALUES
('demo', '192.168.5.183', 3002, 1, 0),
('simulator', '127.0.0.1', 3002, 0, 0);

-- Pragma settings để tối ưu performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  -- 64MB cache
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456; -- 256MB mmap
