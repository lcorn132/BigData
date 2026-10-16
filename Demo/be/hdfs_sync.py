"""Đồng bộ gói serving_export giữa máy local và HDFS qua SSH.

Cách này chỉ cần OpenSSH trên máy chạy demo. Lệnh ``hdfs dfs`` được thực thi
trên NameNode, vì vậy máy Windows không phải cài Hadoop hoặc Java.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Thiếu biến cấu hình {name} trong hdfs.env.bat")
    return value


class HdfsSshClient:
    def __init__(self) -> None:
        self.host = required("HDFS_SSH_HOST")
        self.user = required("HDFS_SSH_USER")
        self.port = os.getenv("HDFS_SSH_PORT", "22").strip() or "22"
        self.key = os.getenv("HDFS_SSH_KEY", "").strip()
        self.hdfs_bin = os.getenv("HDFS_BIN", "/opt/hadoop/bin/hdfs").strip()
        self.hdfs_path = os.getenv(
            "HDFS_EXPORT_PATH", "/cosmetics/serving/serving_export.zip"
        ).strip()

    def ssh_args(self) -> list[str]:
        args = [
            "ssh", "-p", self.port, "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
        ]
        if self.key:
            args.extend(["-i", self.key])
        args.append(f"{self.user}@{self.host}")
        return args

    def scp_args(self) -> list[str]:
        args = [
            "scp", "-P", self.port, "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
        ]
        if self.key:
            args.extend(["-i", self.key])
        return args

    def remote(self, command: str, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.ssh_args(), command], check=True, text=True,
            capture_output=capture,
        )

    def signature(self) -> str:
        command = (
            f"{shlex.quote(self.hdfs_bin)} dfs -stat '%b:%Y' "
            f"{shlex.quote(self.hdfs_path)}"
        )
        return self.remote(command, capture=True).stdout.strip()

    def download(self, destination: Path) -> str:
        signature = self.signature()
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        command = (
            f"{shlex.quote(self.hdfs_bin)} dfs -cat "
            f"{shlex.quote(self.hdfs_path)}"
        )
        with partial.open("wb") as output:
            result = subprocess.run(
                [*self.ssh_args(), command], stdout=output, stderr=sys.stderr,
                check=False,
            )
        if result.returncode != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError("Không thể tải serving_export từ HDFS")
        if not zipfile.is_zipfile(partial):
            partial.unlink(missing_ok=True)
            raise RuntimeError("Tệp tải từ HDFS không phải ZIP hợp lệ")
        partial.replace(destination)
        return signature

    def upload(self, source: Path) -> str:
        if not source.is_file() or not zipfile.is_zipfile(source):
            raise FileNotFoundError(f"Không tìm thấy ZIP hợp lệ: {source}")
        remote_tmp = "/tmp/cosmetics-serving-export.zip"
        subprocess.run(
            [*self.scp_args(), str(source), f"{self.user}@{self.host}:{remote_tmp}"],
            check=True,
        )
        parent = str(Path(self.hdfs_path).parent).replace("\\", "/")
        command = " && ".join([
            f"{shlex.quote(self.hdfs_bin)} dfs -mkdir -p {shlex.quote(parent)}",
            f"{shlex.quote(self.hdfs_bin)} dfs -put -f {shlex.quote(remote_tmp)} {shlex.quote(self.hdfs_path)}",
            f"rm -f {shlex.quote(remote_tmp)}",
        ])
        self.remote(command)
        return self.signature()


def state_key(client: HdfsSshClient, signature: str) -> dict[str, str]:
    return {
        "host": client.host,
        "hdfs_path": client.hdfs_path,
        "signature": signature,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download")
    download.add_argument("--output", type=Path, required=True)
    upload = sub.add_parser("upload")
    upload.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    client = HdfsSshClient()
    if args.command == "download":
        signature = client.download(args.output.resolve())
        print(json.dumps(state_key(client, signature), ensure_ascii=False))
    else:
        signature = client.upload(args.input.resolve())
        print(json.dumps(state_key(client, signature), ensure_ascii=False))


if __name__ == "__main__":
    main()
