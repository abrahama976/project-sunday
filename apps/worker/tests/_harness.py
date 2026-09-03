"""Make the worker's modules importable from a test, with no dependencies.

Every test file used to reach into a module with `ast.parse`, pick out named
functions and `exec` them into a hand-built globals dict. It worked, and it
taxed every change: a new function had to be registered twice — once in a
`_WANTED` set and again as a `_g["name"]` binding — deleting one broke the
harness with a bare KeyError, constants needed their own registration, and
anything that touched an import could not be tested at all. It was also
spreading: one test file ended up extracting from three separate modules.

Two things stood in the way of a plain `import`, and both are handled here:

1. `config.py` reads os.environ["SUPABASE_URL"] and friends AT IMPORT TIME, so
   importing anything downstream of it raises KeyError without a real
   environment.
2. The third-party packages are not installed in a bare checkout — httpx,
   dotenv, supabase, the google stack, googleapiclient.

So: placeholder env values, and stub modules for the uninstalled packages.

The important property is that **every stub raises when called**. Stubbing only
satisfies the import; it must never quietly answer a question. A test that
reaches `httpx.AsyncClient` or `create_client` fails loudly with
TestReachedRealIO rather than passing against a fake. A stub that returned
something plausible would be worse than no tests at all, because it would look
like coverage.

Usage, at the top of a test file:

    from _harness import setup; setup()
    from executors.travel_ops import add_access_leg, verify_journeys

One note worth keeping. `supabase` looks installed when probed from the repo
root — it is not. `importlib.util.find_spec` matches the repo's own `supabase/`
migrations directory as a namespace package, so anything run from there gets a
folder of SQL files instead of the client library. Hence the stub, and hence
`setup()` putting the worker directory first on sys.path.
"""
import os
import sys
import types
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent


class TestReachedRealIO(Exception):
    """A pure test called something that would have done real IO."""


def _unavailable(name):
    def fail(*args, **kwargs):
        raise TestReachedRealIO(
            f"{name} was called in a test. These stubs exist to satisfy "
            "imports, not to answer questions — the test needs a fake it owns, "
            "or it is not a pure test."
        )
    return fail


def _stub(name, **attrs):
    """Register a stub module, wired to its parent so submodules resolve."""
    module = types.ModuleType(name)
    module.__path__ = []          # a package, so `x.y` imports can attach
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    parent, _, leaf = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], leaf, module)
    return module


_DONE = False


def setup():
    """Idempotent. Safe to call from every test file."""
    global _DONE
    if _DONE:
        return
    _DONE = True

    # config.py demands these three at import time.
    os.environ.setdefault("SUPABASE_URL", "https://project-sunday.test.invalid")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
    # Left deliberately empty: code paths that require them should take their
    # "not configured" branch rather than pretend to be live.
    os.environ.setdefault("TFNSW_API_KEY", "")
    os.environ.setdefault("OPENROUTESERVICE_API_KEY", "")
    os.environ.setdefault("NTFY_TOPIC", "")

    _stub("httpx", AsyncClient=_unavailable("httpx.AsyncClient"))
    _stub("dotenv", load_dotenv=lambda *a, **k: None)
    # Client is a bare class so type annotations resolve; create_client raises.
    _stub("supabase", Client=type("Client", (), {}),
          create_client=_unavailable("supabase.create_client"))

    _stub("google")
    _stub("google.api_core")
    api_exceptions = _stub("google.api_core.exceptions")

    class _GoogleAPIError(Exception):
        pass

    api_exceptions.ResourceExhausted = _GoogleAPIError
    api_exceptions.ServiceUnavailable = _GoogleAPIError
    api_exceptions.GoogleAPIError = _GoogleAPIError

    _stub("google.genai", Client=_unavailable("genai.Client"))
    _stub("google.genai.types")
    genai_errors = _stub("google.genai.errors")
    genai_errors.APIError = _GoogleAPIError
    genai_errors.ClientError = _GoogleAPIError
    genai_errors.ServerError = _GoogleAPIError

    _stub("google.oauth2")
    _stub("google.oauth2.credentials",
          Credentials=_unavailable("oauth2.Credentials"))
    _stub("google.auth")
    _stub("google.auth.transport")
    _stub("google.auth.transport.requests",
          Request=_unavailable("auth.transport.Request"))
    _stub("google_auth_oauthlib")
    _stub("google_auth_oauthlib.flow",
          InstalledAppFlow=_unavailable("InstalledAppFlow"))

    _stub("googleapiclient")
    _stub("googleapiclient.discovery",
          build=_unavailable("googleapiclient.discovery.build"))
    _stub("googleapiclient.errors",
          HttpError=type("HttpError", (Exception,), {}))

    # First, so the repo's own `supabase/` directory cannot shadow anything.
    if str(WORKER_DIR) not in sys.path:
        sys.path.insert(0, str(WORKER_DIR))
