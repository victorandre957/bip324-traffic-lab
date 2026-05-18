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


class BitcoinNode:
    def __init__(self, pod_name: str, namespace: str, commands: CommandRunner):
        self.pod_name = pod_name
        self.namespace = namespace
        self.commands = commands

    def cli(self, *arguments: str, check: bool = True) -> str:
        return self.commands.output(
            "kubectl",
            "-n",
            self.namespace,
            "exec",
            self.pod_name,
            "--container",
            "bitcoincore",
            "--",
            "bitcoin-cli",
            *arguments,
            check=check,
        )

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

    def add_peer(self, peer_name: str) -> None:
        self.cli("addnode", peer_name, "onetry", check=False)

    def block_count(self) -> int:
        return int(self.cli("getblockcount"))

    def balance(self) -> float:
        return float(self.wallet_cli("getbalance", check=False) or 0)

    def connection_count(self) -> int:
        return int(self.cli("getconnectioncount", check=False) or 0)

    def new_address(self) -> str:
        return self.wallet_cli("getnewaddress")

    def generate_blocks(self, block_count: int) -> None:
        self.cli("generatetoaddress", str(block_count), self.new_address())

    def send_to(self, address: str, amount: float) -> str:
        return self.wallet_cli("sendtoaddress", address, f"{amount:.8f}")


class BitcoinTrafficGenerator:
    miner_name = "tank-0001"
    node_names = ("tank-0001", "tank-0002", "tank-0003")

    def __init__(self, namespace: str, commands: CommandRunner, seed: str):
        self.namespace = namespace
        self.commands = commands
        self.rng = random.Random(seed)
        self.nodes = [BitcoinNode(pod_name, namespace, commands) for pod_name in self.node_names]
        self.miner = self.nodes[0]
        self.traffic_nodes = [node for node in self.nodes if node.pod_name != self.miner_name]

    def prepare(self) -> None:
        self._wait_for_nodes()
        for node in self.nodes:
            node.create_wallet()
        self._connect_bitcoin_mesh()
        self.miner.generate_blocks(120)
        self._wait_for_height(120)
        self._fund_traffic_nodes()
        self._wait_until_traffic_nodes_have_balance()

    def run_until(self, deadline: float) -> None:
        next_block_time = time.time()
        next_transaction_time = time.time()
        while time.time() < deadline:
            now = time.time()
            if now >= next_transaction_time:
                self._send_mesh_transactions_safely()
                next_transaction_time = now + 5
            if now >= next_block_time:
                self._generate_block_safely()
                next_block_time = now + 15
            time.sleep(1)

    def _wait_for_nodes(self) -> None:
        for node in self.nodes:
            node.wait_until_rpc_ready()

    def _connect_bitcoin_mesh(self) -> None:
        for _ in range(30):
            for node in self.nodes:
                for peer_name in self.node_names:
                    if peer_name != node.pod_name:
                        node.add_peer(peer_name)
            if all(node.connection_count() >= 2 for node in self.nodes):
                return
            time.sleep(2)
        raise RuntimeError("Bitcoin P2P mesh did not connect")

    def _fund_traffic_nodes(self) -> None:
        for node in self.traffic_nodes:
            self.miner.send_to(node.new_address(), 5)
        self.miner.generate_blocks(1)
        self._wait_for_height(121)

    def _wait_for_height(self, expected_height: int) -> None:
        for _ in range(90):
            heights = [node.block_count() for node in self.nodes]
            if min(heights) >= expected_height:
                return
            time.sleep(2)
        raise RuntimeError(f"Bitcoin nodes did not reach height {expected_height}")

    def _wait_until_traffic_nodes_have_balance(self) -> None:
        for _ in range(60):
            balances = [node.balance() for node in self.traffic_nodes]
            if all(balance > 0 for balance in balances):
                return
            time.sleep(2)
        raise RuntimeError("Traffic nodes did not receive spendable balance")

    def _send_mesh_transactions_safely(self) -> None:
        try:
            self._send_mesh_transactions()
        except (RuntimeError, subprocess.CalledProcessError) as exception:
            print(f"[run] transaction round skipped: {exception}")

    def _send_mesh_transactions(self) -> None:
        for index, sender in enumerate(self.nodes):
            if sender.balance() <= 0.001:
                continue
            receiver = self.nodes[(index + 1) % len(self.nodes)]
            sender.send_to(receiver.new_address(), self._transaction_amount())

    def _transaction_amount(self) -> float:
        return self.rng.uniform(0.0001, 0.001)

    def _generate_block_safely(self) -> None:
        try:
            self.miner.generate_blocks(1)
        except subprocess.CalledProcessError as exception:
            print(f"[run] block generation skipped: {exception}")


class SnifferDeployment:
    release_name = "isp-sniffer-capture"

    def __init__(self, namespace: str, paths: SimulationPaths, commands: CommandRunner):
        self.namespace = namespace
        self.paths = paths
        self.commands = commands
        self.selector = f"app=isp-sniffer,capture-release={self.release_name}"
        self.installed = False

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
    ):
        self.duration_minutes = duration_minutes
        self.namespace = namespace
        self.paths = paths
        self.seed = seed or self._generate_seed()
        self.run_started_at = datetime.now(UTC).isoformat()
        self.commands = CommandRunner()
        self._run_directory: Path | None = None

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
            self._deploy_network()
            network_deployed = True
            traffic_generator = BitcoinTrafficGenerator(
                self.namespace,
                self.commands,
                self._derive_seed("bitcoin-traffic"),
            )
            traffic_generator.prepare()
            self._run_capture_window(traffic_generator)
        except Exception:
            run_status = "failed"
            raise
        finally:
            try:
                if sniffer_pod:
                    self._collect_results(sniffer_pod)
            finally:
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
            "namespace": self.namespace,
            "seed": self.seed,
            "component_seeds": self._component_seeds(),
            "reproducibility_note": (
                "The seed fixes generated payloads, transaction amounts, and configured "
                "noise choices. Kubernetes scheduling and packet timing can still change "
                "the exact byte-for-byte PCAP."
            ),
            "startup_order": [
                "isp-sniffer",
                "noise-generator",
                "bitcoin-nodes",
                "bitcoin-traffic",
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
        for tank_pod in self._tank_pods():
            self._copy_from_pod(
                tank_pod,
                "/root/.bitcoin/regtest/debug.log",
                self.run_directory / f"{tank_pod}-debug.log",
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
        ip_map.write_text(
            f"PODS\n{pod_table}\n\nSERVICES\n{service_table}\n",
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
        self.commands.run(self.paths.warnet_binary, "down", check=False)

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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = SimulationRunner(
        duration_minutes=args.duration_minutes,
        namespace=args.namespace,
        paths=SimulationPaths.from_script_location(args.output_dir),
        seed=args.seed,
    )
    try:
        runner.run()
    except UserFacingError as exception:
        print(f"[error] {exception}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
