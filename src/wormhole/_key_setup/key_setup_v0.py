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

# This is the retroactively-named "v0" key-setup protocol: the initial
# one used by all versions of magic-wormhole, at least through the
# 0.24.0 release. We implement here as an IKeySetup so that future
# versions of the client can fall back to it when their peer can't do
# something better.

# states
@frozen
class Init:
    pass
@frozen
class StartedEarly: # waiting for outbound PAKE-0
    pass
@frozen
class WantPAKE: # -> VerifyingOurVersion
    wanted: str
@frozen
class VerifyingKey: # -> Done
    key: bytes
@frozen
class Done:
    pass



import typing
from ..timing import DebugTiming


class KeySetup(typing.Protocol):
    def start_pake0(self, code: str, their_side: str | None) -> dict:
        pass

    def submit_outbound_pake0(self, pake0mt: MessageTuple) -> list[KeySetupAction]:
        pass
    
    def start_pake1(self, code: str, their_side: str, pake0mt: MessageTuple) -> list[KeySetupAction]:
        pass

    # FIXME: refactor (separate methods for different phase strings)
    # got_version(body: bytes)
    # got_pake(phase: int, body: bytes)
    def input(self, side: str, phase: str, body: bytes) -> list[KeySetupAction]:
        pass

    # TODO: because the above is just a way to multiplex depending on
    # (mostly) the phase argument, we could just make the below
    # not-private and 'the' API instead
    def _got_pake(self, phase: int, body: bytes) -> list[KeySetupAction]:
        pass

    def _got_version(self, body: bytes) -> list[KeySetupAction]:
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

    @want_pake.upon(KeySetup._got_pake).to(want_version)
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
        with core._timing.add("pake2", waiting="crypto"):
            core.key = core.spake2_helper.finish(msg2)
        # create and encrypt our VERSION verification message
        data_key = derive_phase_key(core.key, core._side, "version")
        plaintext = dict_to_bytes(core.app_versions)
        encrypted = encrypt_data(data_key, plaintext)

        return [
            ikeysetup.HaveAllegedKey(),
            ikeysetup.Send(core.side, "version", encrypted),
        ]
    
    @want_version.upon(KeySetup._got_version).to(done)
    def process_version(inputs: KeySetup, core: KeySetupState, body: bytes) -> [KeySetupAction]:
        data_key = derive_phase_key(core.key, core.side, "version")
        try:
            plaintext = decrypt_data(data_key, body)
        except CryptoError:
            core._error = WrongPasswordError()
            raise core._error
        return [ikeysetup.Done(core.key, plaintext)]

    @want_pake.upon(KeySetup.input).loop()
    def parse_message(inputs: KeySetup, core: KeySetupState, side: str, phase: str, body: bytes) -> [KeySetupAction]:
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
        if core._their_side is None:
            core._their_side = side
        if core._their_side != side:
            core._error = core._error or CrowdedError()
        if core._error:
            raise core._error
        actions = False
        next_wanted = False

        if phase.startswith("pake"):
            pake_phase = 0
            if "-" in phase:
                pake_phase = int(phase.split("-", 2)[1])
            inputs._got_pake(pake_phase, body)
        elif phase == "version":
            inputs._got_version(body)
        else:
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
    def _(pake0mt: MessageTuple):
        """
        v0 doesn't use a transcript so we don't actually look at the
        message at all
        """

    machine_factory = builder.build()
    machine = machine_factory(
        KeySetupState(side, appid, app_versions, timing, spake2_helper),
    )
    return machine


@implementer(IKeySetup)
class KeySetup_V0:
    def __init__(self, side, appid, app_versions, timing, spake2_helper=None):
        self._side = side
        self._appid = appid
        self._app_versions = app_versions
        self._timing = timing
        if not spake2_helper:
            spake2_helper = SPAKE2_Helper(appid)
        assert isinstance(spake2_helper, SPAKE2_Helper)
        self._sph = spake2_helper

        self._error = None

        self._their_side = None
        self._state = Init()

    def start_pake0(self, code: str, their_side: str | None) -> dict:
        assert self._state == Init()
        msg1 = self._sph.start(code)
        self._state = StartedEarly()
        return {"pake_v1": bytes_to_hexstr(msg1)}

    def submit_outbound_pake0(self, pake0mt: MessageTuple):
        # v0 doesn't use a transcript, the PAKE-0 is ignored
        wanted = "pake"
        self._state = WantPAKE(wanted)
        return wanted

    def start_pake1(self, code: str, their_side: str, pake0mt: MessageTuple) -> NextKeySetupInput:
        raise ValueError("v0 cannot be started late")

    def input(self, side: str, phase: str, body: bytes) -> NextKeySetupInput:
        assert isinstance(side, str), type(phase)
        assert isinstance(phase, str), type(phase)
        assert isinstance(body, bytes), type(body)
        if self._their_side is None:
            self._their_side = side
        if self._their_side != side:
            self._error = self._error or CrowdedError()
        if self._error:
            raise self._error
        actions = False
        next_wanted = False
        match self._state:
            case Init():
                raise ValueError("input() before start")
            case StartedEarly():
                raise ValueError("input() before submit_outbound_pake0")
            case WantPAKE(wanted):
                assert phase == wanted
                payload = bytes_to_dict(body)
                if "pake_v1" not in payload:
                    raise NegotiationError("PAKE-0 missing 'pake_v1'")
                # receiving a phase with "pake_v1" lets us build the
                # key and go into "confirming" mode
                msg2 = hexstr_to_bytes(payload["pake_v1"])
                assert isinstance(msg2, bytes)
                with self._timing.add("pake2", waiting="crypto"):
                    spake2_key = self._sph.finish(msg2)
                key = spake2_key # no transcript
                have_alleged_key = ikeysetup.HaveAllegedKey()
                s_version = self._send_version(key)
                actions = [have_alleged_key, s_version]
                next_wanted = "version"
                self._state = VerifyingKey(key)
            case VerifyingKey(key):
                assert phase == "version"
                data_key = derive_phase_key(key, side, phase)
                try:
                    plaintext = decrypt_data(data_key, body)
                except CryptoError:
                    self._error = WrongPasswordError()
                    raise self._error
                next_wanted = None
                actions = [ikeysetup.Done(key, plaintext)]
                self._state = Done()
            case _:
                raise ValueError("bad state")
        assert isinstance(actions, list)
        assert next_wanted != False
        return actions, next_wanted

    def _send_version(self, key):
        data_key = derive_phase_key(key, self._side, "version")
        plaintext = dict_to_bytes(self._app_versions)
        encrypted = encrypt_data(data_key, plaintext)
        return ikeysetup.Send(self._side, "version", encrypted)
