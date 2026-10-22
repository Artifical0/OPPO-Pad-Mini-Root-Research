"""Verify Android whole-file OTA signatures and ZIP entry CRCs offline.
Trust limitation: the signer certificate is compared with a supplied known package;
this does not read the disconnected device's installed OTA trust store.
"""
import hashlib
import json
import pathlib
import struct
import zipfile
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, utils
from cryptography.hazmat.primitives.serialization import pkcs7


def require(condition, message):
    if not condition: raise ValueError(message)


def der(data, pos=0):
    begin = pos
    require(pos + 2 <= len(data), "DER truncated")
    tag = data[pos]; first = data[pos + 1]; pos += 2
    if first & 128:
        width = first & 127
        require(0 < width <= 4 and pos + width <= len(data), "DER length")
        size = int.from_bytes(data[pos:pos + width], "big"); pos += width
    else: size = first
    require(pos + size <= len(data), "DER boundary")
    return tag, data[pos:pos + size], data[begin:pos + size], pos + size


def children(data):
    pos = 0; result = []
    while pos < len(data):
        tag, value, raw, pos = der(data, pos); result.append((tag, value, raw))
    return result


def oid(data):
    require(data, "Empty OID")
    values = [data[0] // 40, data[0] % 40]; value = 0
    for b in data[1:]:
        value = (value << 7) | (b & 127)
        if b < 128: values.append(value); value = 0
    return ".".join(map(str, values))


def verify(path):
    initial = path.stat()
    with path.open("rb") as stream:
        stream.seek(-6, 2); footer = stream.read(6)
        signature_start, magic, comment_size = struct.unpack("<HHH", footer)
        require(magic == 65535 and 6 < signature_start <= comment_size, "Android signature footer missing")
        stream.seek(-22 - comment_size, 2); eocd = stream.read(22 + comment_size)
        require(eocd[:4] == b"PK\x05\x06" and eocd.find(b"PK\x05\x06", 4) < 0, "Invalid/multiple EOCD")
        require(struct.unpack_from("<H", eocd, 20)[0] == comment_size, "EOCD comment length mismatch")
        encoded = eocd[-signature_start:-6]
    outer = children(der(encoded)[1])
    require(oid(outer[0][1]) == "1.2.840.113549.1.7.2" and outer[1][0] == 160, "Not PKCS7 SignedData")
    signed = children(der(outer[1][1])[1])
    signers = children(signed[-1][1]); require(len(signers) == 1, "Expected one signer")
    signer = children(signers[0][1])
    require(oid(children(signer[2][1])[0][1]) == "2.16.840.1.101.3.4.2.1", "Expected SHA256 digest")
    certs = pkcs7.load_der_pkcs7_certificates(encoded); require(len(certs) == 1, "Expected one OTA certificate")
    cert = certs[0]; key = cert.public_key()
    certificate_hash = cert.fingerprint(hashes.SHA256()).hex()
    signed_length = initial.st_size - comment_size - 2
    spans = []
    with zipfile.ZipFile(path) as archive, path.open("rb") as stream:
        for entry in archive.infolist():
            require(entry.compress_type == zipfile.ZIP_STORED, "CRC streaming currently supports stored entries")
            stream.seek(entry.header_offset); local = stream.read(30)
            fn, extra = struct.unpack_from("<HH", local, 26)
            begin = entry.header_offset + 30 + fn + extra
            spans.append({"name": entry.filename, "begin": begin, "end": begin + entry.file_size, "crc": 0, "expected": entry.CRC})
    whole, digest = hashlib.sha256(), hashlib.sha256()
    position = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            whole.update(chunk)
            if position < signed_length: digest.update(chunk[:min(len(chunk), signed_length - position)])
            for span in spans:
                left = max(position, span["begin"]); right = min(position + len(chunk), span["end"])
                if right > left: span["crc"] = zlib.crc32(chunk[left - position:right - position], span["crc"])
            position += len(chunk)
    require(position == initial.st_size, "File size changed")
    for span in spans: require(span["crc"] & 4294967295 == span["expected"], "ZIP CRC mismatch: " + span["name"])
    if signer[3][0] == 160:
        attributes = signer[3]
        message_digest = None
        for attr in children(attributes[1]):
            values = children(attr[1])
            if oid(values[0][1]) == "1.2.840.113549.1.9.4": message_digest = children(values[1][1])[0][1]
        require(message_digest == digest.digest(), "PKCS7 content digest mismatch")
        key.verify(signer[5][1], b"\x31" + attributes[2][1:], padding.PKCS1v15(), hashes.SHA256())
    else:
        require(signer[4][0] == 4, "Missing RSA signature")
        key.verify(signer[4][1], digest.digest(), padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
    final = path.stat()
    require(initial.st_size == final.st_size and initial.st_mtime_ns == final.st_mtime_ns, "Package changed during verification")
    return {"path": str(path), "bytes": initial.st_size, "sha256": whole.hexdigest(), "whole_file_signature_valid": True,
            "all_entry_crcs_valid": True, "signer_certificate_sha256": certificate_hash, "signer_subject": cert.subject.rfc4514_string(),
            "signer_public_key_sha256": hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),
            "device_ota_trust_store_checked": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=pathlib.Path); parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    result = verify(args.package)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
