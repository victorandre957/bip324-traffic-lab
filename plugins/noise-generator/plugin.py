#!/usr/bin/env python3

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import click
from warnet.process import run_command

PLUGIN_DIR_TAG = "plugin_dir"
CHART_NAME = "noise-generator"


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

    def install_command(self, seed: str | None = None) -> str:
        seed_arg = f" --set-string simulation.seed={seed}" if seed else ""
        return (
            f"helm upgrade --install {self.release_name} {self.chart_path} "
            f"--namespace {self.namespace} --create-namespace "
            f"--wait --timeout 10m "
            f"--set namespace={self.namespace}"
            f"{seed_arg}"
        )


class NoiseGeneratorPlugin:
    def __init__(self, plugin_dir: Path, warnet_content: dict):
        self.namespace = warnet_content.get("namespace") or "default"
        self.release = HelmRelease.create(
            chart_name=CHART_NAME,
            chart_path=plugin_dir / "charts" / CHART_NAME,
            namespace=self.namespace,
        )
        self.seed = os.environ.get("BIP324_TRAFFIC_LAB_SEED")

    def deploy(self) -> None:
        run_command(self.release.install_command(self.seed))
        print(f"[noise-generator] release: {self.release.release_name}")
        print(f"[noise-generator] namespace: {self.namespace}")
        if self.seed:
            print(f"[noise-generator] seed: {self.seed}")


@click.group()
@click.pass_context
def noise_generator(ctx):
    ctx.ensure_object(dict)
    ctx.obj[PLUGIN_DIR_TAG] = Path(__file__).resolve().parent


@noise_generator.command()
@click.argument("plugin_content", type=str)
@click.argument("warnet_content", type=str)
@click.pass_context
def entrypoint(ctx, plugin_content: str, warnet_content: str):
    json.loads(plugin_content)
    plugin = NoiseGeneratorPlugin(
        plugin_dir=ctx.obj[PLUGIN_DIR_TAG],
        warnet_content=json.loads(warnet_content),
    )
    plugin.deploy()


if __name__ == "__main__":
    noise_generator()
