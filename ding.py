# -*- coding: utf-8 -*-
"""                                                            
Created on Mon Dec 18 22:46:04 2023
@author: Agustin Aponte
"""
__version__ = "0.0.1"
import platform
import os
import subprocess
import sys
import logging
import time
import argparse
import traceback
import msvcrt
import ctypes
import winreg
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import struct
import ctypes.wintypes as wintypes
import shutil

# Load iphlpapi
iphlpapi = ctypes.WinDLL('iphlpapi')
kernel32 = ctypes.WinDLL('kernel32')


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

    # Try to make rows and cols as close as possible
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
    except:
        return False

def get_system_path():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", 0, winreg.KEY_READ) as key:
        path, _ = winreg.QueryValueEx(key, "Path")
        return path

def playSound():
    print('\a\b', end='')

def decideModeAndPing(host='localhost'):
    def windowsPing(host):
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
                # Extract first reply
                reply = ctypes.cast(reply_buf, ctypes.POINTER(ICMP_ECHO_REPLY))[0]
                if reply.Status == 0:  # IP_SUCCESS
                    return Ping_result(0, str(reply.RoundTripTime), host)
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
            except:
                pass

    if operatingSystem == 'windows':
        return windowsPing(host)
    print(f"No ping command defined for OS: {operatingSystem}")
    logging.critical(f"OS {operatingSystem} not supported in ding's ping function")
    sys.exit(1)

def printStatus(host_stats):
    # clear screen
    if operatingSystem == 'windows':
        os.system('cls')
    else:
        os.system('clear')

    cols, rows = shutil.get_terminal_size()

    hosts = list(host_stats.items())
    if not hosts:
        print("(S)ilence: OFF")
        return

    # Separador entre paneles (corto para evitar mucho espacio)
    separator = "  "

    # Decide un ancho mínimo razonable por panel
    min_panel_width = 24

    # Calculamos cuántos paneles intentamos poner por fila.
    # Usamos un divisor prudente para no crear paneles enormes.
    panels_per_row = max(1, min(len(hosts), cols // min_panel_width))

    # Ancho efectivo por panel teniendo en cuenta el separador
    panel_width = max(min_panel_width, cols // panels_per_row - len(separator))

    # Procesamos por grupos (filas)
    for row_start in range(0, len(hosts), panels_per_row):
        row_hosts = hosts[row_start: row_start + panels_per_row]

        # Renderizamos cada host del grupo a una lista de líneas (SIN padding final)
        host_panels = []
        for host, stats in row_hosts:
            sent = stats['sent']
            received = stats['received']
            percentage_received = (100 * received / (sent if sent > 0 else 1))

            lines = []
            # Línea 0: nombre (truncate si es muy largo)
            name = f"[{host}]"
            if len(name) > panel_width:
                name = name[:panel_width-3] + "..."
            lines.append(name)

            # Línea 1: status_msg (truncate si es necesario)
            msg = stats.get('status_msg', "")
            if len(msg) > panel_width:
                msg = msg[:panel_width-3] + "..."
            lines.append(msg)

            # Línea 2: recibidos/enviados
            lines.append(f"Rx/Tx {received}/{sent} ({int(percentage_received)}%)")

            # Línea 3: encabezado latencia
            lines.append("Latency:")

            # Líneas siguientes: últimos 5 resultados (formateados)
            recent = stats['results'][-5:]
            latency_lines = []

            for i in range(5):
                if i < len(recent):
                    r = recent[i]
                    if r.result == 0 and r.latency:
                        lat_str = f"{int(r.latency)}ms".rjust(4)
                        bar_len = max(1, int((int(r.latency) + 10) / 20))
                        bar = "█" * bar_len
                        line = f"{lat_str} {bar}"
                    elif r.result == 1:
                        line = "No response"
                    else:
                        line = "Host not found"
                else:
                    line = ""  # <--- placeholder empty line to keep panel size fixed

                # Truncate if too wide
                if len(line) > panel_width:
                    line = line[:panel_width-3] + "..."

                latency_lines.append(line)

            # Add the reserved lines to the panel
            lines.extend(latency_lines)

            host_panels.append(lines)

        # Determinamos cuántas líneas tiene el panel más alto
        max_lines = max(len(p) for p in host_panels)

        # Imprimimos línea a línea, uniendo paneles con el separador corto
        for i in range(max_lines):
            parts = []
            for p in host_panels:
                part = p[i] if i < len(p) else ""
                # Alineamos/paddamos a panel_width justo antes de unir
                parts.append(part.ljust(panel_width))
            print(separator.join(parts))

        print("")  # línea en blanco entre filas de paneles

    # Global status (silence)
    any_host = next(iter(host_stats.values()))
    print(f"(S)ilence: {'ON' if any_host['silenced'] else 'OFF'}")


def printLatencyChart(resultv, host):
    results_to_plot = 5
    def printLatencyLine(result):
        if result.result == 0 and result.latency:
            print(f" {result.latency}ms", end="")
            print(" " * (6 - len(str(result.latency))), end="")
            print("|", "█" * int((int(result.latency) + 10) / 20), end="")
            print()
        elif result.result == 1:
            print(" No response")
        elif result.result == 2:
            print(" Host not found")
    
    print(f" Latency for {host}:")
    if len(resultv) < results_to_plot:
        for result in resultv:
            printLatencyLine(result)
    else:
        for result in resultv[-results_to_plot:]:
            printLatencyLine(result)

def format_duration(seconds):
    if seconds < 60:
        return f"{int(seconds)} s"
    elif seconds < 3600:
        return f"{int(seconds // 60)} m"
    else:
        return f"{int(seconds // 3600)} h"


def ding():
    try:
        cont = True
        host_stats = {}
        argv = parseArgs()
        logging.debug("Parsing command line arguments...")
        logging.debug("Done")
        logging.basicConfig(
            level=getattr(logging, argv.log_level),
            format="%(asctime)s - %(levelname)s - %(message)s",
            filename='ding.log',
            filemode='a'
        )

        # Initialize stats for each host
        for host in argv.hosts:
            host_stats[host] = {
                'sent': 0,
                'received': 0,
                'results': [],
                'silenced': False,
                'current_state': None,
                'state_since': time.time(),
                'status_msg': ""
                }
            
        # --- Auto resize terminal based on number of hosts ---
        if operatingSystem == 'windows':
            width, height = choose_optimal_terminal_size(len(argv.hosts))
            resize_terminal(width, height)

        logging.debug("Starting main loop...")
        while cont:
            # Ping all hosts concurrently
            with ThreadPoolExecutor(max_workers=len(argv.hosts)) as executor:
                future_to_host = {executor.submit(decideModeAndPing, host): host for host in argv.hosts}
                for future in as_completed(future_to_host):
                    host = future_to_host[future]
                    response = future.result()

                    host_stats[host]['sent'] += 1

                    if response.result == 0 and response.latency:
                        if not host_stats[host]['silenced']:
                            playSound()
                        host_stats[host]['received'] += 1

                    if response.result == 2:
                        print(f"Host {host} not found")

                    host_stats[host]['results'].append(response)

                    # ------------------ NEW STATE TRACKING LOGIC ------------------
                    new_state = "up" if (response.result == 0 and response.latency) else "down"
                    old_state = host_stats[host]['current_state']
                    now = time.time()

                    if old_state is None:
                        host_stats[host]['current_state'] = new_state
                        host_stats[host]['state_since'] = now
                    else:
                        if new_state != old_state:
                            host_stats[host]['current_state'] = new_state
                            host_stats[host]['state_since'] = now

                    duration = now - host_stats[host]['state_since']

                    if old_state is None:
                        msg = f"{new_state.upper()} for at least {format_duration(duration)}"
                    elif new_state != old_state:
                        msg = f"{new_state.upper()} for {format_duration(duration)}"
                    else:
                        msg = f"{new_state.upper()} for at least {format_duration(duration)}"

                    host_stats[host]['status_msg'] = msg

            printStatus(host_stats)
            wait_time = 2.0
            check_interval = 0.1
            steps = int(wait_time / check_interval)
            for _ in range(steps):
                if operatingSystem == 'windows' and msvcrt.kbhit():
                    key = msvcrt.getch().decode('utf-8').lower()
                    if key == 's':
                        # Toggle silence for all hosts (or modify to target specific hosts)
                        for host in host_stats:
                            host_stats[host]['silenced'] = not host_stats[host]['silenced']
                time.sleep(check_interval)
    except KeyboardInterrupt:
        print("Stopping ding")
    except Exception:
        traceback.print_exc(file=sys.stdout)
    sys.exit(0)

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
