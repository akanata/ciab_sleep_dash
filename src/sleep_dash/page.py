"""The only HTML in the project.

Plain server-rendered markup, assembled by small ``_xxx() -> str`` functions and
composed by ``_render``. No template engine, no CDN, no build step. Every
interpolation goes through ``html.escape``; HTML attributes are single-quoted so
Python's double-quoted strings need no escaping.

The one rule that is easy to break: **no clock time or date may be formatted into
the markup as final text.** The server does not know the viewer's timezone, so every
instant is emitted as a UTC rendering carrying a ``data-ts`` attribute, and the
inline script rewrites it to the device's own zone. ``test_page.py`` walks the whole
document to enforce this.
"""

import datetime as dt
import json
from html import escape

from sleep_dash import theme
from sleep_dash.view import LegendRow
from sleep_dash.view import Notice
from sleep_dash.view import PageView
from sleep_dash.view import Tile

STYLE = (
    "*{box-sizing:border-box;margin:0;padding:0}"
    f"body{{font-family:{theme.FONT_STACK};background:{theme.PAGE_BG};color:{theme.TEXT};"
    "padding:1.5rem;max-width:1100px;margin:0 auto;line-height:1.5}"
    "h1{font-size:1.05rem;font-weight:600;letter-spacing:.01em}"
    f"h2{{font-size:.85rem;color:{theme.TEXT_MUTED};text-transform:uppercase;"
    "letter-spacing:.03em;margin-bottom:.75rem;font-weight:600}"
    f".card{{background:{theme.CARD_BG};border-radius:12px;padding:1.25rem;margin-bottom:1rem}}"
    "header{display:flex;align-items:baseline;justify-content:space-between;"
    "gap:1rem;flex-wrap:wrap;margin-bottom:1rem}"
    f"header .sub{{font-size:.8rem;color:{theme.TEXT_SECONDARY}}}"
    # Night navigation
    "nav{display:flex;gap:.5rem;align-items:center}"
    f"nav a,nav span{{font-size:.8rem;padding:.35rem .7rem;border-radius:6px;"
    f"background:{theme.BORDER};color:{theme.TEXT};text-decoration:none}}"
    f"nav a:hover{{background:{theme.TEXT_DIM}}}"
    "nav span{opacity:.4}"
    # Summary tiles
    ".metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:.5rem}"
    f".metric{{padding:.6rem;background:{theme.TILE_BG};border-radius:8px}}"
    ".metric .val{font-size:1.25rem;font-weight:700}"
    f".metric .val.empty{{color:{theme.TEXT_DIM};font-weight:400}}"
    f".metric .lbl{{font-size:.7rem;color:{theme.TEXT_MUTED};margin-top:.15rem}}"
    # Legend
    "ul.legend{list-style:none;display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;margin-top:.9rem}"
    "ul.legend li{display:flex;align-items:center;gap:.45rem;font-size:.78rem}"
    "ul.legend .sw{width:11px;height:11px;border-radius:3px;flex:none}"
    f"ul.legend .dur{{color:{theme.TEXT_MUTED}}}"
    # Readout: hidden in the markup, unhidden only by the script, so no
    # interaction is advertised that cannot happen.
    "[hidden]{display:none!important}"
    ".readout{display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:.9rem;"
    f"padding:.6rem .75rem;background:{theme.TILE_BG};border-radius:8px;min-height:2.6rem}}"
    ".readout .pair{display:flex;flex-direction:column}"
    f".readout .k{{font-size:.65rem;color:{theme.TEXT_MUTED};text-transform:uppercase;"
    "letter-spacing:.04em}"
    ".readout .v{font-size:.95rem;font-weight:600;font-variant-numeric:tabular-nums}"
    # Chart
    ".chart-scroll{overflow-x:auto}"
    # min-width keeps the 11px axis labels legible on a phone: the card scrolls
    # sideways instead of scaling the type down to 4px.
    ".chart{width:100%;min-width:640px;height:auto;display:block;touch-action:pan-x pan-y}"
    ".chart:focus{outline:2px solid " + theme.TEXT_SECONDARY + ";outline-offset:2px}"
    # Notices
    ".notice{padding:.9rem 1rem;border-radius:8px;border-left:3px solid;margin-bottom:1rem}"
    ".notice h3{font-size:.95rem;margin-bottom:.3rem}"
    f".notice p{{font-size:.85rem;color:{theme.TEXT_SECONDARY}}}"
    f".notice.info{{background:{theme.CARD_BG};border-color:{theme.SLATE}}}"
    f".notice.warn{{background:{theme.CARD_BG};border-color:{theme.AMBER}}}"
    f".notice.error{{background:{theme.ERROR_BG};border-color:{theme.ROSE}}}"
    # Footer
    f"footer{{font-size:.75rem;color:{theme.TEXT_MUTED};margin-top:1.25rem}}"
    "@media (max-width:480px){body{padding:1rem}}"
)

SCRIPT = (
    "<script>"
    "(function(){"
    "function pad(n){return n<10?'0'+n:''+n;}"
    "function hm(d){return pad(d.getHours())+':'+pad(d.getMinutes());}"
    # 1. Localisation. Runs first and unconditionally: the degraded pages carry
    # timestamps too, and they have no chart. querySelectorAll matches SVG <text>
    # as readily as HTML <time>, so one pass covers the axis and the prose.
    "var nodes=document.querySelectorAll('[data-ts]');"
    "for(var i=0;i<nodes.length;i++){"
    "var el=nodes[i],d=new Date(el.getAttribute('data-ts'));"
    "if(isNaN(d.getTime()))continue;"  # leave the UTC fallback in place
    "var k=el.getAttribute('data-fmt');"
    "if(k==='date'){el.textContent=d.toLocaleDateString(undefined,"
    "{weekday:'short',month:'short',day:'numeric'});}"
    "else if(k==='datetime'){el.textContent=d.toLocaleDateString(undefined,"
    "{month:'short',day:'numeric'})+' '+hm(d);}"
    "else{el.textContent=hm(d);}"
    "}"
    "var z=document.getElementById('tz-label');"
    "if(z){var tz='';try{tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'';}"
    "catch(e){}z.textContent=tz||'local time';}"
    # 2. Crosshair and readout. No chart on this page means we are done.
    "var svg=document.getElementById('night-chart');"
    "var island=document.getElementById('night-data');"
    "if(!svg||!island)return;"
    "var n=JSON.parse(island.textContent);"
    "var cross=document.getElementById('crosshair');"
    "var dot=document.getElementById('crosshair-dot');"
    "var readout=document.getElementById('readout');"
    "var outTime=document.getElementById('readout-time');"
    "var outStage=document.getElementById('readout-stage');"
    "var outHr=document.getElementById('readout-hr');"
    "if(!cross||!readout)return;"
    # Only now is the interaction real, so only now is it advertised.
    "readout.removeAttribute('hidden');"
    "var t0=new Date(n.t0).getTime();"
    "var last=-1;"
    "var pt=svg.createSVGPoint?svg.createSVGPoint():null;"
    # Map a client x into the svg's own user units. getScreenCTM is immune to CSS
    # scaling, page zoom and the horizontal scroll of .chart-scroll; the
    # bounding-rect fallback assumes height:auto, which the stylesheet sets.
    "function userX(clientX){"
    "var m=(pt&&svg.getScreenCTM)?svg.getScreenCTM():null;"
    "if(m){pt.x=clientX;pt.y=0;return pt.matrixTransform(m.inverse()).x;}"
    "var r=svg.getBoundingClientRect();"
    "return r.width?(clientX-r.left)/r.width*n.vw:-1;}"
    "function clear(){"
    "cross.setAttribute('visibility','hidden');"
    "if(dot)dot.setAttribute('visibility','hidden');"
    "last=-1;"
    "outTime.textContent=outStage.textContent=outHr.textContent='\\u2014';"
    "outStage.removeAttribute('style');}"
    "function show(i){"
    "if(i<0)i=0;if(i>=n.minutes)i=n.minutes-1;"
    # O(1) index, and no DOM write per pixel: a sweep costs at most one write per
    # minute, so requestAnimationFrame buys nothing here.
    "if(i===last)return;"
    "last=i;"
    "var x=n.x0+(i+0.5)/n.minutes*n.w;"
    "cross.setAttribute('transform','translate('+x.toFixed(2)+',0)');"
    "cross.setAttribute('visibility','visible');"
    "outTime.textContent=hm(new Date(t0+i*60000));"
    "var s=n.stage[i];"
    "if(s<0){outStage.textContent='\\u2014';outStage.removeAttribute('style');}"
    "else{outStage.textContent=n.names[s];outStage.style.color=n.colors[s];}"
    "var v=n.hr[i];"
    "if(v===null||v===undefined){outHr.textContent='\\u2014';"
    "if(dot)dot.setAttribute('visibility','hidden');}"
    "else{outHr.textContent=v+' bpm';"
    "if(dot){dot.setAttribute('cy',(n.hrY0+(n.hrHi-v)/(n.hrHi-n.hrLo)*n.hrH).toFixed(2));"
    "dot.setAttribute('visibility','visible');}}}"
    "function minuteAt(clientX){"
    "return Math.floor((userX(clientX)-n.x0)/n.w*n.minutes);}"
    "svg.addEventListener('mousemove',function(e){show(minuteAt(e.clientX));});"
    "svg.addEventListener('mouseleave',clear);"
    # No preventDefault, so the page still scrolls under a touch.
    "svg.addEventListener('touchstart',function(e){"
    "if(e.touches.length===1)show(minuteAt(e.touches[0].clientX));});"
    "svg.addEventListener('touchmove',function(e){"
    "if(e.touches.length===1)show(minuteAt(e.touches[0].clientX));});"
    "svg.addEventListener('blur',clear);"
    # Keyboard path. The readout is deliberately NOT an aria-live region: announcing
    # on every mousemove is unusable with a screen reader. role='img' + aria-label on
    # the svg carries the summary, and these keys carry the detail.
    "svg.addEventListener('keydown',function(e){"
    "var step=e.shiftKey?15:1;"
    "if(e.key==='ArrowRight'){show((last<0?-1:last)+step);e.preventDefault();}"
    "else if(e.key==='ArrowLeft'){show((last<0?n.minutes:last)-step);e.preventDefault();}"
    "else if(e.key==='Escape'){clear();}});"
    "})();"
    "</script>"
)


def _time(instant: dt.datetime, fmt: str = "hm") -> str:
    """An instant the browser will localise.

    The text is the UTC rendering, so the page is correct (if not local) with the
    script disabled; ``data-ts`` is what the localisation pass reads.
    """
    if fmt == "date":
        text = instant.strftime("%a %d %b")
    elif fmt == "datetime":
        text = instant.strftime("%d %b %H:%M")
    else:
        text = instant.strftime("%H:%M")
    iso = escape(instant.isoformat(), quote=True)
    return f"<time data-ts='{iso}' data-fmt='{fmt}'>{escape(text)}</time>"


def _notice(notice: Notice) -> str:
    return (
        f"<div class='notice {escape(notice.tone.value, quote=True)}'>"
        f"<h3>{escape(notice.title)}</h3>"
        f"<p>{escape(notice.detail)}</p>"
        "</div>"
    )


def _tile(tile: Tile) -> str:
    if tile.value is None:
        value = "<span class='val empty'>&mdash;</span>"
    else:
        value = f"<span class='val'>{escape(tile.value)}</span>"
    hint = f" <span class='lbl'>{escape(tile.hint)}</span>" if tile.hint else ""
    return f"<div class='metric'>{value}<div class='lbl'>{escape(tile.label)}</div>{hint}</div>"


def _tiles(tiles: tuple[Tile, ...]) -> str:
    if not tiles:
        return ""
    cells = "".join(_tile(t) for t in tiles)
    return f"<section class='card'><h2>This night</h2><div class='metrics'>{cells}</div></section>"


def _legend(rows: tuple[LegendRow, ...]) -> str:
    if not rows:
        return ""
    items = "".join(
        f"<li><span class='sw' style='background:{escape(row.fill, quote=True)}'></span>"
        f"{escape(row.name)}"
        + (f"<span class='dur'>{escape(row.duration)}</span>" if row.duration else "")
        + "</li>"
        for row in rows
    )
    return f"<ul class='legend'>{items}</ul>"


def _nav(view: PageView) -> str:
    def link(key: str | None, label: str) -> str:
        if key is None:
            return f"<span aria-disabled='true'>{escape(label)}</span>"
        return f"<a href='?night={escape(key, quote=True)}'>{escape(label)}</a>"

    return (
        "<nav>" + link(view.earlier_key, "← Earlier") + link(view.later_key, "Later →") + "</nav>"
    )


def _header(view: PageView) -> str:
    if view.night_start is not None:
        title = f"Night of {_time(view.night_start, 'date')}"
        span = ""
        if view.night_end is not None:
            span = (
                f"<div class='sub'>{_time(view.night_start)} &rarr; "
                f"{_time(view.night_end)} &middot; times in "
                "<span id='tz-label'>UTC</span></div>"
            )
        return f"<header><div><h1>{title}</h1>{span}</div>{_nav(view)}</header>"
    return (
        "<header><div><h1>Sleep</h1>"
        "<div class='sub'>times in <span id='tz-label'>UTC</span></div></div>"
        f"{_nav(view)}</header>"
    )


def _readout() -> str:
    """Hidden until the script unhides it; see STYLE."""

    def pair(key: str, ident: str) -> str:
        return (
            f"<span class='pair'><span class='k'>{escape(key)}</span>"
            f"<span class='v' id='{ident}'>&mdash;</span></span>"
        )

    return (
        "<div class='readout' id='readout' hidden>"
        + pair("Time", "readout-time")
        + pair("Stage", "readout-stage")
        + pair("Heart rate", "readout-hr")
        + "</div>"
    )


def _json_island(payload: dict[str, object]) -> str:
    """The per-minute lookup, as data rather than as a JS literal.

    HTML escaping does not apply inside a <script> element -- the only sequence that
    can end it early is "</script". Escaping every "<" makes that unrepresentable
    while staying valid JSON, and is the single documented exception to the
    "everything through html.escape" rule in this module.
    """
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return (
        "<script type='application/json' id='night-data'>"
        + raw.replace("<", "\\u003c")
        + "</script>"
    )


def _chart(view: PageView) -> str:
    if view.chart_svg is None:
        return ""
    island = _json_island(view.chart_payload) if view.chart_payload is not None else ""
    return (
        "<section class='card'>"
        + _readout()
        + f"<div class='chart-scroll'>{view.chart_svg}</div>"
        + _legend(view.legend)
        + "</section>"
        + island
    )


def _footer(view: PageView) -> str:
    parts = list(view.footer)
    rendered = f"rendered {_time(view.rendered_at)}"
    return f"<footer>{' &middot; '.join([*map(escape, parts), rendered])}</footer>"


def _render(view: PageView) -> str:
    body = [
        _header(view),
        "".join(_notice(n) for n in view.notices),
        _chart(view),
        _tiles(view.tiles),
        _footer(view),
    ]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        # So scrollbars and form controls are drawn dark rather than light.
        "<meta name='color-scheme' content='dark'>"
        "<title>Sleep</title><style>"
        + STYLE
        + "</style></head><body>"
        + "".join(body)
        + SCRIPT
        + "</body></html>"
    )


render = _render
