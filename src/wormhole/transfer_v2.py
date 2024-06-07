from __future__ import absolute_import, print_function, unicode_literals

from typing import Union, Callable, List, Dict, BinaryIO

from attr import define, field
from automat import MethodicalMachine
from zope.interface import implementer

from twisted.internet.defer import Deferred
from twisted.internet.protocol import Protocol, Factory

from . import _interfaces
from ._key import derive_phase_key, encrypt_data


@define
class FileOffer:
    id: int          # unique random identifier for this offer
    filename: str    # unicode relative pathname
    timestamp: int   # Unix timestamp (seconds since the epoch in GMT)
    bytes: int       # total number of bytes in the file
    _file: BinaryIO # file-like (how do we do typing protocols?)
    kind: int = 0x01 # "file offer"


@define
class DirectoryOffer:
    id: int          # unique random identifier for this offer
    base: str        # unicode relative pathname
    timestamp: int   # Unix timestamp (seconds since the epoch in GMT)
    bytes: int       # total number of bytes in all files
    kind: int = 0x02 # "directoryoffer"


@define
class OfferReject:
    id: int          # matching identifier for an existing offer from the other side
    reason: str      # unicode string describing why the offer is rejected
    kind: int = 0x04 #  "offer reject"


@define
class OfferAccept:
    id: int          # matching identifier for an existing offer from the other side
    kind: int = 0x03 #  "offer accpet"


# control-channel messages
@define
class Message:
    message: str        # unicode string
    kind: str = "text"


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
        features = ["basic"]
    if not isinstance(features, list) or any(not isinstance(x, str) for x in features):
        raise ValueError(
            "'features' must be a list of str"
        )

    return {
        "transfer": {
            "version": 1,
            "mode": mode,
            "features": features,
            "permission": "ask" if ask_permission else "yes",
        }
    }


# wormhole: _DeferredWormhole,
def deferred_transfer(wormhole, on_error, maybe_code=None, offers=[]):
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
        if transfer.get("version", None) != 1:
            raise RuntimeError("Unknown or missing transfer version")

        mode = transfer.get("mode", None)
        features = transfer.get("features", ())

        if mode not in ["send", "receive", "connect"]:
            raise Exception("Unknown mode '{}'".format(mode))
        if "basic" not in features:
            raise Exception("Must support 'basic' feature")
        print("waiting to dilate")
        endpoints = wormhole.dilate()
        print("got endpoints", endpoints)

        class TransferControl(Protocol):
            pass
        control_proto = await endpoints.control.connect(Factory.forProtocol(TransferControl))
        return control_proto

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

#    transfer = TransferV2()
    transfer = TransferV2(send_control_message, send_file_in_offer, receive_file_in_offer)

    transfer.set_trace(print)

    for offer in offers:
        transfer.make_offer(offer)

    d = Deferred.fromCoroutine(get_control_proto())

    @d.addCallback
    def got_control(control):
        print("control", control)
        transfer.dilated()
        return control

    return transfer


## XXX actually we want a state-machine for each offer
##


@define(slots=False)
class TransferV2(object):
    """
    Speaks both ends of the Transfer v2 application protocol
    """
    m = MethodicalMachine()

    # XXX might make more sense to have this on the outside, only
    # .. i.e. "something" handles all the async stuff? ... so here we
    # just get "a Callable to send stuff"
    # endpoints: EndpointRecord

    send_control_message: Callable[[Union[FileOffer, DirectoryOffer, OfferReject, OfferAccept]], None]
    send_file_in_offer: Callable[[Offer, Callable[[], None]], None]
    receive_file_in_offer: Callable[[Offer, Callable[[], None]], None]

    _queued_offers: List[Offer] = field(factory=list)
    _offers: Dict[str, Offer] = field(factory=dict)
    _peer_offers: Dict [str, Offer] = field(factory=dict)
    _when_done: List[Deferred] = field(factory=list)

    set_trace = getattr(m, "_setTrace", lambda self, f: None)

    # XXX OneShotObserver
    def when_done(self):
        d = Deferred()
        if self._when_done is None:
            d.callback(None)
        else:
            self._when_done.append(d)
        return d

    @m.state(initial=True)
    def await_dilation(self):
        """
        The Dilated connection has not yet succeeded
        """

    @m.state()
    def connected(self):
        """
        We are connected to the peer via Dilation.
        """

    @m.state()
    def closing(self):
        """
        Shutting down and waiting for confirmation
        """

    @m.state()
    def done(self):
        """
        Completed and disconnected.
        """

    @m.input()
    def make_offer(self, offer):
        """
        Present an offer to the peer
        """
        # XXX offer should be some type so we don't have to check it
        # for semantics etc

    @m.input()
    def dilated(self):
        """
        The wormhole Dilation has succeeded
        """

    @m.input()
    def got_accept(self, accept):
        """
        Our peer has accepted a transfer
        """

    @m.input()
    def got_reject(self, reject):
        """
        Our peer has rejected a transfer
        """

    @m.input()
    def got_offer(self, offer):
        """
        Our peer has sent an offer
        """

    @m.input()
    def accept_offer(self, offer_id):
        """
        Accept an offer our peer has previously sent
        """

    @m.input()
    def stop(self):
        """
        We wish to end the transfer session
        """

    @m.input()
    def mailbox_closed(self):
        """
        Our connection has been closed
        """

    @m.output()
    def _queue_offer(self, offer):
        print("queue offer", offer)
        self._queued_offers.append(offer)

    @m.output()
    def _send_queued_offers(self):
        print("send queued", len(self._queued_offers))
        to_send = self._queued_offers
        self._queued_offers = None  # can't go back to "await_dilation" state
        for offer in to_send:
            self.send_control_message(offer)
            self._offers[offer.id] = offer

    @m.output()
    def _send_offer(self, offer):
        print("sendoffer")
        self.send_control_message(offer)
        self._offers[offer.id] = offer

    @m.output()
    def _send_file(self, accept):
        # XXX if not found, protocol-error
        offer = self._offers[accept.id]

        def on_sent():
            del self._offers[accept.id]
        self.send_file_in_offer(offer, on_sent)

    @m.output()
    def _receive_file(self, offer_id):
        # XXX if not found, protocol-error
        peer_offer = self._peer_offers[offer_id]

        def on_received():
            del self._peer_offers[offer_id]
        self.receive_file_in_offer(peer_offer, on_received)
        # pattern like ^ means who cares if this is async or not
        # .. on_received called when the transfer is done.

    @m.output()
    def _remember_offer(self, offer):
        self._peer_offers[offer.id] = offer

    @m.output()
    def _remove_offer(self, reject):
        # XXX if not found, protocol-error
        del self._offers[reject.id]

    @m.output()
    def _close_mailbox(self):
        pass

    @m.output()
    def _notify_done(self):
        done = self._when_done
        self._when_done = None
        for d in done:
            d.callback(None)

    await_dilation.upon(
        make_offer,
        enter=await_dilation,
        outputs=[_queue_offer],
    )
    await_dilation.upon(
        dilated,
        enter=connected,
        outputs=[_send_queued_offers],
    )

    connected.upon(
        make_offer,
        enter=connected,
        outputs=[_send_offer],
    )
    connected.upon(
        got_accept,
        enter=connected,
        outputs=[_send_file]
    )
    connected.upon(
        got_reject,
        enter=connected,
        outputs=[_remove_offer]
    )
    connected.upon(
        got_offer,
        enter=connected,
        outputs=[_remember_offer]
    )
    connected.upon(
        stop,
        enter=closing,
        outputs=[_close_mailbox],
    )
    connected.upon(
        accept_offer,
        enter=connected,
        outputs=[_receive_file],
    )

    closing.upon(
        mailbox_closed,
        enter=done,
        outputs=[_notify_done],
    )
