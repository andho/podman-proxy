# podman-proxy

A super simple dynamic proxy for rootless podman development.

## How to use

Run it:

    pipenv run python podproxy.py <YOUR_HOST_IP> [<HOST_PORT>]

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

### Proxy network

Podproxy will create a network named 'podproxy'. Any containers that use the
'podproxy' network and has a port defined in it's config (`PORT` specified in
Dockerfile), then podproxy will proxy to that container through the podproxy
network. This allows you to create containers without exposing ports on the
host. Once again, hostname has to be defined on the container for podproxy to
proxy to the container.

## Proxy port

Podproxy will try to run on port 80 unless another port is specified as the 3rd
second argument after `YOUR_HOST_IP`. Normally podman doesn't have permission to
ports lower than ???. If using the specified port fails, podproxy will start on
a random port.

## HTTPS

Podproxy currently does not support https as for most cases, http will work for
development purpose. But for those rare cases that https is needed for
development, https support is planned for the future.

### Test container

2 test compose.yml folders has been added for testing purposes.

## Practical

When you create a podman container, you can specify a hostname for the container
using `--hostname` flag. If using compose file, specify `hostname` in the
service. Podproxy will then proxy requests to that hostname, to that container.

For example, if you start a container with hostname `app1.localhost`, then you
can make a request to http://app1.localhost and podproxy will proxy that request
to the exposed/specified port on that container. if you use `*.localhost` it
will work out of the box. But if you hostname is something like `app1.dev` then
you will need to tell you system to resolve `app1.dev` to `127.0.0.1` (or any
loopback address). You can do this using `/etc/hosts` file:

    sudo sh -c "echo '127.0.0.1 app1.dev' >> /etc/hosts"

Or you can use dnsmasq to resolve any `*.dev` domain to localhost (probably) but
I haven't checked on this.

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
- [X] Integrate with [Netavark](https://github.com/containers/netavark)
