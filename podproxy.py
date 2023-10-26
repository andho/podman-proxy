import os
import sys
import subprocess
from collections import namedtuple
from datetime import datetime
import json
import pprint

from jinja2 import Environment, FileSystemLoader, select_autoescape

USAGE = "Usage: python podproxy.py <ip-address> [<port>]"

template_env = Environment(
        loader=FileSystemLoader('templates'))
template = template_env.get_template('nginx.jinja2')

pp = pprint.PrettyPrinter(indent=2)

HOST_IP = "0.0.0.0" # you should pass this as an argument for now
CONFIG_DIR = os.path.join(os.getcwd(), 'nginx')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'default.conf')
PROXY_NAME = 'podproxy-nginx'
PROXY_PORT = '80'
NETWORK = 'podproxy'

ContainerConfig = namedtuple(
        'ContainerConfig',
        ['port', 'upstream', 'hostname', 'name', 'status'])
EventInfo = namedtuple('EventInfo', ['datetime', 'type', 'event', 'id',
                                     'container_image', 'container_name',
                                     'container_app'])

configs = {}
name_to_hostname = {}
hostname_containers = {}

command = ["podman", "events"]

def parse_event(event_line):
    index = event_line.find("(")

    event_info = event_line[0:index-1]
    event_info_list = event_info.split(" ")

    event_type = event_info_list[4]
    event_name = event_info_list[5]
    if event_type != 'container':
        return None

    event_whitelist = ['died', 'start']
    if event_name not in event_whitelist:
        return None

    try:
        event_datetime = datetime.fromisoformat(
            "%s %s%s:00" % (event_info_list[0],event_info_list[1][0:12],event_info_list[3]))
    except Exception as e:
        print(event_info_list)
        return None

    container_info = event_line[index+1:-1]
    container_info_list = [item.split("=") for item in container_info.split(", ")]
    try:
        container_info = {item[0]:item[1] for item in container_info_list}
    except Exception as e:
        print(container_info_list)
        return None

    return EventInfo(
            datetime=event_datetime,
            type=event_info_list[4],
            event=event_info_list[5],
            id=event_info_list[6],
            container_name=container_info['name'],
            container_image=container_info['image'],
            container_app=container_info['app'] if 'app' in container_info else None)

def get_container_info(container_name):
    print("Getting container info for %s" % (container_name,))
    process = subprocess.run(["podman", "inspect", container_name],
                             capture_output=True)

    container_dict = json.loads(process.stdout)

    return container_dict

def update_configs(container_info):
    container_name = container_info['Name']
    if container_name == 'podproxy-nginx':
        return

    hostname = container_info['Config']['Hostname']
    status = container_info['State']['Status']
    
    port_dict = container_info['NetworkSettings']['Ports']
    ports = [port['HostPort'] for ports in port_dict.values() if ports is not None for port in ports]
    if len(ports) > 0:
        upstream = HOST_IP
        print("{}: Using exposed port {}".format(container_name, ports[0]))
    else:
        # there are no exposed ports, so lets try defined ports
        ports = [port.split('/')[0] for port in port_dict.keys()]

        if len(ports) == 0:
            print("No exposed/defined ports on {}".format(container_name))
            return

        if not is_proxy_network_connected(container_info):
            print("Not connected to {} network or have exposed ports".format(NETWORK))
            return

        print("{}: Using internal port {}".format(container_name, ports[0]))

        upstream = get_upstream(container_info)

    config = ContainerConfig(
            port=ports[0],
            upstream=upstream,
            hostname=hostname,
            name=container_name,
            status=status)

    print("Hostname %s added" % (config.hostname,))
    configs[config.hostname] = config
    name_to_hostname[config.name] = config.hostname
    
    if config.hostname not in hostname_containers:
        hostname_containers[config.hostname] = set()

    hostname_containers[config.hostname].add(config.name)

def get_upstream(container_info):
    aliases = container_info['NetworkSettings']['Networks'][NETWORK]['Aliases']

    hostname = container_info['Config']['Hostname']
    id = container_info['Id']
    
    for alias in aliases:
        if alias == hostname:
            return hostname

    for alias in aliases:
        if alias in id:
            return alias

    return aliases[0]

def is_proxy_network_connected(container_info):
    if NETWORK in container_info['NetworkSettings']['Networks']:
        return True

    return False

def remove_config(container_name):
    print("Removing config for container: %s" % (container_name,))
    if container_name not in name_to_hostname:
        return

    hostname = name_to_hostname[container_name]
    print("Matching hostname: %s" % (hostname,))

    if hostname not in hostname_containers:
        return

    hostname_containers[hostname].remove(container_name)

    if len(hostname_containers[hostname]) > 0:
        print("Other containers with same hostname remains")
        return

    print("All containers with hostname %s has been stopped" % (hostname,))

    if hostname not in configs:
        return

    configs.pop(hostname)
    print("Removed hostname %s from configs" % (hostname,))

def update_config_file():
    data = {'server': []}

    for config in configs.values():
        data["upstream %s" % (config.hostname,)] = [
                {'server': "%s:%s" % (config.upstream, config.port)}]
        data['server'].append({
            'server_name': config.hostname,
            'location /': {
                'proxy_pass': 'http://%s' % (config.hostname,),
            },
            'listen': [80],
        })

    rendered_config = template.render(nginx_config=data)

    print("Config updated")

    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        f.write(rendered_config)

def reload_nginx():
    reload_process = subprocess.run(
            ["podman", "exec", "podproxy-nginx", "nginx", "-s", "reload"],
            capture_output=True)
    print(reload_process.stdout)

def get_containers():
    process = subprocess.run(
            ['podman', 'ps', '-q'],
            capture_output=True,
            text=True)

    containers = process.stdout.strip().split("\n")

    for container in containers:
        container_info = get_container_info(container)
        update_configs(container_info[0])

def start_proxy():
    proxy_info = get_container_info('podproxy-nginx')

    if len(proxy_info) > 0:
        print("Proxy container already exists")
        if proxy_info[0]['State']['Status'] != 'running':
            process = subprocess.run(['podman', 'start', PROXY_NAME],
                                     capture_output=True,
                                     text=True)
            
            if process.returncode != 0:
                print(process.stderr)
                raise Exception("Could not start existing proxy container")
    else:
        create_proxy()

    proxy_info = get_container_info('podproxy-nginx')
    port_dict = proxy_info[0]['NetworkSettings']['Ports']
    ports = [port['HostPort'] for ports in port_dict.values() for port in ports]
    print("Proxy running on port %s" % (ports[0],))


def create_proxy():
    create_proxy_network()

    config_map = "%s:%s" % (CONFIG_DIR, '/etc/nginx/conf.d')
    process_args = ['podman', 'run', '-d', '--rm', '--name', 'podproxy-nginx',
                    '-p', '%s:80' % (PROXY_PORT,), '-v', config_map, 'nginx']
    process = subprocess.run(process_args, capture_output=True, text=True)

    if process.returncode == 0:
        return

    if 'cannot expose privileged port %s' % (PROXY_PORT,) not in process.stderr:
        print(process.stderr)
        raise Exception("Unable to start proxy. %s" % (process.returncode,))

    print("Could not start with port {}. Going to use a random port.".format(PROXY_PORT))

    subprocess.run(['podman', 'rm', PROXY_NAME])

    print("Could not start proxy on port %s" % (PROXY_PORT,))

    process_args = ['podman', 'run', '-d', '--name', 'podproxy-nginx',
                              '-p', '80', '-v', config_map, '--net', NETWORK,
                              'nginx']
    process = subprocess.run(process_args, capture_output=True, text=True)

    if process.returncode != 0:
        print(process.stderr)
        raise Exception("Unable to start proxy. %s" % (process.returncode,))

def create_proxy_network():
    # checking if network exists
    process_args = ['podman', 'network', 'exists', NETWORK]
    process = subprocess.run(process_args, text=True)

    if process.returncode == 0:
        return

    process_args = ['podman', 'network', 'create', NETWORK]
    process = subprocess.run(process_args, text=True)

    if process.returncode != 0:
        print(process.stderr)
        raise Exception("Unable to create podman network for proxy")

    print("{} network created for proxy".format(NETWORK))

def main(args):
    if len(args) == 0:
        print(USAGE)
        return

    global HOST_IP
    global PROXY_PORT
    HOST_IP = args[0]
    
    if len(args) >= 2:
        PROXY_PORT = args[1]

    print("Starting proxy")
    start_proxy()

    print("Creating vhosts for any existing containers")
    containers = get_containers()
    update_config_file()
    reload_nginx()

    print("Now listening for any podman events")
    process = subprocess.Popen(command, stdout=subprocess.PIPE)

    for line in process.stdout:
        print(line)
        event = parse_event(line.decode().strip())
        if event is None:
            print("Ignoring event")
            continue

        if event.event == 'died' and event.type == 'container':
            remove_config(event.container_name)
        else:
            container_info = get_container_info(event.container_name)
            if len(container_info) == 0:
                print("Container doesn't exist")
                remove_config(event.container_name)
            else:
                update_configs(container_info[0])

        update_config_file()
        reload_nginx()

if __name__ == "__main__":
    if sys.argv[0] == 'podproxy.py':
        args = sys.argv[1:]
    else:
        args = sys.argv
    main(args)
