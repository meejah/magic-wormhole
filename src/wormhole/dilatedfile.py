
# prototype state-machine "diagrams" / skeleton code for Dilated File
# Transfer

from attr import define, field, Factory
from automat import MethodicalMachine
from typing import BinaryIO, List, Any, Optional
from functools import singledispatch

import msgpack

from twisted.internet.defer import Deferred, ensureDeferred, DeferredList
from twisted.internet.protocol import Protocol, Factory
from twisted.protocols.basic import FileSender
from twisted.internet.interfaces import IPullProducer

from zope.interface import implementer

from .observer import OneShotObserver
from .eventual import EventualQueue


def get_appversion(mode=None, features=None, ask_permission=False):
    """
    Create a dict suitable to union into the ``app_versions``
    information of a Wormhole negotiation. Will be a dict with
    "transfer" mapping to a dict containing our current app-version
    information
    """
    if mode is None:
        mode = "send"
    if mode not in ["send", "receive", "connect"]:
        raise ValueError(
            "Illegal 'mode' for file-transfer: '{}'".format(mode)
        )
    # it's okay to have "unknown" features ... so just check it's "a
    # list of strings"
    if features is None:
        features = ["core0"]
    if not isinstance(features, list) or any(not isinstance(x, str) for x in features):
        raise ValueError(
            "'features' must be a list of str"
        )
    if "core0" not in features:
        raise ValueError(
            "Must support 'core0' feature"
        )

    return {
        "transfer": {
            "mode": mode,
            "features": features,
            "permission": "ask" if ask_permission else "yes",
        }
    }


@define
class FileOffer:
    filename: str    # unicode relative pathname
    bytes: int       # total number of bytes in the file
    _file: Optional[BinaryIO] = None # file-like (how do we do typing protocols?)


@define
class DirectoryOffer:
    base: str         # unicode relative pathname
    bytes: int        # total number of bytes in all files
    files: list[str]  # names of all files relative to base

# Offer == union of DirectoryOffer, FileOffer


def unpack_offer(offer: bytes):
    """
    Deserialize a binary-encoded (wire-format) Offer

    :return Offer: either a FileOffer or DirectoryOffer instance
    """
    kinds = {
        "file-offer": (FileOffer, [str, int]),
        "directory-offer": (DirectoryOffer, [str, int, list]),
    }
    data = msgpack.unpackb(offer)
    kind = data[0]
    args = data[1:]
    try:
        build_offer, schema = kinds[kind]
    except KeyError:
        raise ValueError(f'Unknown offer: "{kind}".')
    _validate_arg_types(args, schema)
    return build_offer(*args)


def _validate_arg_types(args, schema):
    """
    Raises a ValueError if the types of objects in 'args' does not
    match the types in 'schema'
    """
    if len(args) != len(schema):
        raise ValueError(f"{len(args)} args versus {len(schema)} schema types")
    for a, s in zip(args, schema):
        if not isinstance(a, s):
            raise ValueError(f"Type mismatch: wanted {s} but have {type(a)}")
    return


@singledispatch
def encode_offer(offer):
    raise ValueError("Unknown offer type")

@encode_offer.register
def _(offer: FileOffer):
    return b'\x01' + msgpack.packb([
        "file-offer",
        offer.filename,
        offer.bytes,
    ])

@encode_offer.register
def _(offer: DirectoryOffer):
    return b'\x01' + msgpack.packb([
        "directory-offer",
        offer.base,
        offer.files,
    ])


@define
class OfferReject:
    reason: str      # unicode string describing why the offer is rejected


@define
class OfferAccept:
    pass


def unpack_offer_reply(reply):
    kinds = {
        "offer-accept": OfferAccept,
        "offer-reject": OfferReject,
    }
    data = msgpack.unpackb(reply)
    if data[0] not in kinds.keys():
        raise ValueError('Unknown offer reply: "{}".'.format(data[0]))
    kind = data[0]
    args = data[1:]
    # XXX could use more validation? does msgpack have schemas?
    return kinds[kind](*args)


@singledispatch
def encode_offer_reply(offer):
    raise ValueError("Unknown reply type")


@encode_offer_reply.register
def _(reply: OfferAccept):
    return b'\x01' + msgpack.packb(["offer-accept"])


@encode_offer_reply.register
def _(reply: OfferReject):
    return b'\x01' + msgpack.packb(["offer-reject", reply.reason])



# control-channel messages
@define
class Message:
    message: str        # unicode string
    kind: str = "text"


# XXX
# -> treat these as "sub" machines of the overall thing, and emit a
#    "done" message when closing (so the overall machine can clean up its
#    "ongoing Offers" list)

@define(slots=False)
class DilatedFileReceiver:
    """
    Manages the receiving of a single FileOffer
    """
    m = MethodicalMachine()
#   accept_offer: async callable ... well this should be in parent, right? we need a message out that says "ask your human?"
#    _parent_machine: DilatedFileTransfer
    _transfer_success: bool = False

    @m.state(initial=True)
    def wait_offer(self):
        """
        Waiting for the offer message
        """

    @m.state()
    def wait_permission(self):
        """
        Wait for the answer from our permission
        """

    @m.state()
    def permission(self):
        """
        Waiting for a yes/no about an offer
        """

    @m.state()
    def receiving(self):
        """
        Accepting incoming offer data
        """

    @m.state()
    def closing(self):
        """
        Waiting for confirmation the subchannel is closed
        """

    @m.state(terminal=True)
    def closed(self):
        """
        Completed operation.
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has closed
        """

    @m.input()
    def accept_offer(self):
        """
        A decision to accept the offer
        """

    @m.input()
    def reject_offer(self):
        """
        A decision to reject the offer
        """

    # XXX NB: these inputs are like "message_received(...)" if we
    # could pattern-match in a state-machine
    @m.input()
    def recv_offer(self, offer):
        """
        The initial offer message has been received
        """

    @m.input()
    def recv_data(self, data):
        """
        The peer has sent file data to us.
        """

    @m.output()
    def _ask_about_offer(self, offer):
        """
        Use an async callback to ask if this offer should be accepted;
        hook up a "yes" to self.offer_accepted and "no" to
        self.offer_rejected
        """

    @m.output()
    def _send_accept(self):
        # XXX shouldn't be doing IO here .. so all this could do is "return" some messages to send along ... which might be more "pure", but ... why not just send them (in the IO code, that already has it)
        pass

    @m.output()
    def _send_reject(self):
        pass

    @m.output()
    def _handle_data(self, data):
        print("file data", len(data))
        pass

    @m.output()
    def _check_offer_integrity(self):
        print("done offer")
        # if integration confirmed, set self._transfer_success

    @m.output()
    def _transfer_completed(self):
        """
        Tell the session state-machine this transfer is done
        """
        # send result of self._transfer_success to session state-machine

    wait_offer.upon(
        recv_offer,
        enter=wait_permission,
        outputs=[_ask_about_offer],
    )

    wait_permission.upon(
        accept_offer,
        enter=receiving,
        outputs=[_send_accept],
    )
    wait_permission.upon(
        reject_offer,
        enter=closing,
        outputs=[_send_reject],  # _we_ don't close subchannel .. sender does, right? we could (too) though?
    )

    receiving.upon(
        recv_data,
        enter=receiving,
        outputs=[_handle_data],
    )
    receiving.upon(
        subchannel_closed,
        enter=closed,
        outputs=[_check_offer_integrity, _transfer_completed],
    )

    closing.upon(
        subchannel_closed,
        enter=closed,
        outputs=[_transfer_completed],
    )


@define(slots=False)
class DilatedFileSender:
    """
    Manages the sending of a single file
    """
#    _parent_machine: DilatedFileTransfer
    _transfer_success: bool = False
    _offer: FileOffer = None

    m = MethodicalMachine()

    @m.state(initial=True)
    def start(self):
        """
        Initial state
        """

    @m.state()
    def permission(self):
        """
        Waiting for a yes/no about an offer
        """

    @m.state()
    def sending(self):
        """
        Streaming file data
        """

    @m.state()
    def closing(self):
        """
        Waiting for confirmation the subchannel is closed
        """

    @m.state(terminal=True)
    def closed(self):
        """
        Completed operation.
        """

    @m.input()
    def begin_offer(self, offer):
        """
        Open in 'yes' mode
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has closed
        """

    @m.input()
    def offer_accepted(self, offer):
        """
        The peer has accepted our offer
        """

    @m.input()
    def offer_rejected(self, offer):
        """
        The peer has rejected our offer
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has closed
        """

    @m.input()
    def send_data(self):
        """
        Try to send some more data
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has been closed
        """

    @m.output()
    def _send_offer(self, offer):
        print("SEND", offer)
        self._offer = offer

    @m.output()
    def _close_input_file(self):
        pass

    @m.output()
    def _close_subchannel(self):
        pass

    @m.output()
    def _send_some_data(self):
        """
        If we have data remaining, send it.
        """
        # after one reactor turn, recurse:
        # - if data, _send_some_data again
        # - otherwise data_finished

    @m.output()
    def _notify_accepted(self):
        """
        Peer has accepted and streamed entire file
        """

    @m.output()
    def _notify_rejected(self):
        """
        Peer has rejected the file
        """


    start.upon(
        begin_offer,
        enter=permission,
        outputs=[_send_offer],
    )

    permission.upon(
        offer_accepted,
        enter=sending,
        outputs=[_send_some_data],
    )
    permission.upon(
        offer_rejected,
        enter=closing,
        outputs=[_close_input_file, _close_subchannel, _notify_rejected],
    )

    sending.upon(
        send_data,
        enter=sending,
        outputs=[_send_some_data],
    )
    # sending.upon(
    #     data_finished,
    #     enter=closing,
    #     outputs=[_close_input_file, _close_subchannel, _notify_accepted],
    # )

    closing.upon(
        subchannel_closed,
        enter=closed,
        outputs=[],  # actually, "_notify_accepted" here, probably .. so split "closing" case?
    )


# need slots=False to play nicely with MethodicalMachine
@define(slots=False)
class DilatedFileTransfer(object):
    """
    Manages transfers for the Dilated File Transfer protocol
    """

    # state-machine stuff
    m = MethodicalMachine()
    set_trace = getattr(m, "_setTrace", lambda self, f: None)

    _reactor: Any  # IReactor / EventualQueue .. what type do we really want?

    def __attrs_post_init__(self):
        self._done = OneShotObserver(EventualQueue(self._reactor))
        self._senders = dict()

    def when_done(self):
        return self._done.when_fired()

    def got_peer_versions(self, versions):
        if versions["mode"] == "send":
            self.peer_send()
        elif versions["mode"] == "receive":
            self.peer_receive()
        elif versions["mode"] == "connect":
            self.peer_connect()

    @m.state(initial=True)
    def await_peer(self):
        """
        We haven't connected to our peer yet
        """

    @m.state()
    def dilated(self):
        """
        Dilated connection is open
        """

    @m.state()
    def receiving(self):
        """
        Peer will only send
        """

    @m.state()
    def sending(self):
        """
        Peer will only receive
        """

    @m.state()
    def connect(self):
        """
        Peer will send and/or receive
        """

    @m.state()
    def closing(self):
        """
        Shutting down.
        """

    @m.state()
    def closed(self):
        """
        Completed operation.
        """

    @m.input()
    def connected(self, appversions, endpoints):
        """
        XXX rethink -- can't 'input to ourselves' so we want the
        higher-level thing to parse appversions?

        and we don't want to "give the endpoints" to this, we want to
        pass it functions to call (i.e. so the async / whatever stuff
        is done "outside" the state-machine)
        """

    @m.input()
    def peer_send(self):
        """
        Peer is in mode 'send'
        """

    @m.input()
    def peer_receive(self):
        """
        Peer is in mode 'receive'
        """

    @m.input()
    def peer_connect(self):
        """
        Peer is in mode 'connect'
        """

    @m.input()
    def got_file_offer(self, offer):
        """
        We have received a FileOffer from our peer
        """
        # XXX DirectoryOffer conceptually similar, but little harder

    @m.input()
    def send_offer(self, offer):
        """
        Create an offer machine.
        """

    @m.input()
    def completed_send(self, sender):
        """
        An offer started by send_offer() has completed (`sender` is the
        one gotten from send_offer)
        """

    @m.input()
    def offer_received(self):
        """
        The peer has made an offer to us (i.e. opened a subchannel).
        """

    @m.input()
    def completed_receive(self, receiver):
        """
        An offer started by offer_received() has completed (`receiver` is
        gotten from offer_received())
        """

    @m.input()
    def dilation_closed(self):
        """
        The dilated connection has been closed down
        """

    @m.output()
    def _create_receiver(self):
        """
        Make a DilatedFileReceiver
        """
        fr = DilatedFileReceiver()
        # self._receivers ... = fr
        return fr

    @m.output()
    def _create_sender(self, offer):
        """
        Make a DilatedFileSender
        """
        i = object()
        fs = self._senders[i] = DilatedFileSender()
        # keep track of this .. somehow? maybe we _do_ want "offer" as an arg?
        return fs

    @m.output()
    def _protocol_error(self):
        """
        The peer hasn't spoken correctly.
        """

    @m.output()
    def _close_dilation(self):
        """
        Shut down the dilated conection.
        """

    @m.output()
    def _cleanup_outgoing(self):
        """
        Abandon any in-progress sends
        """

    @m.output()
    def _cleanup_incoming(self):
        """
        Abandon any in-progress receives
        """

    @m.output()
    def _cleanup_receiver(self, receiver):
        """
        A particular receiver is done
        """
        # XXX rename subchannel_closed
        receiver.subchannel_closed()
        # self._receivers.remove(receiver)

    await_peer.upon(
        connected,
        enter=dilated,
        outputs=[] #_confirm_modes]
    )

    ### so either we put the "queue offers" etc _in_ the state-machine
    ### (maybe along with e.g. "confirm modes")
    ### ...OR we somehow "wait" outside until our peer arrives before trying to send offers? seems weird...
    ###
    ### ...and i guess a "queue" thing means we need to fix that
    ### automat bug? because then "send the queued offers" is like a
    ### loop that signals the state-machine itself...
    ###
    ### hmmmmm, while trying to write this example out for Glyph it
    ### occurs: can we call _outputs_ directly? e.g. "while"
    ### transitioning can we drain our "offers to send" queue my
    ### directly calling output methods?
    ###
    ### and we also need an "i'm done with offers" signal ... so a
    ### like "waiting for cleanup state"? (that's maybe "closing"?
    ### like in the sending / receiving states)

    # XXX we want some error-handling here, like if both peers are
    # mode=send or both are mode=receive
    dilated.upon(
        peer_receive,
        enter=sending,
        outputs=[]
    )

    dilated.upon(
        peer_send,
        enter=receiving,
        outputs=[]
    )

    dilated.upon(
        peer_connect,
        enter=connect,
        outputs=[],
    )

    sending.upon(
        send_offer,
        enter=sending,
        outputs=[_create_sender],
    )
    sending.upon(
        offer_received,
        enter=closing,
        outputs=[_protocol_error, _close_dilation],
    )
    sending.upon(
        dilation_closed,
        enter=closed,
        outputs=[_cleanup_outgoing],
    )

    receiving.upon(
        offer_received,
        enter=receiving,
        outputs=[_create_receiver],
    )
    receiving.upon(
        send_offer,
        enter=closing,
        outputs=[_protocol_error, _close_dilation],
    )
    receiving.upon(
        dilation_closed,
        enter=closed,
        outputs=[_cleanup_incoming],
    )
    receiving.upon(
        completed_receive,
        enter=receiving,
        outputs=[_cleanup_receiver],
    )

    connect.upon(
        offer_received,
        enter=connect,
        outputs=[_create_receiver],
    )
    connect.upon(
        send_offer,
        enter=connect,
        outputs=[_create_sender],
    )
    connect.upon(
        dilation_closed,
        enter=closed,
        outputs=[_cleanup_outgoing, _cleanup_incoming],
    )

    closing.upon(
        dilation_closed,
        enter=closed,
        outputs=[],
    )




# basically FileSender from Twisted except with the correct kind of
# producer, and it puts the right tag in the start of a message
@implementer(IPullProducer)
class SendUncompressedFile:
    """
    A producer that sends the contents of a file to a consumer.

    Note that the magic-wormhole APIs become a little "weird" in that
    they're message-based, but use the IStream* interfaces .. so like
    'transport.write(...)' is really going to write a whole, framed
    Data message ultimately ... and on the receive side,
    dataReceived() will be called with that whole message (RIGHT???
    triple-check plz...)
    """

    CHUNK_SIZE = 2**14

    lastSent = ""
    deferred = None

    def beginFileTransfer(self, filelike, consumer):
        """
        Begin transferring a file

        :param filelike: Any file-like object (to read data from)

        :param consumer: any IConsumer to write data to (typically the subchannel transport)

        :returns Deferred: triggered when the file has been completely
            written to the consumer.
        """
        self._file = filelike
        self._consumer = consumer

        self._deferred = deferred = Deferred()
        self._consumer.registerProducer(self, False)
        return deferred

    def resumeProducing(self):
        chunk = ""
        if self._file:
            chunk = self._file.read(self.CHUNK_SIZE)
        if not chunk:
            self._file = None
            self._consumer.unregisterProducer()
            if self._deferred:
                self._deferred.callback(None)
                self._deferred = None
            return
        # XXX probably want a "compressed" one too, that writes 0x06-type frames?
        self._consumer.write(b'\x05' + chunk)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        if self._deferred:
            self._deferred.errback(Exception("Consumer asked us to stop producing"))
            self._deferred = None


# wormhole: _DeferredWormhole,
def deferred_transfer(reactor, wormhole, on_error, maybe_code=None, offers=[]):
    """
    Do transfer protocol over an async wormhole interface
    """

    control_proto = None

    async def get_control_proto():
        nonlocal control_proto

        # XXX FIXME
        if maybe_code is None:
            wormhole.allocate_code(2)
        else:
            wormhole.set_code(maybe_code)
        code = await wormhole.get_code()
        print("code", code)

        versions = await wormhole.get_versions()
        print("versions", versions)
        try:
            transfer = versions["transfer"]
        except KeyError:
            raise RuntimeError("Peer doesn't support transfer-v2")

        mode = transfer.get("mode", None)
        features = transfer.get("features", ())

        if mode not in ["send", "receive", "connect"]:
            raise Exception("Unknown mode '{}'".format(mode))
        if "core0" not in features:
            raise Exception("Must support 'core0' feature")
        print("waiting to dilate")
        endpoints = wormhole.dilate()
        print("got endpoints", endpoints)

        return transfer, endpoints
        # class TransferControl(Protocol):
        #     pass
        # control_proto = await endpoints.control.connect(Factory.forProtocol(TransferControl))
        # return control_proto

    def send_control_message(message):
        print(f"send_control: {message}")

    def send_file_in_offer(offer, on_done):
        print(f"send_file: {offer}")
        on_done()
        return

    def receive_file_in_offer(offer, on_done):
        print(f"receive:file: {offer}")
        on_done()
        return

    transfer = DilatedFileTransfer(reactor)
    transfer.set_trace(print)

    async def got_control(versions_and_endpoints):
        versions, endpoints= versions_and_endpoints
        print("versions", versions)

        class TransferControl(Protocol):
            pass
        control_proto = await endpoints.control.connect(Factory.forProtocol(TransferControl))


        transfer.connected(versions, endpoints)
        try:
            mode = versions["mode"]
        except KeyError:
            raise ValueError('Missing "mode" from peer')

        if mode == "send":
            transfer.peer_send()
        elif mode == "receive":
            transfer.peer_receive()
        elif mode == "connect":
            transfer.peer_connect()

        # this is "do stuff when a subchannel opens" part
        class FileReceiverProtocol(Protocol):
            _receiver = None

            def connectionMade(self):
                self._receiver = transfer.offer_received()[0]
                print("subchannel open", self._receiver)

            def connectionLost(self, reason):
                print("lost")
                # differentiate between "ConnectionDone" and
                # otherwise, probably: e.g. "finished" versus "error"?
                ##self._receiver.subchannel_closed()
                transfer.completed_receive(self._receiver)

            def dataReceived(self, data):
                print("subchannel data", data[0], len(data))
                if data[0] == 0x01:
                    offer = unpack_offer(data[1:])
                    print("OFFER", offer)
                    todo = self._receiver.recv_offer(offer)
                    print("TODO", todo)
                    # now we ask our human ... and at some point
                    # deliver .accept_offer() or .reject_offer() to
                    # the machine
                    print("reply")
                    reply = OfferAccept()
                    todo = self._receiver.accept_offer()  # XXX some of these "offer" args can go away
                    print("todo", todo)
                    self.transport.write(encode_offer_reply(reply))
                    # now the sender will start streaming data and we write it out ...
                elif data[0] == 0x05:
                    print("Raw file bytes.")
                    assert self._receiver is not None, "data before header"
                    self._receiver.recv_data(data[1:])
                else:
                    raise RuntimeError("Unknown frame kind: {}".format(data[0]))

        factory = Factory.forProtocol(FileReceiverProtocol)
        listener = await endpoints.listen.listen(factory)
        print("LISTEN", listener)

        # this is the "send outstanding offers" part
        completed_after = list()
        for offer in offers:
            print("send offer", offer)
            sender = transfer.send_offer(offer)[0]

            class FileSenderProtocol(Protocol):
                def connectionMade(self):
                    print("connection", self.factory.machine)
                    ##for msg in self.factory.machine.begin_offer(offer):
                    ## or just:
                    self.transport.write(encode_offer(offer))

                def dataReceived(self, data):
                    print("sender data", data)
                    if data[0] == 0x01:
                        reply = unpack_offer_reply(data[1:])
                        print(reply)
                        if isinstance(reply, OfferReject):
                            print("REJECT", reply.message)
                            self.transport.disconnect()
                        elif isinstance(reply, OfferAccept):
                            print("ACCEPT!")
                            # Producer/Consumer-write all available
                            # data ... but frame each Data with a kind
                            filesend = SendUncompressedFile()
                            done = filesend.beginFileTransfer(offer._file, self.transport)

                            def foo(arg):
                                print("FOO: {}".format(arg))
                                self.transport.loseConnection()
                                self.factory.done.callback(None)
                            done.addCallbacks(foo)

            factory = Factory.forProtocol(FileSenderProtocol)
            factory.machine = sender
            factory.done = Deferred()
            completed_after.append(factory.done)

            subchannel = await endpoints.connect.connect(factory)
            print("sub", subchannel)

            thing = sender.begin_offer(offer)
            print(thing)

        def all_done(arg):
            print("ALL DONE", arg)
            if offers:
                transfer._done.fire(None)
        print("after", completed_after)
        DeferredList(completed_after).addCallbacks(all_done)

        # XXX hook up control_proto to callables that we can give to the state-machine (e.g. "send_control_message")
        # XXX hook up control_proto to state-machine (e.g. "got_control_message")


        # XXX hook up "a subchannel opened" to "got on offer" on the machine
        # -> create (and return?) the DilatedFileReceiver
        # -> hook up the subchannel protocol so it feeds messages into the machine ^ directly
        # -> hook subchannel protocol for disconnect etc too


        # XXX for "send offer" etc we need to hook up "endpoints" to
        # open a subchannel, but a DilatedFileSender on it, etc
        # -> similar to above, but I guess the state-machine returns messages (which are sent to the subchannel?)


        # XXX that is, _all_ async work must be hooked up in here, and be a non-async method

        # XXX error-handling / user feedback, how does that work?
        return versions_and_endpoints

    d = Deferred.fromCoroutine(get_control_proto())
    d.addCallback(lambda x: ensureDeferred(got_control(x)))
    d.addErrback(print)
    # XXX error-handling?

    return transfer
