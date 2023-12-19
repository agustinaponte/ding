# -*- coding: utf-8 -*-
"""
Created on Mon Dec 18 22:46:04 2023
@author: Agustin Aponte

------------------------------------------------------------------------------------

Arguments:
    
    -h | --help
        Shows help and exits
    
    -c <thisMany> | --count <thisMany
        Sets the amount of ping requests to <thisMany> and exits when done. By default, ding pings indefinetely
        
    -l | --lost
        Plays a sound only if some responses are not received
        
    -v | --verbose
        Prints additional information to standard output
        
------------------------------------------------------------------------------------

Examples:
    
ding | Plays sound and shows help
ding <host> | Pings a host and plays sound for every response
ding -l <host> | Pings a host and plays a sound when some responses do not arrive
ding -v <host> | Pings host indefinitely playing a sound for every response, Verbose mode
ding -h | Shows help and exits
ding --help | Shows help and exits
ding -c 5 | Sends five ping requests and plays a sound for every response


"""
import platform
import os
import subprocess
import sys
import getopt

def parseArgs():
    # Returns arguments
    
    # Default values
    arg_help = False
    arg_count = 0
    arg_lost = False
    arg_verbose = False
    arg_host = 'localhost'
    
    # Parse arguments
    try: 
    
    
    return arg_help, arg_count, arg_lost, arg_verbose, arg_host
    
def amAdmin():
    # Checks for root/admin privileges
    if os.lower()=='windows': return 
    if os.lower()=='linux': return 
    if os.lower() != ('windows' or 'linux'): print("Could not recognize operating system")
        
    
def play():
    print('\a\b', end='')
    
def ping(host):
    param = '-n' if platform.system().lower()=='windows' else '-c'
    command = ['ping', param, '1', host]
    return subprocess.call(command) == 0

#
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#

# Get OS information
operatingSystem = platform.system()

# Parse command line arguments:
parseArgs()
    




