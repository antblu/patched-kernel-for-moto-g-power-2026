"""Relay the lab K3s API without terminating TLS."""

import argparse
import ipaddress
import selectors
import socket
import socketserver
import threading


def endpoint(value):
    try:
        address, port = value.rsplit(":", 1)
        address = address.strip("[]")
        ip = ipaddress.ip_address(address)
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError
        return str(ip), port
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected an IP address and port") from error


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        client_ip = self.client_address[0]
        if client_ip != "127.0.0.1":
            try:
                if ipaddress.ip_address(client_ip) not in self.server.phones:
                    return
            except ValueError:
                return
        try:
            with socket.create_connection(self.server.upstream, timeout=5) as upstream:
                with selectors.DefaultSelector() as ready:
                    ready.register(self.request, selectors.EVENT_READ, upstream)
                    ready.register(upstream, selectors.EVENT_READ, self.request)
                    while True:
                        events = ready.select(60)
                        if not events:
                            continue
                        for key, _ in events:
                            data = key.fileobj.recv(65536)
                            if not data:
                                return
                            key.data.sendall(data)
        except OSError:
            return


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(listen_ep, upstream_ep, phones):
    with Server(listen_ep, Relay, bind_and_activate=False) as server:
        server.phones = phones
        server.upstream = upstream_ep
        server.server_bind()
        server.server_activate()
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, nargs="+", type=endpoint)
    parser.add_argument("--upstream", required=True, type=endpoint)
    parser.add_argument("--phone", required=True, nargs="+", type=ipaddress.IPv4Address)
    args = parser.parse_args()
    phones = set(args.phone)
    threads = []
    for ep in args.listen:
        t = threading.Thread(target=serve, args=(ep, args.upstream, phones), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
