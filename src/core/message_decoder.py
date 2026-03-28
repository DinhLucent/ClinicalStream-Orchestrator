#!/usr/bin/env python3
"""
Optimized Message Decoder cho ClinicalStream packets
Tối ưu performance và memory efficiency
"""

import struct
import time
import logging
from typing import Dict, Tuple, Any, Optional
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

# Constants
HEADER_SIZE = 124
S_RECORD_SIZE = 12
CRC_OFFSET = 2

@dataclass
class ReferenceData:
    """Reference data từ database để decode parameters"""
    numerical_params: Dict[int, Dict[str, Any]]
    enumerative_params: Dict[int, Dict[str, Any]]
    enumerative_values: Dict[int, Dict[int, str]]
    therapy_types: Dict[int, str]
    therapy_statuses: Dict[int, str]
    alarms: Dict[int, Dict[str, Any]]
    
    @lru_cache(maxsize=1000)
    def get_meaning(self, param_id: int, value: int) -> str:
        """Cached lookup cho enumerative meanings"""
        meanings = self.enumerative_values.get(param_id, {})
        return meanings.get(value, f"Unknown({value})")

class MessageDecoder:
    """
    Optimized decoder cho ClinicalStream S-messages
    - Fast binary parsing
    - Cached lookups
    - Minimal allocations
    - Error resilient
    """
    
    def __init__(self, reference_data: ReferenceData):
        self.ref = reference_data
        self.packet_count = 0
        self.decode_errors = 0
        
        # Pre-compiled struct formats
        self._header_format = '<HHHIIII80sIIIII2x'  # 124 bytes header
        self._record_format = '<IIi'  # 12 bytes per S-record
        
        # Performance stats
        self.decode_time_total = 0.0
        self.last_decode_time = 0.0
        
        logger.info("MessageDecoder initialized")
    
    def decode_packet_with_monitor_and_header(self, packet_data: bytes) -> Tuple[str, Dict[str, Tuple], Dict[str, Any]]:
        """
        Decode packet thành (text, monitor_dict, header_dict)
        
        Returns:
            text: Human-readable decoded text
            monitor_dict: {param_name: (value, unit, param_id)} cho monitoring
            header_dict: Header information
        """
        start_time = time.perf_counter()
        
        try:
            # Validate packet size
            if len(packet_data) < HEADER_SIZE:
                raise ValueError(f"Packet too small: {len(packet_data)} < {HEADER_SIZE}")
            
            self.packet_count += 1
            
            # Parse header
            header_dict = self._parse_header(packet_data[:HEADER_SIZE])
            
            # Check for power failure flag
            flags = header_dict.get('flags', 0)
            if flags & 0x8000:  # PWRFAIL bit
                self.decode_errors += 1
                return (
                    f"⚠️ POWER FAILURE detected - skipping packet body\nHeader: {header_dict}",
                    {},
                    header_dict
                )
            
            # Parse body
            body_length = header_dict.get('body_length', 0)
            
            if body_length == 0:
                return (
                    f"📋 Header only packet\nHeader: {self._format_header_text(header_dict)}",
                    {},
                    header_dict
                )
            
            if len(packet_data) < HEADER_SIZE + body_length:
                raise ValueError(f"Incomplete packet: expected {HEADER_SIZE + body_length}, got {len(packet_data)}")
            
            body_data = packet_data[HEADER_SIZE:HEADER_SIZE + body_length]
            text_parts, monitor_dict = self._parse_body(body_data, header_dict)
            
            # Combine text
            header_text = self._format_header_text(header_dict)
            body_text = '\n'.join(text_parts) if text_parts else "  (No parameters)"
            full_text = f"{header_text}\n{body_text}"
            
            # Performance tracking
            decode_time = time.perf_counter() - start_time
            self.decode_time_total += decode_time
            self.last_decode_time = decode_time
            
            return full_text, monitor_dict, header_dict
            
        except Exception as e:
            self.decode_errors += 1
            logger.error(f"Decode error: {e}")
            
            return (
                f"❌ DECODE ERROR: {e}\nRaw packet length: {len(packet_data)}",
                {},
                {'error': str(e)}
            )
    
    def _parse_header(self, header_data: bytes) -> Dict[str, Any]:
        """Parse 124-byte header"""
        try:
            (stx, crc, machine_id, clinical_sw_id, 
             msg_counter, cmd_code, msg_info, flags, 
             patient_id_raw, sw_rev, therapy_type_id, 
             therapy_status_id, time_unix, body_length) = struct.unpack(
                self._header_format, header_data
            )
            
            # Clean patient ID (remove null bytes)
            patient_id = patient_id_raw.rstrip(b'\x00').decode('ascii', errors='ignore')
            
            # Format SW revision as a.bVcRd
            sw_rev_str = f"{(sw_rev >> 24) & 0xFF}.{(sw_rev >> 16) & 0xFF}V{(sw_rev >> 8) & 0xFF}R{sw_rev & 0xFF}"
            
            # Lookup therapy info
            therapy_type = self.ref.therapy_types.get(therapy_type_id, f"Unknown({therapy_type_id})")
            therapy_status = self.ref.therapy_statuses.get(therapy_status_id, f"Unknown({therapy_status_id})")
            
            return {
                'stx': stx,
                'crc': crc,
                'machine_id': machine_id,
                'clinical_sw_id': clinical_sw_id,
                'msg_counter': msg_counter,
                'cmd_code': cmd_code,
                'msg_info': msg_info,
                'flags': flags,
                'patient_id': patient_id,
                'sw_rev': sw_rev_str,
                'sw_rev_raw': sw_rev,
                'therapy_type_id': therapy_type_id,
                'therapy_type': therapy_type,
                'therapy_status_id': therapy_status_id,
                'therapy_status': therapy_status,
                'time_unix': time_unix,
                'body_length': body_length
            }
            
        except struct.error as e:
            raise ValueError(f"Header parse error: {e}")
    
    def _format_header_text(self, header_dict: Dict[str, Any]) -> str:
        """Format header cho display"""
        return (
            f"📋 S-Header:\n"
            f"  Machine ID: {header_dict.get('machine_id', 'N/A')}\n"
            f"  SW Rev: {header_dict.get('sw_rev', 'N/A')}\n"
            f"  Patient ID: {header_dict.get('patient_id', 'N/A')}\n"
            f"  Therapy: {header_dict.get('therapy_type', 'N/A')} (ID: {header_dict.get('therapy_type_id', 'N/A')})\n"
            f"  Status: {header_dict.get('therapy_status', 'N/A')} (ID: {header_dict.get('therapy_status_id', 'N/A')})\n"
            f"  Flags: 0x{header_dict.get('flags', 0):04X}\n"
            f"  Body Length: {header_dict.get('body_length', 0)} bytes\n"
            f"  Message Info: {header_dict.get('msg_info', 0)}"
        )
    
    def _parse_body(self, body_data: bytes, header_dict: Dict) -> Tuple[list, Dict[str, Tuple]]:
        """Parse body containing S-records"""
        text_parts = []
        monitor_dict = {}
        
        msg_info = header_dict.get('msg_info', 0)
        
        # Validate msg_info
        if not (0 <= msg_info <= 1000):
            text_parts.append(f"  ⚠️ Invalid msg_info: {msg_info}")
            return text_parts, monitor_dict
        
        if msg_info == 0:
            text_parts.append("  📋 S-Body: (Empty)")
            return text_parts, monitor_dict
        
        text_parts.append(f"📊 S-Body ({msg_info} records):")
        
        # Parse each S-record
        for i in range(msg_info):
            record_start = i * S_RECORD_SIZE
            record_end = record_start + S_RECORD_SIZE
            
            if record_end > len(body_data):
                text_parts.append(f"  ⚠️ Truncated record {i+1}")
                break
            
            try:
                param_code, record_time, value = struct.unpack(
                    self._record_format, 
                    body_data[record_start:record_end]
                )
                
                # Decode parameter
                text_line, param_name, param_value, param_unit, param_id = self._decode_parameter(
                    param_code, value, record_time
                )
                
                text_parts.append(f"  {text_line}")
                
                # Add to monitor dict if it's an actual value
                if param_name and param_value is not None:
                    monitor_dict[param_name] = (param_value, param_unit, param_id)
                
            except struct.error:
                text_parts.append(f"  ❌ Malformed record {i+1}")
                continue
        
        return text_parts, monitor_dict
    
    def _decode_parameter(self, param_code: int, value: int, record_time: int) -> Tuple[str, Optional[str], Any, str, int]:
        """
        Generalized parameter decoder stub.
        Original clinical algorithms removed for proprietary reasons.
        """
        # Placeholder for bitmasking logic
        is_alarm = bool(param_code & 0x80000000)
        is_set_value = bool(param_code & 0x40000000)
        
        param_id = param_code & 0x00FFFFFF
        
        # Generic decoding logic
        param_name = f"PARAM_{param_id}"
        unit = "units"
        scaled_value = value # Generic scaling
        
        if is_alarm:
            text_line = f"[🚨ALARM] ID {param_id:3d}: State - {'PRESENT' if value == 1 else 'CLEAR'}"
            return text_line, f"ALARM_{param_id}", "ALARM", "State", param_id
            
        record_type = "Set" if is_set_value else "Actual"
        text_line = f"[{record_type:^6s}] ID {param_id:3d}: {param_name:<40} = {scaled_value:>10} {unit}"
        
        if not is_set_value:
            return text_line, param_name, scaled_value, unit, param_id
        else:
            return text_line, None, None, "", param_id
    
    def get_stats(self) -> Dict[str, Any]:
        """Lấy decode statistics"""
        avg_decode_time = (self.decode_time_total / self.packet_count 
                          if self.packet_count > 0 else 0)
        
        return {
            'packets_decoded': self.packet_count,
            'decode_errors': self.decode_errors,
            'error_rate': self.decode_errors / self.packet_count if self.packet_count > 0 else 0,
            'avg_decode_time_ms': avg_decode_time * 1000,
            'last_decode_time_ms': self.last_decode_time * 1000,
            'total_decode_time_s': self.decode_time_total
        }
    
    def reset_stats(self):
        """Reset statistics"""
        self.packet_count = 0
        self.decode_errors = 0
        self.decode_time_total = 0.0
        self.last_decode_time = 0.0

def load_reference_data(db_path: str) -> ReferenceData:
    """Load reference data từ SQLite database"""
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Load numerical parameters
        cursor = conn.execute("SELECT id, name, accuracy, unit FROM numerical_parameters")
        numerical_params = {
            row['id']: {
                'name': row['name'],
                'accuracy': row['accuracy'] or 0,
                'unit': row['unit'] or ''
            }
            for row in cursor.fetchall()
        }
        
        # Load enumerative parameters  
        cursor = conn.execute("SELECT id, name FROM enumerative_parameters")
        enumerative_params = {
            row['id']: {'name': row['name']}
            for row in cursor.fetchall()
        }
        
        # Load enumerative values
        cursor = conn.execute("SELECT parameter_id, value, meaning FROM enumerative_values")
        enumerative_values = {}
        for row in cursor.fetchall():
            param_id = row['parameter_id']
            if param_id not in enumerative_values:
                enumerative_values[param_id] = {}
            enumerative_values[param_id][row['value']] = row['meaning']
        
        # Load therapy types
        cursor = conn.execute("SELECT id, name FROM therapy_types")
        therapy_types = {row['id']: row['name'] for row in cursor.fetchall()}
        
        # Load therapy statuses
        cursor = conn.execute("SELECT id, name FROM therapy_statuses")
        therapy_statuses = {row['id']: row['name'] for row in cursor.fetchall()}
        
        # Load alarms
        try:
            cursor = conn.execute("SELECT id, name, priority FROM alarms")
            alarms = {
                row['id']: {
                    'name': row['name'],
                    'priority': row['priority'] or 0
                }
                for row in cursor.fetchall()
            }
        except sqlite3.OperationalError:
            # Fallback if priority column doesn't exist
            cursor = conn.execute("SELECT id, name FROM alarms")
            alarms = {
                row['id']: {
                    'name': row['name'],
                    'priority': 0
                }
                for row in cursor.fetchall()
            }
        
        logger.info(f"Loaded reference data: {len(numerical_params)} numerical, "
                   f"{len(enumerative_params)} enumerative, {len(alarms)} alarms")
        
        return ReferenceData(
            numerical_params=numerical_params,
            enumerative_params=enumerative_params,
            enumerative_values=enumerative_values,
            therapy_types=therapy_types,
            therapy_statuses=therapy_statuses,
            alarms=alarms
        )
        
    finally:
        conn.close()
