#!/usr/bin/env python3
"""
ClinicalStream Stream Simulator - Sanitized Stub
This module is a sanitized simulator for portfolio demonstration.
Proprietary packet structures and clinical waveforms have been removed.
"""

import argparse
import socket
import time
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_simulation(ip: str, port: int, device_id: int):
    """
    Sanitized simulation loop.
    Sends generic heartbeats to demonstrate connectivity.
    """
    logger.info(f"Starting sanitized simulation for Device {device_id} on {ip}:{port}")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ip, port))
            logger.info("Connected to orchestrator.")
            
            packet_count = 0
            while True:
                packet_count += 1
                # Generic portfolio-safe payload
                payload = f"HEARTBEAT|DEVICE_{device_id}|SEQ_{packet_count}|STATE_NORMAL".encode('utf-8')
                
                s.sendall(payload)
                if packet_count % 10 == 0:
                    logger.info(f"Sent {packet_count} generic heartbeat packets.")
                
                time.sleep(1.0) # 1Hz heartbeat
                
    except Exception as e:
        logger.error(f"Simulation interrupted: {e}")

def main():
    parser = argparse.ArgumentParser(description="ClinicalStream Sanitized Simulator")
    parser.add_argument("--ip", default="127.0.0.1", help="Target IP")
    parser.add_argument("--port", type=int, default=3002, help="Target Port")
    parser.add_argument("--device-id", type=int, default=1, help="Simulated Device ID")
    
    args = parser.parse_args()
    run_simulation(args.ip, args.port, args.device_id)

if __name__ == "__main__":
    main()
