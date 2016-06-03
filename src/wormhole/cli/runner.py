from __future__ import print_function
import time
start = time.time()
import os, sys, textwrap
from twisted.internet.defer import maybeDeferred
from twisted.internet.task import react
from ..errors import (TransferError, WrongPasswordError, WelcomeError, Timeout,
                      KeyFormatError)
from ..timing import DebugTiming
from .cli_args import WormholeOptions
top_import_finish = time.time()

def dispatch(args): # returns Deferred
    if args.subCommand == "send":
        with args['timing'].add("import", which="cmd_send"):
            from . import cmd_send
        return cmd_send.send(args)
    if args.subCommand == "receive":
        with args['timing'].add("import", which="cmd_receive"):
            from . import cmd_receive
        return cmd_receive.receive(args)

    raise ValueError("unknown subcommand %s" % args.subCommand)

def run(reactor, argv, cwd, stdout, stderr, executable=None):
    """This is invoked by entry() below, and can also be invoked directly by
    tests.
    """

    parser = WormholeOptions()
    parser.parseOptions(argv)
    parser['cwd'] = cwd
    parser['stdout'] = stdout
    parser['stderr'] = stderr
    parser['timing'] = timing = DebugTiming()

    timing.add("command dispatch")
    timing.add("import", when=start, which="top").finish(when=top_import_finish)
    # fires with None, or raises an error
    d = maybeDeferred(dispatch, parser)
    def _maybe_dump_timing(res):
        timing.add("exit")
        if parser['dump-timing']:
            timing.write(parser['dump-timing'], stderr)
        return res
    d.addBoth(_maybe_dump_timing)
    def _explain_error(f):
        # these errors don't print a traceback, just an explanation
        f.trap(TransferError, WrongPasswordError, WelcomeError, Timeout,
               KeyFormatError)
        if f.check(WrongPasswordError):
            msg = textwrap.fill("ERROR: " + textwrap.dedent(f.value.__doc__))
            print(msg, file=stderr)
        elif f.check(WelcomeError):
            msg = textwrap.fill("ERROR: " + textwrap.dedent(f.value.__doc__))
            print(msg, file=stderr)
            print(file=stderr)
            print(str(f.value), file=stderr)
        elif f.check(KeyFormatError):
            msg = textwrap.fill("ERROR: " + textwrap.dedent(f.value.__doc__))
            print(msg, file=stderr)
        else:
            print("ERROR:", f.value, file=stderr)
        raise SystemExit(1)
    d.addErrback(_explain_error)
    d.addCallback(lambda _: 0)
    return d

def entry():
    """This is used by a setuptools entry_point. When invoked this way,
    setuptools has already put the installed package on sys.path ."""
    react(run, (sys.argv[1:], os.getcwd(), sys.stdout, sys.stderr,
                sys.argv[0]))
