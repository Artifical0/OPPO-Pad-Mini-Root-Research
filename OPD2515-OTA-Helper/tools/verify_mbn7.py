"""Verify observed OEM-only and QTI+OEM MBNv7 images offline.
Authority normalization is verified against both signed stock baselines: the
other authority's sig/chain sizes and metadata bytes are zeroed for signing.
Does not attest fused trust anchors or runtime compatibility.
"""
import hashlib
import struct

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from review import der_object, elf_segments, require, sha


def certificate_chain(blob):
    pos = 0; certs = []; raw = []
    while pos < len(blob) and blob[pos] == 48:
        obj = der_object(blob, pos); raw.append(obj); certs.append(x509.load_der_x509_certificate(obj)); pos += len(obj)
    require(len(certs) == 3 and (not any(blob[pos:]) or all(b == 255 for b in blob[pos:])), "Unexpected chain or padding")
    for i in range(2):
        require(certs[i].issuer == certs[i + 1].subject, "Issuer mismatch")
        certs[i + 1].public_key().verify(certs[i].signature, certs[i].tbs_certificate_bytes, ec.ECDSA(certs[i].signature_hash_algorithm))
    return certs, [sha(c) for c in raw]


def verify(data):
    segments, _ = elf_segments(data)
    choices = [s for s in segments if (s["flags"] >> 24) & 7 == 2]
    require(len(choices) == 1, "Unexpected hash segment count")
    hs = choices[0]; h = data[hs["off"]:hs["off"] + hs["size"]]
    f = list(struct.unpack_from("<10I", h))
    _, version, c, qm, om, ht, qs, qc, os, oc = f
    require(version == 7 and c == 24 and om == 224 and qm in (0, 224), "Unsupported metadata layout")
    require(ht == len(segments) * 48, "Unsupported hash table size")
    common_start, qmeta_start, ometa_start = 40, 40 + c, 40 + c + qm
    table_start = ometa_start + om; qsig_start = table_start + ht
    osig_start = qsig_start + qs + qc
    end = osig_start + os + oc
    require(end <= len(h) and (not any(h[end:]) or all(b == 255 for b in h[end:])), "Unexpected reserved hash-segment bytes")
    table = h[table_start:qsig_start]
    for s in segments:
        expected = bytes(48) if s is hs or s["size"] == 0 else hashlib.sha384(data[s["off"]:s["off"] + s["size"]]).digest()
        require(table[s["index"] * 48:(s["index"] + 1) * 48] == expected, "Signed segment hash mismatch")
    authorities = {}
    for name, start, size, chain_len, other_sig_idx, other_chain_idx, masked_start, masked_len in [
        ("QTI", qsig_start, qs, qc, 8, 9, ometa_start, om),
        ("OEM", osig_start, os, oc, 6, 7, qmeta_start, qm),
    ]:
        if not size:
            require(not chain_len, "Chain without signature"); continue
        signature = der_object(h[start:start + size])
        require(not any(h[start + len(signature):start + size]), "Nonzero signature padding")
        certs, fingerprints = certificate_chain(h[start + size:start + size + chain_len])
        normalized = f.copy(); normalized[other_sig_idx] = normalized[other_chain_idx] = 0
        signed = bytearray(h[:qsig_start]); signed[:40] = struct.pack("<10I", *normalized)
        signed[masked_start:masked_start + masked_len] = bytes(masked_len)
        certs[0].public_key().verify(signature, bytes(signed), ec.ECDSA(hashes.SHA384()))
        authorities[name] = {"signature_verified": True, "chain_verified": True, "certificate_sha256": fingerprints}
    require("OEM" in authorities, "Missing OEM signature")
    common, oem, qti = h[40:40 + c], h[ometa_start:table_start], h[qmeta_start:ometa_start]
    return {"mbn_version": 7, "all_segment_hashes_verified": True, "authorities": authorities,
            "common_metadata_hex": common.hex(), "oem_metadata_hex": oem.hex(), "qti_metadata_hex": qti.hex(),
            "software_id": struct.unpack_from("<I", common, 8)[0], "oem_anti_rollback": struct.unpack_from("<I", oem, 8)[0],
            "qti_anti_rollback": struct.unpack_from("<I", qti, 8)[0] if qti else None,
            "hardware_fuses_read": False}
