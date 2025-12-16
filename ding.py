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

DEFAULT_PING_INTERVAL = 1.0  # seconds
MIN_PING_INTERVAL = 0.2
MAX_PING_INTERVAL = 10.0
WARMUP_PINGS = 6

SPARKLINE_WIDTH = 12
HIGH_LATENCY_MS = 500

SPARK_CHARS = "▁▂▃▄▅▆▇█"
SPARK_FAIL_CHAR = "×"

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

def latency_to_bg_color(latency_ms):
    if latency_ms is None:
        return "\033[48;5;196m"  # timeout → red

    # Hard thresholds
    GOOD_MAX = 80
    WARN_MAX = 200
    BAD_MAX  = 350

    latency_ms = max(0, latency_ms)

    # --- GOOD: dark green → green ---
    if latency_ms <= GOOD_MAX:
        ratio = latency_ms / GOOD_MAX
        r = 0
        g = int(2 + ratio * 2)   # 2 → 4 (dark → green)
        b = 0

    # --- WARNING: green → yellow ---
    elif latency_ms <= WARN_MAX:
        ratio = (latency_ms - GOOD_MAX) / (WARN_MAX - GOOD_MAX)
        r = int(ratio * 5)       # 0 → 5
        g = 4
        b = 0

    # --- BAD: yellow → red ---
    elif latency_ms <= BAD_MAX:
        ratio = (latency_ms - WARN_MAX) / (BAD_MAX - WARN_MAX)
        r = 5
        g = int((1 - ratio) * 4) # 4 → 0
        b = 0

    # --- VERY BAD: solid red ---
    else:
        return "\033[48;5;196m"

    color = 16 + 36*r + 6*g + b

    return f"\033[48;5;{color}m"


def render_latency_bar(results, width=SPARKLINE_WIDTH):
    """
    Render latency history using background-colored spaces.
    """
    if not results:
        return " " * width

    recent = results[-width:]
    out = []

    for r in recent:
        if r.latency is None:
            # timeout
            out.append("\033[48;5;196mx\033[0m")
        else:
            bg = latency_to_bg_color(r.latency)
            out.append(f"{bg} \033[0m")

    # Pad left if needed
    if len(out) < width:
        out = [" "] * (width - len(out)) + out

    return "".join(out)


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

def render_latency_sparkline(results, width=SPARKLINE_WIDTH):
    """
    Build a sparkline from recent ping results.
    Success -> scaled block
    Failure -> ×
    """
    if not results:
        return " " * width

    recent = results[-width:]

    # Extract latencies (None for failures)
    latencies = [r.latency for r in recent]

    valid = [v for v in latencies if v is not None]
    if not valid:
        return SPARK_FAIL_CHAR * len(latencies)

    lo = min(valid)
    hi = max(valid)
    span = max(hi - lo, 1)

    out = []
    for v in latencies:
        if v is None:
            out.append(SPARK_FAIL_CHAR)
        else:
            idx = int((v - lo) / span * (len(SPARK_CHARS) - 1))
            out.append(SPARK_CHARS[idx])

    return "".join(out).rjust(width)


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

# --- Compact view printing ---
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

def build_compact_view(hosts_order, stats, selected_index, global_silence, ping_interval, pending_remove):
    lines = []
    lines.append(
        " DING - "
        f"Freq: {ping_interval:.1f}s - "
        f"(s)ilence: [{'ON ' if global_silence else 'OFF'}] - "
        "(q)uit • (h)elp"
    )
    lines.append("═" * 60)

    lines.append(" "*4+"host"+" "*20+"| status "+"|     latency"+" "*5+ "| uptime "+"| notification mode")
    

    modes = ["none", "on up", "on down", "on change"]
    for i, host in enumerate(hosts_order):
        s = stats[host]
        sel = ">" if i == selected_index else " "
        state = (s['current_state'] or "?").upper()
        # State label color (only for the UP/DOWN text)
        if state == "UP":
            col = ANSI_GREEN
        elif state == "DOWN":
            col = ANSI_RED
        else:
            col = ANSI_YELLOW

        row_color = ""
        row_reset = ""

        # DOWN always red
        if state == "DOWN":
            row_color = ANSI_RED
            row_reset = ANSI_RESET

        # High latency warning (only if UP)
        elif s['latency'] is not None and s['latency'] >= HIGH_LATENCY_MS:
            row_color = ANSI_RED
            row_reset = ANSI_RESET

        lat = f"{s['latency'] or '--':>4}ms" if s['latency'] is not None else "  --  "
        uptime = format_duration(time.time() - s['state_since']) if s.get('state_since') else "-"
        spark = render_latency_bar(s.get('results', []))

        mode = modes[s.get('notify_mode', 3)]
        alert = ANSI_INVERT + " !!! " + ANSI_RESET if s.get('alerting') else ""

        confirm = ""
        if host == pending_remove:
            confirm = ANSI_INVERT + " (r)emove? " + ANSI_RESET


        lines.append(
            f"{row_color}"
            f"{sel} {host:<28} "
            f"{col}{state:<4}{ANSI_RESET} "
            f"{lat} "
            f"{spark}  "
            f"{uptime:<8}  "
            f"{mode:<12} "
            f"{alert}"
            f"{confirm}"
            f"{row_reset}"
        )

    lines.append("\n")
    return "\n".join(lines)
    
def build_help_panel():
    return """
────────────────────────────────────────────────────────────
 Global commands:
   (f)req      Set ping frequency
   (a)dd       Add host
   (r)emove    Remove selected host
   (s)ilence   Toggle global silence
   (p)ause     Pause / resume pinging
   (h)elp      Toggle this menu
   (q)uit      Exit ding

 Host commands (selected host):
   (e)dit      Edit hostname / IP
   (0) none    (1) on up    (2) on down    (3) on change
   (c)lear     Reset host statistics
────────────────────────────────────────────────────────────
""".strip("\n")


def ding():
    def cancel_pending_remove():
        nonlocal pending_remove
        if pending_remove is not None:
            pending_remove = None

    try:
        argv = parseArgs()
        logging.basicConfig(
            level=getattr(logging, argv.log_level),
            format="%(asctime)s - %(levelname)s - %(message)s",
            filename='ding.log',
            filemode='a'
        )

        ping_interval = DEFAULT_PING_INTERVAL

        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        hosts_order = list(argv.hosts)
        host_stats = {}
        global_silence = False
        show_help = False
        paused = False
        pending_remove = None

        now0 = time.time()
        for host in hosts_order:
            host_stats[host] = {
                'sent': 0,
                'received': 0,
                'results': [],

                'current_state': None,
                'state_since': now0,
                'next_ping_time': now0,

                'consecutive_up': 0,
                'consecutive_down': 0,
                'warmup_left': WARMUP_PINGS,
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

        # Timing control
        UI_REFRESH_INTERVAL = 0.15
        last_ui_refresh = 0.0

        running = True
        while running:
            now = time.time()

            # === 0. Schedule new pings based on frequency ===
            if not paused:
                for host in hosts_order:
                    if host not in futures:
                        if now >= host_stats[host]['next_ping_time']:
                            futures[host] = executor.submit(decideModeAndPing, host)
                            host_stats[host]['next_ping_time'] = now + ping_interval

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
                            stats['current_state'] = "down" if stats['consecutive_down'] >= stats['consecutive_up'] else "up"
                            stats['state_since'] = now
                            stats['warmup_done'] = True
                            stats['alert_since'] = None
                            stats['alerting'] = False

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

                    # Immediately reschedule next ping
                    del futures[host]

            # === 2. Refresh UI at fixed interval (smooth) ===
            if now - last_ui_refresh >= UI_REFRESH_INTERVAL:
                last_ui_refresh = now
                parts = []
                if show_help:
                    parts.append(build_help_panel())

                if compact_mode:
                    parts.append(
                        build_compact_view(
                            hosts_order,
                            host_stats,
                            selected_index,
                            global_silence,
                            ping_interval,
                            pending_remove
                        )
                    )
                else:
                    pass

                output = "\n".join(parts)


                # Single write: no flicker!
                sys.stdout.write("\033[H")  # Move to home without clearing
                sys.stdout.write("\033[J")  # Clear from cursor to end (safer)
                sys.stdout.write(output)
                sys.stdout.flush()

            # === 3. Non-blocking keyboard input ===
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ('\x00', '\xe0'):  # Special keys
                    cancel_pending_remove()
                    ch2 = msvcrt.getwch()

                    if ch2 == 'H':      # Up
                        selected_index = (selected_index - 1) % len(hosts_order)

                    elif ch2 == 'P':    # Down
                        selected_index = (selected_index + 1) % len(hosts_order)

                    elif ch2 == 'K':    # Left  -> previous notify mode
                        if hosts_order:
                            host = hosts_order[selected_index]
                            mode = host_stats[host]['notify_mode']
                            host_stats[host]['notify_mode'] = (mode - 1) % 4
                            host_stats[host]['alert_since'] = None

                    elif ch2 == 'M':    # Right -> next notify mode
                        if hosts_order:
                            host = hosts_order[selected_index]
                            mode = host_stats[host]['notify_mode']
                            host_stats[host]['notify_mode'] = (mode + 1) % 4
                            host_stats[host]['alert_since'] = None

                else:
                    key = ch.lower()
                    if key != 'r':
                        cancel_pending_remove()
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
                    elif key == 'h':
                        show_help = not show_help
                    elif key == 'p':
                        paused = not paused
                        last_ui_refresh = 0
                    elif key == 'f':
                        sys.stdout.write("\033[H\033[J")
                        sys.stdout.write("Set ping frequency in seconds (0.2 – 10.0): ")
                        sys.stdout.flush()
                        sys.stdout.write("\033[?25h")

                        try:
                            value = input().strip()
                            new_interval = float(value)
                            if MIN_PING_INTERVAL <= new_interval <= MAX_PING_INTERVAL:
                                ping_interval = new_interval
                        except ValueError:
                            pass
                        finally:
                            sys.stdout.write("\033[?25l")
                            last_ui_refresh = 0

                    elif key == 'c':
                        host = hosts_order[selected_index]
                        now = time.time()
                        host_stats[host].update({
                            'sent': 0,
                            'received': 0,
                            'results': [],
                            'consecutive_up': 0,
                            'consecutive_down': 0,
                            'current_state': None,
                            'state_since': now,
                            'warmup_left': WARMUP_PINGS,
                            'warmup_done': False,
                            'alerting': False,
                            'alert_since': None,
                            'latency': None,
                        })
                    
                    elif key == 'a':
                        sys.stdout.write("\033[H\033[J")
                        sys.stdout.write("Add host(s) (space or comma separated): ")
                        sys.stdout.flush()
                        sys.stdout.write("\033[?25h")

                        try:
                            raw = input().strip()
                            if not raw:
                                pass

                            new_hosts = []
                            for part in raw.replace(',', ' ').split():
                                h = part.strip()
                                if h and h not in host_stats:
                                    new_hosts.append(h)

                            now = time.time()
                            for h in new_hosts:
                                hosts_order.append(h)
                                host_stats[h] = {
                                    'sent': 0,
                                    'received': 0,
                                    'results': [],
                                    'current_state': None,
                                    'state_since': now,
                                    'next_ping_time': now,
                                    'consecutive_up': 0,
                                    'consecutive_down': 0,
                                    'warmup_left': WARMUP_PINGS,
                                    'warmup_done': False,
                                    'status_msg': "",
                                    'notify_mode': 3,
                                    'alerting': False,
                                    'alert_since': None,
                                    'latency': None,
                                }

                        finally:
                            sys.stdout.write("\033[?25l")
                            last_ui_refresh = 0

                    elif key == 'e' and hosts_order:
                        old_host = hosts_order[selected_index]

                        sys.stdout.write("\033[H\033[J")
                        sys.stdout.write(f"Edit host [{old_host}] (leave empty to cancel): ")
                        sys.stdout.flush()
                        sys.stdout.write("\033[?25h")

                        try:
                            new_host = input().strip()
                            if not new_host or new_host == old_host:
                                pass
                            else:
                                # Cancel pending ping
                                fut = futures.pop(old_host, None)
                                if fut:
                                    try:
                                        fut.cancel()
                                    except Exception:
                                        pass

                                # Replace in order list
                                hosts_order[selected_index] = new_host

                                # Reset stats
                                now = time.time()
                                host_stats[new_host] = {
                                    'sent': 0,
                                    'received': 0,
                                    'results': [],
                                    'current_state': None,
                                    'state_since': now,
                                    'next_ping_time': now,
                                    'consecutive_up': 0,
                                    'consecutive_down': 0,
                                    'warmup_left': WARMUP_PINGS,
                                    'warmup_done': False,
                                    'status_msg': "",
                                    'notify_mode': 3,
                                    'alerting': False,
                                    'alert_since': None,
                                    'latency': None,
                                }

                                # Remove old entry
                                host_stats.pop(old_host, None)

                        finally:
                            sys.stdout.write("\033[?25l")
                            last_ui_refresh = 0

                    elif key == 'r' and hosts_order:
                        host = hosts_order[selected_index]

                        if pending_remove != host:
                            pending_remove = host
                        else:
                            # Confirmed removal
                            fut = futures.pop(host, None)
                            if fut:
                                try:
                                    fut.cancel()
                                except Exception:
                                    pass

                            host_stats.pop(host, None)
                            hosts_order.pop(selected_index)

                            pending_remove = None

                            if hosts_order:
                                selected_index = min(selected_index, len(hosts_order) - 1)
                            else:
                                selected_index = 0

                        last_ui_refresh = 0

                    if key != 'r' and pending_remove:
                        host_stats.get(pending_remove, {}).pop('_pending_remove', None)
                        pending_remove = None

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