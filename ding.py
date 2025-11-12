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
        def findResponseTime(ping_command_result):
            for subtext in ping_command_result.split(" "):
                if 'ms' in subtext:
                    latency = "".join(char for char in subtext if char.isdecimal())
                    return latency if latency else None
        param = '-n'
        command = ['ping', param, '1', host]
        logging.debug(f"Running Windows ping command for {host}...")
        try:
            win_ping = subprocess.run(command, capture_output=True, text=True, timeout=5)
            win_ping_result = win_ping.stdout
            win_ping_errors = win_ping.stderr
            if win_ping_errors:
                logging.debug(win_ping_errors)
            if "(0%" in win_ping_result:
                result = 0
            elif "(100%" in win_ping_result:
                result = 1
            elif "host" in win_ping_result.lower():
                result = 2
            else:
                result = 1  # Default to no response if unclear
            latency = findResponseTime(win_ping_result)
            return Ping_result(result, latency, host)
        except subprocess.TimeoutExpired:
            logging.debug(f"Ping timeout for {host}")
            return Ping_result(1, None, host)
        except Exception as e:
            logging.error(f"Error pinging {host}: {e}")
            return Ping_result(2, None, host)

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
