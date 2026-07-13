"""SSDP/mDNS discovery and DNS wire-format helpers for cast targets."""

from __future__ import annotations

import socket
import struct
from typing import Literal
from urllib.parse import urlsplit

from .models import CastDiscoveryTarget


def _parse_ssdp_response(raw_response: bytes) -> dict[str, str]:
    try:
        text = raw_response.decode("utf-8", errors="ignore")
    except Exception:
        return {}
    headers: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _discover_dlna_targets(timeout_seconds: float = 1.0) -> list[CastDiscoveryTarget]:
    message = "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 1",
            "ST: urn:schemas-upnp-org:device:MediaRenderer:1",
            "",
            "",
        ]
    ).encode("ascii")
    targets: list[CastDiscoveryTarget] = []
    seen: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendto(message, ("239.255.255.250", 1900))
        while True:
            try:
                raw_response, address = sock.recvfrom(8192)
            except TimeoutError:
                break
            except OSError:
                break
            headers = _parse_ssdp_response(raw_response)
            location = headers.get("location")
            usn = headers.get("usn") or headers.get("usn".upper())
            target_key = usn or location or address[0]
            if not target_key or target_key in seen:
                continue
            seen.add(target_key)
            parsed_location = urlsplit(location or "")
            host = parsed_location.hostname or address[0]
            port = parsed_location.port
            server_name = headers.get("server") or headers.get("st") or "DLNA Renderer"
            targets.append(
                CastDiscoveryTarget(
                    id=f"dlna:{target_key}",
                    name=server_name,
                    protocol="dlna",
                    host=host,
                    port=port,
                    supports_remote_control=False,
                    enabled=True,
                    discovered=True,
                    discovery_source="ssdp",
                )
            )
    return targets


def _encode_dns_name(name: str) -> bytes:
    return b"".join(
        bytes([len(part)]) + part.encode("utf-8")
        for part in name.rstrip(".").split(".")
    ) + b"\x00"


def _read_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    original_offset = offset
    seen_offsets: set[int] = set()
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if pointer in seen_offsets:
                break
            seen_offsets.add(pointer)
            if not jumped:
                original_offset = offset + 2
            offset = pointer
            jumped = True
            continue
        offset += 1
        labels.append(data[offset : offset + length].decode("utf-8", errors="ignore"))
        offset += length
    return ".".join(label for label in labels if label), original_offset if jumped else offset


def _build_mdns_query(service_name: str) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    question = _encode_dns_name(service_name) + struct.pack("!HH", 12, 1)
    return header + question


def _parse_mdns_response(data: bytes) -> list[dict]:
    if len(data) < 12:
        return []
    _, _, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", data[:12])
    offset = 12
    for _ in range(qdcount):
        _, offset = _read_dns_name(data, offset)
        offset += 4

    records = []
    for _ in range(ancount + nscount + arcount):
        name, offset = _read_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        record_type, record_class, ttl, rdlength = struct.unpack(
            "!HHIH", data[offset : offset + 10]
        )
        offset += 10
        rdata_offset = offset
        offset += rdlength
        if offset > len(data):
            break

        value = None
        if record_type in {12, 33}:  # PTR, SRV
            if record_type == 33 and rdata_offset + 6 <= len(data):
                _, _, port = struct.unpack("!HHH", data[rdata_offset : rdata_offset + 6])
                target, _ = _read_dns_name(data, rdata_offset + 6)
                value = {"port": port, "target": target}
            else:
                target, _ = _read_dns_name(data, rdata_offset)
                value = target
        elif record_type == 1 and rdlength == 4:
            value = socket.inet_ntoa(data[rdata_offset:offset])
        elif record_type == 16:
            chunks = []
            cursor = rdata_offset
            while cursor < offset:
                chunk_len = data[cursor]
                cursor += 1
                chunks.append(data[cursor : cursor + chunk_len].decode("utf-8", errors="ignore"))
                cursor += chunk_len
            value = chunks

        records.append(
            {
                "name": name,
                "type": record_type,
                "class": record_class,
                "ttl": ttl,
                "value": value,
            }
        )
    return records


def _discover_mdns_service_targets(
    *,
    service_name: str,
    protocol: Literal["chromecast", "airplay"],
    timeout_seconds: float = 1.0,
) -> list[CastDiscoveryTarget]:
    query = _build_mdns_query(service_name)
    records: list[dict] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout_seconds)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(query, ("224.0.0.251", 5353))
        while True:
            try:
                raw_response, _ = sock.recvfrom(9000)
            except TimeoutError:
                break
            except OSError:
                break
            records.extend(_parse_mdns_response(raw_response))

    ptr_names = {
        str(record["value"])
        for record in records
        if record["type"] == 12
        and isinstance(record.get("value"), str)
        and service_name in record["name"]
    }
    srv_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 33 and isinstance(record.get("value"), dict)
    }
    address_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 1 and isinstance(record.get("value"), str)
    }
    txt_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 16 and isinstance(record.get("value"), list)
    }

    targets: list[CastDiscoveryTarget] = []
    for instance_name in sorted(ptr_names):
        srv_value = srv_records.get(instance_name) or {}
        target_host = srv_value.get("target") if isinstance(srv_value, dict) else None
        port = srv_value.get("port") if isinstance(srv_value, dict) else None
        host = address_records.get(target_host) or target_host
        display_name = instance_name.split("._", 1)[0].replace("\\032", " ")
        txt_values = txt_records.get(instance_name) or []
        for item in txt_values:
            if item.startswith("fn=") and item[3:]:
                display_name = item[3:]
                break
        target_id = f"{protocol}:{instance_name}"[:100]
        targets.append(
            CastDiscoveryTarget(
                id=target_id,
                name=display_name or protocol.title(),
                protocol=protocol,
                host=host,
                port=port,
                supports_remote_control=False,
                enabled=True,
                discovered=True,
                discovery_source="mdns",
            )
        )
    return targets


def _discover_mdns_targets(timeout_seconds: float = 1.0) -> list[CastDiscoveryTarget]:
    return [
        *_discover_mdns_service_targets(
            service_name="_googlecast._tcp.local",
            protocol="chromecast",
            timeout_seconds=timeout_seconds,
        ),
        *_discover_mdns_service_targets(
            service_name="_airplay._tcp.local",
            protocol="airplay",
            timeout_seconds=timeout_seconds,
        ),
    ]
