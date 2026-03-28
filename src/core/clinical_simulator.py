#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClinicalStream Service-Message Simulator (client) — sends 1 packet/sec to <IP>:3002
- Header: 124 bytes (matches your decoder)
- Body:   N x 12-byte S-records (param_code<uint32>, time<uint32>, value<int32>)
- Session timeline: 30 minutes total with RUN → STOPPED → RUN → STOPPED → END
  00:00–10:00  RUN (5)
  10:00–12:00  THERAPY_STOPPED (7)
  12:00–27:00  RUN (5)
  27:00–29:00  THERAPY_STOPPED (7)
  29:00–30:00  END (8) then exit
Usage:
    python ClinicalStream_simulator.py --ip 127.0.0.1 --port 3002 --machine-id 10 --patient-id TEST01
You can also override --hz and --duration-secs if needed.
"""
import argparse
import socket
import struct
import time
import math
import random
from core.message_decoder import MessageDecoder
from datetime import datetime, timezone

HEADER_SIZE = 124
S_RECORD_SIZE = 12

THERAPY = {
    "CVVHDF": 3,
}
STATUS = {
    "IDLE": 0,
    "RUN": 5,
    "THERAPY_STOPPED": 7,
    "END": 8,
}

def utf32le_patient_id(s: str, total_bytes: int = 80) -> bytes:
    # Encode as sequence of 4-byte little-endian codepoints, pad with zeros to total_bytes
    out = bytearray()
    for ch in s[: total_bytes // 4]:
        out += struct.pack("<I", ord(ch))
    out += b"\x00" * max(0, total_bytes - len(out))
    return bytes(out[:total_bytes])

def make_header(machine_id: int, clinical_sw_id: int, msg_counter: int,
                msg_info: int, flags: int, patient_id: str,
                sw_rev: int, therapy_type_id: int, therapy_status_id: int,
                unix_time: int, body_len: int) -> bytes:
    stx = 0x0002
    crc = 0  # not used by the provided decoder
    cmd_code = 0  # not used; keep 0
    pat = utf32le_patient_id(patient_id, 80)
    return struct.pack(
        "<HHH H I I I I 80s I I I I I",
        stx, crc, machine_id, clinical_sw_id,
        msg_counter, cmd_code, msg_info, flags,
        pat, sw_rev, therapy_type_id, therapy_status_id, unix_time, body_len
    )

# A small set of "safe" parameter IDs commonly present in your DB/log
PARAMS_ACTUAL = [
    1,   # ACCESS_PRESSURE (mmHg)
    2,   # FILTER_PRESSURE (mmHg)
    3,   # EFFLUENT_PRESSURE (mmHg)
    4,   # RETURN_PRESSURE (mmHg)
    6,   # TMP (mmHg)
    7,   # DP (mmHg)
    59,  # CAL_RUN_TIME (s)
    60,  # BLOOD_VOL_PROCESSED (l)
    148, # COUNTS_DIAL_PUMP
    149, # COUNTS_EFFLUENT_PUMP
]

def build_body(now_s: int, since_start_s: int, status_id: int, seed: int = 0) -> bytes:
    """
    Build ~10-14 S-records. Values are simple functions of time with noise.
    Param code for Actual: lower 24 bits = param_id (no 0x40000000 / 0x80000000 flags).
    """
    rnd = random.Random(seed + since_start_s)
    records = []
    def rec(pid: int, value: int):
        param_code = pid & 0x00FFFFFF
        record_time = since_start_s  # seconds since simulator start
        records.append(struct.pack("<IIi", param_code, record_time, int(value)))

    # Basic pressure waveforms (mmHg)
    base = 50 + 5 * math.sin(since_start_s / 12.0)
    ap = int(-20 + 3 * math.sin(since_start_s / 6.0) + rnd.uniform(-2, 2))   # ACCESS_PRESSURE
    fp = int(base + rnd.uniform(-3, 3))                                      # FILTER_PRESSURE
    ep = int(-12 + 2 * math.sin(since_start_s / 8.0) + rnd.uniform(-2, 2))   # EFFLUENT_PRESSURE
    rp = int(25 + 3 * math.sin(since_start_s / 10.0) + rnd.uniform(-2, 2))   # RETURN_PRESSURE
    tmp = fp - rp                                                             # TMP approx
    dp  = rp - ap                                                             # DP approx

    # Counters & volumes
    cal_run_time = since_start_s if status_id == STATUS["RUN"] else since_start_s  # keep increasing for simplicity
    blood_l = max(0.0, 0.004 * since_start_s)  # ~0.24 L per minute
    counts_dial = int(400 + 5 * since_start_s + rnd.uniform(-5, 5))
    counts_eff  = int(350 + 6 * since_start_s + rnd.uniform(-5, 5))

    # When STOPPED, freeze pressures closer to safe values; END: nearly flat
    if status_id == STATUS["THERAPY_STOPPED"]:
        ap = int(-5 + rnd.uniform(-1, 1))
        fp = int(20 + rnd.uniform(-2, 2))
        ep = int(-3 + rnd.uniform(-1, 1))
        rp = int(10 + rnd.uniform(-2, 2))
        tmp = fp - rp
        dp = rp - ap
    elif status_id == STATUS["END"]:
        ap = int(rnd.uniform(-2, 1))
        fp = int(rnd.uniform(0, 3))
        ep = int(rnd.uniform(-1, 1))
        rp = int(rnd.uniform(0, 2))
        tmp = fp - rp
        dp = rp - ap

    # Pack a handful of Actual records
    rec(1, ap)
    rec(2, fp)
    rec(3, ep)
    rec(4, rp)
    rec(6, tmp)
    rec(7, dp)
    rec(59, cal_run_time)
    rec(60, int(blood_l))  # integer liters; app may apply accuracy scaling
    rec(148, counts_dial)
    rec(149, counts_eff)

    # Add 1-3 extra "noise" parameters to vary body length
    extras = [13,14,15,16,120,121,122,123]
    rnd.shuffle(extras)
    for pid in extras[:rnd.randint(1,3)]:
        val = int(100 + 10 * math.sin((since_start_s + pid) / 7.0) + rnd.uniform(-5,5))
        rec(pid, val)

    return b"".join(records)

def compute_sw_rev_from_string(version="3.62.41.68"):
    # Generate a 32-bit that will decode to some dotted string; exact reverse is not critical.
    # We'll just use a fixed constant if not specified.
    return 0x1234ABCD

def status_timeline(elapsed: int) -> int:
    # 30 minutes total
    #  0-600  : RUN
    # 600-720 : STOPPED
    # 720-1620: RUN
    # 1620-1740: STOPPED
    # 1740-1800: END
    if elapsed < 600:
        return STATUS["RUN"]
    elif elapsed < 720:
        return STATUS["THERAPY_STOPPED"]
    elif elapsed < 1620:
        return STATUS["RUN"]
    elif elapsed < 1740:
        return STATUS["THERAPY_STOPPED"]
    else:
        return STATUS["END"]

def run(ip: str, port: int, machine_id: int, patient_id: str,
        therapy_type_name: str = "CVVHDF", hz: float = 1.0,
        duration_secs: int = 1800, clinical_sw_id: int = 0x0201,
        msg_info: int = 164, flags: int = 0x00000002, seed: int = 42):
    therapy_type_id = THERAPY[therapy_type_name]
    sw_rev = compute_sw_rev_from_string()
    period = 1.0 / hz
    msg_counter = 0

    addr = (ip, port)
    print(f"[Simulator] Connecting to {addr} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(5.0)

    def connect():
        while True:
            try:
                sock.connect(addr)
                sock.settimeout(None)  # blocking after connect
                print("[Simulator] Connected.")
                return
            except Exception as e:
                print(f"[Simulator] Connect failed: {e}. Retry in 2s...")
                time.sleep(2)

    connect()
    start = time.time()
    last_send = 0.0

    try:
        while True:
            now = time.time()
            elapsed = int(now - start)
            if elapsed >= duration_secs:
                print("[Simulator] Duration reached; sending final END (if not already) and exiting.")
                break

            if now - last_send < period:
                time.sleep(max(0.0, period - (now - last_send)))
                continue

            status_id = status_timeline(elapsed)
            body = build_body(int(now), elapsed, status_id, seed=seed)
            header = make_header(
                machine_id=machine_id,
                clinical_sw_id=clinical_sw_id,
                msg_counter=msg_counter,
                msg_info=msg_info,
                flags=flags,
                patient_id=patient_id,
                sw_rev=sw_rev,
                therapy_type_id=therapy_type_id,
                therapy_status_id=status_id,
                unix_time=int(now),
                body_len=len(body),
            )
            packet = header + body
            assert len(header) == HEADER_SIZE, f"Header length mismatch: {len(header)} != 124"
            assert len(body) % S_RECORD_SIZE == 0, "Body length must be multiple of 12"

            try:
                sock.sendall(packet)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
                print(f"[Simulator] Connection lost ({e}). Reconnecting...")
                sock.close()
                # Recreate socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(5.0)
                connect()
                # try resend the same packet after reconnect
                sock.sendall(packet)

            msg_counter = (msg_counter + 1) & 0xFFFFFFFF
            last_send = now

    finally:
        try:
            # Send a couple of END status packets before closing, to be safe
            for k in range(2):
                now = int(time.time())
                status_id = STATUS["END"]
                body = build_body(now, duration_secs, status_id)
                header = make_header(machine_id, 0x0201, msg_counter, 164, 0x2, patient_id,
                                     compute_sw_rev_from_string(), THERAPY["CVVHDF"], status_id, now, len(body))
                sock.sendall(header + body)
                msg_counter = (msg_counter + 1) & 0xFFFFFFFF
                time.sleep(0.2)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        print("[Simulator] Closed.")

def main():
    ap = argparse.ArgumentParser(description="ClinicalStream service-message simulator (client)")
    ap.add_argument("--ip", required=True, help="IP của server phần mềm đang lắng nghe (ví dụ 127.0.0.1)")
    ap.add_argument("--port", type=int, default=3002, help="Port server (mặc định 3002)")
    ap.add_argument("--machine-id", type=int, default=10, help="Machine ID hiển thị ở decoder")
    ap.add_argument("--patient-id", type=str, default="TEST01", help="PatientID (UTF-32LE)")
    ap.add_argument("--therapy", type=str, default="CVVHDF", choices=list(THERAPY.keys()), help="Therapy type")
    ap.add_argument("--hz", type=float, default=1.0, help="Tốc độ gửi gói/giây (mặc định 1Hz)")
    ap.add_argument("--duration-secs", type=int, default=1800, help="Tổng thời gian mô phỏng (mặc định 1800s = 30 phút)")
    args = ap.parse_args()

    run(
        ip=args.ip, port=args.port, machine_id=args.machine_id, patient_id=args.patient_id,
        therapy_type_name=args.therapy, hz=args.hz, duration_secs=args.duration_secs
    )

if __name__ == "__main__":
    main()
