# podman-proxy

A super simple dynamic proxy for rootless podman development.

## How to use

Run it:

    pipenv run python podproxy.py <YOUR_HOST_IP>

## What does it do

Podman proxy will do the following:

- At startup it will go through the running containers and create virtual host
  configs for them.
- After startup, it will listen to podman events and update the virtual host
  configs accordingly.
- It will reload nginx when ever configs change

When you start your podman containers, specify a hostname and expose a port.
Podman proxy will config a virtual host with the specified hostname and reverse
proxy to the exposed port. You can specify the internal port without specifying
the external port to let podman chose the port `-p 80`. Podman proxy will grab
the random port from the container.

If you use subdomains of localhost (ie: `test.localhost`), you don't need to do
anything else, otherwise something like `dnsmasq` will be needed which is not
covered by this tool.

## Issues

- Currently if multiple ports are exposed, only the first port is proxied to.
- If multiple containers run in a pod without networking, only one port from
  this pod will work.

## Todos

- [ ] Create a proper package
- [ ] Create a systemd user unit
- [ ] Separate nginx related stuff to a separate module
- [ ] Expose a web dashboard on the default host and show current status
- [ ] Find a better way to run on port 80 without sysctl configuration
- [ ] Integrate with [Netavark](https://github.com/containers/netavark)
