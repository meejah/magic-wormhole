from hypothesis.stateful import rule, precondition, RuleBasedStateMachine, run_state_machine_as_test
from hypothesis.strategies import integers, lists
from hypothesis import given
import pytest
import pytest_twisted

from wormhole.errors import LonelyError
from twisted.internet.testing import MemoryReactorClock
from twisted.internet.interfaces import IHostnameResolver
from wormhole.eventual import EventualQueue
from wormhole import create



from twisted.internet import defer
defer.setDebugging(True)


client_to_mailbox = [
    {"type": "claim", },
    {"type": "allocate", },
    {"type": "open", "mailbox_id": None},
    {"type": "add", },
    {"type": "release", },
    {"type": "close", "mailbox_id": None, "mood": None},
]

mailbox_to_client = [
    {"type": "welcome", },
    {"type": "claimed", },
    {"type": "allocated", },
    {"type": "opened", },
    {"type": "nameplates", },
    {"type": "ack", },
    {"type": "error", },
    {"type": "message", "side": None, "phase": None},
    {"type": "released", },
    {"type": "closed", },
]

class WormholeMachine(RuleBasedStateMachine):
    def __init__(self, wormhole, reactor):
        RuleBasedStateMachine.__init__(self)
        self._reactor = reactor
        self._pending_wormhole = wormhole
        self.wormhole = None

    @rule() # how to connect to welcome?
    @precondition(lambda self: self.wormhole is None)
    def new_wormhole(self):
        self.wormhole = self._pending_wormhole
        assert self.wormhole._boss is not None

    @rule()
    @precondition(lambda self: self.wormhole) # can't run this transition/check until we have a wormhole
    def welcome(self):
        # we haven't recv'd a welcome yet
        d = self.wormhole.get_welcome() # we extract a deferred that will be called when we get a welcome message
        assert not d.called # on a deferred there's a "called"
        self.wormhole._boss.rx_welcome({"type": "welcome", "motd": "hello, world"})

        self._reactor.advance(1)
        ## await ...
        assert d.called # now we have a welcome message!


def test_foo(mailbox):

    reactor = MemoryReactorClockResolver()
    eq = EventualQueue(reactor)
    w = create("foo", "ws://whatever:1/v1", reactor, _eventual_queue=eq)

    machines = []

    def create_machine():
        m = WormholeMachine(w, reactor)
        machines.append(m)
        return m
    run_state_machine_as_test(create_machine)

