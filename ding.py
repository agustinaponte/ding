# -*- coding: utf-8 -*-
"""
Created on Mon Dec 18 22:46:04 2023
Updated to add compact view with per-host notification modes
@author: Agustin Aponte
"""
__version__ = "0.0.3"

import platform
import os
import sys
import logging
import time
import argparse
import traceback
import msvcrt
import ctypes
import winreg
from concurrent.futures import ThreadPoolExecutor
import socket
import struct
import ctypes.wintypes as wintypes
import threading

DOWN_THRESHOLD = 3   # failures in a row → DOWN
UP_THRESHOLD = 2     # successes in a row → UP

# Load iphlpapi
iphlpapi = ctypes.WinDLL('iphlpapi')
kernel32 = ctypes.WinDLL('kernel32')

if os.name == "nt":
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

# --- small helper banner (unchanged) ---
ding_banner = """
-----------------------------------------
  ______     _                   
 |_   _ `.  (_)                  
   | | `. \\  __   _ .--.   .--./) 
   | |  | |[  | [ `.-. | / /'`\\ ; 
  _| |_.' / | |  | | | | \\ \\._// 
 |______.' [___][___||__].',__`  
                         (( __)) 
-----------------------------------------
Ping utility with sound notifications.
🔔🔔🔔 Version: {__version__} 🔔🔔🔔
-----------------------------------------
"""
operatingSystem = platform.system().lower()

# --- Terminal resize utilities (unchanged) ---
def resize_terminal(width, height):
    """Resize the Windows terminal window."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11

    # Set screen buffer size
    buffer_size = wintypes._COORD(width, height)
    kernel32.SetConsoleScreenBufferSize(handle, buffer_size)

    # Set window size
    rect = wintypes.SMALL_RECT(0, 0, width - 1, height - 1)
    kernel32.SetConsoleWindowInfo(handle, True, ctypes.byref(rect))

def choose_optimal_terminal_size(num_hosts, min_panel_width=24, base_height=20):
    """
    Compute optimal terminal width/height so hosts form a near-square matrix
    with minimal wasted padding.
    """
    cols = int(num_hosts ** 0.5)
    if cols * cols < num_hosts:
        cols += 1

    rows = (num_hosts + cols - 1) // cols

    # Minimal width = columns * panel_width + spacing
    width = cols * (min_panel_width + 2)

    # Minimal height = rows * estimated panel height
    est_panel_height = 10
    height = rows * est_panel_height + 5

    # Safety cap: Windows terminals break > 200x80 sometimes
    width = min(width, 200)
    height = min(height, 80)

    return width, height


# Helper to format Windows error codes
def _format_win_error(err):
    buf = ctypes.create_unicode_buffer(512)
    kernel32.FormatMessageW(
        0x00001000,  # FORMAT_MESSAGE_FROM_SYSTEM
        None,
        err,
        0,
        buf,
        len(buf),
        None
    )
    return buf.value.strip()

# Structures for ICMP
class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p)
    ]

class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [
        ("Address", ctypes.c_uint32),
        ("Status", ctypes.c_uint32),
        ("RoundTripTime", ctypes.c_uint32),
        ("DataSize", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("Data", ctypes.c_void_p),
        ("Options", IP_OPTION_INFORMATION)
    ]

# Icmp* prototypes
IcmpCreateFile = iphlpapi.IcmpCreateFile
IcmpCreateFile.restype = wintypes.HANDLE
IcmpCreateFile.argtypes = []

IcmpCloseHandle = iphlpapi.IcmpCloseHandle
IcmpCloseHandle.restype = wintypes.BOOL
IcmpCloseHandle.argtypes = [wintypes.HANDLE]

IcmpSendEcho2 = iphlpapi.IcmpSendEcho2
IcmpSendEcho2.restype = wintypes.DWORD
IcmpSendEcho2.argtypes = [
    wintypes.HANDLE,     # IcmpHandle
    wintypes.HANDLE,     # Event (can be NULL)
    ctypes.c_void_p,     # ApcRoutine (can be NULL)
    ctypes.c_void_p,     # ApcContext (can be NULL)
    wintypes.DWORD,      # DestinationAddress
    ctypes.c_void_p,     # RequestData pointer
    wintypes.WORD,       # RequestSize
    ctypes.POINTER(IP_OPTION_INFORMATION),  # RequestOptions
    ctypes.c_void_p,     # ReplyBuffer pointer
    wintypes.DWORD,      # ReplySize
    wintypes.DWORD       # Timeout
]


class Ping_result:
    def __init__(self, result, latency, host):
        self.result = result
        self.latency = latency
        self.host = host  # Track host for multi-host output

# --- Argument parser (unchanged) ---
def parseArgs():
    parser = argparse.ArgumentParser(
        prog="ding",
        description=ding_banner.format(__version__=__version__),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: ding google.com,example.com or ding google.com example.com')
    
    parser.add_argument('hosts', nargs='+', help='Hosts to be pinged (space-separated or comma-separated)', metavar='<host>')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='ERROR', help='Set the logging level')
    parser.add_argument('--version', action='version', version=f'ding {__version__}')
    argv = parser.parse_args(sys.argv[1:])

    # Handle comma-separated or space-separated hosts
    hosts = []
    for host in argv.hosts:
        hosts.extend(host.split(','))
    hosts = [h.strip() for h in hosts if h.strip()]
    
    if not hosts:
        parser.print_help()
        sys.exit(1)
    argv.hosts = hosts
    return argv

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except (AttributeError, OSError):
        return False

def get_system_path():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", 0, winreg.KEY_READ) as key:
        path, _ = winreg.QueryValueEx(key, "Path")
        return path

# --- Sound: simple bell, kept as-is but callable from notifier thread ---
def playSound():
    # Keep as minimal portable console bell for now
    # If you later want to use winsound.PlaySound you can replace this function.
    print('\a\b', end='', flush=True)

# --- decideModeAndPing: unchanged logic, returns Ping_result ---
def decideModeAndPing(host='localhost'):
    def windowsPing(host):
        handle = None
        try:
            # Resolve host
            ip = socket.gethostbyname(host)
            packed = socket.inet_aton(ip)
            ip_addr = struct.unpack("<I", packed)[0]  # little-endian DWORD for Windows

            # Open ICMP handle
            handle = IcmpCreateFile()
            if handle == wintypes.HANDLE(-1).value or handle is None:
                err = ctypes.GetLastError()
                logging.error(f"IcmpCreateFile failed: {err}: {_format_win_error(err)}")
                return Ping_result(2, None, host)

            # Payload (must persist during call!)
            data = b'1234567890ABCDEF'
            data_buf = ctypes.create_string_buffer(data)
            data_len = len(data)

            # Options
            ip_opts = IP_OPTION_INFORMATION(Ttl=128, Tos=0, Flags=0, OptionsSize=0, OptionsData=None)

            # Reply buffer: one reply structure + payload
            reply_size = ctypes.sizeof(ICMP_ECHO_REPLY) + data_len + 8
            reply_buf = ctypes.create_string_buffer(reply_size)

            # Call synchronous IcmpSendEcho2 (Event & APC = NULL)
            timeout_ms = 2000
            res = IcmpSendEcho2(
                handle,
                None, None, None,                 # no async
                ip_addr,
                ctypes.byref(data_buf),
                data_len,
                ctypes.byref(ip_opts),
                ctypes.byref(reply_buf),
                reply_size,
                timeout_ms
            )

            if res > 0:
                reply = ctypes.cast(reply_buf, ctypes.POINTER(ICMP_ECHO_REPLY))[0]
                if reply.Status == 0:  # IP_SUCCESS
                    # convert RoundTripTime to a normal int
                    try:
                        rtt = int(reply.RoundTripTime)
                    except Exception:
                        rtt = None
                    return Ping_result(0, rtt, host)
                else:
                    return Ping_result(1, None, host)

            # 0 = timeout or error
            return Ping_result(1, None, host)

        except socket.gaierror:
            return Ping_result(2, None, host)
        except Exception as e:
            logging.exception(f"Unexpected error: {e}")
            return Ping_result(2, None, host)
        finally:
            try:
                if handle:
                    IcmpCloseHandle(handle)
            except (AttributeError, OSError):
                pass

    if operatingSystem == 'windows':
        return windowsPing(host)
    print(f"No ping command defined for OS: {operatingSystem}")
    logging.critical(f"OS {operatingSystem} not supported in ding's ping function")
    sys.exit(1)


# --- utility helpers for display ---
def format_duration(seconds):
    if seconds < 60:
        return f"{int(seconds)} s"
    elif seconds < 3600:
        return f"{int(seconds // 60)} m"
    else:
        return f"{int(seconds // 3600)} h"

# --- Evaluate whether a host is "alerting" according to its notify_mode ---
# Modes:
# 0 = no notification
# 1 = notify when up   (alert while host is UP)
# 2 = notify when down (alert while host is DOWN)
# 3 = notify state change (alert for a short hold period after a change)
ALERT_HOLD_SECONDS = 5.0  # how long mode 3 holds alert after a state change

def evaluate_alert(stats, new_state, old_state):
    """
    Return True if this host should be considered 'alerting' right now.
    For modes 1/2 we consider the instantaneous state (alert while in that state).
    For mode 3 (state change), set alert for ALERT_HOLD_SECONDS after a change.
    """
    mode = stats.get('notify_mode', 3)

    # mode 0: never alert
    if mode == 0:
        return False

    # mode 1: alert while host is UP
    if mode == 1:
        return new_state == "up"

    # mode 2: alert while host is DOWN
    if mode == 2:
        return new_state == "down"

    # mode 3: state change -> keep alert True for ALERT_HOLD_SECONDS after change
    if mode == 3:
        changed = new_state != old_state
        now_ts = time.time()
        if changed:
            # mark when alert started
            stats['alert_since'] = now_ts
            return True

        alert_since = stats.get('alert_since')
        if alert_since is None:
            return False

        if now_ts - alert_since <= ALERT_HOLD_SECONDS:
            return True

        # clear alert_since after hold expires
        stats['alert_since'] = None
        return False

    return False

# --- Compact view and legacy view printing ---
# Colors (ANSI) - Windows 10+ terminals usually support these.
ANSI_RESET = "\033[0m"
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_INVERT = "\033[7m"

class NotifierThread(threading.Thread):
    def __init__(self, host_stats, interval=1.5):
        super().__init__(daemon=True)
        self.host_stats = host_stats
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def any_alerting(self):
        if getattr(self, 'global_silence', False):
            return False
        for s in self.host_stats.values():
            if s.get('alerting'):
                return True
        return False

    def run(self):
        # Repeatedly play sound while any host is alerting
        while not self.stopped():
            if self.any_alerting():
                try:
                    playSound()
                except Exception:
                    pass
                # wait small interval but break early if stopped
                slept = 0.0
                while slept < self.interval and not self.stopped():
                    time.sleep(0.1)
                    slept += 0.1
            else:
                # sleep a bit before checking again
                time.sleep(0.2)

def build_compact_view(hosts_order, stats, selected_index, global_silence):
    lines = []
    lines.append(
        " DING - Real-time Ping Monitor     "
        f"Silence: [{'ON ' if global_silence else 'OFF'}]     "
        "TAB = toggle view • Q = quit • ↑↓/jk = select • 0-3 = mode"
    )
    lines.append("═" * 80)

    modes = ["none", "on up", "on down", "on change"]
    for i, host in enumerate(hosts_order):
        s = stats[host]
        sel = ">" if i == selected_index else " "
        state = (s['current_state'] or "?").upper()
        col = ANSI_GREEN if state == "UP" else ANSI_RED if state == "DOWN" else ANSI_YELLOW
        lat = f"{s['latency'] or '-':>4}ms" if s['latency'] is not None else "  -  "
        uptime = format_duration(time.time() - s['state_since']) if s.get('state_since') else "-"
        mode = modes[s.get('notify_mode', 3)]
        alert = ANSI_INVERT + " !!! " + ANSI_RESET if s.get('alerting') else ""

        lines.append(f"{sel} {host:<30} {col}{state:<4}{ANSI_RESET} {lat}  {uptime:<8}  {mode:<12} {alert}")

    lines.append("\n")
    return "\n".join(lines)

def build_legacy_view(host_stats, global_silence):
    # Keep your original panel layout if desired — or simplify
    # For now, just fall back to compact when not used
    return build_compact_view(list(host_stats.keys()), host_stats, 0, global_silence)
    
def ding():
    try:
        argv = parseArgs()
        logging.basicConfig(
            level=getattr(logging, argv.log_level),
            format="%(asctime)s - %(levelname)s - %(message)s",
            filename='ding.log',
            filemode='a'
        )

        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        hosts_order = list(argv.hosts)
        host_stats = {}
        global_silence = False

        now0 = time.time()
        for host in hosts_order:
            host_stats[host] = {
                'sent': 0,
                'received': 0,
                'results': [],

                'current_state': None,
                'state_since': now0,

                'consecutive_up': 0,
                'consecutive_down': 0,
                'warmup_left': 4,
                'warmup_done': False,

                'status_msg': "",
                'notify_mode': 3,
                'alerting': False,
                'alert_since': None,
                'latency': None,
            }

        selected_index = 0
        compact_mode = True

        executor = ThreadPoolExecutor(max_workers=max(8, len(hosts_order)))
        futures = {}

        notifier = NotifierThread(host_stats, interval=1.0)
        notifier.global_silence = global_silence
        notifier.start()

        # Initial pings
        for h in hosts_order:
            futures[h] = executor.submit(decideModeAndPing, h)

        # Timing control
        UI_REFRESH_INTERVAL = 0.15
        last_ui_refresh = 0.0

        running = True
        while running:
            now = time.time()

            # === 1. Process completed pings ===
            for host in list(futures.keys()):
                fut = futures[host]
                if fut.done():
                    try:
                        response = fut.result()
                    except Exception as e:
                        logging.exception(f"Ping error for {host}: {e}")
                        response = Ping_result(2, None, host)

                    stats = host_stats[host]
                    stats['sent'] += 1
                    stats['results'].append(response)
                    if len(stats['results']) > 100:
                        stats['results'] = stats['results'][-100:]

                    stats['latency'] = response.latency if response.result == 0 else None

                    old_state = stats['current_state']

                    if response.result == 0:
                        stats['consecutive_up'] += 1
                        stats['consecutive_down'] = 0
                    else:
                        stats['consecutive_down'] += 1
                        stats['consecutive_up'] = 0

                    # --- Warm-up phase ---
                    if not stats['warmup_done']:
                        stats['warmup_left'] -= 1

                        if stats['warmup_left'] <= 0:
                            # Decide initial state by majority
                            if stats['consecutive_down'] >= stats['consecutive_up']:
                                stats['current_state'] = "down"
                            else:
                                stats['current_state'] = "up"

                            stats['state_since'] = now
                            stats['warmup_done'] = True

                        # No alerts during warmup
                        stats['alerting'] = False
                        continue  # skip alert/state logic until warmup finishes

                    # --- Normal state transitions ---
                    new_state = old_state

                    if old_state == "up" and stats['consecutive_down'] >= DOWN_THRESHOLD:
                        new_state = "down"

                    elif old_state == "down" and stats['consecutive_up'] >= UP_THRESHOLD:
                        new_state = "up"

                    if new_state != old_state:
                        stats['current_state'] = new_state
                        stats['state_since'] = now


                    if response.result == 0:
                        stats['received'] += 1

                    stats['status_msg'] = f"{new_state.upper()} {format_duration(now - stats['state_since'])}"

                    if not stats['warmup_done']:
                        stats['alerting'] = False
                    else:
                        stats['alerting'] = evaluate_alert(stats, new_state, old_state)

                    stats['alerting'] = evaluate_alert(stats, new_state, old_state)

                    # Immediately reschedule next ping
                    del futures[host]
                    futures[host] = executor.submit(decideModeAndPing, host)

            # === 2. Refresh UI at fixed interval (smooth) ===
            if now - last_ui_refresh >= UI_REFRESH_INTERVAL:
                last_ui_refresh = now

                if compact_mode:
                    output = build_compact_view(hosts_order, host_stats, selected_index, global_silence)
                else:
                    output = build_legacy_view(host_stats, global_silence)

                # Single write: no flicker!
                sys.stdout.write("\033[H")  # Move to home without clearing
                sys.stdout.write("\033[J")  # Clear from cursor to end (safer)
                sys.stdout.write(output)
                sys.stdout.flush()

            # === 3. Non-blocking keyboard input (responsive!) ===
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ('\x00', '\xe0'):  # Special keys
                    ch2 = msvcrt.getwch()
                    if ch2 == 'H':      # Up
                        selected_index = (selected_index - 1) % len(hosts_order)
                    elif ch2 == 'P':    # Down
                        selected_index = (selected_index + 1) % len(hosts_order)
                    elif ch2 == 'K':    # Left (optional)
                        pass
                    elif ch2 == 'M':    # Right
                        pass
                else:
                    key = ch.lower()
                    if key == 'q':
                        running = False
                    elif key == '\t':
                        compact_mode = not compact_mode
                    elif key in 'jk':
                        selected_index = (selected_index + (1 if key == 'j' else -1)) % len(hosts_order)
                    elif key in '0123':
                        host = hosts_order[selected_index]
                        host_stats[host]['notify_mode'] = int(key)
                        host_stats[host]['alert_since'] = None  # reset hold timer
                    elif key == 's':
                        global_silence = not global_silence
                        notifier.global_silence = global_silence
                        last_ui_refresh = 0

                # Force immediate redraw after keypress
                last_ui_refresh = 0

            # Minimal sleep to keep CPU low but responsive
            time.sleep(0.01)

    except Exception:
        traceback.print_exc()
    finally:
        # Cleanup
        sys.stdout.write("\033[?25h")  # Show cursor
        sys.stdout.write("\033[H\033[J")  # Final clear
        sys.stdout.flush()

        try:
            notifier.stop()
            notifier.join(timeout=1.0)
        except Exception:
            pass
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        except Exception:
            pass
        print("ding stopped.")

if __name__ == "__main__":
    # Auto-elevate if not admin
    if not is_admin():
        print("Requesting admin privileges...")

        # Re-launch the script with admin rights
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",                                # triggers UAC prompt
            sys.executable,                         # python.exe
            f'"{sys.argv[0]}" {params}',
            None,
            1
        )
        sys.exit(0)  # Exit the non-admin process

    # Now runs as admin
    ding()