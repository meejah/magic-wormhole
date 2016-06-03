from twisted.python import usage
from textwrap import dedent
from . import public_relay
from .. import __version__

# g = parser.add_argument_group("wormhole configuration options")
# parser.set_defaults(timing=None)
# subparsers = parser.add_subparsers(title="subcommands",
#                                    dest="subcommand")


class ServerShowUsageOptions(usage.Options):
    optParameters = [
        ("number", "n", 100, "show last N entries", int),
    ]


class ServerTailUsageOptions(usage.Options):
    pass


class ServerStartOptions(usage.Options):
    pass


class ServerStopOptions(usage.Options):
    pass


class ServerRestartOptions(usage.Options):
    pass


class ServerOptions(usage.Options):
    optParameters = [
        ("rendezvous", "r", "tcp:3000", "endpoint specification for the rendezvous port"),
        ("transit", None, "tcp:3001", "endpoint specification for the transit-relay port"),
        ("advertise-version", None, None, "version to recommend to clients"),
        ("blur-usage", None, None, "round logged access times to improve privacy"),
    ]

    optFlags = [
        ("no-daemon", "n", "Do not daemonize"),
    ]

    subCommands = [
        ("start", None, ServerStartOptions, "Start a relay server"),
        ("stop", None, ServerStopOptions, "Stop a running relay server"),
        ("restart", None, ServerRestartOptions, "Restart a running relay server"),
        ("show-usage", None, ServerShowUsageOptions, "Display usage data"),
        ("tail-usage", None, ServerTailUsageOptions, "Follow latest usage"),
    ]


class SendOptions(usage.Options):
    optParameters = [
        ("text", 't', None, 'text message to send, instead of a file. Use "-" to read from stdin.', type(u"")),
        ("code", None, None, "human-generated code phrase", type(u"")),
    ]
    optFlags = [
        ("zero", "0", "enable no-code anything-goes mode"),
    ]

    # a single argument for what to send; can be None
    def parseArgs(self, what=None):
        self["what"] = what


class ReceiveOptions(usage.Options):
    optParameters = [
        ("output-file", "o", None,
         "The file or directory to create, overriding the name suggested "
         "by the sender."),
    ]

    optFlags = [
        ("accept-file", None, "accept file transfer with asking for confirmation"),
        ("zero", "0", "enable no-code anything-goes mode"),
        ("only-text", "t", "refuse file transfers, only accept text transfers"),
    ]

    def parseArgs(self, code=None):
        self['code'] = code

    # FIXME this should go somewhere
    "The magic-wormhole code, from the sender. If omitted, the program will ask for it, using tab-completion."


class WormholeOptions(usage.Options):
    synopsis = "wormhole SUBCOMMAND (subcommand-options)"
    description=dedent("""
    Create a Magic Wormhole and communicate through it. Wormholes are created
    by speaking the same magic CODE in two different places at the same time.
    Wormholes are secure against anyone who doesn't use the same code.""")

    optFlags = [
        ("verify", "v", "display (and wait for acceptance of) verification string"),
        ("hide-progress", None, "supress progress-bar display"),
        ("no-listen", None, "(debug) don't open a listening socket for Transit"),
        ("tor", None, "use Tor when connecting"),
    ]
    optParameters = [
        ("relay-url", None, public_relay.RENDEZVOUS_RELAY, "rendezvous relay to use", type(u"")),
        ("transit-helper", None, public_relay.TRANSIT_RELAY, "transit relay to use"),
        ("code-length", "c", 2, "length of code (in bytes/words)"),
        ("dump-timing", None, None, "(debug) write timing data to file"),
    ]

    subCommands = [
        ("server", None, ServerOptions, "Commands for the wormwhole relay server"),
        ("send", None, SendOptions, "Send text message, file, or directory"),
        ("receive", None, ReceiveOptions, "Receive a text message, file, or directory"),
    ]

    def OFFopt_version(self):
        print("magic-wormhole "+ __version__)
