# ding
 Like ping, but with sound
# What does ding do
By default, ding pings a host and plays a sound each time it receives a response. It also displays a small chart showing latency.

# Arguments

`-h | --help`
Shows help and exits


# ToDo
Check for admin/root privileges

If admin/root: Use lower level ping methods
Else: Use each os's ping binary


`-c <thisMany> | --count <thisMany>
Sets the amount of ping requests to `<thisMany>` and exits when done. By default, ding pings indefinetely.

` -l | --lost`
Only plays a sound only if some responses are not received. Helpful to get notified when a host is not reachable.

Use lower level ping methods if admin/root

Packet size: Accept an argument to specify packet size

Display latency and responses in a convenient way

Show uptime and aditional information about the host

Work with multiple hosts
# Examples:

```
ding <host> | Pings a host and plays sound for every response
```
