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
    if operatingSystem == 'windows':
        os.system('cls')
    for host, stats in host_stats.items():
        sent = stats['sent']
        received = stats['received']
        percentage_received = (100 * received / (sent if sent > 0 else 1))
        print(f"\rPinging {host}:\n Received/sent {received}/{sent} ({int(percentage_received)}%)")
        printLatencyChart(stats['results'], host)
    print(f" (S)ilence: {'ON' if stats['silenced'] else 'OFF'}\n")

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
            host_stats[host] = {'sent': 0, 'received': 0, 'results': [], 'silenced': False}

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
    if not is_admin():
        print("Requesting admin privileges...")
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            f'"{sys.argv[0]}" {params}',
            None,
            1
        )
        sys.exit(0)

    ding()