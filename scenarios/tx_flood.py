#!/usr/bin/env python3

import threading
from random import choice, randrange
from time import sleep

from commander import Commander


class TXFlood(Commander):
    def set_test_params(self):
        self.num_nodes = 1
        self.addresses = []
        self.threads = []

    def add_options(self, parser):
        parser.description = (
            "Sends random transactions between all nodes with available balance in their wallet"
        )
        parser.usage = "warnet run /path/to/tx_flood.py [options]"
        parser.add_argument(
            "--interval",
            dest="interval",
            default=10,
            type=int,
            help="Number of seconds between TX generation (default 10 seconds)",
        )

    def send_transactions_forever(self, node):
        wallet = self.ensure_miner(node)
        for address_type in ["legacy", "p2sh-segwit", "bech32", "bech32m"]:
            self.addresses.append(wallet.getnewaddress(address_type=address_type))
        while True:
            sleep(self.options.interval)
            try:
                balance = wallet.getbalance()
                if balance < 1:
                    continue
                amounts = {}
                output_count = randrange(1, (len(self.nodes) // 2) + 1)
                for _ in range(output_count):
                    available_sats = int(float((balance / 20) / output_count) * 1e8)
                    amounts[choice(self.addresses)] = (
                        randrange(available_sats // 4, available_sats) / 1e8
                    )
                wallet.sendmany(dummy="", amounts=amounts)
                self.log.info(f"node {node.index} sent tx with {output_count} outputs")
            except Exception as exception:
                self.log.error(f"node {node.index} error: {exception}")

    def run_test(self):
        self.log.info(f"Starting TX mess with {len(self.nodes)} threads")
        for node in self.nodes:
            sleep(1)
            thread = self._start_transaction_thread(node)
            self.threads.append({"thread": thread, "node": node})

        while len(self.threads) > 0:
            for transaction_worker in self.threads:
                if not transaction_worker["thread"].is_alive():
                    node = transaction_worker["node"]
                    self.log.info(f"restarting thread for node {node.index}")
                    transaction_worker["thread"] = self._start_transaction_thread(node)
            sleep(30)

    def _start_transaction_thread(self, node):
        thread = threading.Thread(target=lambda: self.send_transactions_forever(node))
        thread.daemon = False
        thread.start()
        return thread


def main():
    TXFlood("").main()


if __name__ == "__main__":
    main()
