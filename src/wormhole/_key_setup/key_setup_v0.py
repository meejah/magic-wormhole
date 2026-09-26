import typing
from attrs import frozen, define
from zope.interface import implementer
from automat import TypeMachineBuilder

from ..util import (bytes_to_dict, bytes_to_hexstr,
                    hexstr_to_bytes, derive_phase_key,
                    dict_to_bytes, encrypt_data,
                    decrypt_data, CryptoError)
from ..errors import CrowdedError, WrongPasswordError, NegotiationError
from . import ikeysetup
from .ikeysetup import IKeySetup, NextKeySetupInput, MessageTuple, KeySetupAction
from .spake2_helper import SPAKE2_Helper
from ..timing import DebugTiming

# This is the retroactively-named "v0" key-setup protocol: the initial
# one used by all versions of magic-wormhole, at least through the
# 0.24.0 release. We implement here as an IKeySetup so that future
# versions of the client can fall back to it when their peer can't do
# something better.

class KeySetup(typing.Protocol):
    def start_pake0(self, code: str, their_side: str | None) -> dict:
        pass

    def submit_outbound_pake0(self, pake0mt: MessageTuple) -> list[KeySetupAction]:
        pass

    def start_pake1(self, code: str, their_side: str, pake0mt: MessageTuple) -> list[KeySetupAction]:
        pass

    # could do "got_pake1()" etc and get rid of "phase" argument.. but
    # then we need to change API every time there's more messages?
    def got_pake(self, phase: int, body: bytes) -> list[KeySetupAction]:
        pass

    def got_version(self, body: bytes) -> list[KeySetupAction]:
        pass


@define
class KeySetupState:
    side: str
    appid: str
    app_versions: dict[str, typing.Any]
    timing: DebugTiming  # can we do ITiming / zope here?
    spake2_helper: None | SPAKE2_Helper = None
    their_side: None | str = None
    key: None | bytes = None
    _error: None | Exception = None

    def __attrs_post_init__(self):
        if not self.spake2_helper:
            self.spake2_helper = SPAKE2_Helper(self.appid)


def create_keysetup_v0(side: str, appid: str, app_versions: dict[str, typing.Any], timing, spake2_helper=None):
    # could create a KeySetup_V0 instead .. ideally map APIs exactly
    builder = TypeMachineBuilder(KeySetup, KeySetupState)
    init = builder.state("init")
    started_early = builder.state("started_early")
    want_pake = builder.state("want_pake")
    want_version = builder.state("want_version")
    verifying_key = builder.state("verifying_key")
    done = builder.state("done")

    @want_pake.upon(KeySetup.got_pake).to(want_version)
    def process_pake(inputs: KeySetup, core: KeySetupState, phase: int, body: bytes) -> [KeySetupAction]:
        if phase != 0:
            raise ValueError("Unknown PAKE phase {}".format(phase))
        payload = bytes_to_dict(body)
        if "pake_v1" not in payload:
            raise NegotiationError("PAKE-0 missing 'pake_v1'")
        # receiving a phase with "pake_v1" lets us build the
        # key and go into "confirming" mode
        msg2 = hexstr_to_bytes(payload["pake_v1"])
        assert isinstance(msg2, bytes)
        with core.timing.add("pake2", waiting="crypto"):
            core.key = core.spake2_helper.finish(msg2)
        # create and encrypt our VERSION verification message
        data_key = derive_phase_key(core.key, core.side, "version")
        plaintext = dict_to_bytes(core.app_versions)
        encrypted = encrypt_data(data_key, plaintext)

        return [
            ikeysetup.HaveAllegedKey(),
            ikeysetup.Send(core.side, "version", encrypted),
            ikeysetup.WantVersion(),
        ]

    @want_version.upon(KeySetup.got_version).to(done)
    def process_version(inputs: KeySetup, core: KeySetupState, body: bytes) -> [KeySetupAction]:
        data_key = derive_phase_key(core.key, core.their_side, "version")
        try:
            plaintext = decrypt_data(data_key, body)
        except CryptoError:
            core._error = WrongPasswordError()
            raise core._error
        return [ikeysetup.Done(core.key, plaintext)]

    # bump this out of here it's not really "state-machine" stuff
    def parse_message(side: str, phase: str, body: bytes) -> list[KeySetupAction]:
        """
        fact-check and de-multiplex this input, possibly causing some of
        the private inputs to be triggered on this state machine. may
        raise errors.
        """
        # TODO: parsing etc might be better done outside this
        # state-machine, or at least the "is the side right"
        # handingling, as per other comments
        assert isinstance(side, str), type(phase)
        assert isinstance(phase, str), type(phase)
        assert isinstance(body, bytes), type(body)
        if state.their_side is None:
            state.their_side = side
        if state.their_side != side:
            state._error = state._error or CrowdedError()
        if state._error:
            raise state._error
        actions = False
        next_wanted = False

        if phase.startswith("pake"):
            pake_phase = 0
            if "-" in phase:
                pake_phase = int(phase.split("-", 2)[1])
            return machine.got_pake(pake_phase, body)
        elif phase == "version":
            return machine.got_version(body)
        raise RuntimeError("illegal phase '{}' during key setup".format(phase))

    @init.upon(KeySetup.start_pake0).to(started_early)
    def start_pake0(inputs: KeySetup, core: KeySetupState, code: str, their_side: str) -> dict:
        if core.their_side is not None and core.their_side != their_side:
            # TODO: maybe an Error(..) output instead?
            raise CrowdedError()
        core.their_side = their_side
        msg1 = core.spake2_helper.start(code)
        # TODO: instead maybe a list of outputs [PakeAttributes({"pake_v1": ...})]
        return {"pake_v1": bytes_to_hexstr(msg1)}

    @started_early.upon(KeySetup.submit_outbound_pake0).to(want_pake)
    def _(side, phase, body):
        """
        v0 doesn't use a transcript so we don't actually look at the
        message at all
        """
        return "pake"

    machine_factory = builder.build()
    state = KeySetupState(side, appid, app_versions, timing, spake2_helper)
    machine = machine_factory(state)

    # hack to keep the same API; this can go away if we bump the
    # "parse_message" logic up to negotiator
    machine.input = parse_message

    return machine
