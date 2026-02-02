# ─────────────────────────────────────────────────────────────────────────────
# Planner semanal/mensual/anual con categorías, recurrencias, prioridades,
# sugerencias de horario (heurística) y tema oscuro con switch (esta raro).
#
# Requisitos:
#   pip install streamlit plotly pandas sqlite3 calendar typing json
# ─────────────────────────────────────────────────────────────────────────────

import json
import sqlite3
import calendar
from datetime import datetime, date, time, timedelta
from typing import List, Dict, Tuple, Optional

import pandas as pd
import plotly.express as px
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Config UI y Tema
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Planner + Calendar", layout="wide")

# Toggle de tema oscuro
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False
st.session_state.dark_mode = st.sidebar.toggle("🌙 Tema oscuro", value=st.session_state.dark_mode)

def inject_dark_css(dark: bool):
    if not dark:
        return
    st.markdown("""
    <style>
      :root, .stApp { background-color: #0e1117 !important; color: #e8eaed !important; }
      .stMarkdown, .stText, .stRadio, .stSelectbox, .stDateInput, .stTimeInput, .stNumberInput, .stButton {
          color: #e8eaed !important;
      }
      .st-bh, .st-bk, .st-bq { background: #161a23 !important; }
      .stAlert, .stDataFrame { background: #161a23 !important; }
      .stButton>button { background:#1f6feb; color:white; border-radius:8px; }
    </style>
    """, unsafe_allow_html=True)

inject_dark_css(st.session_state.dark_mode)
PLOTLY_TEMPLATE = "plotly_dark" if st.session_state.dark_mode else "plotly"

# ─────────────────────────────────────────────────────────────────────────────
# DB y constantes
# ─────────────────────────────────────────────────────────────────────────────
DB_PATH = "planner.db"
WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                name TEXT,
                color TEXT,
                UNIQUE(user_id, name)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                title TEXT,
                category_id INTEGER,
                date TEXT,               -- YYYY-MM-DD (puntual)
                start_time TEXT,         -- HH:MM
                end_time TEXT,           -- HH:MM
                is_recurring INTEGER,    -- 0/1
                rrule TEXT,              -- JSON: {days:[0-6], start_date, end_date, start_time, end_time}
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS priorities(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                week_start TEXT,         -- YYYY-MM-DD (lunes)
                goals TEXT,              -- texto libre
                p1 TEXT, p1_done INTEGER DEFAULT 0,
                p2 TEXT, p2_done INTEGER DEFAULT 0,
                p3 TEXT, p3_done INTEGER DEFAULT 0,
                updated_at TEXT,
                UNIQUE(user_id, week_start)
            )
        """)
        con.commit()

def ensure_user(user_id: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT OR IGNORE INTO users(id) VALUES (?)", (user_id,))
        con.commit()

def list_categories(user_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT id, name, color FROM categories WHERE user_id=? ORDER BY name", (user_id,))
        rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "color": r[2]} for r in rows]

def upsert_category(user_id: str, name: str, color: str):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO categories(user_id, name, color) VALUES (?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET color=excluded.color
        """, (user_id, name, color))
        con.commit()

def delete_category(user_id: str, cat_id: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM categories WHERE user_id=? AND id=?", (user_id, cat_id))
        con.commit()

def add_event_punctual(user_id: str, title: str, category_id: int, d: date, start: time, end: time):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO events(user_id, title, category_id, date, start_time, end_time, is_recurring, rrule, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
        """, (user_id, title, category_id, d.isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"), datetime.now().isoformat()))
        con.commit()

def add_event_recurring(user_id: str, title: str, category_id: int,
                        start_date: date, end_date: date, days: List[int], start: time, end: time):
    rrule = {
        "days": days,  # 0=Lun...6=Dom
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "freq": "weekly"
    }
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO events(user_id, title, category_id, date, start_time, end_time, is_recurring, rrule, created_at)
            VALUES (?, ?, ?, NULL, NULL, NULL, 1, ?, ?)
        """, (user_id, title, category_id, json.dumps(rrule), datetime.now().isoformat()))
        con.commit()

def delete_event(user_id: str, event_id: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM events WHERE user_id=? AND id=?", (user_id, event_id))
        con.commit()

def list_events_raw(user_id: str) -> List[Dict]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, title, category_id, date, start_time, end_time, is_recurring, rrule
            FROM events WHERE user_id=?
        """, (user_id,))
        rows = cur.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "title": r[1], "category_id": r[2],
            "date": r[3], "start_time": r[4], "end_time": r[5],
            "is_recurring": bool(r[6]),
            "rrule": json.loads(r[7]) if r[7] else None
        })
    return out

# Prioridades
def get_priorities(user_id: str, week0: date) -> Dict:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT goals, p1, p1_done, p2, p2_done, p3, p3_done
            FROM priorities WHERE user_id=? AND week_start=?
        """, (user_id, week0.isoformat()))
        row = cur.fetchone()
    if not row:
        return {"goals":"", "p1":"", "p1_done":0, "p2":"", "p2_done":0, "p3":"", "p3_done":0}
    return {"goals":row[0] or "", "p1":row[1] or "", "p1_done":row[2] or 0,
            "p2":row[3] or "", "p2_done":row[4] or 0, "p3":row[5] or "", "p3_done":row[6] or 0}

def upsert_priorities(user_id: str, week0: date, goals: str, p1: str, p1_done: bool, p2: str, p2_done: bool, p3: str, p3_done: bool):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO priorities(user_id, week_start, goals, p1, p1_done, p2, p2_done, p3, p3_done, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, week_start) DO UPDATE SET
              goals=excluded.goals, p1=excluded.p1, p1_done=excluded.p1_done,
              p2=excluded.p2, p2_done=excluded.p2_done, p3=excluded.p3, p3_done=excluded.p3_done,
              updated_at=excluded.updated_at
        """, (user_id, week0.isoformat(), goals, p1, int(p1_done), p2, int(p2_done), p3, int(p3_done), datetime.now().isoformat()))
        con.commit()

# ─────────────────────────────────────────────────────────────────────────────
# Utilidades de tiempo / expansión
# ─────────────────────────────────────────────────────────────────────────────
def week_start(any_date: date) -> date:
    return any_date - timedelta(days=any_date.weekday())

def combine_dt(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute)

def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return not (a_end <= b_start or b_end <= a_start)

def minutes_between(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)

def expand_events_for_week(user_id: str, week0: date) -> List[Dict]:
    cats = {c["id"]: c for c in list_categories(user_id)}
    events = list_events_raw(user_id)
    occurrences = []
    week_days = [week0 + timedelta(days=i) for i in range(7)]
    for ev in events:
        if not ev["is_recurring"]:
            if ev["date"]:
                ev_date = date.fromisoformat(ev["date"])
                if ev_date in week_days:
                    s = combine_dt(ev_date, datetime.strptime(ev["start_time"], "%H:%M").time())
                    e = combine_dt(ev_date, datetime.strptime(ev["end_time"], "%H:%M").time())
                    occurrences.append({
                        "id": ev["id"], "title": ev["title"],
                        "start": s, "end": e, "category": cats.get(ev["category_id"]),
                        "recurring": False
                    })
        else:
            rr = ev["rrule"]
            start_date = date.fromisoformat(rr["start_date"])
            end_date = date.fromisoformat(rr["end_date"])
            s_t = datetime.strptime(rr["start_time"], "%H:%M").time()
            e_t = datetime.strptime(rr["end_time"], "%H:%M").time()
            for wd in week_days:
                if start_date <= wd <= end_date and wd.weekday() in rr["days"]:
                    s = combine_dt(wd, s_t); e = combine_dt(wd, e_t)
                    occurrences.append({
                        "id": ev["id"], "title": ev["title"],
                        "start": s, "end": e, "category": cats.get(ev["category_id"]),
                        "recurring": True
                    })
    occurrences.sort(key=lambda x: x["start"])
    return occurrences

def expand_events_for_range(user_id: str, start_d: date, end_d: date) -> List[Dict]:
    cats = {c["id"]: c for c in list_categories(user_id)}
    events = list_events_raw(user_id)
    occurrences = []
    days = [start_d + timedelta(days=i) for i in range((end_d - start_d).days + 1)]
    for ev in events:
        if not ev["is_recurring"]:
            if ev["date"]:
                ev_date = date.fromisoformat(ev["date"])
                if start_d <= ev_date <= end_d:
                    s = combine_dt(ev_date, datetime.strptime(ev["start_time"], "%H:%M").time())
                    e = combine_dt(ev_date, datetime.strptime(ev["end_time"], "%H:%M").time())
                    occurrences.append({"id": ev["id"], "title": ev["title"],
                        "start": s, "end": e, "category": cats.get(ev["category_id"]), "recurring": False})
        else:
            rr = ev["rrule"]
            s_date = date.fromisoformat(rr["start_date"])
            e_date = date.fromisoformat(rr["end_date"])
            s_t = datetime.strptime(rr["start_time"], "%H:%M").time()
            e_t = datetime.strptime(rr["end_time"], "%H:%M").time()
            for d in days:
                if s_date <= d <= e_date and d.weekday() in rr["days"]:
                    s = combine_dt(d, s_t); e = combine_dt(d, e_t)
                    occurrences.append({"id": ev["id"], "title": ev["title"],
                        "start": s, "end": e, "category": cats.get(ev["category_id"]), "recurring": True})
    occurrences.sort(key=lambda x: x["start"])
    return occurrences

# ─────────────────────────────────────────────────────────────────────────────
# “IA” heurística: encontrar huecos
# ─────────────────────────────────────────────────────────────────────────────
def day_window(week0: date, wd: int, win_start: time, win_end: time) -> Tuple[datetime, datetime]:
    d = week0 + timedelta(days=wd)
    return combine_dt(d, win_start), combine_dt(d, win_end)

def find_slot_in_day(busy: List[Tuple[datetime, datetime]],
                     win_s: datetime, win_e: datetime, duration_min: int) -> Optional[Tuple[datetime, datetime]]:
    busy_sorted = sorted([b for b in busy if overlaps(b[0], b[1], win_s, win_e)], key=lambda x: x[0])
    cursor = win_s
    for (b_s, b_e) in busy_sorted:
        if cursor < b_s and minutes_between(cursor, b_s) >= duration_min:
            return cursor, cursor + timedelta(minutes=duration_min)
        cursor = max(cursor, b_e)
    if minutes_between(cursor, win_e) >= duration_min:
        return cursor, cursor + timedelta(minutes=duration_min)
    return None

def suggest_slots(occs: List[Dict], week0: date, days_mask: List[int],
                  duration_min: int, win_start: time, win_end: time,
                  respect_existing: bool, start_from_now: bool = True, only_next: bool = True):
    suggestions = []
    busy_by_day = {i: [] for i in range(7)}
    if respect_existing:
        for ev in occs:
            busy_by_day[ev["start"].weekday()].append((ev["start"], ev["end"]))
    days_to_try = days_mask if days_mask else list(range(7))
    now_dt = datetime.now()
    for i in days_to_try:
        win_s, win_e = day_window(week0, i, win_start, win_end)
        if start_from_now and (week0 + timedelta(days=i)) == now_dt.date():
            if win_s < now_dt < win_e:
                win_s = now_dt
        busy = [] if not respect_existing else busy_by_day[i]
        slot = find_slot_in_day(busy, win_s, win_e, duration_min)
        if slot:
            suggestions.append(slot)
            if respect_existing:
                busy_by_day[i].append(slot)
                busy_by_day[i].sort(key=lambda x: x[0])
        if not days_mask and slot:
            break
    if only_next and suggestions:
        future = [s for s in suggestions if s[0] >= now_dt]
        if future:
            suggestions = [sorted(future, key=lambda x: x[0])[0]]
        else:
            suggestions = [sorted(suggestions, key=lambda x: x[0])[0]]
    return suggestions

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: Usuario y semana
# ─────────────────────────────────────────────────────────────────────────────
init_db()
user_id = st.sidebar.text_input("Usuario (ID único):")
if not user_id:
    st.info("🔐 Escribe tu usuario en la barra lateral para empezar.")
    st.stop()
ensure_user(user_id)

today = date.today()
sel_date = st.sidebar.date_input("Semana de (elige un día):", today)
wk0 = week_start(sel_date)
st.sidebar.caption(f"Semana: {wk0.isoformat()} → {(wk0 + timedelta(days=6)).isoformat()}")

# ─────────────────────────────────────────────────────────────────────────────
# Categorías
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.subheader("🎨 Categorías")
cats = list_categories(user_id)
with st.sidebar.expander("Agregar / editar categoría"):
    new_name = st.text_input("Nombre de categoría")
    new_color = st.color_picker("Color", value="#4C78A8")
    if st.button("Guardar categoría"):
        if new_name.strip():
            upsert_category(user_id, new_name.strip(), new_color)
            st.rerun()
if cats:
    with st.sidebar.expander("Eliminar categoría"):
        cat_opt = st.selectbox("Selecciona", options=cats, format_func=lambda c: f"{c['name']} ({c['color']})")
        if st.button("Eliminar categoría seleccionada"):
            delete_category(user_id, cat_opt["id"])
            st.rerun()
else:
    st.sidebar.info("Crea una categoría arriba.")

# ─────────────────────────────────────────────────────────────────────────────
# Calendario: Semana / Mes / Año
# ─────────────────────────────────────────────────────────────────────────────
st.header("📅 Calendario")
vista = st.radio("Vista", ["Semana", "Mes", "Año"], horizontal=True)

def render_month_grid(occ_list: List[Dict], focus: date):
    year, month = focus.year, focus.month
    cal = calendar.Calendar(firstweekday=0)  # 0=Lun
    month_days = list(cal.itermonthdates(year, month))
    bucket = {}
    for oc in occ_list:
        d = oc["start"].date()
        bucket.setdefault(d, []).append(oc)
    # estilos
    base_bg = "#161a23" if st.session_state.dark_mode else "#fafafa"
    border = "#2a2f3a" if st.session_state.dark_mode else "#e6e6e6"
    text_muted = "#8892a6" if st.session_state.dark_mode else "#999"
    st.markdown(f"""
    <style>
      .cal {{ display:grid; grid-template-columns: repeat(7, 1fr); gap:8px; }}
      .cell {{ border:1px solid {border}; border-radius:8px; padding:8px; min-height:100px; background:{base_bg}; }}
      .cell .dom {{ font-weight:600; font-size:0.9rem; margin-bottom:6px; }}
      .badge {{ display:inline-block; padding:2px 6px; border-radius:6px; font-size:0.7rem; margin:1px 2px 0 0; color:#fff; }}
      .muted {{ color:{text_muted}; }}
      .cal-head {{ display:grid; grid-template-columns: repeat(7, 1fr); margin-bottom:6px; }}
      .dow {{ font-weight:700; text-align:center; }}
    </style>
    """, unsafe_allow_html=True)
    st.markdown(
        "<div class='cal-head'>" +
        "".join(f"<div class='dow'>{d}</div>" for d in ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]) +
        "</div>", unsafe_allow_html=True
    )
    html = "<div class='cal'>"
    for d in month_days:
        in_month = (d.month == month)
        day_events = bucket.get(d, [])
        muted = "" if in_month else " muted"
        html += f"<div class='cell'><div class='dom{muted}'>{d.day}</div>"
        for oc in day_events[:3]:
            cat = oc["category"]; color = (cat["color"] if cat else "#888")
            name = oc["title"]
            html += f"<span class='badge' style='background:{color}' title='{name}'>{name[:12]}</span> "
        if len(day_events) > 3:
            html += f"<div style='font-size:0.7rem;margin-top:4px;'>+{len(day_events)-3} más</div>"
        html += "</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

if vista == "Semana":
    occ = expand_events_for_week(user_id, wk0)   
    if not occ:
        st.info("No hay actividades en esta semana.")
    else:
        data = []
        for x in occ:
            cat_name = x["category"]["name"] if x["category"] else "Sin categoría"
            cat_color = x["category"]["color"] if x["category"] else "#999999"
            data.append({"Actividad": x["title"], "Inicio": x["start"], "Fin": x["end"],
                         "Día": WEEKDAYS_ES[x["start"].weekday()], "Categoría": cat_name, "Color": cat_color})
        df = pd.DataFrame(data)
        fig = px.timeline(df, x_start="Inicio", x_end="Fin", y="Día", color="Categoría",
                          hover_data=["Actividad"],
                          color_discrete_map={row["Categoría"]: row["Color"]
                                              for _, row in df.drop_duplicates("Categoría").iterrows()},
                          template=PLOTLY_TEMPLATE)
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=460, xaxis_title="", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

elif vista == "Mes":
    
    focus_month = st.date_input("Mes a visualizar", wk0.replace(day=1))
    start_m = focus_month.replace(day=1)
    last_day = calendar.monthrange(start_m.year, start_m.month)[1]
    end_m = focus_month.replace(day=last_day)
    occ_m = expand_events_for_range(user_id, start_m, end_m)
    st.subheader(f"{start_m.strftime('%B %Y').title()}")
    render_month_grid(occ_m, start_m)
    dia_detalle = st.date_input("Ver detalle del día", start_m, min_value=start_m, max_value=end_m, key="mes_detalle")
    det = [o for o in occ_m if o["start"].date()==dia_detalle]
    if det:
        st.markdown(f"**Eventos el {dia_detalle.isoformat()}:**")
        for o in det:
            st.write(f"- {o['title']} • {o['start'].strftime('%H:%M')}–{o['end'].strftime('%H:%M')} ({o['category']['name'] if o['category'] else 'Sin categoría'})")
    else:
        st.caption("Sin eventos ese día.")

else:
    year_sel = st.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1)
    start_y = date(year_sel,1,1); end_y = date(year_sel,12,31)
    occ_y = expand_events_for_range(user_id, start_y, end_y)
    # Heatmap simple por semana vs día
    days = pd.date_range(start_y, end_y, freq="D")
    df = pd.DataFrame({"date": days})
    if occ_y:
        tmp = pd.DataFrame({"date": [pd.to_datetime(oc["start"]).normalize() for oc in occ_y]})
        tmp = tmp.groupby("date").size().reset_index(name="count")
        df = df.merge(tmp, on="date", how="left")
        df["count"] = df["count"].fillna(0).astype(int)
    else:
        df["count"] = 0

    df["dow"] = df["date"].dt.weekday
    df["week"] = df["date"].dt.isocalendar().week.astype(int)

    df.loc[(df["date"].dt.month == 1) & (df["week"] > 50), "week"] = 0
    max_week = int(df["week"].max())
    df.loc[(df["date"].dt.month == 12) & (df["week"] == 1), "week"] = max_week + 1

    fig = px.density_heatmap(
        df, x="week", y="dow", z="count", text_auto=True,
        category_orders={"dow":[0,1,2,3,4,5,6]},
        labels={"dow":"Día", "week":"Semana", "count":"#"},
        template=PLOTLY_TEMPLATE
    )

    fig.update_yaxes(
        tickmode="array", tickvals=[0,1,2,3,4,5,6],
        ticktext=["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"],
        autorange="reversed"
    )
    fig.update_layout(height=280, margin=dict(l=10,r=10,t=30,b=10))
    st.plotly_chart(fig, use_container_width=True)

    day_pick = st.date_input("Día a detallar", date.today(), min_value=start_y, max_value=end_y, key="anio_detalle")
    det = [o for o in (occ_y or []) if o["start"].date() == day_pick]

    if det:
        st.markdown(f"**Eventos el {day_pick.isoformat()}:**")
        for o in det:
            cat = o["category"]["name"] if o.get("category") else "Sin categoría"
            st.write(f"- {o['title']} • {o['start'].strftime('%H:%M')}–{o['end'].strftime('%H:%M')} ({cat})")
        else:
            st.caption("Sin eventos ese día.")

# ─────────────────────────────────────────────────────────────────────────────
# Próximas actividades
# ─────────────────────────────────────────────────────────────────────────────
st.header("⏰ Próximas actividades")
occ_all = expand_events_for_range(user_id, wk0, wk0 + timedelta(days=6))
upcoming = sorted([x for x in occ_all if x["start"] >= datetime.now()], key=lambda x: x["start"])[:8]
if not upcoming:
    st.info("No hay actividades próximas.")
else:
    for x in upcoming:
        st.write(f"• {x['title']} — {x['start'].strftime('%a %d %b %H:%M')} → {x['end'].strftime('%H:%M')} ({x['category']['name'] if x['category'] else 'Sin categoría'})")

# ─────────────────────────────────────────────────────────────────────────────
# Prioridades / Objetivos semanales
# ─────────────────────────────────────────────────────────────────────────────
st.header("🎯 Prioridades de la semana")
pr = get_priorities(user_id, wk0)
c1, c2 = st.columns([2,1])
with c1:
    goals = st.text_area("Objetivos semanales (resumen)", value=pr["goals"], height=100)
with c2:
    st.caption("Top 3 prioridades")
    p1 = st.text_input("Prioridad 1", value=pr["p1"])
    p1_done = st.checkbox("Completada 1", value=bool(pr["p1_done"]))
    p2 = st.text_input("Prioridad 2", value=pr["p2"])
    p2_done = st.checkbox("Completada 2", value=bool(pr["p2_done"]))
    p3 = st.text_input("Prioridad 3", value=pr["p3"])
    p3_done = st.checkbox("Completada 3", value=bool(pr["p3_done"]))
if st.button("Guardar prioridades"):
    upsert_priorities(user_id, wk0, goals, p1, p1_done, p2, p2_done, p3, p3_done)
    st.success("Prioridades guardadas.")
progress = (int(p1_done) + int(p2_done) + int(p3_done)) / 3 if any([p1, p2, p3]) else 0
st.progress(progress)

# ─────────────────────────────────────────────────────────────────────────────
# Crear actividad
# ─────────────────────────────────────────────────────────────────────────────
st.header("➕ Agregar actividad")
colA, colB = st.columns(2)
with colA:
    title = st.text_input("Título")
    if cats:
        cat_sel = st.selectbox("Categoría", options=cats, format_func=lambda c: c["name"])
        cat_id = cat_sel["id"]
    else:
        st.warning("Primero crea una categoría en la barra lateral.")
        cat_id = None
with colB:
    mode = st.radio("Tipo", ["Puntual", "Recurrente"], horizontal=True)

if mode == "Puntual":
    d = st.date_input("Fecha", wk0)
    c1, c2 = st.columns(2)
    with c1:
        s_t = st.time_input("Inicio", time(9, 0))
    with c2:
        e_t = st.time_input("Fin", time(10, 0))
    if st.button("Agregar evento puntual", use_container_width=True, disabled=not (title and cat_id)):
        if e_t <= s_t:
            st.error("La hora de fin debe ser posterior a la de inicio.")
        else:
            add_event_punctual(user_id, title, cat_id, d, s_t, e_t)
            st.success("Evento puntual agregado.")
            st.rerun()
else:
    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Desde", wk0)
    with c2:
        end_date = st.date_input("Hasta", wk0 + timedelta(days=28))
    st.caption("Días de la semana (0=Lun ... 6=Dom)")
    days_cols = st.columns(7)
    sel_days = []
    for i, col in enumerate(days_cols):
        if col.checkbox(WEEKDAYS_ES[i], value=(i < 5)):
            sel_days.append(i)
    c3, c4 = st.columns(2)
    with c3:
        s_t = st.time_input("Inicio (rec)", time(18, 0), key="rec_s")
    with c4:
        e_t = st.time_input("Fin (rec)", time(19, 0), key="rec_e")
    if st.button("Agregar evento recurrente", use_container_width=True, disabled=not (title and cat_id)):
        if e_t <= s_t:
            st.error("La hora de fin debe ser posterior a la de inicio.")
        elif not sel_days:
            st.error("Selecciona al menos un día.")
        elif end_date < start_date:
            st.error("Rango de fechas inválido.")
        else:
            add_event_recurring(user_id, title, cat_id, start_date, end_date, sel_days, s_t, e_t)
            st.success("Evento recurrente agregado.")
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Sugerencia de horario (heurística)
# ─────────────────────────────────────────────────────────────────────────────
st.header("🧠 Sugerir próximo hueco")
with st.form("ai_form"):
    act_name = st.text_input("Actividad a ubicar (p.ej., Gimnasio)")
    cat_for_ai = st.selectbox("Categoría", options=cats, format_func=lambda c: c["name"]) if cats else None
    dur_min = st.number_input("Duración (min)", min_value=15, max_value=300, step=15, value=60)
    win_c1, win_c2 = st.columns(2)
    with win_c1:
        win_start = st.time_input("Ventana día: desde", time(6, 0))
    with win_c2:
        win_end = st.time_input("Ventana día: hasta", time(22, 0))
    st.caption("Días preferidos (opcional). Si no marcas, buscará el primer hueco de la semana.")
    ai_days_cols = st.columns(7)
    ai_days = []
    for i, col in enumerate(ai_days_cols):
        if col.checkbox(WEEKDAYS_ES[i], key=f"ai_{i}", value=False):
            ai_days.append(i)
    respect = st.checkbox("Respetar actividades existentes", value=True)
    only_next = st.checkbox("Solo la próxima disponible desde ahora", value=True)
    submit_ai = st.form_submit_button("Sugerir")

if submit_ai:
    if not act_name or not cat_for_ai:
        st.error("Indica nombre y categoría.")
    elif win_end <= win_start:
        st.error("Ventana inválida.")
    else:
        occs = expand_events_for_week(user_id, wk0)
        suggestions = suggest_slots(occs, wk0, ai_days, int(dur_min), win_start, win_end, respect, True, only_next)
        if not suggestions:
            st.warning("No hay huecos con esos parámetros.")
        else:
            st.success("Sugerencia(s):")
            for idx, (s, e) in enumerate(suggestions, start=1):
                st.write(f"• {idx}. {s.strftime('%a %d %b %H:%M')} → {e.strftime('%H:%M')}")
            if st.button("Agregar sugerencias al calendario"):
                for (s, e) in suggestions:
                    add_event_punctual(user_id, act_name, cat_for_ai["id"], s.date(), s.time(), e.time())
                st.success("Sugerencias agregadas.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Gestión rápida: eliminar
# ─────────────────────────────────────────────────────────────────────────────
st.header("🗑️ Borrar eventos (definición puntual/recurrente)")
raw = list_events_raw(user_id)
if raw:
    opt = st.selectbox(
        "Selecciona evento a eliminar. Si es recurrente, se dejarán de generar ocurrencias futuras.",
        options=raw, format_func=lambda e: f"[#{e['id']}] {'REC' if e['is_recurring'] else 'PUN'} - {e['title']}"
    )
    if st.button("Eliminar evento seleccionado"):
        delete_event(user_id, opt["id"])
        st.success("Evento eliminado.")
        st.rerun()
else:
    st.caption("No hay eventos definidos todavía.")

#arreglar lo de los proximos huecos, o ver si asi esta bien
# anadir notificaciones (streamlit-notifications)
# anadir integracion con google calendar (google-api-python-client, google-auth-httplib2, google-auth-oauthlib)
# anadir exportar a ics (ics) csv (pandas)
# enviar por email (streamlit-email)