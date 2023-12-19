# ding
 Like ping, but with sound


# What does ding do
By default, ding pings a host and plays a sound each time it receives a response.



# Arguments

`-h | --help`
Shows help and exits

`-c <thisMany> | --count <thisMany`
Sets the amount of ping requests to `<thisMany>` and exits when done. By default, ding pings indefinetely

` -l | --lost`
Plays a sound only if some responses are not received

`-v | --verbose`
Prints additional information

# Algorithm
Checks for operating system and admin/root privileges

If admin/root:
	Uses lower level ping methods
Else:
	Uses each os's ping binary



# ToDo

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
