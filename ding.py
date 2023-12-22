# -*- coding: utf-8 -*-
"""                                                            
Created on Mon Dec 18 22:46:04 2023
@author: Agustin Aponte
"""
import platform
import os
import subprocess
import sys
import logging
import time
import argparse

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename='ding.log',
    filemode='a'
    )

ding_banner = """
____________.###+..+###-_______________________________________________________
_____________+###..###+________________________________________________________
_________.+######..#######._________________█████__███_________________________
________+#######.__.########_______________░░███__░░░__________________________
_______#####.__________.#####____________███████__████__████████____███████____
_______###._______________+##___________███░░███_░░███_░░███░░███__███░░███____
______+##.________________.##+_________░███_░███__░███__░███_░███_░███_░███____
______###__________________###_________░███_░███__░███__░███_░███_░███_░███____
______##.__________________.##.________░░████████_█████_████_█████░░███████____
_____.##.__________________.##._________░░░░░░░░_░░░░░_░░░░_░░░░░__░░░░░███____
_____###____________________###____________________________________███_░███____
_____##+____________________+##___________________________________░░██████_____
____.##.____________________.##.___________________________________░░░░░░______
____###______________________###____________Like_ping,_but_with_better_sound___
___.############################.______________________________________________
+##################################+___________________________________________
##.__________##########___________##___________________________________________
+###############.__.+##############+___________________________________________
_____________##########________________________________________________________
________________####___________________________________________________________
"""
operatingSystem = platform.system().lower()
count = 0

class Ping_result:
    def __init__(self, result, latency):
        # set self.result to True if a response was received, False if no response
        self.result = result
        self.latency = latency

def parseArgs():
    # Parse arguments
    parser = argparse.ArgumentParser(
        prog="ding",
        description=ding_banner)
    parser.add_argument('host',nargs='?',help='Host/s to be pinged', metavar='<host>')
    args = parser.parse_args(sys.argv[1:])
    return args
    
def runningAsAdmin():
    # Checks for root/admin privileges
    if operatingSystem=='windows': return 
    if operatingSystem=='linux': return 
    if operatingSystem != ('windows' or 'linux'): logging.critical("ding does not recognize operating system")
    sys.exit()
    
def playSound():
    # Play sound using motherboard speaker
    print('\a\b', end='')
    
def ping(host='localhost'):
    # Pings once, returns:
    #  0 if host responds
    #  1 if host does not respond
    #  2 if host was not found
    
    def windowsPing(host):
        def findResponseTime(ping_command_result):
            for subtext in ping_command_result.split(" "):
                if 'ms' in subtext:
                    time = "".join(char for char in subtext if char.isdecimal())
                    return time
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
    
    def linuxPing(host):
        param = '-c'
        command = ['ping', param, '1', host]
        return subprocess.call(command,stdout=subprocess.PIPE) == 0

    if operatingSystem=='windows': return windowsPing(host)
    if operatingSystem =='linux': return linuxPing(host)
    print("There is no ping command defined for this operating system ","(",operatingSystem,")")
    logging.CRITICAL("Operating System ",operatingSystem,"has not been specified in ding's ping function")
    sys.exit()

def printStatus(host,sent,received):
    if operatingSystem=='windows':
        os.system('cls')
        #sys.stdout.write("\033[K")
    percentage_received = (100*received/(sent if sent>0 else 1))
    print("\r","Pinging",host,":\n Received/sent ",received,"/",sent,'(',str(int(percentage_received)),'% )')

def printLatencyChart(resultv):
    results_to_plot = 10
    def printLatencyLine(result):
        if result[0]==0:
            print(result[1],"ms",end="")
            print(" "*(6-len(str(result[1]))),end="")
            print("|","▇"*int((int(result[1])+10)/20),end="")
            print()
        if result[0]==1:
            print("No response")
        if result[0]==2:
            print("Host not found")        
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
    cont=True
    sent=0
    received=0
    resultv=[]
    
    logging.debug("Parsing command line arguments... \n")
    argv=sys.argv
    argv = parseArgs()
    logging.debug("Done")
    
    logging.debug("Starting main loop...")
    while cont == True:
        
        response = ping(argv.host)
        sent+=1
        print(response.result)
        if response.result==0:
            playSound()
            received+=1
        if response.result==2:
            print("Host",argv.host,"not found")

        resultv.append([response.result, response.latency])
        printStatus(argv.host,sent,received)
        printLatencyChart(resultv)
        time.sleep(2)
        
    
if __name__ == "__main__":
    ding()