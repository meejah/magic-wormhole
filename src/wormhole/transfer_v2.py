from __future__ import absolute_import, print_function, unicode_literals

import struct

from zope.interface import implementer

from twisted.internet.defer import Deferred, maybeDeferred, DeferredList, ensureDeferred, gatherResults
from twisted.internet.protocol import Protocol, Factory
from twisted.python.filepath import FilePath

import msgpack

from .observer import OneShotObserver
from .eventual import EventualQueue
from wormhole.dilatedfile import (
    FileOffer,
    DirectoryOffer,
    OfferAccept,
    OfferReject,
    FileData,
    FileAcknowledge,
    Message,
    DilatedFileTransfer,
    DilatedStatusTracker,
)


def decode_message(msg):
    """
    :returns: an instance of one of the message types
    """
    kind = msg[0]
    empty_payloads = [0x03]
    Class = {
        0x01: FileOffer,
        0x02: DirectoryOffer,
        0x03: OfferAccept,
        0x04: OfferReject,
        0x05: FileData,
        0x06: FileAcknowledge,
    }[kind]
    if kind in empty_payloads:
        return Class()
    else:
        if kind == 0x05:
            return FileData(msg[1:])
        else:
            payload = msgpack.loads(msg[1:])
            return Class(**payload)


def encode_message(msg):
    """
    :returns: a bytes consisting of the kind byte plus msgpack-encoded
        payload for the given message, which must be one of XXX
    """
    kind = {
        FileOffer: 0x01,
        DirectoryOffer: 0x02,
        OfferAccept: 0x03,
        OfferReject: 0x04,
        FileData: 0x05,
        FileAcknowledge: 0x06,
    }[type(msg)]
    raw_data = msg.marshal()
    kind_byte = struct.pack(">B", kind)
    if raw_data is None:
        return kind_byte
    else:
        if kind == 0x05:
            payload = raw_data
        else:
            payload = msgpack.dumps(msg.marshal())
        return kind_byte + payload


#XXX fixme notes
#
# if we want this to do ALL kinds of offers (probably), then:
# - need "offer async-iterator" or similar (e.g. chat application doesn't even know how _many_ offers there will be)
# - receiver should have an "accept_offer_p" that returns ... something ("open file" for file offers, "some kind of directory API instance" for directory offers, callback for text-message offers?)
#     - so it needs some 'context' object
#     - ...and separate sub-state-machines for each kind of offer
#     - ...and more generic "make_offer()" function?

# wormhole: _DeferredWormhole,
async def deferred_transfer(reactor, wormhole, on_error, offer_placement, on_message=None, transit=None, code=None, offers=None, next_message=None, on_status=None):
    """
    Do transfer protocol over an async wormhole interface

    :param IReactorCore reactor:

    :param IDeferredWormhole wormhole: the wormhole instance to use

    :param Callable on_error: fixme what is this for?

    :param Callable[] offer_placement: find the location to put the
        offer, or reject it. todo: documentation, and is this really a good way?
        (also: reject non-coro-functions)
    """

    # XXX FIXME
    if code is None:
        wormhole.allocate_code(2)
        code = await wormhole.get_code()
    else:
        wormhole.set_code(code)
        await wormhole.get_code()
    print("code", code)

    versions = await wormhole.get_versions()

    try:
        transfer = versions["transfer"]  # XXX transfer-v2
    except KeyError:
        # XXX fall back to "classic" file-trasfer
        raise RuntimeError("Peer doesn't support Dilated transfer")


    status_tracker = DilatedStatusTracker()
    if on_status is not None:
        status_tracker.add_listener(on_status)

    boss = DilatedFileTransfer()
    boss.got_peer_versions(transfer)

    dilated = wormhole.dilate(transit)

    recv_factory = Factory.forProtocol(Receiver)
    recv_factory.status = status_tracker
    recv_factory.boss = boss

    # this CAN'T be async, because it's part of the Receiver
    # state-machine, so we eat the (possible) async-ness of the app
    # code here.
    # todo: handle errors better
    # todo: allow app callback to be "not-async"
    # todo: what if app callback is _sync_?? (e.g. input())
    #       -> either proper error, or deferToThread()
    def accept_or_reject(receiver, offer):

        async def ask_app_code():
            try:
                result = await ensureDeferred(offer_placement(offer))
            except Exception as e:
                print(f"Error asking for offer: {e}")
                result = None
            if result:
                reactor.callLater(0, receiver.accept_offer, offer, result)
            else:
                reactor.callLater(0, receiver.reject_offer, offer)
        d = ensureDeferred(ask_app_code())
    recv_factory.accept_or_reject_p = accept_or_reject

    listen_ep = dilated.listener_for("transfer")
    await listen_ep.listen(recv_factory)  # returns "port"

    # XXX shutdown still "exercise to the reader" :/
    # but aping what Fowl does, we want to:
    # - send "closing" with highest phase number message we've seen
    # - wait for "closing" from peer
    # - bonus: confirm they didn't cheat and send extra messages
    # - once a peer has two "closing" messages (i.e. their's + peer's) they CLOSE mailbox and exit
    when_done = Deferred()
    connect_ep = dilated.connector_for("transfer")

    if offers:
        # could be a param / option / Semaphore to send certain number
        # "at once" or not?
        outstanding = []
        for offer in offers:
            if offer.is_file():
                outstanding.append(
                    ensureDeferred(
                        send_file_offer(connect_ep, wormhole, boss, offer, status_tracker)
                    )
                )
            else:
                outstanding.append(
                    ensureDeferred(
                        send_directory_offer(connect_ep, wormhole, boss, offer, status_tracker)
                    )
                )
        await gatherResults(outstanding)

    # can we just read paths off stdin and thus support cheap
    # drag-and-drop sort of behavior?
    # todo: "termios" will break on windows so just don't support it there?
    from twisted.internet.stdio import StandardIO
    import termios
    import sys
    import tty
    from pathlib import Path

    class FileDrop(Protocol):
        def dataReceived(self, data):
            offer = Path(data.decode("utf8"))  # todo: why utf8??
            if offer.exists():
                print(f"dragged file: {offer}")
                if offer.is_file():
                    d = ensureDeferred(send_file_offer(connect_ep, wormhole, boss, offer, status_tracker))
                else:
                    d = ensureDeferred(send_directory_offer(connect_ep, wormhole, boss, offer, status_tracker))
                print(d)
                d.addErrback(print)

    old_settings = termios.tcgetattr(sys.stdin.fileno())
    # see also https://github.com/Textualize/rich/issues/1103
    tty.setcbreak(sys.stdin.fileno())

    try:
        dropper = FileDrop()
        _ = StandardIO(dropper)

        await when_done  # never fires; need shutdown path implemented
        await wormhole.close()

    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)


class Receiver(Protocol):
    _machine = None

    def send_message(self, msg):
        self.transport.write(encode_message(msg))

    def connectionMade(self):
        self._machine = self.factory.boss.offer_received(self.factory.accept_or_reject_p, self.send_message, self.factory.status)
        ##self._machine.set_trace(lambda *args: print("TRACE", args))

    def dataReceived(self, raw_data):
        # should be an entire record (right??)
        msg = decode_message(raw_data)
        ##print(f"recv: {type(msg)}")
        self._machine.on_message(msg)

    def connectionLost(self, why):
        ##print(f"subchannel closed {why}")
        self._machine.subchannel_closed()


from twisted.internet.interfaces import IPullProducer

@implementer(IPullProducer)
class FileDataSource:
    """
    A source of data which is a file, implemented using IPullProducer
    """

    def __init__(self, fp, on_bytes_sent, chunk_size=2**11):
        self._fp = fp
        self._on_bytes = on_bytes_sent
        self._chunk_size = chunk_size
        self._when_done = []

    def when_done(self):
        d = Deferred()
        if self._when_done is None:
            d.callback(None)
        else:
            self._when_done.append(d)
        return d

    def start(self, consumer, machine):
        self.consumer = consumer
        self.machine = machine
        self.consumer.registerProducer(self, False)

    def resumeProducing(self):
        """
        IPullProducer API: produce one chunk (only)
        """
        data = self._fp.read(self._chunk_size)
        ##print("resumeProducing", len(data) if data else -1)
        if data:
            # we want all data to go through the state-machine; it
            # will call send_message which will write to our consumer
            # (the protocol transport)
            self._on_bytes(len(data))
            self.machine.send_data(data)
        else:
            self.stopProducing()

    def stopProducing(self):
        ##print("stopProducing")
        self.consumer.unregisterProducer()
        self._fp.close()
        notify = self._when_done
        self._when_done = None
        for d in notify:
            d.callback(None)


class Sender(Protocol):
    _connection = None
    _disconnection = None
    _sender = None

    def when_connected(self):
        d = Deferred()
        if self._connection is None:
            self._connection = [d]
        elif self._connection is True:
            d.callback(None)
        else:
            self._connection.append(d)
        return d

    def when_closed(self):
        d = Deferred()
        if self._disconnection is None:
            self._disconnection = [d]
        elif self._disconnection is True:
            d.callback(None)
        else:
            self._disconnection.append(d)
        return d

    def connectionMade(self):
        print("subchannel open", self)
        notify = self._connection or tuple()
        self._connection = True
        for d in notify:
            d.callback(None)

    def dataReceived(self, raw_data):
        # should be an entire record (right??)
        ##print(f"recv: {raw_data}")
        msg = decode_message(raw_data)
        ##print(f"parsed: {msg}")
        out_msg = self._sender.on_message(msg)
        if out_msg:
            print(f"have outgoing: {out_msg}")
            self.transport.write(encode_message(out_msg))

    def connectionLost(self, why):
        print(f"subchannel closed {why}")
        self._sender.subchannel_closed()
        notify = self._disconnection
        self._disconnection = True
        if notify:
            for d in notify:
                d.callback(None)


async def send_file_offer(connect_ep, wormhole, boss, fpath, status_tracker):
    proto = await connect_ep.connect(Factory.forProtocol(Sender))
    print("proto", proto)
    await proto.when_connected()

    # XXX need a whole different state-machine for directories i think..
    assert fpath.is_file(), "file must exist and be a file"
    offer = FileOffer(fpath.name, fpath.stat().st_mtime, fpath.stat().st_size)
    offer_id = status_tracker.outgoing_added(fpath.name, "file", fpath.stat().st_size)

    def got_bytes(count):
        #print(f"got bytes {count}")
        status_tracker.update_bytes(offer_id, count)
    file_data_streamer = FileDataSource(fpath.open("rb"), got_bytes)

    def send_message(msg):
        proto.transport.write(encode_message(msg))

    def start_streaming():
        ##print("ready to send data...")
        file_data_streamer.start(proto.transport, sender)
        ##print("started")
        d = file_data_streamer.when_done()
        d.addCallbacks(
            lambda _: sender.data_finished(),
            lambda _: sender.error(),
        )

    def finished():
        ##print("finished")
        status_tracker.offer_acknowledged(offer_id)
        proto.transport.loseConnection()


    proto._sender = sender = boss.make_offer(send_message, start_streaming, finished)

    ##print("sending offer", sender)
    sender.send_offer(offer)

    await proto.when_closed()
    print("done")


async def send_directory_offer(connect_ep, wormhole, boss, fpath, status_tracker):
    proto = await connect_ep.connect(Factory.forProtocol(Sender))
    ##print("proto", proto)
    await proto.when_connected()

    assert fpath.is_dir(), "path is not a directory"

    # e.g. src/wormhole becomes "wormhole" here
    base = fpath.name
    size = 0
    files = []
    streamers = []

    def got_bytes(count):
        ##print(f"got bytes {count}")
        status_tracker.update_bytes(offer_id, count)

    def recursive_walk(root):
        nonlocal size
        for path, subdirs, fnames in root.walk():
            for fname in fnames:
                rel = path / fname
                size += rel.lstat().st_size
                files.append(str(rel))
                streamers.append(
                    FileDataSource(rel.open("rb"), got_bytes)
                )
            for subdir in subdirs:
                recursive_walk(root / subdir)
    recursive_walk(fpath)
    ##print(f"{len(files)} files, {size} bytes")

    offer = DirectoryOffer(base, size, files)
    offer_id = status_tracker.outgoing_added(fpath.name, "directory", size)

    def send_message(msg):
        data = encode_message(msg)
        ##print(f"sending {len(data)} bytes")
        proto.transport.write(data)

    def start_streaming():
        ##print("ready to send data...")

        async def send_files():
            for fname, streamer in zip(files, streamers):
                ##print(f"  {fname}")
                status_tracker.update_current_file(offer_id, fname)
                send_message(
                    FileOffer(
                        str(fname),
                        0,  # todo: timestamp
                        0,  # todo: bytes
                    )
                )
                streamer.start(proto.transport, sender)
                await streamer.when_done()

        d = ensureDeferred(send_files())
        d.addCallbacks(
            lambda _: sender.data_finished(),
            lambda _: sender.error(),
        )

    def finished():
        ##print("finished")
        # todo: we didn't actually track if each one is acknowledged...
        status_tracker.offer_acknowledged(offer_id)
        proto.transport.loseConnection()


    proto._sender = sender = boss.make_offer(send_message, start_streaming, finished)

    sender.send_offer(offer)
    await proto.when_closed()
