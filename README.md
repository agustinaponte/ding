# ding
 Like ping, but with sound

____________.###+..+###-__________________________________________________________
_____________+###..###+___________________________________________________________
_________.+######..#######._________________█████__███_________________________
________+#######.__.########_________________░░███__░░░_______________________________
_______#####.__________.#####___________███████__████__████████____███████
_______###._______________+##_________███_░░__███___░░███____░░███__░███__███__░░███
______+##.________________.##+________░███_░__███__░_███__░__███__░███_░_███_░_███
______###__________________###________░███_░__███__░_███____░███__░███__░███_░_███
______##.__________________.##.________░░████████_█████__████_████__███████
_____.##.__________________.##.__________________________░░░░░░░░_░░░░░_░░░░_░░░░░__░░░░░________________███
_____###____________________###__________________________________________███_░███
_____##+____________________+##___________________________________░░________██████
____.##.____________________.##.___________________________________░░░░░░_______________
____###______________________###____________Like_ping,_but_with_better_sound______
___.############################._________________________________________________
+##################################+______________________________________________
##.__________##########___________##______________________________________________
+###############.__.+##############+______________________________________________
_____________##########___________________________________________________________
________________####______________________________________________________________



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
