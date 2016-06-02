from __future__ import print_function
import os, sys, six, tempfile, zipfile, hashlib
from tqdm import tqdm
from twisted.python import log
from twisted.protocols import basic
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from ..errors import TransferError, WormholeClosedError
from ..wormhole import wormhole
from ..transit import TransitSender
from ..util import dict_to_bytes, bytes_to_dict, bytes_to_hexstr

APPID = u"lothar.com/wormhole/text-or-file-xfer"

@inlineCallbacks
def add_ssh(args, reactor=reactor):
    """
    I implement 'wormhole add-ssh'.
    """
    # notes to self:
    # if we're the server, we get a username

    print("DING", args, dir(args))
    user = args.args
    tor = None
    w = wormhole(APPID, args.relay_url, reactor)
    try:
        # XXX need to w.close() at the end...
        code = yield w.get_code()
        print("Code:", code)
        yield w.send("the ssh key")
        msg = yield w.get()
        
    finally:
        yield w.close()
