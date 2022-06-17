import sys
from twisted.internet.task import react

from wormhole import create
from wormhole.transfer_v2 import deferred_transfer
from wormhole.cli.public_relay import RENDEZVOUS_RELAY, TRANSIT_RELAY

@react
async def main(reactor):
    code = sys.argv[1]
    w = create(
        u"lothar.com/wormhole/text-or-file-xfer",
        RENDEZVOUS_RELAY,
        reactor,
        _enable_dilate=True,
        versions={
            "transfer": {
                "mode": "receive",
                "features": ["basic"],
                "permission": "ask",
            }
        }
    )
    w.set_code(code)
    code = await w.get_code()
    print(f"code: {code}")
    w.dilate()
    versions = await w.get_versions()
    print("versions: {}".format(versions))
