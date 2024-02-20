# ding
 Like ping, but with sound
# What does ding do
By default, ding pings a host and plays a sound each time it receives a response. It also displays latencies in a user friendly way.

# Arguments

`-h | --help`
Shows help and exits

# Examples:

```
ding <host> | Pings a host and plays sound for every response
```

# ToDo/Ideas
Check for admin/root privileges

If admin/root: Use lower level ping methods
Else: Use each os's ping binary


`-c <thisMany> | --count <thisMany>
Sets the amount of ping requests to `<thisMany>` and exits when done. By default, ding pings indefinetely.

` -l | --lost`
Only plays a sound only if some responses are not received. Helpful to notice when a host is not reachable.

Packet size: Accept an argument to specify packet size

Show uptime and aditional information about the host

Work with multiple hosts
