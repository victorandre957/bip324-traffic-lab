#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class UserFacingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulationPaths:
    repository_root: Path
    simulation_root: Path
    results_root: Path
    warnet_binary: Path

    @classmethod
    def from_script_location(cls, results_root: str | Path | None = None) -> "SimulationPaths":
        simulation_root = Path(__file__).resolve().parents[1]
        repository_root = simulation_root.parent
        resolved_results_root = (
            Path(results_root).expanduser().resolve()
            if results_root
            else simulation_root / "results"
        )
        return cls(
            repository_root=repository_root,
            simulation_root=simulation_root,
            results_root=resolved_results_root,
            warnet_binary=cls._warnet_binary(repository_root),
        )

    @staticmethod
    def _warnet_binary(repository_root: Path) -> Path:
        from_path = shutil.which("warnet")
        if from_path:
            return Path(from_path)
        return repository_root / ".venv" / "bin" / "warnet"


@dataclass(frozen=True)
class NodeTrafficProfile:
    role: str
    tx_probability: float
    output_choices: tuple[int, ...]
    amount_min: float
    amount_max: float

    def metadata(self) -> dict[str, object]:
        return {
            "role": self.role,
            "tx_probability": self.tx_probability,
            "output_choices": list(self.output_choices),
            "amount_min": self.amount_min,
            "amount_max": self.amount_max,
        }


@dataclass(frozen=True)
class BlockLoadProfile:
    transactions_per_block: int
    outputs_per_transaction: int
    output_amount: float

    def metadata(self) -> dict[str, object]:
        estimated_vbytes = self.transactions_per_block * (110 + 31 * self.outputs_per_transaction)
        return {
            "transactions_per_block": self.transactions_per_block,
            "outputs_per_transaction": self.outputs_per_transaction,
            "output_amount_btc": self.output_amount,
            "estimated_payload_bytes": estimated_vbytes,
            "note": "Estimated transaction payload only; actual block size varies with signatures and relay timing.",
        }


class CommandRunner:
    def run(
        self,
        *command: str | Path,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        return subprocess.run([str(part) for part in command], check=check, env=command_env)

    def output(self, *command: str | Path, check: bool = True) -> str:
        result = subprocess.run(
            [str(part) for part in command],
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()

    def combined_output(self, *command: str | Path) -> str:
        result = subprocess.run(
            [str(part) for part in command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return result.stdout


class BitcoinNode:
    default_regtest_p2p_port = 18444
    settings_path = "/root/.bitcoin/regtest/settings.json"

    def __init__(self, pod_name: str, namespace: str, commands: CommandRunner):
        self.pod_name = pod_name
        self.namespace = namespace
        self.commands = commands
        self._pod_ip: str | None = None
        self._p2p_port: int | None = None
        self._p2p_port_source = "default-regtest"

    def exec(self, *arguments: str, check: bool = True) -> str:
        return self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "exec",
            self.pod_name,
            "--container",
            "bitcoincore",
            "--",
            *arguments,
            check=check,
        )

    def cli(self, *arguments: str, check: bool = True) -> str:
        return self.exec("bitcoin-cli", *arguments, check=check)

    def wallet_cli(self, *arguments: str, check: bool = True) -> str:
        return self.cli("-rpcwallet=traffic", *arguments, check=check)

    def wait_until_rpc_ready(self) -> None:
        for _ in range(90):
            if self.cli("getblockchaininfo", check=False):
                return
            time.sleep(2)
        raise RuntimeError(f"{self.pod_name} RPC did not become ready")

    def create_wallet(self) -> None:
        self.cli("-named", "createwallet", "wallet_name=traffic", check=False)
        self.cli("loadwallet", "traffic", check=False)

    def pod_ip(self) -> str:
        if self._pod_ip:
            return self._pod_ip
        for _ in range(30):
            pod_ip = self.commands.output(
                "kubectl",
                "-n",
                self.namespace,
                "get",
                "pod",
                self.pod_name,
                "-o",
                "jsonpath={.status.podIP}",
                check=False,
            )
            if pod_ip:
                self._pod_ip = pod_ip
                return pod_ip
            time.sleep(1)
        raise RuntimeError(f"{self.pod_name} has no Kubernetes pod IP")

    def p2p_port(self) -> int:
        if self._p2p_port is None:
            randomized_port = self._read_randomized_p2p_port()
            if randomized_port:
                self._p2p_port = randomized_port
                self._p2p_port_source = "settings.json randomizedp2pport"
            else:
                self._p2p_port = self.default_regtest_p2p_port
        return self._p2p_port

    def p2p_address(self) -> str:
        return f"{self.pod_ip()}:{self.p2p_port()}"

    def add_peer(self, peer: "BitcoinNode") -> None:
        self.cli("addnode", peer.p2p_address(), "onetry", check=False)

    def peer_info(self) -> list[dict[str, object]]:
        raw_info = self.cli("getpeerinfo", check=False)
        if not raw_info:
            return []
        try:
            parsed = json.loads(raw_info)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def has_outbound_connection_to(self, peer: "BitcoinNode") -> bool:
        return peer.p2p_address() in self.outbound_peer_addresses()

    def outbound_peer_addresses(self) -> set[str]:
        return {
            str(info["addr"])
            for info in self.peer_info()
            if info.get("addr") and not info.get("inbound", False)
        }

    def _read_randomized_p2p_port(self) -> int | None:
        raw_settings = self.exec(
            "sh",
            "-c",
            f"cat {self.settings_path} 2>/dev/null || true",
            check=False,
        )
        if not raw_settings:
            return None
        try:
            settings = json.loads(raw_settings)
            port = settings.get("randomizedp2pport") if isinstance(settings, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return int(port) if port else None

    def connection_info(self) -> dict[str, str | int]:
        return {
            "pod_ip": self.pod_ip(),
            "p2p_port": self.p2p_port(),
            "p2p_port_source": self._p2p_port_source,
            "p2p_address": self.p2p_address(),
        }

    def block_count(self) -> int:
        return int(self.cli("getblockcount"))

    def balance(self) -> float:
        return float(self.wallet_cli("getbalance", check=False) or 0)

    def new_address(self) -> str:
        return self.wallet_cli("getnewaddress")

    def generate_blocks(self, block_count: int) -> None:
        self.cli("generatetoaddress", str(block_count), self.new_address())

    def send_to(self, address: str, amount: float) -> str:
        return self.wallet_cli("sendtoaddress", address, f"{amount:.8f}")

    def send_many(self, outputs: dict[str, float]) -> str:
        formatted_outputs = {
            address: round(amount, 8)
            for address, amount in outputs.items()
        }
        return self.wallet_cli("sendmany", "", json.dumps(formatted_outputs, sort_keys=True))


class BitcoinTrafficGenerator:
    miner_name = "tank-0001"
    initial_node_names = ("tank-0001", "tank-0002", "tank-0003")
    delayed_node_names = ("tank-0004", "tank-0005")
    node_names = initial_node_names + delayed_node_names
    traffic_profiles = {
        "tank-0001": NodeTrafficProfile("miner", 0.15, (1, 2), 0.00005, 0.00015),
        "tank-0002": NodeTrafficProfile("heavy_sender", 0.95, (4, 8, 12, 16), 0.00010, 0.00080),
        "tank-0003": NodeTrafficProfile("light_sender", 0.45, (1, 2, 4), 0.00005, 0.00030),
        "tank-0004": NodeTrafficProfile("delayed_bursty_sender", 0.80, (8, 12, 20), 0.00010, 0.00100),
        "tank-0005": NodeTrafficProfile("delayed_quiet_peer", 0.20, (1, 2), 0.00003, 0.00012),
    }
    block_load_profiles = {
        "small": BlockLoadProfile(4, 64, 0.00001),
        "medium": BlockLoadProfile(12, 256, 0.00001),
        "mainnet-like": BlockLoadProfile(96, 512, 0.00001),
    }
    initial_topology_edges = (
        ("tank-0001", "tank-0002"),
        ("tank-0002", "tank-0003"),
    )
    delayed_topology_edges = (
        ("tank-0004", "tank-0002"),
        ("tank-0004", "tank-0003"),
        ("tank-0005", "tank-0003"),
    )
    configured_network_conditions = {
        "tank-0001": {"delay_ms": 8, "jitter_ms": 2, "loss_percent": 0.0},
        "tank-0002": {"delay_ms": 24, "jitter_ms": 5, "loss_percent": 0.0},
        "tank-0003": {"delay_ms": 65, "jitter_ms": 12, "loss_percent": 0.0},
        "tank-0004": {"delay_ms": 120, "jitter_ms": 25, "loss_percent": 0.0},
        "tank-0005": {"delay_ms": 180, "jitter_ms": 40, "loss_percent": 0.2},
    }

    def __init__(self, namespace: str, commands: CommandRunner, seed: str, block_profile: str):
        self.namespace = namespace
        self.commands = commands
        self.rng = random.Random(seed)
        self.block_profile_name = block_profile
        self.block_profile = self.block_load_profiles[block_profile]
        self.nodes_by_name = {
            pod_name: BitcoinNode(pod_name, namespace, commands)
            for pod_name in self.node_names
        }
        self.nodes = [self.nodes_by_name[pod_name] for pod_name in self.node_names]
        self.initial_nodes = [self.nodes_by_name[pod_name] for pod_name in self.initial_node_names]
        self.delayed_nodes = [self.nodes_by_name[pod_name] for pod_name in self.delayed_node_names]
        self.active_nodes = list(self.initial_nodes)
        self.miner = self.nodes_by_name[self.miner_name]
        self.traffic_nodes = [node for node in self.active_nodes if node.pod_name != self.miner_name]
        self.delayed_nodes_joined = False
        self.node_addresses: dict[str, dict[str, str | int]] = {}
        self.block_output_addresses: list[str] = []
        self.network_condition_status: dict[str, dict[str, object]] = {}

    @classmethod
    def profile_metadata(cls) -> dict[str, dict[str, object]]:
        return {
            node_name: profile.metadata()
            for node_name, profile in cls.traffic_profiles.items()
        }

    @classmethod
    def block_profile_metadata(cls, name: str) -> dict[str, object]:
        return cls.block_load_profiles[name].metadata()

    def prepare(self) -> None:
        self._wait_for_nodes()
        self._cache_node_addresses()
        for node in self.nodes:
            node.create_wallet()
        self._connect_edges(self.initial_topology_edges)
        self._collect_network_condition_status()
        self.miner.generate_blocks(120)
        self._wait_for_height(120, self.active_nodes)
        self._fund_nodes(self.traffic_nodes)
        self._wait_until_nodes_have_balance(self.traffic_nodes)
        self._prepare_block_output_addresses()

    def run_until(self, deadline: float) -> None:
        next_block_time = time.time()
        next_transaction_time = time.time()
        delayed_join_time = time.time() + max(0, deadline - time.time()) / 2
        while time.time() < deadline:
            now = time.time()
            if not self.delayed_nodes_joined and now >= delayed_join_time:
                self._join_delayed_nodes_safely()
            if now >= next_transaction_time:
                self._send_mesh_transactions_safely()
                next_transaction_time = now + self._next_transaction_interval()
            if now >= next_block_time:
                self._generate_block_safely()
                next_block_time = now + self._next_block_interval()
            time.sleep(1)

    def _wait_for_nodes(self) -> None:
        for node in self.nodes:
            node.wait_until_rpc_ready()

    def _cache_node_addresses(self) -> None:
        self.node_addresses = {
            node.pod_name: node.connection_info()
            for node in self.nodes
        }

    def _connect_edges(
        self,
        edges: tuple[tuple[str, str], ...],
    ) -> None:
        for _ in range(60):
            pending_edges = [
                (source_name, target_name)
                for source_name, target_name in edges
                if not self.nodes_by_name[source_name].has_outbound_connection_to(
                    self.nodes_by_name[target_name]
                )
            ]
            if not pending_edges:
                return
            for source_name, target_name in pending_edges:
                self.nodes_by_name[source_name].add_peer(self.nodes_by_name[target_name])
            time.sleep(2)
        diagnostics = {
            source_name: sorted(self.nodes_by_name[source_name].outbound_peer_addresses())
            for source_name in sorted({source for source, _ in pending_edges})
        }
        raise UserFacingError(
            "Bitcoin topology edges did not connect. "
            f"Pending edges: {pending_edges}. Connected outbound peers: {diagnostics}"
        )

    def _join_delayed_nodes_safely(self) -> None:
        try:
            self._join_delayed_nodes()
        except (RuntimeError, subprocess.CalledProcessError) as exception:
            print(f"[run] delayed node join skipped: {exception}")

    def _join_delayed_nodes(self) -> None:
        print("[run] joining delayed Bitcoin nodes")
        current_height = self.miner.block_count()
        self._connect_edges(self.delayed_topology_edges)

        self._wait_for_height(current_height, self.delayed_nodes)
        self._fund_nodes(self.delayed_nodes)
        self._wait_until_nodes_have_balance(self.delayed_nodes)
        self.active_nodes.extend(self.delayed_nodes)
        self.traffic_nodes = [node for node in self.active_nodes if node.pod_name != self.miner_name]
        self.delayed_nodes_joined = True

    def _collect_network_condition_status(self) -> None:
        for node in self.nodes:
            output = self.commands.combined_output(
                "kubectl",
                "-n",
                self.namespace,
                "logs",
                node.pod_name,
                "--container",
                "latency-shaper",
            ).strip()
            configured = dict(self.configured_network_conditions[node.pod_name])
            self.network_condition_status[node.pod_name] = {
                **configured,
                "applied": "[netem] applied" in output,
                "sidecar_output": output,
            }

    def _fund_nodes(self, nodes: list[BitcoinNode]) -> None:
        for node in nodes:
            self.miner.send_to(node.new_address(), 5)
        self.miner.generate_blocks(1)
        self._wait_for_height(self.miner.block_count(), self.active_nodes + nodes)

    def _wait_for_height(self, expected_height: int, nodes: list[BitcoinNode] | None = None) -> None:
        watched_nodes = nodes or self.active_nodes
        for _ in range(90):
            heights = [node.block_count() for node in watched_nodes]
            if min(heights) >= expected_height:
                return
            time.sleep(2)
        raise RuntimeError(f"Bitcoin nodes did not reach height {expected_height}")

    def _wait_until_nodes_have_balance(self, nodes: list[BitcoinNode]) -> None:
        for _ in range(60):
            balances = [node.balance() for node in nodes]
            if all(balance > 0 for balance in balances):
                return
            time.sleep(2)
        raise RuntimeError("Bitcoin nodes did not receive spendable balance")

    def _send_mesh_transactions_safely(self) -> None:
        try:
            self._send_mesh_transactions()
        except (RuntimeError, subprocess.CalledProcessError) as exception:
            print(f"[run] transaction round skipped: {exception}")

    def _send_mesh_transactions(self) -> None:
        for index, sender in enumerate(self.active_nodes):
            if sender.balance() <= 0.001:
                continue
            profile = self.traffic_profiles[sender.pod_name]
            if self.rng.random() > profile.tx_probability:
                continue
            receiver = self.active_nodes[(index + 1) % len(self.active_nodes)]
            sender.send_many(self._transaction_outputs(sender, receiver))

    def _transaction_outputs(self, sender: BitcoinNode, receiver: BitcoinNode) -> dict[str, float]:
        profile = self.traffic_profiles[sender.pod_name]
        output_count = self.rng.choice(profile.output_choices)
        return {
            receiver.new_address(): self._transaction_amount(profile)
            for _ in range(output_count)
        }

    def _transaction_amount(self, profile: NodeTrafficProfile) -> float:
        return self.rng.uniform(profile.amount_min, profile.amount_max)

    def _next_transaction_interval(self) -> float:
        return self.rng.uniform(2.0, 9.0)

    def _next_block_interval(self) -> float:
        return self.rng.uniform(10.0, 24.0)

    def _generate_block_safely(self) -> None:
        try:
            self._prime_mempool_for_block()
            self.miner.generate_blocks(1)
        except subprocess.CalledProcessError as exception:
            print(f"[run] block generation skipped: {exception}")

    def _prepare_block_output_addresses(self) -> None:
        receivers = self.traffic_nodes or [self.miner]
        self.block_output_addresses = [
            receivers[index % len(receivers)].new_address()
            for index in range(self.block_profile.outputs_per_transaction)
        ]

    def _prime_mempool_for_block(self) -> None:
        if not self.block_output_addresses:
            return
        print(
            "[run] priming mempool for "
            f"{self.block_profile_name} block profile "
            f"({self.block_profile.transactions_per_block} transactions x "
            f"{self.block_profile.outputs_per_transaction} outputs)"
        )
        outputs = {
            address: self.block_profile.output_amount
            for address in self.block_output_addresses
        }
        for _ in range(self.block_profile.transactions_per_block):
            self.miner.send_many(outputs)


class SnifferDeployment:
    release_name = "isp-sniffer-capture"

    def __init__(self, namespace: str, paths: SimulationPaths, commands: CommandRunner):
        self.namespace = namespace
        self.paths = paths
        self.commands = commands
        self.selector = f"app=isp-sniffer,capture-release={self.release_name}"
        self.installed = False
        self.pod_name = ""

    def deploy(self) -> str:
        self.commands.run(
            "helm",
            "upgrade",
            "--install",
            self.release_name,
            self.paths.simulation_root / "plugins/isp-sniffer/charts/isp-sniffer",
            "--namespace",
            self.namespace,
            "--create-namespace",
            "--set",
            f"namespace={self.namespace}",
        )
        self.installed = True
        sniffer_pod = self._wait_for_pod_name()
        self.pod_name = sniffer_pod
        self._wait_until_ready()
        self._wait_until_capturing(sniffer_pod)
        return sniffer_pod

    def uninstall(self) -> None:
        self.commands.run(
            "helm",
            "uninstall",
            self.release_name,
            "--namespace",
            self.namespace,
            check=False,
        )
        # A standalone Pod can remain Terminating after Helm reports success.
        # Waiting here prevents a subsequent run from trying to patch that old Pod.
        self.commands.run(
            "kubectl",
            "-n",
            self.namespace,
            "wait",
            "pod",
            "-l",
            self.selector,
            "--for=delete",
            "--timeout=60s",
            check=False,
        )

    def write_diagnostics(self, destination: Path) -> None:
        pod_name = self.pod_name or self._wait_for_existing_pod_name()
        commands = [
            ("pod description", "kubectl", "-n", self.namespace, "describe", "pod", pod_name),
            ("container logs", "kubectl", "-n", self.namespace, "logs", pod_name),
            ("previous container logs", "kubectl", "-n", self.namespace, "logs", pod_name, "--previous"),
        ]
        sections = []
        for title, *command in commands:
            sections.append(f"===== {title} =====\n")
            sections.append(self.commands.combined_output(*command))
            sections.append("\n")
        destination.write_text("".join(sections), encoding="utf-8")

    def _wait_for_existing_pod_name(self) -> str:
        return self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "pods",
            "-l",
            self.selector,
            "-o",
            "jsonpath={.items[0].metadata.name}",
            check=False,
        )

    def _wait_for_pod_name(self) -> str:
        for _ in range(60):
            pod_name = self.commands.output(
                "kubectl",
                "-n",
                self.namespace,
                "get",
                "pods",
                "-l",
                self.selector,
                "-o",
                "jsonpath={.items[0].metadata.name}",
                check=False,
            )
            if pod_name:
                return pod_name
            time.sleep(1)
        raise RuntimeError("isp-sniffer pod not found")

    def _wait_until_ready(self) -> None:
        self.commands.run(
            "kubectl",
            "-n",
            self.namespace,
            "wait",
            "pod",
            "-l",
            self.selector,
            "--for=condition=Ready",
            "--timeout=120s",
        )

    def _wait_until_capturing(self, pod_name: str) -> None:
        for _ in range(30):
            logs = self.commands.output(
                "kubectl",
                "-n",
                self.namespace,
                "logs",
                pod_name,
                check=False,
            )
            if "[isp-sniffer] pcap" in logs:
                return
            time.sleep(1)
        raise RuntimeError("isp-sniffer did not start packet capture")


class SimulationRunner:
    noise_components = (
        "bitcoin-traffic",
        "http-server",
        "http-client",
        "https-server",
        "https-client",
        "streaming-server",
        "streaming-client",
        "obfs4-server",
        "obfs4-client",
        "tor-da",
        "tor-relay",
        "tor-client",
        "torrent-seeder",
        "torrent-leecher",
    )

    def __init__(
        self,
        duration_minutes: int,
        namespace: str,
        paths: SimulationPaths,
        seed: str | None = None,
        block_profile: str = "medium",
    ):
        self.duration_minutes = duration_minutes
        self.namespace = namespace
        self.paths = paths
        self.seed = seed or self._generate_seed()
        self.block_profile = block_profile
        self.run_started_at = datetime.now(UTC).isoformat()
        self.commands = CommandRunner()
        self._run_directory: Path | None = None
        self.bitcoin_node_addresses: dict[str, dict[str, str | int]] = {}
        self.bitcoin_network_conditions: dict[str, dict[str, object]] = {}

    @property
    def run_directory(self) -> Path:
        if self._run_directory is None:
            raise RuntimeError("run directory has not been initialized")
        return self._run_directory

    def run(self) -> None:
        sniffer_pod = ""
        network_deployed = False
        sniffer = SnifferDeployment(self.namespace, self.paths, self.commands)
        run_status = "finished"
        try:
            self._check_prerequisites()
            self._run_directory = self._create_run_directory()
            self._write_metadata(status="created")
            self._write_metadata(status="running")
            sniffer_pod = sniffer.deploy()
            network_deployed = True
            self._deploy_network()
            self._wait_for_scenario_ready()
            traffic_generator = BitcoinTrafficGenerator(
                self.namespace,
                self.commands,
                self._derive_seed("bitcoin-traffic"),
                self.block_profile,
            )
            traffic_generator.prepare()
            self.bitcoin_node_addresses = traffic_generator.node_addresses
            self.bitcoin_network_conditions = traffic_generator.network_condition_status
            self._start_obfs4_noise()
            self._write_metadata(status="running")
            self._run_capture_window(traffic_generator)
        except Exception:
            run_status = "failed"
            if self._run_directory is not None:
                try:
                    self._write_network_diagnostics()
                except Exception as exception:
                    print(f"[run] could not save network diagnostics: {exception}")
            raise
        finally:
            try:
                if sniffer_pod:
                    self._stop_packet_capture(sniffer_pod)
                    self._collect_results(sniffer_pod)
            finally:
                if run_status == "failed" and self._run_directory is not None and sniffer.installed:
                    try:
                        sniffer.write_diagnostics(self.run_directory / "sniffer-startup-diagnostics.txt")
                    except Exception as exception:
                        print(f"[run] could not save sniffer diagnostics: {exception}")
                if network_deployed:
                    self._stop_network()
                if sniffer.installed:
                    sniffer.uninstall()
                if self._run_directory is not None:
                    self._write_metadata(status=run_status)
        print(f"[run] results saved in {self.run_directory}")
        print(f"[run] seed: {self.seed}")

    def _check_prerequisites(self) -> None:
        for command_name in ("kubectl", "helm"):
            if not shutil.which(command_name):
                raise UserFacingError(
                    f"Required command not found: {command_name}. "
                    "Install it and make sure it is available on PATH."
                )
        if not self.paths.warnet_binary.exists() and not shutil.which(str(self.paths.warnet_binary)):
            raise UserFacingError(
                f"Warnet executable not found at {self.paths.warnet_binary}. "
                "Activate the repository .venv and install Warnet with: "
                "python -m pip install -e warnet"
            )
        result = subprocess.run(
            ["kubectl", "cluster-info", "--request-timeout=5s"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            raise UserFacingError(
                "Kubernetes cluster is not reachable from the current kube-context.\n\n"
                "Common fixes:\n"
                "- If you use Minikube: minikube start\n"
                "- If you use Kind: kind get clusters, then export/use the right kubeconfig\n"
                "- Check the active context: kubectl config current-context\n"
                "- Verify access: kubectl cluster-info\n\n"
                f"kubectl said:\n{details}"
            )

    @staticmethod
    def _generate_seed() -> str:
        return secrets.token_hex(16)

    def _derive_seed(self, component: str) -> str:
        return hashlib.sha256(f"{self.seed}:{component}".encode("utf-8")).hexdigest()

    def _component_seeds(self) -> dict[str, str]:
        return {component: self._derive_seed(component) for component in self.noise_components}

    def _create_run_directory(self) -> Path:
        run_id = time.strftime("%Y%m%d%H%M%S")
        run_directory = self.paths.results_root / f"run-{run_id}"
        run_directory.mkdir(parents=True, exist_ok=True)
        return run_directory

    def _write_metadata(self, status: str) -> None:
        metadata = {
            "status": status,
            "run_directory": str(self.run_directory),
            "run_started_at": self.run_started_at,
            "metadata_written_at": datetime.now(UTC).isoformat(),
            "duration_minutes": self.duration_minutes,
            "delayed_bitcoin_nodes": list(BitcoinTrafficGenerator.delayed_node_names),
            "delayed_bitcoin_join_after_seconds": self.duration_minutes * 60 / 2,
            "bitcoin_traffic_profiles": BitcoinTrafficGenerator.profile_metadata(),
            "bitcoin_topology_profile": {
                "name": "sparse-mixed-reachability",
                "initial_edges": [list(edge) for edge in BitcoinTrafficGenerator.initial_topology_edges],
                "delayed_edges": [list(edge) for edge in BitcoinTrafficGenerator.delayed_topology_edges],
                "unreachable_from_inbound_peers": ["tank-0005"],
                "note": "Topology drives the lab only and is not consumed by passive detection.",
            },
            "bitcoin_network_conditions": self.bitcoin_network_conditions or {
                name: {**condition, "applied": None}
                for name, condition in BitcoinTrafficGenerator.configured_network_conditions.items()
            },
            "bitcoin_timing_profile": {
                "transaction_interval_seconds": "uniform[2.0, 9.0]",
                "block_interval_seconds": "uniform[10.0, 24.0]",
                "jitter_seed": self._derive_seed("bitcoin-traffic"),
            },
            "bitcoin_block_load_profile": {
                "name": self.block_profile,
                **BitcoinTrafficGenerator.block_profile_metadata(self.block_profile),
            },
            "passive_capture_profile": {
                "pcap": "isp-capture.pcap",
                "interface": "bridge",
                "snaplen_bytes": 256,
                "timestamp_precision": "nanoseconds",
                "buffer_size_kib": 4096,
                "offload_state_artifact": "capture-environment.txt",
                "packet_loss_artifact": "tcpdump-stats.log",
                "graceful_stop_before_copy": True,
                "tcp_ip_fingerprint_fields": [
                    "ip_version",
                    "ip_ttl_or_ipv6_hop_limit",
                    "ipv4_fragment_flags",
                    "tcp_window_size",
                    "tcp_mss",
                    "tcp_window_scale",
                    "tcp_sack_permitted",
                    "tcp_timestamp_present",
                    "tcp_options_order",
                    "tcp_sequence_number",
                    "tcp_ack_number",
                    "tcp_retransmission_overlap",
                ],
                "analysis_role": (
                    "Complementary passive context for grouping prediction quality by "
                    "visible TCP/IP stack signature; not validation ground truth."
                ),
            },
            "namespace": self.namespace,
            "seed": self.seed,
            "component_seeds": self._component_seeds(),
            "bitcoin_node_p2p_addresses": self.bitcoin_node_addresses,
            "bitcoin_node_image": {
                "repository": "bip324-traffic-lab-bitcoin",
                "tag": "28.1.0-decoy",
            },
            "reproducibility_note": (
                "The seed fixes generated payloads, transaction amounts, and configured "
                "noise choices. Kubernetes scheduling and packet timing can still change "
                "the exact byte-for-byte PCAP."
            ),
            "startup_order": [
                "isp-sniffer",
                "noise-generator-pods",
                "initial-bitcoin-nodes",
                "bitcoin-traffic",
                "obfs4-traffic-after-bitcoin-ready",
                "delayed-bitcoin-nodes-at-midpoint",
            ],
            "tools": {
                "warnet_binary": str(self.paths.warnet_binary),
                "simulation_root": str(self.paths.simulation_root),
            },
        }
        (self.run_directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _deploy_network(self) -> None:
        self.commands.run(
            self.paths.warnet_binary,
            "deploy",
            self.paths.simulation_root,
            env={
                "BIP324_TRAFFIC_LAB_SEED": self.seed,
                "BIP324_TRAFFIC_LAB_RUN_DIR": str(self.run_directory),
            },
        )

    def _wait_for_scenario_ready(self) -> None:
        tank_pods = [f"pod/{name}" for name in BitcoinTrafficGenerator.node_names]
        try:
            self.commands.run(
                "kubectl",
                "-n",
                self.namespace,
                "wait",
                *tank_pods,
                "--for=condition=Ready",
                "--timeout=4m",
            )
            self.commands.run(
                "kubectl",
                "-n",
                self.namespace,
                "wait",
                "pod",
                "-l",
                "app=noise-generator",
                "--for=condition=Ready",
                "--timeout=4m",
            )
        except subprocess.CalledProcessError as exception:
            raise UserFacingError(
                "The Warnet scenario did not become ready. "
                "See network-startup-diagnostics.txt in the run directory."
            ) from exception

    def _start_obfs4_noise(self) -> None:
        pod_name = self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "pod",
            "-l",
            "app=noise-generator,role=obfs4-client",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        )
        if not pod_name:
            raise UserFacingError("The obfs4 noise client pod was not found.")
        self.commands.run(
            "kubectl",
            "-n",
            self.namespace,
            "exec",
            pod_name,
            "--",
            "touch",
            "/traffic-control/start",
        )
        print("[run] obfs4 noise traffic started after Bitcoin setup")

    def _write_network_diagnostics(self) -> None:
        diagnostics = self.commands.combined_output(
            "kubectl", "-n", self.namespace, "get", "pods", "-o", "wide"
        )
        diagnostics += "\n\n"
        diagnostics += self.commands.combined_output(
            "kubectl", "-n", self.namespace, "get", "events", "--sort-by=.lastTimestamp"
        )
        (self.run_directory / "network-startup-diagnostics.txt").write_text(
            diagnostics, encoding="utf-8"
        )

    def _run_capture_window(self, traffic_generator: BitcoinTrafficGenerator) -> None:
        print(f"[run] simulation running for {self.duration_minutes} minutes")
        traffic_generator.run_until(time.time() + self.duration_minutes * 60)

    def _collect_results(self, sniffer_pod: str) -> None:
        self._write_pod_ip_map()
        self._copy_from_pod(
            sniffer_pod,
            "/captures/isp-capture.pcap",
            self.run_directory / "isp-capture.pcap",
        )
        self._copy_from_pod(
            sniffer_pod,
            "/captures/tcpdump-stats.log",
            self.run_directory / "tcpdump-stats.log",
        )
        self._copy_from_pod(
            sniffer_pod,
            "/captures/capture-environment.txt",
            self.run_directory / "capture-environment.txt",
        )
        for tank_pod in self._tank_pods():
            self._copy_from_pod(
                tank_pod,
                "/root/.bitcoin/regtest/debug.log",
                self.run_directory / f"{tank_pod}-debug.log",
            )

    def _stop_packet_capture(self, sniffer_pod: str) -> None:
        self.commands.run(
            "kubectl",
            "-n",
            self.namespace,
            "exec",
            sniffer_pod,
            "--",
            "sh",
            "-c",
            "pkill -2 tcpdump 2>/dev/null || true; "
            "for i in $(seq 1 50); do "
            "test -f /captures/capture-complete && exit 0; sleep 0.1; "
            "done; exit 1",
            check=False,
        )

    def _write_pod_ip_map(self) -> None:
        pod_table = self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "pods",
            "-o",
            "wide",
        )
        service_table = self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "services",
            "-o",
            "wide",
        )
        ip_map = self.run_directory / "ip-map.txt"
        bitcoin_addresses = json.dumps(
            self.bitcoin_node_addresses,
            indent=2,
            sort_keys=True,
        )
        ip_map.write_text(
            (
                f"PODS\n{pod_table}\n\n"
                f"SERVICES\n{service_table}\n\n"
                f"BITCOIN RANDOMIZED P2P ADDRESSES\n{bitcoin_addresses}\n"
            ),
            encoding="utf-8",
        )

    def _tank_pods(self) -> list[str]:
        pod_names = self._kubectl_output(
            "get",
            "pods",
            "-o",
            "jsonpath={.items[*].metadata.name}",
        )
        return [pod_name for pod_name in pod_names.split() if pod_name.startswith("tank-")]

    def _copy_from_pod(self, pod_name: str, source_path: str, destination_path: Path) -> None:
        self.commands.run(
            "kubectl",
            "cp",
            f"{self.namespace}/{pod_name}:{source_path}",
            destination_path,
            check=False,
        )

    def _stop_network(self) -> None:
        releases = self.commands.output(
            "helm",
            "list",
            "--namespace",
            self.namespace,
            "--short",
            check=False,
        )
        scenario_releases = [
            release
            for release in releases.splitlines()
            if release.startswith("tank-") or release.startswith("noise-generator-")
        ]
        if scenario_releases:
            self.commands.run(
                "helm",
                "uninstall",
                "--namespace",
                self.namespace,
                *scenario_releases,
                check=False,
            )

    def _kubectl_output(self, *arguments: str, check: bool = True) -> str:
        return self.commands.output("kubectl", "-n", self.namespace, *arguments, check=check)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BIP324 traffic lab and collect artifacts.")
    parser.add_argument("duration_minutes", nargs="?", default=10, type=int)
    parser.add_argument("--namespace", default="default")
    parser.add_argument(
        "--seed",
        default=None,
        help="Seed to reproduce deterministic payloads and pseudo-random simulation choices.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where run-* artifacts are written. Defaults to bip324-traffic-lab/results.",
    )
    parser.add_argument(
        "--block-profile",
        choices=tuple(BitcoinTrafficGenerator.block_load_profiles),
        default="medium",
        help="Mempool load generated before each mined block.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = SimulationRunner(
        duration_minutes=args.duration_minutes,
        namespace=args.namespace,
        paths=SimulationPaths.from_script_location(args.output_dir),
        seed=args.seed,
        block_profile=args.block_profile,
    )
    try:
        runner.run()
    except UserFacingError as exception:
        print(f"[error] {exception}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
