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
    # Ping_result.result: 
    # 0 if host responds
    # 1 if host does not respond
    # 2 if host was not found
    def __init__(self, result, latency):
        self.result = result
        self.latency = latency

def parseArgs():
    # Parse arguments
    parser = argparse.ArgumentParser(
        prog="ding",
        description=ding_banner.format(__version__=__version__),
        formatter_class=argparse.RawDescriptionHelpFormatter,  # Preserve newlines in description
        epilog='Example: ding google.com')
    
    parser.add_argument('host',nargs='?',help='Host to be pinged', metavar='<host>')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='ERROR', help='Set the logging level')
    parser.add_argument('--version', action='version', version=f'ding {__version__}')
    args = parser.parse_args(sys.argv[1:])
    return args

args = parseArgs()

logging.basicConfig(
    level=getattr(logging, args.log_level),
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename='ding.log',
    filemode='a'
    )  
    
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
    # Play sound using motherboard speaker
    print('\a\b', end='')

def decideModeAndPing(host='localhost'):
    # Pings once, returns a Ping_result object
    def windowsPing(host):
        def findResponseTime(ping_command_result):
            for subtext in ping_command_result.split(" "):
                if 'ms' in subtext:
                    latency = "".join(char for char in subtext if char.isdecimal())
                    return latency
        param = '-n'
        command = ['ping', param, '1', host]
        logging.debug("Running Windows ping command...")
        win_ping = subprocess.run(command, capture_output = True, text = True)
        win_ping_result = win_ping.stdout
        win_ping_errors = win_ping.stderr
        if not (win_ping_errors is None): logging.debug(win_ping_errors)
        if "(0%" in win_ping_result: result = 0
        if "(100%" in win_ping_result: result = 1
        if "host" in win_ping_result: result = 2
        latency = findResponseTime(win_ping_result)
        return Ping_result(result,latency)
    
    #def linuxPing(host):
    #    param = '-c'
    #    command = ['ping', param, '1', host]
    #    return subprocess.call(command,stdout=subprocess.PIPE) == 0

    if operatingSystem=='windows': return windowsPing(host)
    # if operatingSystem =='linux': return linuxPing(host)
    print("There is no ping command defined for this operating system ","(",operatingSystem,")")
    logging.CRITICAL("Operating System ",operatingSystem,"has not been specified in ding's ping function")
    sys.exit()

def printStatus(host,sent,received):
    if operatingSystem=='windows':
        os.system('cls')
    percentage_received = (100*received/(sent if sent>0 else 1))
    print("\r","Pinging",host,":\n Received/sent ",received,"/",sent,'(',str(int(percentage_received)),'% )')
    print(" Latency:")

def printLatencyChart(resultv):
    results_to_plot = 10
    def printLatencyLine(result):
        if result[0]==0:
            print(" ",result[1],"ms",end="")
            print(" "*(6-len(str(result[1]))),end="")
            print("|","█"*int((int(result[1])+10)/20),end="")
            print()
        if result[0]==1:
            print(" No response")
        if result[0]==2:
            print(" Host not found")        
    def plotChart(resultv):
            for result in resultv:
                printLatencyLine(result)        
    if len(resultv)<results_to_plot:
        plotChart(resultv)
    else:
        plotChart(resultv[-results_to_plot:])

#
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#

def ding():
    try:
        cont=True
        sent=0
        received=0
        resultv=[]
        silenced = False  # Silence default state
                
        logging.debug("Parsing command line arguments... \n")
        argv=sys.argv
        argv = parseArgs()
        logging.debug("Done")
        
        logging.debug("Starting main loop...")
        while cont == True:
            response = decideModeAndPing(argv.host)
            sent+=1
            print(response.result)
            if response.result==0:
                if not silenced:
                    playSound()
                received+=1
            if response.result==2:
                print("Host",argv.host,"not found")

            resultv.append([response.result, response.latency])
            printStatus(argv.host,sent,received)
            printLatencyChart(resultv)
            print(" (S)ilence:", "ON" if silenced else "OFF")
            wait_time = 2.0
            check_interval = 0.1
            steps = int(wait_time / check_interval)
            for _ in range(steps):
                if operatingSystem == 'windows' and msvcrt.kbhit():
                    key = msvcrt.getch().decode('utf-8').lower()
                    if key == 's':
                        silenced = not silenced  # Toggle silence state
                time.sleep(check_interval)
    except KeyboardInterrupt:
        print("Stopping ding")
    except Exception:
        traceback.print_exc(file=sys.stdout)
    sys.exit(0)
    
if __name__ == "__main__":
    ding()