
# prototype state-machine "diagrams" / skeleton code for Dilated File
# Transfer

from attr import define, field, Factory
from automat import MethodicalMachine
from typing import BinaryIO, List, Any

from twisted.internet.defer import Deferred, ensureDeferred
from twisted.internet.protocol import Protocol, Factory

from .observer import OneShotObserver


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
    timestamp: int   # Unix timestamp (seconds since the epoch in GMT)
    bytes: int       # total number of bytes in the file
    _file: BinaryIO # file-like (how do we do typing protocols?)
    kind: int = 0x01 # "file offer"


@define
class DirectoryOffer:
    base: str        # unicode relative pathname
    timestamp: int   # Unix timestamp (seconds since the epoch in GMT)
    bytes: int       # total number of bytes in all files
    kind: int = 0x02 # "directoryoffer"


@define
class OfferReject:
    reason: str      # unicode string describing why the offer is rejected
    kind: int = 0x04 #  "offer reject"


@define
class OfferAccept:
    kind: int = 0x03 #  "offer accpet"


# control-channel messages
@define
class Message:
    message: str        # unicode string
    kind: str = "text"


@define
class DilatedFileReceiver:
    """
    Manages the receiving of a single FileOffer
    """
    m = MethodicalMachine()

    @m.state(initial=True)
    def start(self):
        """
        Initial state
        """

    @m.state()
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
    def begin(self, subchannel):
        """
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has closed
        """

    @m.input()
    def accept_offer(self, offer):
        """
        A decision to accept the offer
        """

    @m.input()
    def reject_offer(self, offer):
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

    @m.input()
    def data_finished(self):
        """
        All expected data is received
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has closed
        """

    @m.output()
    def _remember_subchannel(self, subchannel):
        self._subchannel = subchannel
        # hook up "it closed" to .subchannel_closed
        # hook up "got message" to .. something

    @m.output()
    def _ask_about_offer(self, offer):
        """
        Use an async callback to ask if this offer should be accepted;
        hook up a "yes" to self.offer_accepted and "no" to
        self.offer_rejected
        """

    @m.output()
    def _send_accept(self):
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

    start.upon(
        begin,
        enter=wait_offer,
        outputs=[_remember_subchannel],
    )

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
        outputs=[_check_offer_integrity],
    )

    closing.upon(
        subchannel_closed,
        enter=closed,
        outputs=[],
    )


@define
class DilatedFileSender:
    """
    Manages the sending of a single file
    """
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
    def data_finished(self):
        """
        There is no more data to send
        """

    @m.input()
    def subchannel_closed(self):
        """
        The subchannel has been closed
        """

    @m.output()
    def _remember_subchannel(self, subchannel):
        self._subchannel = subchannel
        # hook up "it closed" to .subchannel_closed
        # hook up "got message" to .. something

    @m.output()
    def _send_offer(self, offer):
        print("SEND", offer)

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
        outputs=[_send_offer],  # XXX why did we "_remember_subchannel" before?
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
    sending.upon(
        data_finished,
        enter=closing,
        outputs=[_close_input_file, _close_subchannel, _notify_accepted],
    )

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
        self._done = OneShotObserver(self._reactor)


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
        Make an offer to the other peer.
        """

    @m.input()
    def offer_received(self, offer):
        """
        The peer has made an offer to us.
        """

    @m.input()
    def dilation_closed(self):
        """
        The dilated connection has been closed down
        """

    @m.output()
    def _create_receiver(self, offer):
        """
        Make a DilatedFileReceiver
        """
        # make DilatedFileReceiver
        # hook it up to its subchannel data (how? we need a loop in _this_ state-machine probably?)

    @m.output()
    def _create_sender(self, offer):
        """
        Make a DilatedFileSender
        """
        fs = DilatedFileSender()
        fs.begin_offer(offer)
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

        for offer in offers:
            print("send offer", offer)
            thing = transfer.send_offer(offer)
            print(thing)

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
