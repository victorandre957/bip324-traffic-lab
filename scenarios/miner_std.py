#!/usr/bin/env python3

from time import sleep

from commander import Commander


class Miner:
    def __init__(self, node, should_mature_wallet):
        self.node = node
        self.wallet = Commander.ensure_miner(self.node)
        self.address = self.wallet.getnewaddress()
        self.should_mature_wallet = should_mature_wallet


class MinerStd(Commander):
    def set_test_params(self):
        self.num_nodes = 0
        self.miners = []

    def add_options(self, parser):
        parser.description = "Generate blocks over time"
        parser.usage = "warnet run /path/to/miner_std.py [options]"
        parser.add_argument(
            "--allnodes",
            dest="allnodes",
            action="store_true",
            help="When true, generate blocks from all nodes instead of just nodes[0]",
        )
        parser.add_argument(
            "--interval",
            dest="interval",
            default=60,
            type=int,
            help="Number of seconds between block generation (default 60 seconds)",
        )
        parser.add_argument(
            "--mature",
            dest="mature",
            action="store_true",
            help="When true, generate 101 blocks ONCE per miner",
        )
        parser.add_argument(
            "--tank",
            dest="tank",
            type=str,
            help="Select one tank by name as the only miner",
        )

    def run_test(self):
        self.log.info("Starting miners.")
        if self.options.tank:
            self.miners = [Miner(self.tanks[self.options.tank], self.options.mature)]
        else:
            max_miners = len(self.nodes) if self.options.allnodes else 1
            for index in range(max_miners):
                self.miners.append(Miner(self.nodes[index], self.options.mature))

        while True:
            for miner in self.miners:
                block_count = 1
                if miner.should_mature_wallet:
                    block_count = 101
                    miner.should_mature_wallet = False
                try:
                    self.generatetoaddress(
                        miner.node,
                        block_count,
                        miner.address,
                        sync_fun=self.no_op,
                    )
                    height = miner.node.getblockcount()
                    self.log.info(
                        f"generated {block_count} block(s) from node {miner.node.index}. "
                        f"New chain height: {height}"
                    )
                except Exception as exception:
                    self.log.error(f"node {miner.node.index} error: {exception}")
                sleep(self.options.interval)


def main():
    MinerStd("").main()


if __name__ == "__main__":
    main()
