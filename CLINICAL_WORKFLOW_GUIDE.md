# 📊 ClinicalStream DEVICE MANAGER - WORKFLOW GUIDE
## 🎯 Hướng dẫn cho AI Developer kế thừa dự án

> **Mục đích**: Tài liệu này giúp AI developers hiểu nhanh workflow và kiến trúc của ClinicalStream Device Manager để có thể kế thừa và phát triển tiếp.

---

## 🚀 **KHỞI ĐỘNG NHANH**

### **Environment Setup:**
```bash
conda activate flex  # Activate conda environment named 'flex'
python main.py       # Start GUI application
```

### **Core Dependencies:**
- **Required**: PySide6 (GUI), SQLite (Database)
- **Optional**: matplotlib (Charts), pandas (Export), psutil (Monitoring)

---

## 🏗️ **KIẾN TRÚC HỆ THỐNG**

### **Layered Architecture:**

```
🎯 APPLICATION LAYER
├── main.py                    # Entry point & routing
├── advanced_main_window.py    # GUI controller chính
├── monitor_window.py          # Real-time display
└── history_window.py          # Data analysis

🧵 WORKER LAYER  
├── advanced_device_worker.py  # TCP handler per device
├── session_writer.py          # 12s buffer + segments
└── config_manager.py          # JSON settings management

🔍 PROCESSING LAYER
├── message_decoder.py         # Binary S-message parser
├── advanced_database_manager.py # SQLite operations
└── storage_engine.py          # 2-tier storage

💾 STORAGE LAYER
├── SQLite Database            # Metadata, index, alarms
├── .sbin Files               # Raw binary data (compressed)
└── JSON Configs              # Device & system settings
```

---

## 📊 **DATA FLOW WORKFLOW**

### **Real-time Pipeline:**
```
ClinicalStream Device (TCP) 
    ↓ S-Message (binary)
AdvancedDeviceWorker 
    ↓ decode_message()
MessageDecoder 
    ↓ Parsed data (dict)
SessionWriter (12s buffer)
    ↓ flush_buffer() every 12s
StorageEngine 
    ↓ Parallel write
[SQLite metadata] + [.sbin compressed]
    ↓ Real-time signal
GUI Monitor (live update)
```

### **Treatment FSM States:**
- **IDLE**: Không có treatment, không ghi data
- **RUNNING**: Therapy status = 5, bắt đầu session
- **ENDING**: Therapy status = 8, finalize & backup  
- **ENDED**: Session complete, compressed storage

---

## 🎯 **CORE COMPONENTS CHI TIẾT**

### **1. AdvancedDeviceWorker** (Mỗi device 1 thread)
```python
# TCP connection với auto-reconnect
# FSM treatment lifecycle
# Real-time data processing
# Error handling & recovery
```

### **2. SessionWriter** (Data buffering)
```python
# 12s flush interval (tối ưu I/O)
# Segment-based storage (2GB max)
# Compression enabled (gzip level 6)
# Auto backup khi end treatment
```

### **3. MessageDecoder** (Binary parsing)
```python
# S-message format parsing
# Reference data lookup (cached)
# Parameter meaning translation
# Error-resilient decoding
```

### **4. Storage Strategy** ⭐ **QUAN TRỌNG**
```python
# PRINCIPLE: SQL chỉ để metadata, .sbin chứa raw data
# SQLite: timestamps, patient_id, basic metadata
# .sbin: Full binary data, decode on-demand
# Lý do: Performance + Storage efficiency
```

---

## 🖥️ **GUI WORKFLOW**

### **Main Window:**
- **Device Table**: Quản lý devices (add/edit/delete/connect)
- **System Stats**: Memory, CPU, threads monitoring
- **Auto-connect**: Tự động kết nối devices configured

### **Monitor Window:**
- **S-Header Panel**: Device status, therapy info, patient ID
- **S-Body Grid**: 150+ parameters với smart filtering
- **Filters**: All/Active/Favorites/Alarms/Search
- **Real-time**: 200ms-5s configurable refresh

### **History Window:**
- **Session Browser**: List sessions với metadata  
- **Timeline Charts**: Matplotlib visualization
- **Export**: CSV/JSON/Excel formats
- **On-demand decode**: .sbin → readable data

---

## ⚡ **PERFORMANCE & OPTIMIZATION**

### **Multi-threading:**
- 1 thread per device (không blocking)
- 12s flush buffer (giảm I/O overhead)
- SQLite WAL mode (concurrent reads)
- LRU caching (parameter lookups)

### **Memory Management:**
- Buffered writes (16MB max buffer)
- Compressed segments (gzip level 6)
- Auto-cleanup on disconnect
- Segment rotation (2GB limit)

### **Error Handling:**
- Auto-reconnect (exponential backoff)
- Graceful degradation (partial data OK)
- Comprehensive logging (file + console)
- Recovery after connection loss

---

## 🔧 **CONFIGURATION**

### **JSON-based configs:**
- `devices.json`: Device definitions
- `storage_config.json`: Storage settings  
- `monitor_favorites.json`: Per-device favorites
- Hot-reload support

### **Key Settings:**
```python
flush_interval: 12.0s      # Buffer flush frequency
max_segment_size: 2GB      # Segment rotation size
compression_level: 6       # Gzip compression
refresh_interval: 1000ms   # GUI update frequency
```

---

## 🚨 **QUAN TRỌNG CHO AI DEVELOPER**

### **1. Storage Philosophy:**
- **NGUYÊN TẮC**: SQLite chỉ metadata, .sbin chứa raw data
- **LÝ DO**: Performance + không bị bloat database
- **CÁCH DÙNG**: Decode .sbin on-demand khi cần xem detail

### **2. Threading Model:**
- Mỗi device = 1 worker thread độc lập
- GUI thread riêng biệt (không blocking)
- SessionWriter có background thread riêng

### **3. Error Recovery:**
- Auto-reconnect với backoff algorithm
- Session linking sau reconnect (based on patient_id)
- Graceful handling của connection gaps

### **4. Scalability:**
- Thiết kế cho 20+ devices đồng thời
- Memory-efficient với buffer management
- Disk I/O optimized với segment strategy

---

## 🔍 **DEBUGGING & TROUBLESHOOTING**

### **Log Files:**
- `logs/ClinicalStream_manager.log`: Main application log
- `logs/[device_name].log`: Per-device logs
- SQL queries logged at DEBUG level

### **Common Issues:**
1. **Reference DB missing**: Check `ClinicalStream_reference.db` location
2. **Connection fails**: Verify device IP/port in `devices.json`  
3. **Performance lag**: Check thread count, memory usage
4. **Storage errors**: Verify write permissions on data directory

---

## 📝 **DEVELOPMENT WORKFLOW**

### **Adding New Features:**
1. **GUI Changes**: Modify `advanced_main_window.py` 
2. **Data Processing**: Update `message_decoder.py`
3. **Storage Changes**: Modify `storage_engine.py`
4. **Device Logic**: Update `advanced_device_worker.py`

### **Testing:**
```bash
python main.py --tests        # Run unit tests
python main.py --config validate  # Validate configs
```

### **Configuration:**
```bash
python main.py --config backup    # Backup current config
python main.py --config export output.json  # Export config
```

---

## 💡 **TIPS CHO AI DEVELOPER**

1. **Đọc code theo flow**: main.py → advanced_main_window.py → advanced_device_worker.py
2. **Hiểu storage strategy**: SQLite metadata + .sbin raw data  
3. **Threading model**: 1 device = 1 thread, GUI thread riêng
4. **Performance critical**: 12s buffer, compression, caching
5. **Error handling**: Auto-reconnect, graceful degradation
6. **Scalability**: Thiết kế cho production với 20+ devices

---

## 🎖️ **LEGACY & CONTINUATION**

**Dự án này được thiết kế cho production environment y tế quan trọng:**
- **Reliability**: Auto-recovery, error handling
- **Performance**: Multi-device concurrent handling  
- **Scalability**: 20+ devices simultaneous
    ↓ Concurrent Persistence
[SQLite Metadata] + [.sbin Compressed Raw]
    ↓ Qt Logic Signal
GUI Monitor (Sub-second Update)
```

### **State Machine (FSM) Lifecycle:**
- **IDLE**: Awaiting device stream initiation.
- **RUNNING**: Active treatment detected; data acquisition started.
- **ENDING**: Finalizing telemetry stream; completing I/O synchronization.
- **ENDED**: Session archived and compressed.

---

## 🎯 **Core Component Deep-Dive**

### **1. AdvancedDeviceWorker** (Thread-per-Device isolation)
- Asynchronous TCP reconnection with exponential backoff.
- Precise FSM state tracking for treatment lifecycle.
- Real-time packet validation and sequence auditing.

### **2. SessionWriter** (High-Performance Buffering)
- **12s Flush Interval**: Optimized to minimize disk I/O contention.
- **Segment Rotation**: Dynamic file chunking (2GB max) for stability.
- **Integrated Compression**: Gzip level 6 for storage efficiency.

### **3. MessageDecoder** (Packet Orchestration)
- Robust parsing of clinical telemetry formats.
- High-speed reference lookup with LRU caching.
- Error-resilient decoding to handle corrupted packets.

### **4. Storage Strategy** ⭐ **CRITICAL**
- **Principle**: SQLite is for metadata and indexing; `.sbin` is for high-throughput raw telemetry.
- **Efficiency**: Prevents database bloat while maintaining sub-second query performance for historical trends.

---

## ⚡ **Performance & Optimization**

### **Execution Model:**
- Non-blocking multi-threading (1 thread per socket).
- SQLite WAL (Write-Ahead Logging) mode for concurrent read/write.
- Predictive caching for parameter metadata translation.

### **Reliability Patterns:**
- **Fault Tolerance**: Automatic session resumption based on patient/device matching.
- **Data Integrity**: Sequence ID tracking to identify "Connection Gaps".
- **Adaptive Filtering**: UI only renders changed parameters to save CPU cycles.

---

## 🔍 **Maintenance & Troubleshooting**

### **Telemetry Logs:**
- `logs/clinicalstream_manager.log`: Global system events.
- `logs/[device_name].log`: Isolated device communication logs.

### **Common Engineering Gates:**
1. **Bootstrap Failures**: Verify `ClinicalStream_reference.db` lookup paths.
2. **Sync Latency**: Check thread count vs. system core availability.
3. **IO Blockage**: Ensure write permissions on the designated data directory.

---

## 📝 **Development Workflow**

### **Extending Functionality:**
1. **UX Evolution**: Modify `src/gui/*.py`
2. **Logic Enhancement**: Update `src/core/advanced_device_worker.py`
3. **Schema Migration**: Update `schema/database_schema.sql`

### **System Validation:**
```bash
python src/main.py --tests        # Run Architectural Tests
python src/main.py --config validate  # Verify Schemas
```

---

## 🎖️ **Architectural Legacy**

**This system is engineered for stability in high-density clinical environments:**
- **Reliability**: Self-healing architectures with deep fault detection.
- **Throughput**: Optimized for 100Hz+ data streams across 20+ concurrent sources.
- **Portability**: Clean separation between core logic and UI components.

---

*Engineered by DinhLucent - Standards-based clinical data orchestration.*
