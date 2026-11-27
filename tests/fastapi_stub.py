"""Minimal stand-ins for fastapi, pydantic and python-dotenv, so app.main can be imported and its endpoint functions
called directly in tests: no web server, no network, nothing to install. Only what main.py uses."""
import sys
import types


class HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        super().__init__(status_code, detail)
        self.status_code, self.detail = status_code, detail


class _App:
    def __init__(self, **kw):
        self.routes = {}

    def _route(self, method):
        def decorator(path, **kw):
            def wrap(fn):
                self.routes[(method, path)] = fn
                return fn
            return wrap
        return decorator

    def get(self, path, **kw): return self._route("GET")(path, **kw)
    def post(self, path, **kw): return self._route("POST")(path, **kw)
    def put(self, path, **kw): return self._route("PUT")(path, **kw)
    def head(self, path, **kw): return self._route("HEAD")(path, **kw)
    def add_middleware(self, *a, **k): pass


class BackgroundTasks:
    """Runs tasks immediately (real FastAPI runs them just after the response is sent)."""
    def add_task(self, fn, *a, **k): fn(*a, **k)


class FileResponse:
    def __init__(self, path, media_type=None): self.path, self.media_type = path, media_type


class PlainTextResponse:
    def __init__(self, content, status_code=200, media_type=None, headers=None):
        self.body, self.status_code, self.media_type, self.headers = content, status_code, media_type, headers


class HTMLResponse:
    def __init__(self, content, status_code=200): self.body, self.status_code = content, status_code


class RedirectResponse:
    def __init__(self, url, status_code=307): self.url, self.status_code = url, status_code


class BaseModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def install():
    def mod(name, **attrs):
        m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
    mod("fastapi", FastAPI=_App, HTTPException=HTTPException, Header=lambda default=None, **k: default,
        Query=lambda default=None, **k: default, Request=object, BackgroundTasks=BackgroundTasks)
    mod("fastapi.middleware")
    mod("fastapi.middleware.cors", CORSMiddleware=object)
    mod("fastapi.responses", FileResponse=FileResponse, PlainTextResponse=PlainTextResponse, RedirectResponse=RedirectResponse, HTMLResponse=HTMLResponse)
    mod("pydantic", BaseModel=BaseModel)
    mod("dotenv", load_dotenv=lambda *a, **k: None)
