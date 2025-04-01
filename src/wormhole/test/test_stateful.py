from hypothesis.stateful import rule, precondition, RuleBasedStateMachine, run_state_machine_as_test, Bundle
from hypothesis.strategies import integers, lists
from hypothesis import given
import pytest
import pytest_twisted

from wormhole.errors import LonelyError
from twisted.internet.testing import MemoryReactorClock
from twisted.internet.interfaces import IHostnameResolver
from wormhole.eventual import EventualQueue
from wormhole import create
from autobahn.twisted.testing import MemoryReactorClockResolver


from twisted.internet import defer
defer.setDebugging(True)

# the stateful transition goals :
# client_to_mailbox = [
#     {"type": "claim", },
#     {"type": "allocate", },
#     {"type": "open", "mailbox_id": None},
#     {"type": "add", },
#     {"type": "release", },
#     {"type": "close", "mailbox_id": None, "mood": None},
# ]

# mailbox_to_client = [
#     {"type": "welcome", },
#     {"type": "claimed", },
#     {"type": "allocated", },
#     {"type": "opened", },
#     {"type": "nameplates", },
#     {"type": "ack", },
#     {"type": "error", },
#     {"type": "message", "side": None, "phase": None},
#     {"type": "released", },
#     {"type": "closed", },
# ]

class WormholeMachine(RuleBasedStateMachine):
    def __init__(self, reactor, eventual_queue):
        RuleBasedStateMachine.__init__(self)
        self._reactor = reactor
        self._eventual_queue = eventual_queue

    Wormholes = Bundle('wormholes')

    @rule(target=Wormholes) # how to connect to welcome?
    def new_wormhole(self):
        return create("foo", "ws://whatever:1/v1", self._reactor, _eventual_queue=self._eventual_queue)

    @rule(w=Wormholes)
    def welcome(self,w):
        # we haven't recv'd a welcome yet
        d = w.get_welcome() # we extract a deferred that will be called when we get a welcome message
        assert not d.called # on a deferred there's a "called"
        w._boss.rx_welcome({"type": "welcome", "motd": "hello, world"})

        self._reactor.advance(1)
        ## await ...
        assert d.called # now we have a welcome message!

    # @rule(w=Wormholes)
    # def client_bind(self):
    #     d = w.bind()
    #     assert not d.called
    #     w._rendezvous.ws_open()

    # @rule(heap=Heaps, value=integers())
    # def push(self, heap, value):
    #     heappush(heap, value)

def test_foo(mailbox):

    reactor = MemoryReactorClockResolver()
    eq = EventualQueue(reactor)

    def create_machine():
        return WormholeMachine(reactor, eq)

    run_state_machine_as_test(create_machine)
