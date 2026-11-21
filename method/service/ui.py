"""Web UI: "Secrets" for every user, plus admin pages (users, tokens, projects, members, categories, grants, vault).

Server-rendered with the stdlib only. Login is Google OpenID Connect (authorization code + PKCE). A Google account
may enter only if its verified email belongs to a user an admin created, or is listed in ADMIN_EMAILS. Vault values
are never in page HTML: they are fetched on click (CSRF-protected, audited per read) to reveal or copy.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import hmac
import json
import pathlib
import secrets
import time
import urllib.parse
import urllib.request
from html import escape as e

from starlette.requests import Request
import jwt
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from method.service.markdown_view import render as render_markdown
from method.service.store import AccessDenied, ProjectNotFound, RevisionConflict, Store

GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

SESSION_TTL = 8 * 3600
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def sign(secret: str, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())}"


def unsign(secret: str, value: str | None) -> dict | None:
    try:
        body, mac = (value or "").split(".")
        good = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, good):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload if payload.get("exp", 0) > time.time() else None
    except (ValueError, TypeError):
        return None


STATIC = pathlib.Path(__file__).with_name("static")
# Content hash of the static files: appended to asset URLs so a changed file is never served from an old CDN/browser cache.
ASSET_V = hashlib.sha256(b"".join(f.read_bytes() for f in sorted(STATIC.glob("*")) if f.is_file())).hexdigest()[:10]
STATIC_TYPES = {"pico.min.css": "text/css", "app.css": "text/css", "logo.png": "image/png", "icon.png": "image/png"}
_SESSION: contextvars.ContextVar = contextvars.ContextVar("evui_session", default=None)
_NAV: contextvars.ContextVar = contextvars.ContextVar("evui_nav", default="")
_FLASH: contextvars.ContextVar = contextvars.ContextVar("evui_flash", default="")
FLASH = {"created": "Secret created.", "saved": "Changes saved.", "shared": "Sharing updated.", "deleted": "Deleted.",
         "revoked": "Evidence secret revoked.", "user-created": "User created.", "user-updated": "User updated.",
         "user-deleted": "User deleted.", "category-created": "Category added.", "project-created": "Project created.",
         "member-added": "Member added.", "member-removed": "Member removed.",
         "protocol-saved": "Protocol saved as a new revision."}
BASE_JS = (
    "document.addEventListener('submit',e=>{const m=e.target.dataset&&e.target.dataset.confirm;if(m&&!confirm(m))e.preventDefault();});"
    "document.addEventListener('change',e=>{const t=e.target,id=t.dataset&&t.dataset.mask;"
    "if(id)document.getElementById(id).classList.toggle('masked',t.checked);});"
    "document.addEventListener('click',async e=>{const b=e.target.closest('button[data-copy]');if(!b)return;"
    "await navigator.clipboard.writeText(document.getElementById(b.dataset.copy).textContent);"
    "const t=b.textContent;b.textContent='Copied';setTimeout(()=>b.textContent=t,1500);});")
NAV_FOR = (("/ui/vault", "secrets"), ("/ui/secret", "secrets"), ("/ui/token", "token"), ("/ui/users", "users"),
           ("/ui/tokens", "users"), ("/ui/project", "projects"), ("/ui/protocol", "projects"), ("/ui/categories", "categories"))
GOOGLE_G = (
    "<svg width='20' height='20' viewBox='0 0 48 48' aria-hidden='true'>"
    "<path fill='#EA4335' d='M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z'/>"
    "<path fill='#4285F4' d='M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z'/>"
    "<path fill='#FBBC05' d='M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C.9 16.3 0 20 0 24s.9 7.7 2.6 10.8l7.9-6.1z'/>"
    "<path fill='#34A853' d='M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z'/>"
    "</svg>")


def mail(address: str | None) -> str:
    """Escaped email wrapped so Cloudflare's email obfuscation leaves it readable."""
    return f"<!--email_off-->{e(address or '')}<!--/email_off-->"


def page(title: str, body: str, csrf: str = "", status: int = 200, admin: bool = False, script: str = "",
         bare: bool = False) -> HTMLResponse:
    sess = _SESSION.get()
    if csrf and not bare:
        active = _NAV.get()

        def link(key: str, href: str, label: str) -> str:
            return f"<li><a href='{href}'{' aria-current=page' if key == active else ''}>{label}</a></li>"

        links = (link("secrets", "/ui/vault", "Secrets") + link("projects", "/ui/projects", "Projects")
                 + link("token", "/ui/token", "Evidence secret")
                 + (link("users", "/ui/users", "Users") + link("categories", "/ui/categories", "Categories") if admin else ""))
        who = (f"<li class='who'>{mail(sess.get('email')) if sess else ''} "
               f"<mark>{'admin' if admin else 'member'}</mark></li>")
        logout = (f"<li><form class='inline' method='post' action='/ui/logout'>"
                  f"<input type='hidden' name='csrf' value='{e(csrf)}'><button class='outline secondary'>Log out</button></form></li>")
        top = (f"<header class='app'><nav class='container'><ul><li><a href='/ui/vault'>"
               f"<img src='/ui/static/logo.png?v={ASSET_V}' alt='Evidence' height='40'></a></li></ul>"
               f"<ul class='links'>{links}</ul><ul class='account'>{who}{logout}</ul></nav></header>")
        flash = _FLASH.get()
        notice = f"<p class='flash' role='status'>{e(flash)}</p>" if flash else ""
        content = f"{top}<main class='container'>{notice}{body}</main>"
    else:
        content = body
    nonce = secrets.token_urlsafe(16)
    tag = f"<script nonce='{nonce}'>{BASE_JS}{script}</script>"
    html = (f"<!doctype html><html lang='en' data-theme='dark'><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)} - Evidence</title>"
            f"<link rel='icon' type='image/png' href='/ui/static/icon.png?v={ASSET_V}'>"
            f"<link rel='stylesheet' href='/ui/static/pico.min.css?v={ASSET_V}'><link rel='stylesheet' href='/ui/static/app.css?v={ASSET_V}'>"
            f"<body data-csrf='{e(csrf)}'>{content}{tag}")
    return HTMLResponse(html, status_code=status, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": ("default-src 'none'; style-src 'self'; img-src 'self'; "
                                    f"script-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")})


def agent_prompt(origin: str) -> str:
    """The prompt a person pastes into an AI agent to register the current repository with this service."""
    return (
        f"Connect this repository to my Evidence service at {origin}.\n\n"
        "My personal Evidence secret is already exported as EVIDENCE_TOKEN in this shell. "
        "Never print it, echo it, log it or write it to any file.\n\n"
        f"1. Download the installer: curl -fsSL {origin}/install.py -o /tmp/evidence_install.py\n"
        f"2. Run: python3 /tmp/evidence_install.py join --target . --agent claude --service-url {origin}/mcp\n"
        "   (use --agent codex, cursor, devin or trae if that is the agent I am running)\n"
        "   - This registers the repository: its git origin is the project key. If the project is new, an existing "
        "EVIDENCE_PROTOCOL.md in this folder is imported as the first protocol revision. If the project already exists, "
        "I am just added to it as an editor.\n"
        "   - If it refuses because of old standalone Evidence guidance (for example CLAUDE.md or a rules file that points "
        "at a local EVIDENCE_PROTOCOL.md), show me those files and wait for my OK before changing anything.\n"
        "3. Show me what changed (git status and the new files). Do not commit anything yet: .mcp.json contains the service URL.\n"
        "4. Tell me whether I must restart this session so the \"evidence\" MCP server loads, then verify it by calling "
        "protocol_header for this project and show me the first lines.\n"
    )


def verify_google_id_token(token: str, jwks, client_id: str, nonce: str) -> dict:
    """Validated claims of a Google ID token; raises jwt.PyJWTError or ValueError. Needs a verified email."""
    claims = jwt.decode(token, jwks.get_signing_key_from_jwt(token).key, algorithms=["RS256"], audience=client_id,
                        options={"require": ["exp", "iat", "sub", "iss", "aud", "email"]}, leeway=30)
    if claims["iss"] not in GOOGLE_ISSUERS:
        raise ValueError("unexpected issuer")
    if claims.get("nonce") != nonce:
        raise ValueError("nonce mismatch")
    if claims.get("email_verified") is not True:
        raise ValueError("email is not verified")
    return claims


def register_ui(app, store: Store, public_url: str, google_client_id: str, google_client_secret: str,
                session_secret: str, protocol_file, admin_emails: frozenset[str] = frozenset()) -> None:
    secure = public_url.startswith("https://")
    origin = public_url.rstrip("/").removesuffix("/mcp")
    discovery: dict = {}
    jwks = {}

    def endpoints() -> dict:
        if not discovery:
            with urllib.request.urlopen(GOOGLE_DISCOVERY, timeout=10) as r:
                discovery.update(json.load(r))
            jwks["client"] = jwt.PyJWKClient(discovery["jwks_uri"], cache_jwk_set=True, lifespan=3600)
        return discovery

    def set_cookie(resp, name: str, payload: dict, ttl: int):
        resp.set_cookie(name, sign(session_secret, {**payload, "exp": time.time() + ttl}), max_age=ttl,
                        httponly=True, secure=secure, samesite="lax", path="/ui")

    def session_of(request: Request) -> dict | None:
        return unsign(session_secret, request.cookies.get("evui"))

    async def guarded(request: Request, handler, post: bool = False, admin: bool = True):
        """Session (+ admin) + CSRF gate; maps store errors to HTML error pages."""
        sess = session_of(request)
        if sess is None or (admin and not sess.get("admin")):
            return RedirectResponse("/ui/login" if sess is None else "/ui/vault", status_code=303)
        _SESSION.set(sess)  # lets page() show the signed-in email; to_thread copies the context
        _NAV.set(next((k for prefix, k in NAV_FOR if request.url.path.startswith(prefix)), ""))
        _FLASH.set(FLASH.get(request.query_params.get("msg", ""), ""))
        form = await request.form() if post else {}
        if post and not hmac.compare_digest(str(form.get("csrf", "")), sess["csrf"]):
            return page("Error", "<p class='err'>Invalid CSRF token.</p>", sess["csrf"], 403, sess["admin"])
        try:
            return await asyncio.to_thread(handler, sess, form)
        except AccessDenied as exc:
            return page("Denied", f"<p class='err'>{e(str(exc))}</p>", sess["csrf"], 403, sess["admin"])
        except ProjectNotFound as exc:
            return page("Not found", f"<p class='err'>{e(str(exc))}</p>", sess["csrf"], 404, sess["admin"])
        except (ValueError, RevisionConflict) as exc:
            return page("Error", f"<p class='err'>{e(str(exc))}</p>", sess["csrf"], 400, sess["admin"])

    def form_html(action: str, csrf: str, fields: dict, button: str, inline: bool = True, extra: str = "",
                  confirm: str = "", cls: str = "") -> str:
        hidden = "".join(f"<input type='hidden' name='{e(k)}' value='{e(str(v))}'>" for k, v in fields.items())
        ask = f" data-confirm='{e(confirm)}'" if confirm else ""
        btn = f"<button class='{cls}'>{e(button)}</button>" if cls else f"<button>{e(button)}</button>"
        if inline:
            return (f"<form method='post' action='{e(action)}' class='inline'{ask}>"
                    f"<input type='hidden' name='csrf' value='{e(csrf)}'>{hidden}{extra}{btn}</form>")
        return (f"<form method='post' action='{e(action)}'{ask}><input type='hidden' name='csrf' value='{e(csrf)}'>{hidden}"
                f"<fieldset role='group'>{extra}{btn}</fieldset></form>")

    def back(path: str, msg: str = ""):
        if msg:
            path += ("&" if "?" in path else "?") + "msg=" + msg
        return RedirectResponse(path, status_code=303)

    # ---- login -------------------------------------------------------------

    @app.custom_route("/", methods=["GET"], include_in_schema=False)
    @app.custom_route("/ui", methods=["GET"], include_in_schema=False)
    async def ui_root(_request):
        return back("/ui/vault")

    @app.custom_route("/ui/static/{name}", methods=["GET"], include_in_schema=False)
    async def static(request: Request):
        name = request.path_params["name"]
        if name not in STATIC_TYPES:
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(STATIC / name, media_type=STATIC_TYPES[name], headers={"Cache-Control": "public, max-age=86400"})

    @app.custom_route("/ui/login", methods=["GET"], include_in_schema=False)
    async def login_page(request: Request):
        if session_of(request) is not None:
            return back("/ui/vault")
        problem = {"denied": "This Google account is not authorised. Ask an administrator to add your email.",
                   "state": "The sign-in expired or was interrupted. Please try again."}.get(request.query_params.get("e", ""))
        note = f"<p class='err' role='alert'>{e(problem)}</p>" if problem else ""
        body = ("<main class='login'><article>"
                f"<img src='/ui/static/logo.png?v={ASSET_V}' alt='Evidence' width='260'>"
                f"<p class='tagline'>Shared protocols and secrets for your AI agents.</p>"
                f"<a role='button' class='google' href='/ui/login/google'>{GOOGLE_G}<span>Sign in with Google</span></a>"
                f"{note}</article></main>")
        return page("Sign in", body, bare=True)

    @app.custom_route("/ui/login/google", methods=["GET"], include_in_schema=False)
    async def login(_request):
        cfg = await asyncio.to_thread(endpoints)
        state, nonce, verifier_code = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        query = urllib.parse.urlencode({
            "client_id": google_client_id, "response_type": "code", "redirect_uri": f"{origin}/ui/callback",
            "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
            "code_challenge": _b64(hashlib.sha256(verifier_code.encode()).digest()), "code_challenge_method": "S256"})
        resp = back(f"{cfg['authorization_endpoint']}?{query}")
        set_cookie(resp, "evui_login", {"state": state, "nonce": nonce, "v": verifier_code}, 600)
        return resp

    @app.custom_route("/ui/callback", methods=["GET"], include_in_schema=False)
    async def callback(request: Request):
        pending = unsign(session_secret, request.cookies.get("evui_login"))
        code, state = request.query_params.get("code"), request.query_params.get("state", "")
        if not pending or not code or not hmac.compare_digest(state, pending["state"]):
            return back("/ui/login?e=state")
        cfg = await asyncio.to_thread(endpoints)
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": code, "client_id": google_client_id,
            "client_secret": google_client_secret, "redirect_uri": f"{origin}/ui/callback",
            "code_verifier": pending["v"]}).encode()

        def authenticate():
            with urllib.request.urlopen(urllib.request.Request(cfg["token_endpoint"], data=data), timeout=10) as r:
                raw = json.load(r)["id_token"]
            claims = verify_google_id_token(raw, jwks["client"], google_client_id, pending["nonce"])
            email = claims["email"].lower()
            is_admin = email in admin_emails
            subject = store.login_user(email, claims.get("name") or "", is_admin)
            return None if subject is None else (subject, email, is_admin)

        try:
            who = await asyncio.to_thread(authenticate)
        except Exception:  # noqa: BLE001 - any exchange/verification failure is a failed login; details stay off the page
            who = None
        if who is None:
            return back("/ui/login?e=denied")
        resp = back("/ui/vault")
        set_cookie(resp, "evui", {"sub": who[0], "email": who[1], "admin": who[2], "csrf": secrets.token_urlsafe(24)}, SESSION_TTL)
        resp.delete_cookie("evui_login", path="/ui")
        return resp

    # ---- secrets (every logged-in user) ------------------------------------

    SECRETS_JS = (
        "const csrf=document.body.dataset.csrf;"
        "document.addEventListener('click',async ev=>{const b=ev.target.closest('button[data-act]');if(!b)return;"
        "const card=b.closest('.secret'),out=card.querySelector('pre.val'),act=b.dataset.act;"
        "if(act==='reveal'&&!out.hidden){out.hidden=true;out.textContent='';b.textContent='Reveal';return;}"
        "b.disabled=true;let r;try{r=await fetch('/ui/vault/value',{method:'POST',credentials:'same-origin',"
        "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
        "body:new URLSearchParams({csrf,name:card.dataset.name})});}finally{b.disabled=false;}"
        "if(!r.ok){alert('You are not allowed to read this secret.');return;}const v=(await r.json()).value;"
        "if(act==='copy'){await navigator.clipboard.writeText(v);const t=b.textContent;b.textContent='Copied';"
        "setTimeout(()=>b.textContent=t,1500);}"
        "else{out.textContent=v;out.hidden=false;b.textContent='Hide';"
        "setTimeout(()=>{out.hidden=true;out.textContent='';b.textContent='Reveal';},30000);}});"
        "const q=document.getElementById('q'),cat=document.getElementById('cat'),cards=[...document.querySelectorAll('.secret')],"
        "count=document.getElementById('count');"
        "function filter(){const t=(q.value||'').toLowerCase(),c=cat.value;let n=0;cards.forEach(a=>{"
        "const ok=(!t||a.dataset.search.includes(t))&&(!c||a.dataset.cat===c);a.hidden=!ok;if(ok)n++;});"
        "count.textContent=n+' of '+cards.length+' secret'+(cards.length===1?'':'s');}"
        "if(q){q.addEventListener('input',filter);cat.addEventListener('change',filter);}")

    def head(title: str, actions: str = "", sub: str = "") -> str:
        return (f"<div class='page-head'><div><h2>{e(title)}</h2>{f'<p class=muted>{sub}</p>' if sub else ''}</div>"
                f"<div class='page-actions'>{actions}</div></div>")

    def category_options(selected: str = "") -> str:
        return "".join(
            f"<option value='{e(c['name'])}'{' selected' if c['name'] == selected else ''}>"
            f"{e(c['name'])}{' - ' + e(c['description']) if c['description'] else ''}</option>" for c in store.list_categories())

    def clean_value(raw: str) -> str:
        """Browsers submit textarea newlines as CRLF. Keep multi-line text as typed (with LF); trim single-line values."""
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip() if "\n" not in text.strip() else text.rstrip("\n") + "\n"

    def share_pickers(projects: list[dict], people: list[dict], picked_projects=(), picked_users=()) -> str:
        proj = "".join(
            f"<label><input type='checkbox' name='project' value='{e(p['slug'])}'{' checked' if p['slug'] in picked_projects else ''}> "
            f"<span>{e(p['name'])} <small class='muted'>{e(p['slug'])}</small></span></label>" for p in projects
        ) or "<p class='muted'>You do not own or edit a project yet.</p>"
        def person(u):
            name = f" <small class='muted'>{e(u['display_name'])}</small>" if u.get("display_name") else ""
            checked = " checked" if u["subject"] in picked_users else ""
            return f"<label><input type='checkbox' name='user' value='{e(u['subject'])}'{checked}> <span>{mail(u['email'])}{name}</span></label>"

        ppl = "".join(person(u) for u in people) or "<p class='muted'>No other users yet.</p>"
        return (f"<fieldset class='pickers'><legend>Share with projects</legend><div class='checks'>{proj}</div></fieldset>"
                f"<fieldset class='pickers'><legend>Share with people</legend><div class='checks'>{ppl}</div></fieldset>")

    def secrets_page(sess, _f):
        items = store.vault_list(sess["sub"], False)
        cards = ""
        for it in items:
            pills = "".join(f"<span class='badge proj'>{e(s)}</span>" for s in it["projects"])
            if it["users"]:
                pills += f"<span class='badge'>{it['users']} {'person' if it['users'] == 1 else 'people'}</span>"
            shared = pills or "<span class='badge'>private</span>"
            manage = (f"<a role='button' class='outline secondary compact' href='/ui/secret?name={e(urllib.parse.quote(it['name']))}'>Manage</a>"
                      if it["mine"] or sess["admin"] else "")
            desc = f"<p class='desc'>{e(it['description'])}</p>" if it["description"] else ""
            search = " ".join([it["name"], it["description"], it["category"], str(it["owner"]), *it["projects"]]).lower()
            cards += (
                f"<article class='secret' data-name='{e(it['name'])}' data-cat='{e(it['category'])}' data-search='{e(search)}'>"
                f"<header><div class='title'><strong class='sname'>{e(it['name'])}</strong>"
                f"<span class='badge cat'>{e(it['category'])}</span></div>"
                f"<div class='actions'><button data-act='reveal'>Reveal</button><button data-act='copy' class='outline'>Copy</button>{manage}</div></header>"
                f"{desc}"
                f"<p class='meta'><small class='muted'>{'Owned by you' if it['mine'] else 'From ' + mail(it['owner'])} &middot; "
                f"Shared with:</small> {shared} <small class='muted'>&middot; updated {e(it['updated_at'][:10])}</small></p>"
                f"<pre class='val' hidden></pre></article>")
        cats = sorted({it["category"] for it in items})
        toolbar = (f"<div class='toolbar'><input id='q' type='search' placeholder='Search by name, description or project' aria-label='Search secrets'>"
                   f"<select id='cat' aria-label='Category'><option value=''>All categories</option>"
                   + "".join(f"<option>{e(c)}</option>" for c in cats) + "</select></div>"
                   f"<p id='count' class='muted'>{len(items)} of {len(items)} secret{'' if len(items) == 1 else 's'}</p>") if items else ""
        empty = ("<article class='empty'><h3>No secrets yet</h3><p class='muted'>Store passwords, API keys, certificates or whole .env "
                 "files, then share them with projects and people. Nothing is shown until someone asks to reveal or copy it.</p>"
                 "<a role='button' href='/ui/secret/new'>Add your first secret</a></article>")
        body = (head("Secrets", "<a role='button' href='/ui/secret/new'>+ New secret</a>",
                     "Everything you own or that was shared with you. Values load only when you click, and every read is logged.")
                + toolbar + (cards or empty))
        return page("Secrets", body, sess["csrf"], admin=sess["admin"], script=SECRETS_JS if items else "")

    @app.custom_route("/ui/vault", methods=["GET"], include_in_schema=False)
    async def vault_page(request):
        return await guarded(request, secrets_page, admin=False)

    def secret_value(sess, f):
        value = store.vault_get(f.get("name", ""), sess["sub"])  # audited as vault.read
        return JSONResponse({"value": value}, headers={"Cache-Control": "no-store"})

    @app.custom_route("/ui/vault/value", methods=["POST"], include_in_schema=False)
    async def vault_value(request):
        return await guarded(request, secret_value, True, admin=False)

    def new_secret_page(preselect: str):
        def render(sess, _f):
            projects = store.list_manageable_projects(sess["sub"], sess["admin"])
            people = store.list_people(sess["sub"])
            form = (
                f"<form method='post' action='/ui/vault/save' class='secret-form'>"
                f"<input type='hidden' name='csrf' value='{e(sess['csrf'])}'>"
                f"<div class='grid'><label>Name<input name='name' required maxlength='128' pattern='[A-Za-z_][A-Za-z0-9_]*' "
                f"placeholder='CLOUDFLARE_API_TOKEN' autocomplete='off' spellcheck='false'>"
                f"<small>Letters, digits and underscores. This is also the environment variable name when you use <code>run</code>.</small></label>"
                f"<label>Category<select name='category'>{category_options()}</select>"
                f"<small>Project owners always see everything in their project; other members see the categories they were granted.</small></label></div>"
                f"<label>Description <small>(optional, not secret)</small><input name='description' maxlength='500' "
                f"placeholder='What it is for and where it is used'></label>"
                f"<label>Value<textarea id='secret-value' name='value' class='mono' rows='10' required spellcheck='false' "
                f"autocomplete='off' autocapitalize='off' placeholder='Paste the secret. Several lines are fine: SSH keys, certificates, JSON, .env blocks.'></textarea>"
                f"<small>Line breaks are kept exactly as typed. It is encrypted before it is stored.</small></label>"
                f"<label class='check'><input type='checkbox' data-mask='secret-value'> Hide characters while I type</label>"
                f"{share_pickers(projects, people, picked_projects=(preselect,) if preselect else ())}"
                f"<div class='form-actions'><button>Create secret</button><a role='button' class='outline secondary' href='/ui/vault'>Cancel</a></div></form>")
            body = (f"<p><a href='/ui/vault'>&larr; Secrets</a></p>"
                    + head("New secret", sub="Share it with projects and people now, or later from its Manage page.")
                    + f"<article>{form}</article>")
            return page("New secret", body, sess["csrf"], admin=sess["admin"])
        return render

    @app.custom_route("/ui/secret/new", methods=["GET"], include_in_schema=False)
    async def secret_new_get(request):
        return await guarded(request, new_secret_page(request.query_params.get("project", "")), admin=False)

    def secret_create(sess, f):
        name = f["name"].strip()
        if store.secret_exists(name):
            raise ValueError(f"A secret named {name} already exists. Open it from the list and use Manage to change it.")
        store.vault_put(name, f["category"], clean_value(f["value"]), sess["sub"], sess["admin"], None, f.get("description", ""))
        projects, users = f.getlist("project"), f.getlist("user")
        if projects or users:
            store.set_secret_shares(name, projects, users, sess["sub"], sess["admin"])
        return back("/ui/vault", "created")

    @app.custom_route("/ui/vault/save", methods=["POST"], include_in_schema=False)
    async def vault_save(request):
        return await guarded(request, secret_create, True, admin=False)

    def secret_page(name: str):
        def render(sess, _f):
            shares = store.secret_shares(name, sess["sub"], sess["admin"])
            csrf = sess["csrf"]
            current = next((x for x in store.vault_list(sess["sub"], sess["admin"], include_unreadable=True) if x["name"] == name), None)
            details = (
                f"<form method='post' action='/ui/secret/update'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                f"<input type='hidden' name='name' value='{e(name)}'>"
                f"<div class='grid'><label>Category<select name='category'>{category_options(shares['category'])}</select></label>"
                f"<label>Description<input name='description' maxlength='500' value='{e(shares['description'])}'></label></div>"
                f"<label>New value <small>(leave empty to keep the current one)</small>"
                f"<textarea id='new-value' name='value' class='mono' rows='6' spellcheck='false' autocomplete='off' autocapitalize='off'></textarea></label>"
                f"<label class='check'><input type='checkbox' data-mask='new-value'> Hide characters while I type</label>"
                f"<button>Save changes</button></form>")
            sharing = (f"<form method='post' action='/ui/secret/share'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                       f"<input type='hidden' name='name' value='{e(name)}'>"
                       + share_pickers(shares["manageable_projects"], shares["people"], shares["projects"], shares["users"])
                       + "<button>Save sharing</button></form>")
            delete = (f"<p class='muted'>Deleting removes the secret for everyone it is shared with. This cannot be undone.</p>"
                      + form_html("/ui/secret/delete", csrf, {"name": name}, "Delete this secret",
                                  confirm=f"Delete {name} for everyone? This cannot be undone.", cls="danger"))
            owner = mail(current["owner"]) if current else ""
            body = (f"<p><a href='/ui/vault'>&larr; Secrets</a></p>"
                    + head(name, sub=f"Owned by {owner}. Revision {current['revision'] if current else 1}. "
                           f"Project owners read it everywhere it is shared; other members need the <strong>{e(shares['category'])}</strong> "
                           f"category on that project. People you pick below can always read it.")
                    + f"<article><header>Details</header>{details}</article>"
                    + f"<article><header>Sharing</header>{sharing}</article>"
                    + f"<article class='danger-zone'><header>Delete</header>{delete}</article>")
            return page(name, body, csrf, admin=sess["admin"])
        return render

    @app.custom_route("/ui/secret", methods=["GET"], include_in_schema=False)
    async def secret_get(request):
        return await guarded(request, secret_page(request.query_params.get("name", "")), admin=False)

    def secret_update(sess, f):
        raw = f.get("value", "")
        store.vault_update(f["name"], sess["sub"], sess["admin"], category=f["category"],
                           description=f.get("description", ""), value=clean_value(raw) if raw.strip() else None)
        return back(f"/ui/secret?name={urllib.parse.quote(f['name'])}", "saved")

    @app.custom_route("/ui/secret/update", methods=["POST"], include_in_schema=False)
    async def secret_update_route(request):
        return await guarded(request, secret_update, True, admin=False)

    def secret_share(sess, f):
        store.set_secret_shares(f["name"], f.getlist("project"), f.getlist("user"), sess["sub"], sess["admin"])
        return back(f"/ui/secret?name={urllib.parse.quote(f['name'])}", "shared")

    @app.custom_route("/ui/secret/share", methods=["POST"], include_in_schema=False)
    async def secret_share_route(request):
        return await guarded(request, secret_share, True, admin=False)

    def secret_delete(sess, f):
        store.vault_delete(f["name"], sess["sub"], sess["admin"])
        return back("/ui/vault", "deleted")

    @app.custom_route("/ui/secret/delete", methods=["POST"], include_in_schema=False)
    async def secret_delete_route(request):
        return await guarded(request, secret_delete, True, admin=False)

    # ---- my Evidence secret (the evk_ token) -------------------------------

    def hint(t) -> str:
        return (f"<code>evk_&hellip;{e(t['token_hint'])}</code>" if t.get("token_hint")
                else "<span class='muted'>not recorded</span>")

    def token_page(sess, _f, notice: str = ""):
        csrf = sess["csrf"]
        tokens = store.list_own_tokens(sess["sub"])
        shown_revoked = sum(1 for t in tokens if t["revoked_at"])
        hidden = store.count_own_revoked(sess["sub"]) - shown_revoked
        rows = "".join(
            f"<tr><td>{e(t['label'] or 'unnamed')}</td><td>{hint(t)}</td>"
            f"<td>{e(str(t['created_at'])[:16].replace('T', ' '))}</td>"
            f"<td>{e(str(t['last_used'])[:16].replace('T', ' ')) if t['last_used'] else 'never'}</td><td>"
            + ("<span class='badge off'>revoked</span>" if t["revoked_at"] else
               form_html("/ui/token/revoke", csrf, {"id": t["id"]}, "Revoke",
                         confirm="Revoke this Evidence secret? Anything using it will stop working.", cls="danger"))
            + "</td></tr>" for t in tokens)
        more = (f"<p class='muted'><small>{hidden} older revoked secret{'s' if hidden != 1 else ''} not shown. "
                f"All active ones and your 3 most recently revoked are listed.</small></p>") if hidden > 0 else ""
        table = (f"<table class='striped'><tr><th>Label</th><th>Ends with</th><th>Created</th><th>Last used</th><th></th></tr>{rows}</table>{more}"
                 if rows else "<p class='muted'>You have not generated an Evidence secret yet.</p>")
        gen = form_html("/ui/token/new", csrf, {}, "Generate Evidence secret", False,
                        "<input name='label' placeholder='Where will you use it? (laptop, CI...)' maxlength='100'>")
        how = (f"<pre><code>export EVIDENCE_TOKEN=&lt;your Evidence secret&gt;\n"
               f"python3 evidence_install.py join --target . --agent claude --service-url {e(origin)}/mcp\n"
               f"python3 evidence_install.py run --target . -- ./your-command</code></pre>")
        body = (f"{notice}" + head("Evidence secret", sub="The key that lets you and your AI agents join projects and pull the secrets "
                                    "shared with you. It is not one of the vault secrets: keep it private and revoke it if it leaks.")
                + f"<article><header>Generate a new one</header>{gen}</article>"
                + f"<article><header>Your Evidence secrets</header>{table}</article>"
                + f"<article><header>Add a project to Evidence "
                  f"<button type='button' class='compact' data-copy='agent-prompt'>Copy prompt</button></header>"
                  f"<ol class='steps'><li>In a terminal, in the repository, run <code>export EVIDENCE_TOKEN=&lt;your Evidence secret&gt;</code>.</li>"
                  f"<li>Start your AI agent there and paste this prompt. The secret itself is never part of the prompt.</li></ol>"
                  f"<pre id='agent-prompt' class='prompt'>{e(agent_prompt(origin))}</pre></article>"
                + f"<article><header>How to use it</header>{how}</article>")
        return page("Evidence secret", body, csrf, admin=sess["admin"])

    @app.custom_route("/ui/token", methods=["GET"], include_in_schema=False)
    async def token_get(request):
        return await guarded(request, token_page, admin=False)

    def token_new(sess, f):
        issued = store.issue_own_token(sess["sub"], f.get("label", ""))
        notice = ("<article class='reveal-once'><header><strong>Copy it now</strong></header>"
                  "<p>This Evidence secret is shown only once. Only a fingerprint is stored, so it cannot be recovered later.</p>"
                  f"<pre class='tok'>{e(issued['token'])}</pre></article>")
        return token_page(sess, f, notice)

    @app.custom_route("/ui/token/new", methods=["POST"], include_in_schema=False)
    async def token_new_route(request):
        return await guarded(request, token_new, True, admin=False)

    def token_revoke_own(sess, f):
        store.revoke_own_token(f["id"], sess["sub"])
        return back("/ui/token", "revoked")

    @app.custom_route("/ui/token/revoke", methods=["POST"], include_in_schema=False)
    async def token_revoke_route(request):
        return await guarded(request, token_revoke_own, True, admin=False)

    # ---- users (admin) -----------------------------------------------------

    def users_page(sess, _form, notice: str = ""):
        csrf = sess["csrf"]
        rows = ""
        for u in store.list_users(True):
            sub = u["subject"]
            tokens = [t for t in store.list_tokens(sub, True) if not t["revoked_at"]]
            tok_html = "".join(
                f"<div class='tokrow'>{hint(t)} <small class='muted'>created {e(str(t['created_at'])[:10])}</small> "
                f"{form_html('/ui/tokens/revoke', csrf, {'id': t['id']}, 'Revoke', confirm='Revoke this Evidence secret?', cls='danger')}</div>"
                for t in tokens) or "<span class='muted'>none</span>"
            status = "<span class='badge off'>disabled</span>" if u["disabled"] else "<span class='badge ok'>active</span>"
            who = u['email'] or u['subject']
            rows += (f"<tr><td><div class='usercell'><span class='avatar' aria-hidden='true'>{e(who[:1].upper())}</span>"
                     f"<div>{mail(who)}<br><small class='muted'>{e(u['display_name'] or '')}</small></div></div></td><td>{status}</td>"
                     f"<td>{tok_html}{form_html('/ui/users/token', csrf, {'subject': sub}, 'New', )}</td><td class='row-actions'>"
                     f"{form_html('/ui/users/toggle', csrf, {'subject': sub, 'disabled': '0' if u['disabled'] else '1'}, 'Enable' if u['disabled'] else 'Disable', cls='outline')}"
                     f"{form_html('/ui/users/delete', csrf, {'subject': sub}, 'Delete', confirm='Delete this user? This cannot be undone.', cls='danger')}</td></tr>")
        create = ("<details class='create'><summary role='button'>+ New user</summary>"
                  + form_html("/ui/users", csrf, {}, "Create user", False,
                              "<input name='email' type='email' placeholder='Google email' required> <input name='display_name' placeholder='Name'>")
                  + "<p class='muted'>They sign in with that Google account, then generate their own Evidence secret.</p></details>")
        body = (f"{notice}" + head("Users", sub="People who can sign in. Unknown Google accounts are refused.") + create
                + f"<table class='striped'><tr><th>User</th><th>Status</th><th>Evidence secrets</th><th></th></tr>{rows}</table>")
        return page("Users", body, csrf, admin=True)

    @app.custom_route("/ui/users", methods=["GET"], include_in_schema=False)
    async def users_get(request):
        return await guarded(request, users_page)

    def user_create(sess, f):
        store.create_user(f.get("email", ""), f.get("display_name", ""), True)
        return back("/ui/users", "user-created")

    @app.custom_route("/ui/users", methods=["POST"], include_in_schema=False)
    async def users_post(request):
        return await guarded(request, user_create, True)

    def user_toggle(sess, f):
        store.update_user(f["subject"], True, disabled=f.get("disabled") == "1")
        return back("/ui/users", "user-updated")

    @app.custom_route("/ui/users/toggle", methods=["POST"], include_in_schema=False)
    async def users_toggle(request):
        return await guarded(request, user_toggle, True)

    def user_delete(sess, f):
        store.delete_user(f["subject"], True)
        return back("/ui/users", "user-deleted")

    @app.custom_route("/ui/users/delete", methods=["POST"], include_in_schema=False)
    async def users_delete(request):
        return await guarded(request, user_delete, True)

    def token_issue(sess, f):
        issued = store.issue_token(f["subject"], f.get("label", ""), True)
        notice = ("<article class='reveal-once'><header><strong>Copy it now</strong></header>"
                  "<p>Shown once; only its hash is stored.</p>"
                  f"<pre class='tok'>{e(issued['token'])}</pre></article>")
        return users_page(sess, f, notice)  # rendered in-response, never redirected or logged

    @app.custom_route("/ui/users/token", methods=["POST"], include_in_schema=False)
    async def users_token(request):
        return await guarded(request, token_issue, True)

    def token_revoke(sess, f):
        store.revoke_token(f["id"], True)
        return back("/ui/users", "revoked")

    @app.custom_route("/ui/tokens/revoke", methods=["POST"], include_in_schema=False)
    async def tokens_revoke(request):
        return await guarded(request, token_revoke, True)

    # ---- categories (admin) ------------------------------------------------

    def categories_page(sess, _f):
        rows = "".join(f"<tr><td><span class='badge cat'>{e(c['name'])}</span></td><td>{e(c['description'])}</td></tr>"
                       for c in store.list_categories())
        create = ("<details class='create'><summary role='button'>+ New category</summary>"
                  + form_html("/ui/categories", sess["csrf"], {}, "Add category", False,
                              "<input name='name' placeholder='name (lowercase)' required pattern='[a-z0-9][a-z0-9-]*'> <input name='description' placeholder='Description'>")
                  + "</details>")
        body = (head("Categories", sub="Secrets are grouped into categories. Project members read the categories they were granted.")
                + create + f"<table class='striped'><tr><th>Category</th><th>Description</th></tr>{rows}</table>")
        return page("Categories", body, sess["csrf"], admin=True)

    @app.custom_route("/ui/categories", methods=["GET"], include_in_schema=False)
    async def categories_get(request):
        return await guarded(request, categories_page)

    def category_create(sess, f):
        store.create_category(f.get("name", ""), f.get("description", ""))
        return back("/ui/categories", "category-created")

    @app.custom_route("/ui/categories", methods=["POST"], include_in_schema=False)
    async def categories_post(request):
        return await guarded(request, category_create, True)

    # ---- projects, members, grants (admin) ---------------------------------

    def projects_page(sess, _f):
        csrf, admin = sess["csrf"], sess["admin"]
        rows = ""
        for p in store.list_projects(sess["sub"], admin):
            role = f"<span class='badge ok'>{e(p['role'])}</span>" if p["role"] else "<span class='badge'>admin view</span>"
            manage = (f"<a role='button' class='outline secondary compact' href='/ui/project?slug={e(urllib.parse.quote(p['slug']))}'>Manage</a>"
                      if admin else "")
            rows += (f"<tr><td><a href='/ui/protocol?slug={e(urllib.parse.quote(p['slug']))}'><strong>{e(p['name'])}</strong></a>"
                     f"<br><small class='muted'>{e(p['slug'])}</small></td><td>{role}</td>"
                     f"<td>revision {p['revision']}<br><small class='muted'>{e(str(p['updated_at'])[:10])}</small></td>"
                     f"<td class='row-actions'><a role='button' class='compact' href='/ui/protocol?slug={e(urllib.parse.quote(p['slug']))}'>Protocol</a> {manage}</td></tr>")
        create = ("<details class='create'><summary role='button'>+ New project</summary>"
                  + form_html("/ui/projects", csrf, {}, "Create project", False,
                              "<input name='slug' placeholder='slug (lowercase)' required> <input name='name' placeholder='Name' required>")
                  + "</details>") if admin else ""
        empty = ("<article class='empty'><h3>No projects yet</h3><p class='muted'>Add a repository from your terminal with an AI agent: "
                 "the prompt is on the <a href='/ui/token'>Evidence secret</a> page. The project appears here once it is registered.</p></article>")
        body = (head("Projects", sub="Each project keeps its protocol here: read it, download it, edit it and see its history.") + create
                + (f"<table class='striped'><tr><th>Project</th><th>Your role</th><th>Protocol</th><th></th></tr>{rows}</table>" if rows else empty))
        return page("Projects", body, csrf, admin=admin)

    @app.custom_route("/ui/projects", methods=["GET"], include_in_schema=False)
    async def projects_get(request):
        return await guarded(request, projects_page, admin=False)

    # ---- the protocol document (what EVIDENCE_PROTOCOL.md used to be) ------

    def sync_badge(m: dict) -> str:
        when = f" <small class='muted'>{e(str(m['read_at'])[:16].replace('T', ' '))} via {e(m['via'])}</small>" if m["read_at"] else ""
        if m["status"] == "current":
            return f"<span class='badge ok'>up to date</span> <small class='muted'>revision {m['read_revision']}</small>{when}"
        if m["status"] == "behind":
            return f"<span class='badge warn'>{m['behind']} behind</span> <small class='muted'>read revision {m['read_revision']}</small>{when}"
        return "<span class='badge off'>never read</span>"

    def sync_card(status: dict) -> str:
        rows = "".join(f"<tr><td>{mail(m['email'])}<br><small class='muted'>{e(m['role'])}</small></td><td>{sync_badge(m)}</td></tr>"
                       for m in status["members"])
        warn = status["synced"] < status["total"]
        return (f"<details class='sync{' attention' if warn else ''}'><summary>Sync status: {status['synced']} of {status['total']} member"
                f"{'' if status['total'] == 1 else 's'} {'has' if status['total'] == 1 else 'have'} read revision {status['current_revision']}</summary>"
                f"<table class='striped'><tr><th>Member</th><th>Protocol read</th></tr>{rows}</table>"
                f"<p class='muted'><small>Counted when a member's AI agent reads the protocol through Evidence, or when they open it here. "
                f"Someone who never starts an agent session on this project shows as never read.</small></p></details>")

    def protocol_tabs(slug: str, role: str | None, admin: bool, current: bool = True) -> str:
        q = e(urllib.parse.quote(slug))
        out = (f"<a role='button' class='outline secondary compact' href='/ui/protocol/history?slug={q}'>History</a>"
               f"<a role='button' class='outline secondary compact' href='/ui/protocol/raw?slug={q}'>Download .md</a>")
        if role in ("owner", "editor") and current:
            out += f"<a role='button' class='compact' href='/ui/protocol/edit?slug={q}'>Edit</a>"
        if admin:
            out += f"<a role='button' class='outline secondary compact' href='/ui/project?slug={q}'>Manage</a>"
        return out

    def protocol_view(slug: str, rev: str):
        def render(sess, _f):
            current = store.get_protocol(slug, sess["sub"], sess["admin"])
            latest = store.list_revisions(slug, sess["sub"], 1, sess["admin"])[0]
            if rev.isdigit() and int(rev) != current["revision"]:
                doc = store.get_revision(slug, int(rev), sess["sub"], sess["admin"])
                banner = (f"<p class='flash'>You are reading revision {doc['revision']}, not the current one (revision {current['revision']}). "
                          f"<a href='/ui/protocol?slug={e(urllib.parse.quote(slug))}'>Back to the current protocol</a></p>")
                sub = f"Revision {doc['revision']} &middot; {e(doc['created_at'][:16].replace('T', ' '))} by {mail(doc['actor_email'])}"
                content, is_current = doc["content"], False
            else:
                banner, is_current, content = "", True, current["content"]
                store.touch_read(slug, sess["sub"], current["revision"], "web")
                sub = (f"{e(slug)} &middot; revision {current['revision']} &middot; updated {e(latest['created_at'][:16].replace('T', ' '))}"
                       f" by {mail(latest['actor_email'])} &mdash; {e(latest['summary'])}")
            body = (f"<p><a href='/ui/projects'>&larr; Projects</a></p>" + banner
                    + head(current["name"], protocol_tabs(slug, current["role"], sess["admin"], is_current), sub)
                    + sync_card(store.sync_status(slug, sess["sub"], sess["admin"]))
                    + f"<article class='protocol'>{render_markdown(content)}</article>")
            return page(current["name"], body, sess["csrf"], admin=sess["admin"])
        return render

    @app.custom_route("/ui/protocol", methods=["GET"], include_in_schema=False)
    async def protocol_get(request):
        return await guarded(request, protocol_view(request.query_params.get("slug", ""), request.query_params.get("rev", "")), admin=False)

    def protocol_raw(slug: str, rev: str):
        def render(sess, _f):
            if rev.isdigit():
                text = store.get_revision(slug, int(rev), sess["sub"], sess["admin"])["content"]
            else:
                text = store.get_protocol(slug, sess["sub"], sess["admin"])["content"]
            return PlainTextResponse(text, media_type="text/markdown; charset=utf-8", headers={
                "Content-Disposition": 'attachment; filename="EVIDENCE_PROTOCOL.md"', "Cache-Control": "no-store"})
        return render

    @app.custom_route("/ui/protocol/raw", methods=["GET"], include_in_schema=False)
    async def protocol_raw_get(request):
        return await guarded(request, protocol_raw(request.query_params.get("slug", ""), request.query_params.get("rev", "")), admin=False)

    def protocol_history(slug: str):
        def render(sess, _f):
            current = store.get_protocol(slug, sess["sub"], sess["admin"])
            q = e(urllib.parse.quote(slug))
            rows = "".join(
                f"<tr><td>revision {r['revision']}{' <span class=badge-ok>current</span>' if r['revision'] == current['revision'] else ''}</td>"
                f"<td>{e(r['created_at'][:16].replace('T', ' '))}</td><td>{mail(r['actor_email'] or r['actor_subject'])}</td><td>{e(r['summary'])}</td>"
                f"<td class='row-actions'><a role='button' class='outline secondary compact' href='/ui/protocol?slug={q}&rev={r['revision']}'>Read</a> "
                f"<a role='button' class='outline secondary compact' href='/ui/protocol/raw?slug={q}&rev={r['revision']}'>.md</a></td></tr>"
                for r in store.list_revisions(slug, sess["sub"], 100, sess["admin"])).replace("badge-ok", "badge ok")
            body = (f"<p><a href='/ui/protocol?slug={q}'>&larr; Protocol</a></p>" + head(f"{current['name']}: history", sub="Every saved revision is kept.")
                    + f"<table class='striped'><tr><th>Revision</th><th>When</th><th>Who</th><th>What changed</th><th></th></tr>{rows}</table>")
            return page("History", body, sess["csrf"], admin=sess["admin"])
        return render

    @app.custom_route("/ui/protocol/history", methods=["GET"], include_in_schema=False)
    async def protocol_history_get(request):
        return await guarded(request, protocol_history(request.query_params.get("slug", "")), admin=False)

    def edit_page(sess, slug: str, content: str, expected: int, name: str, error: str = "", summary: str = ""):
        q = e(urllib.parse.quote(slug))
        note = f"<p class='err' role='alert'>{e(error)}</p>" if error else ""
        form = (f"<form method='post' action='/ui/protocol/save'><input type='hidden' name='csrf' value='{e(sess['csrf'])}'>"
                f"<input type='hidden' name='slug' value='{e(slug)}'><input type='hidden' name='expected_revision' value='{expected}'>"
                f"<label>What did you change?<input name='summary' required maxlength='500' value='{e(summary)}' "
                f"placeholder='One line for the history'></label>"
                f"<label>Protocol (Markdown)<textarea name='content' class='mono protocol-edit' rows='32' spellcheck='false' required>{e(content)}</textarea>"
                f"<small>Saving creates revision {expected + 1}. The header block is regenerated for you.</small></label>"
                f"<div class='form-actions'><button>Save revision</button><a role='button' class='outline secondary' href='/ui/protocol?slug={q}'>Cancel</a></div></form>")
        body = (f"<p><a href='/ui/protocol?slug={q}'>&larr; Protocol</a></p>" + head(f"Edit {name}") + note + f"<article>{form}</article>")
        return page(f"Edit {name}", body, sess["csrf"], admin=sess["admin"])

    def protocol_edit(slug: str):
        def render(sess, _f):
            current = store.get_protocol(slug, sess["sub"], sess["admin"])
            if current["role"] not in ("owner", "editor"):
                raise AccessDenied("You can read this protocol but only owners and editors can change it.")
            return edit_page(sess, slug, current["content"], current["revision"], current["name"])
        return render

    @app.custom_route("/ui/protocol/edit", methods=["GET"], include_in_schema=False)
    async def protocol_edit_get(request):
        return await guarded(request, protocol_edit(request.query_params.get("slug", "")), admin=False)

    def protocol_save(sess, f):
        slug = f["slug"]
        content = f.get("content", "").replace("\r\n", "\n").replace("\r", "\n")
        try:
            expected = int(f["expected_revision"])
        except (KeyError, ValueError):
            raise ValueError("missing revision; reload the edit page") from None
        normalized = protocol_file(slug, content, "normalize")
        try:
            store.update_protocol(slug, normalized, expected, sess["sub"], f.get("summary", ""), sess.get("email"))
        except RevisionConflict as exc:  # keep the user's text, never lose work; saving again is a deliberate overwrite
            current = store.get_protocol(slug, sess["sub"], sess["admin"])
            return edit_page(sess, slug, content, exc.current_revision, current["name"], summary=f.get("summary", ""),
                             error=(f"Revision {exc.current_revision} was saved by someone else while you were editing. Your text is kept below. "
                                    f"Open the latest in another tab to compare, then save again to replace it."))
        return back(f"/ui/protocol?slug={urllib.parse.quote(slug)}", "protocol-saved")

    @app.custom_route("/ui/protocol/save", methods=["POST"], include_in_schema=False)
    async def protocol_save_post(request):
        return await guarded(request, protocol_save, True, admin=False)

    def projects_admin_gate(sess):
        if not sess["admin"]:
            raise AccessDenied("Only administrators can create projects here. Register a repository with the join command instead.")

    def project_create(sess, f):
        projects_admin_gate(sess)
        slug, name = f.get("slug", ""), f.get("name", "")
        content = protocol_file(slug, f"# {name}\n", "normalize")
        store.create_project(slug, name, content, sess["sub"])
        return back(f"/ui/project?slug={urllib.parse.quote(slug)}", "project-created")

    @app.custom_route("/ui/projects", methods=["POST"], include_in_schema=False)
    async def projects_post(request):
        return await guarded(request, project_create, True)

    def project_page(slug: str):
        def render(sess, _f):
            csrf = sess["csrf"]
            members = store.list_members(slug, sess["sub"], True)
            cats = store.list_categories()
            granted = store.member_category_names(slug)
            sync = {m["subject"]: m for m in store.sync_status(slug, sess["sub"], True)["members"]}
            mrows = ""
            for m in members:
                boxes = "".join(
                    f"<label><input type='checkbox' name='cat' value='{e(c['name'])}'"
                    f"{' checked' if c['name'] in granted.get(m['subject'], set()) else ''}> {e(c['name'])}</label>" for c in cats)
                owner = "<span class='badge ok'>owner: all categories</span>" if m["role"] == "owner" else ""
                mrows += (f"<tr><td>{mail(m['email'] or m['subject'])}<br><small class='muted'>{e(m['role'])}</small></td>"
                          f"<td>{sync_badge(sync[m['subject']])}</td><td>"
                          f"{form_html('/ui/project/grants', csrf, {'slug': slug, 'subject': m['subject']}, 'Save', extra=boxes)}{owner}</td><td>"
                          f"{form_html('/ui/project/member/remove', csrf, {'slug': slug, 'subject': m['subject']}, 'Remove', confirm='Remove this member?', cls='danger')}</td></tr>")
            roles = "<select name='role'><option>editor</option><option>reader</option><option>owner</option></select>"
            users = "".join(f"<option value='{e(u['subject'])}'>{mail(u['email'] or u['subject'])}</option>" for u in store.list_users(True))
            add_member = ("<details class='create'><summary role='button'>+ Add member</summary>"
                          + form_html("/ui/project/member", csrf, {"slug": slug}, "Add member", False, f"<select name='subject'>{users}</select> {roles}")
                          + "</details>")
            srows = "".join(
                f"<tr><td>{e(s['name'])}<br><small class='muted'>{e(s['description'])}</small></td><td><span class='badge cat'>{e(s['category'])}</span></td>"
                f"<td>{mail(s['owner'])}</td><td class='row-actions'>"
                f"{form_html('/ui/project/vault/unshare', csrf, {'slug': slug, 'name': s['name']}, 'Unshare', confirm='Stop sharing this secret with the project?', cls='outline')}"
                f"{form_html('/ui/project/vault/delete', csrf, {'slug': slug, 'name': s['name']}, 'Delete', confirm='Delete this secret for everyone?', cls='danger')}</td></tr>"
                for s in store.vault_list(sess["sub"], True, slug, include_unreadable=True))
            stable = (f"<table class='striped'><tr><th>Secret</th><th>Category</th><th>Owner</th><th></th></tr>{srows}</table>"
                      if srows else "<p class='muted'>Nothing is shared with this project yet, so this project reads no secrets.</p>")
            loose = [s for s in store.vault_list(sess["sub"], True, None, include_unreadable=True) if slug not in s["projects"]]
            if loose:
                picks = "".join(f"<label><input type='checkbox' name='name' value='{e(s['name'])}'> {e(s['name'])} "
                                f"<span class='badge cat'>{e(s['category'])}</span></label>" for s in loose)
                stable += ("<details class='create'><summary role='button'>+ Share existing secrets</summary>"
                           + form_html("/ui/project/vault/share", csrf, {"slug": slug}, "Share selected", False, f"<div class='checks'>{picks}</div>")
                           + "</details>")
            audit = "".join(
                f"<tr><td>{e(a['created_at'][:19].replace('T', ' '))}</td><td>{e(a['event_type'])}</td>"
                f"<td><small class='muted'>{e(json.dumps(a['details'])) if a['details'] else ''}</small></td></tr>" for a in store.list_audit(slug, sess["sub"], 30, True))
            body = (f"<p><a href='/ui/projects'>&larr; Projects</a></p>" + head(slug, f"<a role='button' href='/ui/protocol?slug={e(urllib.parse.quote(slug))}'>Protocol</a>")
                    + f"<article><header>Members and secret access</header>"
                      "<p class='muted'>Categories only limit what non-owner members may read. They do not give the project any secret: "
                      "share secrets with it in the next section.</p>" + add_member
                    + f"<table class='striped'><tr><th>Member</th><th>Protocol</th><th>Categories they can read</th><th></th></tr>{mrows}</table></article>"
                    + f"<article><header>Secrets shared with this project "
                      f"<a role='button' class='compact' href='/ui/secret/new?project={e(urllib.parse.quote(slug))}'>+ New secret</a></header>{stable}</article>"
                    + f"<article><header>Activity</header><table class='striped'><tr><th>When</th><th>Event</th><th>Details</th></tr>{audit}</table></article>")
            return page(slug, body, csrf, admin=True)
        return render

    @app.custom_route("/ui/project", methods=["GET"], include_in_schema=False)
    async def project_get(request):
        return await guarded(request, project_page(request.query_params.get("slug", "")))

    def project_action(fn, msg: str = "saved"):
        async def route(request: Request):
            def handler(sess, f):
                fn(sess, f)
                return back(f"/ui/project?slug={urllib.parse.quote(f['slug'])}", msg)
            return await guarded(request, handler, True)
        return route

    @app.custom_route("/ui/project/member", methods=["POST"], include_in_schema=False)
    async def member_add(request):
        return await project_action(lambda s, f: store.add_member(f["slug"], f["subject"], f["role"], s["sub"], True), "member-added")(request)

    @app.custom_route("/ui/project/member/remove", methods=["POST"], include_in_schema=False)
    async def member_remove(request):
        return await project_action(lambda s, f: store.remove_member(f["slug"], f["subject"], s["sub"], True), "member-removed")(request)

    @app.custom_route("/ui/project/grants", methods=["POST"], include_in_schema=False)
    async def grants_set(request):
        return await project_action(
            lambda s, f: store.set_member_categories(f["slug"], f["subject"], f.getlist("cat"), s["sub"], True), "saved")(request)

    @app.custom_route("/ui/project/vault/delete", methods=["POST"], include_in_schema=False)
    async def vault_remove(request):
        return await project_action(lambda s, f: store.vault_delete(f["name"], s["sub"], True), "deleted")(request)

    @app.custom_route("/ui/project/vault/share", methods=["POST"], include_in_schema=False)
    async def vault_share(request):
        return await project_action(lambda s, f: store.share_into_project(f.getlist("name"), f["slug"], s["sub"], True), "shared")(request)

    @app.custom_route("/ui/project/vault/unshare", methods=["POST"], include_in_schema=False)
    async def vault_unshare(request):
        return await project_action(lambda s, f: store.unshare_from_project(f["name"], f["slug"], s["sub"], True), "shared")(request)
