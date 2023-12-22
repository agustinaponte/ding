# ding
 Like ping, but with sound
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
____###______________________###____________Like_ping,_but_with_sound__________
___.############################.______________________________________________
+##################################+___________________________________________
##.__________##########___________##___________________________________________
+###############.__.+##############+___________________________________________
_____________##########________________________________________________________
________________####___________________________________________________________
# What does ding do
By default, ding pings a host and plays a sound each time it receives a response and shows a small chart with latency.

# Arguments

`-h | --help`
Shows help and exits

`-c <thisMany> | --count <thisMany>
Sets the amount of ping requests to `<thisMany>` and exits when done. By default, ding pings indefinetely.

` -l | --lost`
Only plays a sound only if some responses are not received. Helpful to get notified when a host is not reachable.

`-v | --verbose`
Prints additional information

# Algorithm
Checks for operating system and admin/root privileges

If admin/root:
	Uses lower level ping methods (not implemented yet)
Else:
	Uses each os's ping binary (Linux not implemented yet)

# ToDo

Use lower level ping methods if admin/root

Packet size: Accept an argument to specify packet size

Display latency and responses in a convenient way

Show uptime and aditional information about the host

Work with multiple hosts
# Examples:

```
ding | Plays sound and shows help
ding <host> | Pings a host and plays sound for every response
ding -d <host> | Pings a host and plays a sound when some responses do not arrive
```
