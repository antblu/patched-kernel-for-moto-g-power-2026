"""Reconcile IPv4 routing for the K3s worker on Android's shared network."""

import argparse
import ipaddress
import json
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time


PROTOCOL = "242"
UID_OWNER_MAP = "/sys/fs/bpf/netd_shared/map_netd_uid_owner_map"
# UID 65532 only. The little-endian value is {iif: 0, rule: BACKGROUND_MATCH}.
UID_KEY = ("key", "hex", "fc", "ff", "00", "00")
UID_VALUE = ("00", "00", "00", "00", "00", "10", "00", "00")
PRIORITIES = (100, 101, 102)
FORWARDING = (
    Path("/proc/sys/net/ipv4/ip_forward"),
    Path("/proc/sys/net/bridge/bridge-nf-call-iptables"),
    Path("/proc/sys/net/ipv4/conf/all/route_localnet"),
    Path("/proc/sys/net/ipv4/conf/default/route_localnet"),
)


def ip(*args, read=False):
    command = ["ip", "-4", "-N"]
    if read:
        command.append("-j")
    result = subprocess.run(command + list(args), check=True, capture_output=read, text=True)
    if read:
        return json.loads(result.stdout)


def rule_args(priority, selectors, table):
    return ("priority", str(priority), *selectors, "lookup", str(table), "protocol", PROTOCOL)


def reconcile(priority, selectors, table, owned):
    expected = dict(zip(selectors[::2], selectors[1::2]))
    if len(owned) == 1 and table is not None:
        rule = owned[0]
        actual = {key: f"{rule[field]}/{rule.get(field + 'len', 32)}"
                  for key, field in (("from", "src"), ("to", "dst"))
                  if rule.get(field) not in (None, "all")}
        if "iif" in rule:
            actual["iif"] = rule["iif"]
        if str(rule.get("table")) == str(table) and actual == expected:
            return

    for rule in owned:
        ip("rule", "del", "priority", str(priority), "protocol", PROTOCOL)
    if table is not None:
        ip("rule", "add", *rule_args(priority, selectors, table))


def reconcile_nat(rule, remove, first_comment=None):
    command = ("iptables-legacy", "-w", "5", "-t", "nat")
    probe = subprocess.run((*command, "-C", *rule), capture_output=True, text=True)
    if probe.returncode not in (0, 1):
        probe.check_returncode()
    if probe.returncode == 0:
        if not remove and not first_comment:
            return
        if not remove:
            rules = subprocess.check_output((*command, "-S", rule[0]), text=True)
            first_rule = next((line for line in rules.splitlines() if line.startswith("-A ")), "")
            if first_comment in shlex.split(first_rule):
                return
        subprocess.run((*command, "-D", *rule), check=True)
    if not remove:
        subprocess.run((*command, "-I" if first_comment else "-A", *rule), check=True)


def reconcile_relay(args, remove):
    source, target = args.relay
    destination = ("-j", "DNAT", "--to-destination", f"{target[0]}:{target[1]}")
    reconcile_nat((
        "OUTPUT", "-d", str(source[0]), "-p", "tcp", "--dport", str(source[1]),
        "-m", "owner", "--uid-owner", "0", "-m", "comment", "--comment",
        "vegas26-k3s-lab-api", *destination,
    ), remove)
    if not target[0].is_loopback:
        target_table = 52 if target[0] in ipaddress.IPv4Network("100.64.0.0/10") else 254
        for priority, selector, tbl in ((99, ("to", str(source[0])), 254), (98, ("to", str(target[0])), target_table)):
            snapshots = ip("rule", "show", "priority", str(priority), read=True)
            if not remove and any(str(r.get("protocol")) != PROTOCOL for r in snapshots):
                raise RuntimeError(f"Routing priority {priority} is already in use")
            owned = [r for r in snapshots if str(r.get("protocol")) == PROTOCOL]
            reconcile(priority, selector, None if remove else tbl, owned)
        overlay_dev = "tailscale0" if Path("/sys/class/net/tailscale0").exists() else "wg-k3s"
        if remove:
            subprocess.run(("ip", "-4", "route", "del", str(source[0]), "dev", overlay_dev), check=False, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(("ip", "-4", "route", "replace", str(source[0]), "dev", overlay_dev), check=True)
    if args.service_api:
        address, port = args.service_api
        comment = "vegas26-k3s-pod-api"
        # Handle this one Service before kube-proxy sends it to unreachable WSL NAT.
        reconcile_nat((
            "PREROUTING", "-i", "cni0", "-s", str(args.node_network), "-d", str(address),
            "-p", "tcp", "--dport", str(port), "-m", "comment", "--comment", comment,
            *destination,
        ), remove, first_comment=comment)


def configure(args, remove=False):
    rules = [
        (("to", str(args.pod_network)), 254),
        (("to", str(args.service_network)), 254),
        (("from", str(args.node_network), "iif", "cni0"), None),
    ]
    if not remove:
        links = ip("link", "show", read=True)
        tables = set()
        if any(link["ifname"] == args.wifi for link in links):
            routes = ip("route", "show", "table", "all", "default", "dev", args.wifi, read=True)
            tables = {str(route["table"]) for route in routes if "table" in route}
        if len(tables) > 1:
            raise RuntimeError(f"Multiple default route tables for {args.wifi}")
        if tables:
            rules[2] = (rules[2][0], tables.pop())

    snapshots = [ip("rule", "show", "priority", str(priority), read=True)
                 for priority in PRIORITIES]
    if not remove:
        for priority, current in zip(PRIORITIES, snapshots):
            if any(str(rule.get("protocol")) != PROTOCOL for rule in current):
                raise RuntimeError(f"Routing priority {priority} is already in use")
    for priority, (selectors, table), current in zip(PRIORITIES, rules, snapshots):
        owned = [rule for rule in current if str(rule.get("protocol")) == PROTOCOL]
        reconcile(priority, selectors, None if remove else table, owned)
    if args.relay:
        reconcile_relay(args, remove)


def is_private_endpoint_ip(address):
    return address.is_private or address.is_loopback or address in ipaddress.IPv4Network("100.64.0.0/10")


def endpoint(value):
    try:
        address, port = value.rsplit(":", 1)
        address, port = ipaddress.IPv4Address(address), int(port)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected an IPv4 address and port") from error
    if not is_private_endpoint_ip(address) or not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Expected a private, CGNAT, or loopback IPv4 endpoint")
    return address, port


def uid_exemption_present():
    result = subprocess.run(
        ("bpftool", "-j", "map", "lookup", "pinned", UID_OWNER_MAP, *UID_KEY),
        capture_output=True, text=True,
    )
    # bpftool 7.5 emits JSON null and status 254 for an absent key.
    if result.returncode == 254 and result.stdout.strip() == "null":
        return None
    if result.returncode:
        result.check_returncode()
    return json.loads(result.stdout)


def reconcile_uid_exemption():
    if uid_exemption_present() is not None:
        return False
    subprocess.run((
        "bpftool", "map", "update", "pinned", UID_OWNER_MAP, *UID_KEY,
        "value", "hex", *UID_VALUE, "noexist",
    ), check=True)
    return True


def remove_uid_exemption():
    entry = uid_exemption_present()
    if isinstance(entry, dict) and (
        entry.get("formatted", {}).get("value") == {"iif": 0, "rule": 4096}
        or entry.get("value") == ["0x" + byte for byte in UID_VALUE]
    ):
        subprocess.run(("bpftool", "map", "delete", "pinned", UID_OWNER_MAP, *UID_KEY), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "remove", "watch"))
    parser.add_argument("pod_network", type=ipaddress.IPv4Network)
    parser.add_argument("service_network", type=ipaddress.IPv4Network)
    parser.add_argument("node_network", type=ipaddress.IPv4Network)
    parser.add_argument("--wifi", default="wlan0")
    parser.add_argument("--relay", nargs=2, type=endpoint, metavar=("ADVERTISED", "RELAY"))
    parser.add_argument("--service-api", type=endpoint, metavar="CLUSTER_IP:PORT")
    parser.add_argument("--allow-uid-65532", action="store_true")
    args = parser.parse_args()
    if (
        not args.node_network.subnet_of(args.pod_network)
        or args.pod_network.overlaps(args.service_network)
        or not all(network.is_private and network.prefixlen >= 8 for network in (
            args.pod_network, args.service_network, args.node_network
        ))
    ):
        parser.error("Expected distinct private pod and service networks and a local PodCIDR")
    if args.service_api and (not args.relay or args.service_api[0] not in args.service_network):
        parser.error("The API Service relay requires a relay and a ClusterIP in the Service CIDR")

    if args.action != "watch":
        if args.allow_uid_65532:
            parser.error("The UID exemption is managed only by the watcher")
        configure(args, remove=args.action == "remove")
        return

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    signal.signal(signal.SIGINT, stop)
    previous_error = None
    saved_forwarding = {}
    owns_uid_exemption = False
    try:
        configure(args)
        for path in FORWARDING:
            if path.exists():
                saved_forwarding[path] = path.read_text().strip()
                if saved_forwarding[path] != "1":
                    path.write_text("1\n")
        while True:
            try:
                configure(args)
                if args.allow_uid_65532 and reconcile_uid_exemption():
                    owns_uid_exemption = True
                previous_error = None
            except (RuntimeError, subprocess.CalledProcessError) as error:
                message = str(error)
                if message != previous_error:
                    print(message, file=sys.stderr, flush=True)
                previous_error = message
            time.sleep(15)
    finally:
        try:
            if owns_uid_exemption:
                remove_uid_exemption()
        finally:
            try:
                configure(args, remove=True)
            finally:
                for path, value in saved_forwarding.items():
                    if value != "1" and path.read_text().strip() == "1":
                        path.write_text(value + "\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
