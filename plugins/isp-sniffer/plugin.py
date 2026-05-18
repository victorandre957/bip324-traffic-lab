#!/usr/bin/env python3

import json
import time
from dataclasses import dataclass
from pathlib import Path

import click
from warnet.process import run_command

PLUGIN_DIR_TAG = "plugin_dir"
CHART_NAME = "isp-sniffer"
SNIFFER_POD_SUFFIX = "isp-sniffer"


@dataclass(frozen=True)
class HelmRelease:
    chart_name: str
    chart_path: Path
    namespace: str
    release_name: str

    @classmethod
    def create(cls, chart_name: str, chart_path: Path, namespace: str) -> "HelmRelease":
        return cls(
            chart_name=chart_name,
            chart_path=chart_path,
            namespace=namespace,
            release_name=f"{chart_name}-{int(time.time())}",
        )

    def install_command(self) -> str:
        return (
            f"helm upgrade --install {self.release_name} {self.chart_path} "
            f"--namespace {self.namespace} --create-namespace "
            f"--set namespace={self.namespace}"
        )

    def pod_name(self, suffix: str) -> str:
        return f"{self.release_name}-{suffix}"


class IspSnifferPlugin:
    def __init__(self, plugin_dir: Path, warnet_content: dict):
        self.namespace = warnet_content.get("namespace") or "default"
        self.release = HelmRelease.create(
            chart_name=CHART_NAME,
            chart_path=plugin_dir / "charts" / CHART_NAME,
            namespace=self.namespace,
        )

    def deploy(self) -> None:
        run_command(self.release.install_command())
        sniffer_pod = self.release.pod_name(SNIFFER_POD_SUFFIX)
        print(f"[isp-sniffer] release: {self.release.release_name}")
        print(
            f"[isp-sniffer] pcap: kubectl cp "
            f"{self.namespace}/{sniffer_pod}:/captures/isp-capture.pcap ./isp-capture.pcap"
        )


@click.group()
@click.pass_context
def isp_sniffer(ctx):
    ctx.ensure_object(dict)
    ctx.obj[PLUGIN_DIR_TAG] = Path(__file__).resolve().parent


@isp_sniffer.command()
@click.argument("plugin_content", type=str)
@click.argument("warnet_content", type=str)
@click.pass_context
def entrypoint(ctx, plugin_content: str, warnet_content: str):
    json.loads(plugin_content)
    plugin = IspSnifferPlugin(
        plugin_dir=ctx.obj[PLUGIN_DIR_TAG],
        warnet_content=json.loads(warnet_content),
    )
    plugin.deploy()


if __name__ == "__main__":
    isp_sniffer()
