import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd

class DatabaseManager:
    """SQLite database management for ClinicalStream"""
    
    def __init__(self, device_name: str, base_dir: str = "collected_data"):
        self.device_name = device_name
        self.base_dir = base_dir
        self.device_dir = os.path.join(base_dir, self._sanitize_name(device_name))
        self.db_path = os.path.join(self.device_dir, "database", "monitor_data.db")
        self.sessions_db_path = os.path.join(self.device_dir, "database", "sessions.db")
        
        # Tạo thư mục database
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Khởi tạo database
        self.init_database()
        self.init_sessions_database()
    
    def _sanitize_name(self, name: str) -> str:
        """Làm sạch tên thiết bị cho file path"""
        import re
        return re.sub(r'[\\/*?:"<>|]', "", name)
    
    def init_database(self):
        """Khởi tạo database chính cho monitor data"""
        with sqlite3.connect(self.db_path) as conn:
            # Bảng chính lưu dữ liệu monitor
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monitor_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    device_name TEXT NOT NULL,
                    parameter_name TEXT NOT NULL,
                    value REAL,
                    unit TEXT,
                    tier TEXT NOT NULL,
                    treatment_session_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Bảng lưu dữ liệu tổng hợp
            conn.execute("""
                CREATE TABLE IF NOT EXISTS aggregated_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    device_name TEXT NOT NULL,
                    parameter_name TEXT NOT NULL,
                    min_value REAL,
                    max_value REAL,
                    avg_value REAL,
                    last_value REAL,
                    sample_count INTEGER,
                    std_dev REAL,
                    unit TEXT,
                    tier TEXT NOT NULL,
                    treatment_session_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tạo indexes để tối ưu truy vấn
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON monitor_data(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_param ON monitor_data(device_name, parameter_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tier ON monitor_data(tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON monitor_data(treatment_session_id)")
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_timestamp ON aggregated_data(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_device_param ON aggregated_data(device_name, parameter_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_tier ON aggregated_data(tier)")
            
            conn.commit()
    
    def init_sessions_database(self):
        """Khởi tạo database cho sessions"""
        with sqlite3.connect(self.sessions_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS treatment_sessions (
                    id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    start_time DATETIME,
                    end_time DATETIME,
                    status TEXT,
                    total_bytes INTEGER,
                    run_time_final INTEGER,
                    therapy_status_id INTEGER,
                    therapy_type_id INTEGER,
                    patient_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Bảng lưu thống kê session
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_statistics (
                    session_id TEXT,
                    parameter_name TEXT,
                    min_value REAL,
                    max_value REAL,
                    avg_value REAL,
                    first_value REAL,
                    last_value REAL,
                    total_samples INTEGER,
                    unit TEXT,
                    PRIMARY KEY (session_id, parameter_name),
                    FOREIGN KEY (session_id) REFERENCES treatment_sessions(id)
                )
            """)
            
            conn.commit()
    
    def insert_monitor_data(self, timestamp: datetime, parameter_name: str, value: float, 
                           unit: str, tier: str, session_id: Optional[str] = None):
        """Chèn dữ liệu monitor vào database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO monitor_data 
                (timestamp, device_name, parameter_name, value, unit, tier, treatment_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, self.device_name, parameter_name, value, unit, tier, session_id))
            conn.commit()
    
    def insert_aggregated_data(self, timestamp: datetime, data: Dict, tier: str, 
                              session_id: Optional[str] = None):
        """Chèn dữ liệu tổng hợp vào database"""
        with sqlite3.connect(self.db_path) as conn:
            for param_name, param_data in data.items():
                if isinstance(param_data, dict) and 'min' in param_data:
                    conn.execute("""
                        INSERT INTO aggregated_data 
                        (timestamp, device_name, parameter_name, min_value, max_value, 
                         avg_value, last_value, sample_count, std_dev, unit, tier, treatment_session_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        timestamp, self.device_name, param_name,
                        param_data.get('min'), param_data.get('max'), param_data.get('avg'),
                        param_data.get('last'), param_data.get('count'), param_data.get('std_dev', 0),
                        param_data.get('unit'), tier, session_id
                    ))
            conn.commit()
    
    def insert_session(self, session_id: str, start_time: datetime, status: str = "active",
                      therapy_status_id: Optional[int] = None, therapy_type_id: Optional[int] = None,
                      patient_id: Optional[str] = None):
        """Chèn session mới"""
        with sqlite3.connect(self.sessions_db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO treatment_sessions 
                (id, device_name, start_time, status, therapy_status_id, therapy_type_id, patient_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_id, self.device_name, start_time, status, 
                  therapy_status_id, therapy_type_id, patient_id))
            conn.commit()
    
    def update_session(self, session_id: str, end_time: Optional[datetime] = None,
                      status: Optional[str] = None, total_bytes: Optional[int] = None,
                      run_time_final: Optional[int] = None):
        """Cập nhật session"""
        with sqlite3.connect(self.sessions_db_path) as conn:
            updates = []
            params = []
            
            if end_time:
                updates.append("end_time = ?")
                params.append(end_time)
            if status:
                updates.append("status = ?")
                params.append(status)
            if total_bytes is not None:
                updates.append("total_bytes = ?")
                params.append(total_bytes)
            if run_time_final is not None:
                updates.append("run_time_final = ?")
                params.append(run_time_final)
            
            if updates:
                params.append(session_id)
                query = f"UPDATE treatment_sessions SET {', '.join(updates)} WHERE id = ?"
                conn.execute(query, params)
                conn.commit()
    
    def get_parameter_history(self, parameter_name: str, start_time: datetime, 
                             end_time: datetime, tier: str = "monitoring") -> List[Tuple]:
        """Lấy lịch sử của một parameter trong khoảng thời gian"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, value, unit, tier
                FROM monitor_data 
                WHERE device_name = ? AND parameter_name = ? 
                AND timestamp BETWEEN ? AND ? AND tier = ?
                ORDER BY timestamp
            """, (self.device_name, parameter_name, start_time, end_time, tier))
            return cursor.fetchall()
    
    def get_aggregated_history(self, parameter_name: str, start_time: datetime,
                              end_time: datetime, tier: str = "monitoring") -> List[Tuple]:
        """Lấy lịch sử dữ liệu tổng hợp"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, min_value, max_value, avg_value, last_value, 
                       sample_count, std_dev, unit
                FROM aggregated_data 
                WHERE device_name = ? AND parameter_name = ? 
                AND timestamp BETWEEN ? AND ? AND tier = ?
                ORDER BY timestamp
            """, (self.device_name, parameter_name, start_time, end_time, tier))
            return cursor.fetchall()
    
    def get_treatment_sessions(self, start_date: Optional[datetime] = None,
                              end_date: Optional[datetime] = None) -> List[Dict]:
        """Lấy danh sách các ca chạy"""
        with sqlite3.connect(self.sessions_db_path) as conn:
            query = """
                SELECT id, start_time, end_time, status, total_bytes, 
                       run_time_final, therapy_status_id, therapy_type_id, patient_id
                FROM treatment_sessions 
                WHERE device_name = ?
            """
            params = [self.device_name]
            
            if start_date:
                query += " AND start_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND start_time <= ?"
                params.append(end_date)
            
            query += " ORDER BY start_time DESC"
            
            cursor = conn.execute(query, params)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_session_summary(self, session_id: str) -> Dict:
        """Lấy tổng quan của một ca chạy"""
        with sqlite3.connect(self.sessions_db_path) as conn:
            # Thông tin session
            cursor = conn.execute("""
                SELECT * FROM treatment_sessions WHERE id = ?
            """, (session_id,))
            session_data = cursor.fetchone()
            
            if not session_data:
                return {}
            
            # Thống kê parameters
            cursor = conn.execute("""
                SELECT parameter_name, min_value, max_value, avg_value, 
                       first_value, last_value, total_samples, unit
                FROM session_statistics 
                WHERE session_id = ?
                ORDER BY parameter_name
            """, (session_id,))
            
            parameters = []
            for row in cursor.fetchall():
                parameters.append({
                    'name': row[0],
                    'min': row[1],
                    'max': row[2],
                    'avg': row[3],
                    'first': row[4],
                    'last': row[5],
                    'samples': row[6],
                    'unit': row[7]
                })
            
            return {
                'session_id': session_id,
                'device_name': session_data[1],
                'start_time': session_data[2],
                'end_time': session_data[3],
                'status': session_data[4],
                'total_bytes': session_data[5],
                'run_time_final': session_data[6],
                'therapy_status_id': session_data[7],
                'therapy_type_id': session_data[8],
                'patient_id': session_data[9],
                'parameters': parameters
            }
    
    def get_parameter_statistics(self, parameter_name: str, days: int = 7) -> Dict:
        """Lấy thống kê của một parameter trong N ngày gần đây"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            # Thống kê từ dữ liệu tổng hợp
            cursor = conn.execute("""
                SELECT 
                    DATE(timestamp) as date,
                    COUNT(*) as samples,
                    AVG(avg_value) as daily_avg,
                    MIN(min_value) as daily_min,
                    MAX(max_value) as daily_max,
                    AVG(std_dev) as avg_std_dev
                FROM aggregated_data 
                WHERE device_name = ? AND parameter_name = ? 
                AND timestamp BETWEEN ? AND ?
                GROUP BY DATE(timestamp)
                ORDER BY date
            """, (self.device_name, parameter_name, start_date, end_date))
            
            daily_stats = []
            for row in cursor.fetchall():
                daily_stats.append({
                    'date': row[0],
                    'samples': row[1],
                    'avg': row[2],
                    'min': row[3],
                    'max': row[4],
                    'std_dev': row[5]
                })
            
            # Thống kê tổng thể
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_samples,
                    AVG(avg_value) as overall_avg,
                    MIN(min_value) as overall_min,
                    MAX(max_value) as overall_max,
                    AVG(std_dev) as overall_std_dev
                FROM aggregated_data 
                WHERE device_name = ? AND parameter_name = ? 
                AND timestamp BETWEEN ? AND ?
            """, (self.device_name, parameter_name, start_date, end_date))
            
            overall_stats = cursor.fetchone()
            
            return {
                'parameter_name': parameter_name,
                'period_days': days,
                'start_date': start_date,
                'end_date': end_date,
                'daily_statistics': daily_stats,
                'overall_statistics': {
                    'total_samples': overall_stats[0],
                    'average': overall_stats[1],
                    'min': overall_stats[2],
                    'max': overall_stats[3],
                    'std_dev': overall_stats[4]
                }
            }
    
    def export_to_csv(self, parameter_name: str, start_time: datetime, 
                      end_time: datetime, output_path: str, tier: str = "monitoring"):
        """Xuất dữ liệu ra file CSV"""
        data = self.get_aggregated_history(parameter_name, start_time, end_time, tier)
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'min_value', 'max_value', 'avg_value', 
            'last_value', 'sample_count', 'std_dev', 'unit'
        ])
        
        df.to_csv(output_path, index=False)
        return output_path
    
    def get_database_info(self) -> Dict:
        """Lấy thông tin về database"""
        with sqlite3.connect(self.db_path) as conn:
            # Số lượng records
            cursor = conn.execute("SELECT COUNT(*) FROM monitor_data")
            total_records = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM aggregated_data")
            total_aggregated = cursor.fetchone()[0]
            
            # Kích thước database
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            
            # Thời gian dữ liệu đầu tiên và cuối cùng
            cursor = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM monitor_data")
            time_range = cursor.fetchone()
            
            return {
                'device_name': self.device_name,
                'total_monitor_records': total_records,
                'total_aggregated_records': total_aggregated,
                'database_size_mb': round(db_size / (1024 * 1024), 2),
                'first_record': time_range[0] if time_range[0] else None,
                'last_record': time_range[1] if time_range[1] else None,
                'parameters_count': self.get_parameters_count()
            }
    
    def get_parameters_count(self) -> int:
        """Lấy số lượng parameters unique"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(DISTINCT parameter_name) FROM monitor_data
            """)
            return cursor.fetchone()[0]
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """Dọn dẹp dữ liệu cũ"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        with sqlite3.connect(self.db_path) as conn:
            # Xóa dữ liệu monitor cũ
            conn.execute("""
                DELETE FROM monitor_data 
                WHERE timestamp < ?
            """, (cutoff_date,))
            
            # Xóa dữ liệu tổng hợp cũ
            conn.execute("""
                DELETE FROM aggregated_data 
                WHERE timestamp < ?
            """, (cutoff_date,))
            
            conn.commit()
        
        # Vacuum database để tối ưu kích thước
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("VACUUM")
