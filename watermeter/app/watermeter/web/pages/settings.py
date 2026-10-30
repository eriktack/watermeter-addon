"""Settings page: the tunable settings (`settings.FIELDS`), saved to `/data/settings.json` and applied at once.
`GET settings` shows the form; `POST settings` (form) checks, saves and applies, or shows the form again with the error.
The connection (camera, MQTT, log level) stays in the add-on's Configuration tab in Home Assistant."""
from __future__ import annotations

from aiohttp import web

from ...settings import FIELDS, Field, Settings, save_settings, settings_from_dict, settings_to_dict

GROUPS = (("capture", "Capture"), ("recognition", "Recognition"), ("validation", "Validation"),
          ("retention", "Keeping images"))


def _input(f: Field, value, models: tuple[str, ...]) -> str:
    from ..app import esc

    name = f"{f.group}.{f.name}"
    if f.kind == "bool":
        return f'<input type="checkbox" name="{name}" value="1"{" checked" if value else ""}>'
    if f.kind == "patterns":
        return f'<textarea name="{name}" rows="3" cols="16">{esc(chr(10).join(value))}</textarea>'
    choices = f.choices if f.kind == "choice" else (models if f.kind == "model" else ())
    if f.kind == "model" and value not in choices:
        choices = (value, *choices)
    if choices:
        options = "".join(f'<option{" selected" if c == value else ""}>{esc(c)}</option>' for c in choices)
        return f'<select name="{name}">{options}</select>'
    if f.kind == "model":
        return f'<input name="{name}" value="{esc(value)}" size="40">'
    step = "1" if f.kind == "int" else "any"
    return f'<input type="number" name="{name}" value="{esc(value)}" min="{f.lo:g}" max="{f.hi:g}" step="{step}">'


def _body(settings: Settings, models: tuple[str, ...], message: str = "", bad: bool = False) -> str:
    from ..app import esc

    values = settings_to_dict(settings)
    sections = []
    for group, title in GROUPS:
        rows = "".join(
            f'<tr><th><label>{esc(f.label)}</label></th><td>{_input(f, values[f.group][f.name], models)}</td>'
            f'<td class="muted">{esc(f.help)}</td></tr>' for f in FIELDS if f.group == group)
        sections.append(f"<h2>{esc(title)}</h2><table>{rows}</table>")
    note = f'<p class="{"bad" if bad else "ok"}">{esc(message)}</p>' if message else ""
    return f"""\
{note}<form method="post" action="settings">
{"".join(sections)}
<p><button type="submit" class="primary">Save</button>
<span class="muted">Applied at once, no restart. The camera and MQTT connection are in the add-on's Configuration tab
in Home Assistant.</span></p>
</form>"""


def parse_form(form) -> dict:
    """The posted form as the settings' JSON form: numbers parsed, checkboxes present or not, patterns one per line.
    A field that cannot be parsed raises ValueError naming it."""
    data: dict = {}
    for f in FIELDS:
        raw = form.get(f"{f.group}.{f.name}")
        if f.kind == "bool":
            value = raw is not None
        elif raw is None:
            continue
        elif f.kind == "patterns":
            value = raw.splitlines()
        elif f.kind in ("int", "float"):
            try:
                value = int(raw) if f.kind == "int" else float(raw)
            except ValueError:
                raise ValueError(f"{f.label}: {'a whole number' if f.kind == 'int' else 'a number'}") from None
        else:
            value = raw
        data.setdefault(f.group, {})[f.name] = value
    return data


async def handler(request: web.Request) -> web.Response:
    from ..app import context, render_page

    ctx = context(request)
    return render_page(request, "settings", "Settings", _body(ctx.settings, ctx.models))


async def save_handler(request: web.Request) -> web.Response:
    from ..app import context, render_page

    ctx = context(request)
    form = await request.post()
    try:
        settings = settings_from_dict(parse_form(form))
        if ctx.models and settings.recognition.model not in ctx.models:
            raise ValueError(f"Digit model: {settings.recognition.model} is not in the models folder")
    except ValueError as e:
        return render_page(request, "settings", "Settings", _body(ctx.settings, ctx.models, str(e), bad=True))
    if ctx.apply_settings is not None:
        ctx.apply_settings(settings)
    else:   # no service loop (tools/dev_web.py): save and use
        save_settings(ctx.data_dir / "settings.json", settings)
        ctx.settings = settings
    return render_page(request, "settings", "Settings", _body(ctx.settings, ctx.models, "Saved."))
