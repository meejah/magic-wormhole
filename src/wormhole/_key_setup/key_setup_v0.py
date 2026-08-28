import typing
import automat
from zope.interface import implementer
from spake2 import SPAKE2_Symmetric
from attrs import define, frozen

from ..util import (bytes_to_dict, bytes_to_hexstr, dict_to_bytes,
                    hexstr_to_bytes, to_bytes, derive_phase_key,
                    encrypt_data, decrypt_data, CryptoError)
from ..errors import CrowdedError, WrongPasswordError, CausalityError
from .ikeysetup import IKeySetup, Send, HaveAllegedKey, Done, KeySetupOutput

# This is the retroactively-named "v0" key-setup protocol: the initial
# one used by all versions of magic-wormhole, at least through the
# 0.24.0 release. We implement here as an IKeySetup so that future
# versions of the client can fall back to it when their peer can't do
# something better.

# aug26 attempt to translate to _new_ Automat state-machine API


## @implementer(IKeySetup)
class KeySetupZero(typing.Protocol):
    def start(code: str) -> dict:
        """Set the wormhole code and generate the PAKE0 components.

        Call this when the complete wormhole code is available and
        we've either received the peer's PAKE-0 (phase="pake") message
        or we know we shouldn't wait for it. It will be used by any
        PAKE algorithms involved in this particular version of the key
        setup protocol. The return value contains components to go into
        our outbound PAKE-0 message.
        """

    def received_pake(body: bytes) -> list[KeySetupOutput]:
        """
        Input messages might be processed immediately, or queued until
        the arrival of some future message. Any number of
        `OutputMessage` instances may be produced by a call to
        `received_*()` and should all be processed by the caller
        (not necessarily immediately).

        Output messages may be one of:

        * Send(phase, body): send outbound key-setup message to the mailbox.
          "phase" will specify a PAKE-n or VERSION phase. "body" is bytes.
        * HaveAllegedKey(key): we have an alleged key
          # TODO: stop providing the key, leave it for "done"
        * Done(key, version_data): the key and application version
          bytes should be delivered to the Boss.

        :throws: CrowdedError, WrongPasswordError, or CausalityError,
        all of which are terminal and sticky.
        """

    def received_version(body: bytes) -> list[KeySetupOutput]:
        """
        """


@define
class KeySetupState:
    side: bytes
    app_id: str
    app_versions: dict
    key: bytes | None = None
    spake: SPAKE2_Symmetric | None = None



def remember_message(inputs: KeySetupZero, state: KeySetupState, message: InputMessage) -> InputMessage | None:
    print("REMEMERM", message)
    return message


builder = automat.TypeMachineBuilder(Negotiate, KeySetupState)
idle = builder.state("idle")
want_pake = builder.state("want_pake")#, remember_message)
have_alleged_key = builder.state("have_alleged_key")
done = builder.state("done")

@idle.upon(Negotiate.start).to(want_pake)
def init_state(neg: Negotiate, state: KeySetupState, code: str) -> dict:
    # i think we can set stuff in 'state' here and it propagates?
    code_b = to_bytes(code)
    id_b = to_bytes(state.app_id)
    state.spake = SPAKE2_Symmetric(code_b, idSymmetric=id_b)
    print("INIT", state.spake)
    msg1 = state.spake.start()
    return {
        "pake_v1": bytes_to_hexstr(msg1),
    }

@want_pake.upon(Negotiate.received_pake).to(have_alleged_key)
def process_pake(inputs: Negotiate, state: KeySetupState, body: bytes) -> list[OutputMessage]:
    payload = bytes_to_dict(body)
    msg2 = hexstr_to_bytes(payload["pake_v1"])
    print("PROCESSPAKE", state.spake)
    #with self._timing.add("pake2", waiting="crypto"):
    state.key = state.spake.finish(msg2)

    data_key = derive_phase_key(state.key, state.side, "version")
    plaintext = dict_to_bytes(state.app_versions)
    encrypted = encrypt_data(data_key, plaintext)
    return [M_AddMessage("version", encrypted)]

@have_alleged_key.upon(Negotiate.received_versions).to(done)
def finalize(inputs: Negotiate, state: KeySetupState):
    print("finalize")

negotiate_factory = builder.build()

def negotiate_v0(side, appid, app_versions):
    machine = negotiate_factory(
        KeySetupState(side, appid, app_versions),
    )
    return machine


@implementer(INegotiation)
class Negotiate_V0:
    def __init__(self, side, appid, app_versions, timing):
        self._side = side
        self._appid = appid
        self._app_versions = app_versions
        self._timing = timing

        self._started = False
        self._done = False
        self._error = None

        self._sp = None # established by got_code
        self._msg1 = None

        self._their_side = None
        self._inbound_messages = dict()
        self._wanted = None
        self._outputs: list[KeySetupOutput] = []

    def start(self, code):
        assert not self._started, "start() may only be called once)"
        self._started = True
        code_b = to_bytes(code)
        id_b = to_bytes(self._appid)
        with self._timing.add("pake1", waiting="crypto"):
            self._sp = SPAKE2_Symmetric(code_b, idSymmetric=id_b)
            self._msg1 = self._sp.start()
        self._wanted = "pake"
        self._process()
        return {"pake_v1": bytes_to_hexstr(self._msg1)}

    def input(self, side, phase, body):
        assert isinstance(side, str), type(phase)
        assert isinstance(phase, str), type(phase)
        assert isinstance(body, bytes), type(body)
        assert not self._done
        if self._their_side is None:
            self._their_side = side
        if self._their_side != side:
            self._error = self._error or CrowdedError()
        if phase == "version" and not self._started:
            self._error = self._error or CausalityError()
        if self._error:
            raise self._error
        assert phase not in self._inbound_messages
        self._inbound_messages[phase] = (side, body)
        self._process()

    def _process(self):
        while self._wanted and self._wanted in self._inbound_messages:
            (s, b) = self._inbound_messages[self._wanted]
            if self._wanted == "pake":
                self._wanted = self._process_pake(s, self._wanted, b)
            elif self._wanted == "version":
                self._wanted = self._process_version(s, self._wanted, b)
            else:
                raise AssertionError("unhandled phase %s" % self._wanted)

    def _process_pake(self, side, phase, body):
        print("HAHA")
        payload = bytes_to_dict(body)
        msg2 = hexstr_to_bytes(payload["pake_v1"])
        assert isinstance(msg2, bytes)
        with self._timing.add("pake2", waiting="crypto"):
            key = self._sp.finish(msg2)
        self._key = key

        self._outputs.append(HaveAllegedKey(key))
        data_key = derive_phase_key(self._key, self._side, "version")
        plaintext = dict_to_bytes(self._app_versions)
        encrypted = encrypt_data(data_key, plaintext)
        self._outputs.append(Send("version", encrypted))
        return "version"

    def _process_version(self, side, phase, body):
        assert self._key
        data_key = derive_phase_key(self._key, side, phase)
        try:
            plaintext = decrypt_data(data_key, body)
        except CryptoError:
            self._error = WrongPasswordError()
            raise self._error
        self._done = True
        self._outputs.append(Done(self._key, plaintext))
        return None

    def output(self):
        if self._error:
            raise self._error
        if self._outputs:
            return self._outputs.pop(0)
        return None
