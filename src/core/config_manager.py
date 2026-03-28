#!/usr/bin/env python3
"""
Configuration Manager for ClinicalStream Orchestrator
Manages JSON configuration for devices, monitor settings, and system settings
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field
import logging
import datetime

logger = logging.getLogger(__name__)

@dataclass
class MonitorConfig:
    """Cấu hình cho MonitorWindow"""
    refresh_interval_ms: int = 1000
    columns_count: int = 3
    filter_type: str = "All"  # All, Active Only, Favorites Only, Alarms Only
    search_text: str = ""
    favorites: List[str] = field(default_factory=list)
    window_geometry: Dict[str, int] = field(default_factory=dict)
    presets: Dict[str, List[str]] = field(default_factory=dict)
    
    def __post_init__(self):
        # Default presets
        if not self.presets:
            self.presets = {
                "pressure": ["PRESSURE", "PRESS", "mmHg"],
                "flow": ["FLOW", "RATE", "ml/min", "l/min"],
                "pump": ["PUMP", "RPM", "SPEED"],
                "temperature": ["TEMP", "°C"],
                "alarms": ["ALARM", "🚨"]
            }

@dataclass 
class SessionConfig:
    """Cấu hình cho SessionWriter"""
    flush_interval_seconds: float = 12.0
    max_buffer_size_mb: int = 16
    max_segment_size_gb: int = 2
    backup_enabled: bool = True
    compression_enabled: bool = True
    compression_level: int = 6
    data_root_dir: str = "data"
    retention_days: int = 30

@dataclass
class SystemConfig:
    """Cấu hình hệ thống"""
    log_level: str = "INFO"
    max_log_files: int = 5
    log_file_size_mb: int = 10
    auto_backup_interval_hours: int = 24
    database_backup_enabled: bool = True
    performance_monitoring: bool = True
    connection_timeout_seconds: int = 5
    reconnect_delay_seconds: int = 2
    max_reconnect_delay_seconds: int = 60

@dataclass
class HistoryConfig:
    """Cấu hình cho HistoryWindow"""
    default_days_range: int = 7
    max_decode_points: int = 10000
    chart_default_type: str = "Line"
    export_default_format: str = "CSV"
    downsample_threshold: int = 50000
    cache_decoded_data: bool = True

@dataclass
class AppConfig:
    """Cấu hình tổng thể ứng dụng"""
    version: str = "2.0"
    session: SessionConfig = field(default_factory=SessionConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    monitor_defaults: MonitorConfig = field(default_factory=MonitorConfig)
    
    # Per-device monitor configs
    device_monitors: Dict[str, MonitorConfig] = field(default_factory=dict)
    
    # Window states
    main_window_geometry: Dict[str, int] = field(default_factory=dict)
    main_window_state: bytes = field(default_factory=bytes)

class ConfigManager:
    """Manager để load/save cấu hình"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        
        # Config files
        self.main_config_file = self.config_dir / "manager_config.json"
        self.devices_config_file = self.config_dir / "devices.json"
        self.monitor_configs_dir = self.config_dir / "monitors"
        self.monitor_configs_dir.mkdir(exist_ok=True)
        
        # Loaded configs
        self.app_config = AppConfig()
        self.devices_config = []
        
        # Load existing configs
        self.load_all_configs()
        
        logger.info(f"ConfigManager initialized with config dir: {config_dir}")
    
    def load_all_configs(self):
        """Load tất cả cấu hình"""
        self.load_app_config()
        self.load_devices_config()
        self.load_monitor_configs()
    
    def load_app_config(self) -> AppConfig:
        """Load app configuration"""
        if self.main_config_file.exists():
            try:
                with open(self.main_config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Parse nested configs
                session_data = data.get('session', {})
                system_data = data.get('system', {})
                history_data = data.get('history', {})
                monitor_defaults_data = data.get('monitor_defaults', {})
                
                self.app_config = AppConfig(
                    version=data.get('version', '2.0'),
                    session=SessionConfig(**session_data),
                    system=SystemConfig(**system_data),
                    history=HistoryConfig(**history_data),
                    monitor_defaults=MonitorConfig(**monitor_defaults_data),
                    device_monitors=data.get('device_monitors', {}),
                    main_window_geometry=data.get('main_window_geometry', {}),
                    main_window_state=data.get('main_window_state', b'')
                )
                
                logger.info("App config loaded successfully")
                
            except Exception as e:
                logger.warning(f"Error loading app config: {e}, using defaults")
                self.app_config = AppConfig()
        else:
            logger.info("No app config found, using defaults")
            self.app_config = AppConfig()
        
        return self.app_config
    
    def save_app_config(self):
        """Save app configuration"""
        try:
            data = asdict(self.app_config)
            
            with open(self.main_config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info("App config saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving app config: {e}")
    
    def load_devices_config(self) -> List[Dict]:
        """Load devices configuration"""
        if self.devices_config_file.exists():
            try:
                with open(self.devices_config_file, 'r', encoding='utf-8') as f:
                    self.devices_config = json.load(f)
                
                logger.info(f"Loaded {len(self.devices_config)} device configs")
                
            except Exception as e:
                logger.warning(f"Error loading devices config: {e}")
                self.devices_config = []
        else:
            # Create default devices config
            self.devices_config = [
                {
                    "name": "demo",
                    "ip": "192.168.5.183",
                    "port": 3002,
                    "enabled": True,
                    "auto_start": False
                }
            ]
            self.save_devices_config()
        
        return self.devices_config
    
    def save_devices_config(self):
        """Save devices configuration"""
        try:
            with open(self.devices_config_file, 'w', encoding='utf-8') as f:
                json.dump(self.devices_config, f, indent=2, ensure_ascii=False)
            
            logger.info("Devices config saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving devices config: {e}")
    
    def load_monitor_configs(self):
        """Load monitor configs cho từng device"""
        for device_name in os.listdir(self.monitor_configs_dir):
            config_file = self.monitor_configs_dir / f"{device_name}.json"
            if config_file.exists():
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    self.app_config.device_monitors[device_name] = MonitorConfig(**data)
                    
                except Exception as e:
                    logger.warning(f"Error loading monitor config for {device_name}: {e}")
    
    def save_monitor_config(self, device_name: str, config: MonitorConfig):
        """Save monitor config cho một device"""
        try:
            config_file = self.monitor_configs_dir / f"{device_name}.json"
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(config), f, indent=2, ensure_ascii=False)
            
            # Update in memory
            self.app_config.device_monitors[device_name] = config
            
            logger.info(f"Monitor config saved for device: {device_name}")
            
        except Exception as e:
            logger.error(f"Error saving monitor config for {device_name}: {e}")
    
    def get_monitor_config(self, device_name: str) -> MonitorConfig:
        """Lấy monitor config cho device (hoặc default)"""
        if device_name in self.app_config.device_monitors:
            return self.app_config.device_monitors[device_name]
        else:
            # Return copy of defaults
            import copy
            return copy.deepcopy(self.app_config.monitor_defaults)
    
    def add_device_config(self, device_config: Dict):
        """Thêm device config mới"""
        # Check duplicate
        for existing in self.devices_config:
            if existing.get('name') == device_config.get('name'):
                logger.warning(f"Device {device_config.get('name')} already exists")
                return False
        
        self.devices_config.append(device_config)
        self.save_devices_config()
        return True
    
    def update_device_config(self, device_name: str, updated_config: Dict):
        """Cập nhật device config"""
        for i, device in enumerate(self.devices_config):
            if device.get('name') == device_name:
                self.devices_config[i] = updated_config
                self.save_devices_config()
                return True
        
        logger.warning(f"Device {device_name} not found for update")
        return False
    
    def remove_device_config(self, device_name: str):
        """Xóa device config"""
        self.devices_config = [d for d in self.devices_config if d.get('name') != device_name]
        
        # Remove monitor config file
        config_file = self.monitor_configs_dir / f"{device_name}.json"
        if config_file.exists():
            config_file.unlink()
        
        # Remove from memory
        if device_name in self.app_config.device_monitors:
            del self.app_config.device_monitors[device_name]
        
        self.save_devices_config()
        logger.info(f"Removed device config: {device_name}")
    
    def backup_configs(self, backup_dir: str = "config_backup"):
        """Backup tất cả config files"""
        import shutil
        import datetime
        
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_subdir = backup_path / f"config_backup_{timestamp}"
        backup_subdir.mkdir()
        
        try:
            # Copy config directory
            shutil.copytree(self.config_dir, backup_subdir / "config")
            
            logger.info(f"Config backup created: {backup_subdir}")
            return str(backup_subdir)
            
        except Exception as e:
            logger.error(f"Error creating config backup: {e}")
            return None
    
    def restore_configs(self, backup_path: str):
        """Restore configs từ backup"""
        import shutil
        
        backup_config_dir = Path(backup_path) / "config"
        if not backup_config_dir.exists():
            raise ValueError(f"Backup config directory not found: {backup_config_dir}")
        
        try:
            # Backup current configs first
            self.backup_configs("config_backup/pre_restore")
            
            # Remove current config dir
            if self.config_dir.exists():
                shutil.rmtree(self.config_dir)
            
            # Restore from backup
            shutil.copytree(backup_config_dir, self.config_dir)
            
            # Reload configs
            self.load_all_configs()
            
            logger.info(f"Configs restored from: {backup_path}")
            
        except Exception as e:
            logger.error(f"Error restoring configs: {e}")
            raise
    
    def validate_config(self) -> List[str]:
        """Validate configuration và trả về danh sách lỗi"""
        errors = []
        
        # Validate session config
        session = self.app_config.session
        if session.flush_interval_seconds <= 0:
            errors.append("Session flush interval must be positive")
        
        if session.max_buffer_size_mb <= 0:
            errors.append("Max buffer size must be positive")
        
        # Validate devices
        device_names = set()
        for device in self.devices_config:
            name = device.get('name', '')
            if not name:
                errors.append("Device name cannot be empty")
            elif name in device_names:
                errors.append(f"Duplicate device name: {name}")
            else:
                device_names.add(name)
            
            # Validate IP
            ip = device.get('ip', '')
            if not ip:
                errors.append(f"Device {name}: IP cannot be empty")
            
            # Validate port
            port = device.get('port', 0)
            if not (1 <= port <= 65535):
                errors.append(f"Device {name}: Invalid port {port}")
        
        # Validate system config
        system = self.app_config.system
        if system.connection_timeout_seconds <= 0:
            errors.append("Connection timeout must be positive")
        
        if system.max_log_files <= 0:
            errors.append("Max log files must be positive")
        
        return errors
    
    def reset_to_defaults(self):
        """Reset configuration về defaults"""
        logger.warning("Resetting configuration to defaults")
        
        self.app_config = AppConfig()
        self.devices_config = [
            {
                "name": "demo",
                "ip": "192.168.5.183", 
                "port": 3002,
                "enabled": True,
                "auto_start": False
            }
        ]
        
        # Save defaults
        self.save_app_config()
        self.save_devices_config()
    
    def export_config(self, export_path: str):
        """Export toàn bộ config ra file"""
        export_data = {
            "app_config": asdict(self.app_config),
            "devices_config": self.devices_config,
            "export_timestamp": datetime.datetime.now().isoformat(),
            "version": "2.0"
        }
        
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Config exported to: {export_path}")
            
        except Exception as e:
            logger.error(f"Error exporting config: {e}")
            raise
    
    def import_config(self, import_path: str):
        """Import config từ file"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            # Validate import data
            if 'app_config' not in import_data or 'devices_config' not in import_data:
                raise ValueError("Invalid config file format")
            
            # Backup current configs
            self.backup_configs("config_backup/pre_import")
            
            # Import app config
            app_data = import_data['app_config']
            self.app_config = AppConfig(
                version=app_data.get('version', '2.0'),
                session=SessionConfig(**app_data.get('session', {})),
                system=SystemConfig(**app_data.get('system', {})),
                history=HistoryConfig(**app_data.get('history', {})),
                monitor_defaults=MonitorConfig(**app_data.get('monitor_defaults', {})),
                device_monitors=app_data.get('device_monitors', {}),
                main_window_geometry=app_data.get('main_window_geometry', {}),
                main_window_state=app_data.get('main_window_state', b'')
            )
            
            # Import devices config
            self.devices_config = import_data['devices_config']
            
            # Validate imported config
            errors = self.validate_config()
            if errors:
                logger.warning(f"Config validation errors after import: {errors}")
            
            # Save imported configs
            self.save_app_config()
            self.save_devices_config()
            
            logger.info(f"Config imported from: {import_path}")
            
        except Exception as e:
            logger.error(f"Error importing config: {e}")
            raise
    
    def get_session_config_for_storage_engine(self):
        """Chuyển đổi SessionConfig thành format cho StorageEngine"""
        from session_writer import SessionConfig
        
        return SessionConfig(
            flush_interval=self.app_config.session.flush_interval_seconds,
            max_buffer_size=self.app_config.session.max_buffer_size_mb * 1024 * 1024,
            max_segment_size=self.app_config.session.max_segment_size_gb * 1024 * 1024 * 1024,
            backup_enabled=self.app_config.session.backup_enabled,
            compression_enabled=self.app_config.session.compression_enabled,
            compression_level=self.app_config.session.compression_level,
            data_root=self.app_config.session.data_root_dir
        )

# Global config manager instance
_config_manager = None

def get_config_manager() -> ConfigManager:
    """Get global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

def init_config_manager(config_dir: str = "config") -> ConfigManager:
    """Initialize global config manager"""
    global _config_manager
    _config_manager = ConfigManager(config_dir)
    return _config_manager
