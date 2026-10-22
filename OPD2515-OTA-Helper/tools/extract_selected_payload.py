"""Extract selected self-contained payload partitions directly from a stored ZIP.
Every compressed operation and final image is hash-checked. Never writes a device.
"""
import argparse
import bz2
import hashlib
import json
import lzma
import pathlib
import re
import struct
import zipfile

from inspect_payload import fields, one, partition_info


def require(ok, message):
    if not ok: raise ValueError(message)


def extract(archive_path, out, names):
    require(not out.exists(), "输出目录存在")
    initial = archive_path.stat()
    with zipfile.ZipFile(archive_path) as archive:
        matching = [p for p in archive.infolist() if p.filename == "payload.bin"]
        require(len(matching) == 1, "需要唯一 payload.bin")
        item = matching[0]
        require(item.compress_type == zipfile.ZIP_STORED and not item.flag_bits & 1, "仅支持未加密且 stored 的 payload")
        with archive_path.open("rb") as src:
            src.seek(item.header_offset); local = src.read(30)
            require(local[:4] == b"PK\x03\x04", "ZIP local header 不符")
            fn, extra = struct.unpack_from("<HH", local, 26)
            start = item.header_offset + 30 + fn + extra
            src.seek(start); header = src.read(24)
            require(header[:4] == b"CrAU", "payload magic 不符")
            version, manifest_len, sig_len = struct.unpack_from(">QQI", header, 4)
            require(version == 2 and 0 < manifest_len <= 32 * 1024 * 1024 and sig_len <= 1024 * 1024, "payload header 异常")
            manifest = src.read(manifest_len); require(len(manifest) == manifest_len, "manifest 截断")
            block = one(manifest, 3, 0, 4096)
            partitions = {one(p, 1, 2).decode(): p for n, w, p in fields(manifest) if (n, w) == (13, 2)}
            require(set(names).issubset(partitions), "目标分区缺失")
            blob_start = start + 24 + manifest_len + sig_len
            out.mkdir(parents=True)
            results = {}
            for name in names:
                require(re.fullmatch(r"[a-zA-Z0-9_]+", name), "分区名异常")
                p = partitions[name]; info = partition_info(one(p, 7, 2))
                require(info and info["sha256"] and 0 < info["bytes"] <= 256 * 1024 * 1024, "分区大小或摘要异常")
                target = out / (name + ".img")
                occupied = []; operation_count = 0
                print("提取", name, info["bytes"], "bytes", flush=True)
                with target.open("xb") as dst:
                    dst.truncate(info["bytes"])
                    for number, wire, operation in fields(p):
                        if (number, wire) != (8, 2): continue
                        operation_count += 1
                        kind = one(operation, 1, 0)
                        require(kind in (0, 1, 6, 8), "非完整替换操作：" + str(kind))
                        extents = []
                        for en, ew, extent in fields(operation):
                            if (en, ew) != (6, 2): continue
                            first, count = one(extent, 1, 0), one(extent, 2, 0)
                            require(first is not None and count and count > 0, "extent 异常")
                            offset, length = first * block, count * block
                            require(offset + length <= info["bytes"], "extent 越界")
                            extents.append((offset, length)); occupied.append((offset, offset + length))
                        total = sum(length for _, length in extents)
                        require(0 < total <= 32 * 1024 * 1024, "操作输出过大")
                        if kind == 6:
                            data = bytes(total)
                        else:
                            off, length = one(operation, 2, 0), one(operation, 3, 0)
                            require(off is not None and length and 0 < length <= 64 * 1024 * 1024 and blob_start + off + length <= start + item.file_size, "blob 越界")
                            src.seek(blob_start + off); packed = src.read(length)
                            require(len(packed) == length, "blob 截断")
                            expected = one(operation, 8, 2)
                            require(expected and len(expected) == 32 and hashlib.sha256(packed).digest() == expected, "blob SHA256 不符")
                            if kind == 0: data = packed
                            else:
                                decoder = bz2.BZ2Decompressor() if kind == 1 else lzma.LZMADecompressor()
                                data = decoder.decompress(packed, max_length=total + 1)
                                require(decoder.eof and not decoder.unused_data, "压缩数据不完整或含额外内容")
                            require(len(data) <= total, "解压结果超过 extent")
                            data = data.ljust(total, b"\0")
                        consumed = 0
                        for offset, length in extents:
                            dst.seek(offset); dst.write(data[consumed:consumed + length]); consumed += length
                cursor = 0
                for begin, end in sorted(occupied):
                    require(begin == cursor, "extent 未完整覆盖或发生重叠")
                    cursor = end
                require(cursor == info["bytes"], "未覆盖整个镜像")
                with target.open("rb") as stream: actual = hashlib.file_digest(stream, "sha256").hexdigest()
                require(actual == info["sha256"], "最终镜像 SHA256 不符：" + name)
                results[name] = dict(file=target.name, bytes=info["bytes"], sha256=actual, operations=operation_count, verified=True)
            final = archive_path.stat()
            require(initial.st_size == final.st_size and initial.st_mtime_ns == final.st_mtime_ns, "提取期间包改变")
            (out / "extraction-manifest.json").write_text(json.dumps({"package": str(archive_path), "package_bytes": initial.st_size, "partitions": results, "device_writes": False}, indent=2), encoding="utf-8")
            return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--partitions", nargs="+", required=True)
    args = parser.parse_args()
    try: extract(args.package, args.out, args.partitions)
    except (ValueError, OSError, lzma.LZMAError) as error: parser.exit(1, "BLOCKED: " + str(error) + "\n")


if __name__ == "__main__": main()
