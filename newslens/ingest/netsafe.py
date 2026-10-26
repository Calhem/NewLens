"""Network safety: which addresses NewsLens may connect to, checked at the moment of connecting.

Every TCP connection goes through SafeBackend. It resolves the host name itself, rejects the
whole host if ANY address is prohibited, then connects to the address it just checked. The
TLS layer still verifies the certificate against the host name. Because the check and the
connection use the same resolution, a DNS answer can't change in between (DNS rebinding), and
redirects get no special treatment: each new connection is checked again.
"""

import concurrent.futures
import ipaddress
import socket
from dataclasses import dataclass, field

import httpcore

NAT64 = ipaddress.ip_network("64:ff9b::/96")
SHARED = ipaddress.ip_network("100.64.0.0/10")   # carrier-grade NAT; not covered by is_private


class BlockedAddress(Exception):
    """A host resolved to an address NewsLens must never connect to."""


def _embedded_ipv4(ip):
    """IPv4 addresses hidden inside an IPv6 address (mapped, 6to4, Teredo, NAT64)."""
    if ip.version != 6:
        return []
    found = []
    if ip.ipv4_mapped:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour:
        found.append(ip.sixtofour)
    if ip.teredo:
        found.extend(ip.teredo)
    if ip in NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def prohibited(ip):
    """True for any address that isn't ordinary public internet: loopback, private, link-local
    (including cloud metadata at 169.254.169.254), multicast, reserved, unspecified, shared."""
    ip = ipaddress.ip_address(ip)
    for inner in _embedded_ipv4(ip):
        if prohibited(inner):
            return True
    return (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
            or (ip.version == 4 and ip in SHARED))


@dataclass(frozen=True)
class AddressPolicy:
    """Which addresses and ports may be used. The default is the strict production policy.

    `test_addresses` exists only so tests can reach a local test server; production code never
    sets it, and a test checks the default stays empty.
    """
    allowed_ports: frozenset = frozenset({80, 443})
    test_addresses: frozenset = frozenset()

    def check(self, ip, port):
        if port not in self.allowed_ports:
            raise BlockedAddress(f"port {port} is not allowed")
        if str(ipaddress.ip_address(ip)) in self.test_addresses:
            return
        if prohibited(ip):
            raise BlockedAddress(f"{ip} is not a public internet address")


STRICT = AddressPolicy()


def system_resolver(host):
    """All addresses the operating system gives for a host name."""
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


@dataclass
class SafeBackend(httpcore.NetworkBackend):
    policy: AddressPolicy = STRICT
    resolver: object = system_resolver
    dns_timeout: float = 5.0
    _inner: httpcore.NetworkBackend = field(default_factory=httpcore.SyncBackend)

    def resolve(self, host):
        host = host.strip("[]")
        try:
            return [str(ipaddress.ip_address(host))]   # an address written in the URL
        except ValueError:
            pass
        # getaddrinfo has no timeout of its own, so it runs in a worker thread we stop waiting
        # for. (The thread may finish later in the background; it can't connect to anything.)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            addresses = pool.submit(self.resolver, host).result(timeout=self.dns_timeout)
        except concurrent.futures.TimeoutError:
            raise httpcore.ConnectTimeout(f"DNS lookup for {host} timed out")
        except OSError as error:
            raise httpcore.ConnectError(f"DNS lookup for {host} failed: {error}")
        finally:
            pool.shutdown(wait=False)        # don't wait for a stuck lookup
        if not addresses:
            raise httpcore.ConnectError(f"{host} has no addresses")
        return addresses

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = self.resolve(host)
        for ip in addresses:                 # every address must be allowed, not just one
            self.policy.check(ip, port)
        return self._inner.connect_tcp(addresses[0], port, timeout=timeout,
                                       local_address=local_address, socket_options=socket_options)

    def connect_unix_socket(self, *args, **kwargs):
        raise BlockedAddress("unix sockets are never used")

    def sleep(self, seconds):
        self._inner.sleep(seconds)
