from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
from client import ApiClient
from presentation import cell_color, weather_map

st.set_page_config(page_title="SGW Resilience", page_icon="🌊", layout="wide")


@st.cache_resource
def client():
    return ApiClient()


def call(method, path, **kwargs):
    try:
        return client().request(method, path, **kwargs)
    except Exception as exc:
        st.error(str(exc))
        return None


def display_time(value):
    return pd.to_datetime(value, utc=True).strftime("%d %b %Y, %H:%M:%S UTC")


def table(rows, columns=None):
    if rows:
        frame = pd.DataFrame(rows)
        if columns:
            frame = frame[columns]
        labels = {
            "asset": "Asset",
            "asset_id": "Asset ID",
            "priority": "Priority",
            "index": "Priority index",
            "status": "Status",
            "state": "Status",
            "reasons": "Reasons",
            "data_quality": "Data quality",
            "description": "Description",
            "assignee": "Assignee",
            "updated_at": "Updated",
            "due_at": "Due",
        }
        column_config = {column: label for column, label in labels.items() if column in frame}
        for column in ("priority", "status", "state"):
            if column in frame:
                column_config[column] = st.column_config.TextColumn(labels[column], width="small")
        for column in ("updated_at", "created_at", "due_at", "at", "timestamp", "window_end"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True, format="ISO8601")
                column_config[column] = st.column_config.DatetimeColumn(
                    label=labels.get(column), format="DD MMM YYYY, HH:mm:ss [UTC]", width="medium"
                )
        styled = frame.style
        for column in ("priority", "status", "state"):
            if column in frame:
                styled = styled.map(cell_color, subset=[column]).format(
                    lambda value: value.replace("_", " ").title(), subset=[column]
                )
        if "index" in frame:
            styled = styled.format(precision=1, na_rep="Unknown", subset=["index"])
        if "data_quality" in frame:
            styled = styled.map(
                lambda value: cell_color("acknowledged") if value else "", subset=["data_quality"]
            )
        st.dataframe(styled, column_config=column_config, hide_index=True, width="stretch")
    else:
        st.info("No records yet.")


def select_record(label, records, key, format_func):
    records_by_id = {record["id"]: record for record in records}
    if st.session_state.get(key) not in records_by_id:
        st.session_state[key] = None
    selected_id = st.selectbox(
        label,
        list(records_by_id),
        index=None,
        key=key,
        format_func=lambda identifier: format_func(records_by_id[identifier]),
    )
    return records_by_id.get(selected_id)


def evidence_cards(evidence):
    for item in evidence:
        with st.expander(f"{item['id']} · {item['section']}"):
            st.caption(
                f"{item['document']} · version {item['version']} · relevance {item['score']:.2f}"
            )
            st.write(item["text"])


st.title("SGW Resilience")
st.caption("Flood preparedness and equipment condition review · Synthetic demo data")
if st.session_state.pop("demo_reset_complete", False):
    st.session_state["confirm_demo_reset"] = False
    st.success("Demo reset. Load the initial flood warning or a telemetry sample to start again.")

with st.sidebar:
    st.subheader("Operator workspace")
    actor = st.text_input(
        "Reviewer",
        "Operations lead",
        help="Demo attribution only; enterprise identity is a future integration.",
    )
    if st.button("Load initial flood warning", width="stretch"):
        if call("POST", "/demo/weather/initial"):
            st.success("Warning loaded")
            st.rerun()
    if st.button("Load expanded warning", width="stretch"):
        if call("POST", "/demo/weather/update"):
            st.success("Warning updated")
            st.rerun()
    if st.button("Refresh workspace", width="stretch"):
        st.rerun()
    with st.expander("Reset demo"):
        st.warning("Deletes all demo progress and restores the original sample data.")
        confirmed_reset = st.checkbox(
            "I understand this clears the current demo", key="confirm_demo_reset"
        )
        if st.button("Reset to initial state", disabled=not confirmed_reset, width="stretch"):
            if call("POST", "/demo/reset", json={"confirm": True}):
                st.session_state.clear()
                st.session_state["demo_reset_complete"] = True
                st.rerun()
    health = call("GET", "/health")
    if health:
        st.caption("Generation: " + health["llm_mode"])
    st.caption("Actions require human approval.")

assets = call("GET", "/assets")
if assets is None:
    st.stop()
asset_names = {a["id"]: a["name"] for a in assets}
alerts = call("GET", "/alerts") or []
tasks = call("GET", "/tasks") or []
tabs = st.tabs(
    [
        "Situation",
        "Equipment condition",
        "Decision & approval",
        "Response work",
        "Leadership & evidence",
    ],
    key="workspace_tabs",
)

with tabs[0]:
    st.subheader("Weather readiness")
    events = call("GET", "/events") or []
    if not events:
        st.info("Load a warning from the sidebar to begin the first workflow.")
    for event in events:
        st.write(f"**{event['hazard'].title()} · {event['region']} · {event['severity'].upper()}**")
        st.caption(
            f"{event['id']} · revision {event['revision']} · valid until {display_time(event['valid_until'])} · source: {event['source']}"
        )
    st.pydeck_chart(
        weather_map(assets, events, alerts), key="warning_map", height=460, width="stretch"
    )
    st.caption(
        "Blue shading: current warning area · Marker colour: review priority · Grey: outside current warning or not assessed."
    )
    st.caption("Simulated assets and warning area.")
    weather_rows = []
    for alert in alerts:
        if alert["kind"] == "weather":
            weather_rows.append(
                {
                    "asset": asset_names.get(alert["asset_id"]),
                    "asset_id": alert["asset_id"],
                    "priority": alert["priority"],
                    "index": alert["details"].get("score"),
                    "status": alert["status"],
                    "reasons": "; ".join(alert["details"].get("reasons", [])),
                    "data_quality": "; ".join(alert["details"].get("data_quality", [])),
                }
            )
    table(weather_rows)
    st.caption("Priority: 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low")
    st.caption(
        "Alert status: Open · Acknowledged · Closed. Closing an alert does not remove exposure."
    )
    st.caption(
        "The priority index is an illustrative rule-based review order, not a failure probability."
    )
    selected_asset = st.selectbox(
        "Asset context", list(asset_names), format_func=lambda x: f"{x} · {asset_names[x]}"
    )
    context = call("GET", f"/assets/{selected_asset}/context")
    if context:
        left, right = st.columns(2)
        with left:
            st.write("Maintenance records")
            table(context["maintenance"], ["description", "state", "priority", "updated_at"])
        with right:
            st.write("Existing field work")
            table(context["tasks"], ["description", "assignee", "status"])
        st.caption("Asset data updated: " + display_time(context["asset"]["updated_at"]))

with tabs[1]:
    st.subheader("Pump condition monitoring")
    st.caption("Demo telemetry is available for Riverside pump station (P-02).")
    st.write(
        "Review recent operating behavior. An anomaly is a request for investigation, not a failure forecast."
    )
    scenario = st.radio("Synthetic telemetry scenario", ["normal", "anomaly"], horizontal=True)
    if st.button("Load telemetry sample"):
        batch = call("GET", f"/demo/telemetry/{scenario}")
        if batch:
            st.session_state["telemetry"] = batch["points"]
            st.session_state.pop("condition_result", None)
    points = st.session_state.get("telemetry", [])
    if points:
        frame = pd.DataFrame(points)
        st.caption(f"{frame['asset_id'].iloc[0]} · {len(frame)} one-minute observations")
        st.plotly_chart(
            px.line(
                frame,
                x="timestamp",
                y=["current_a", "flow_m3h", "motor_temp_c"],
                facet_row="variable",
                title="Telemetry by signal",
            ),
            width="stretch",
        )
        if st.button("Evaluate condition", type="primary"):
            result = call("POST", "/telemetry/evaluate", json={"points": points, "actor": actor})
            if result:
                st.session_state["condition_result"] = result
                alerts = call("GET", "/alerts") or alerts
                st.success("Condition assessment stored. Review alerts in Decision & approval.")
    result = st.session_state.get("condition_result")
    if result:
        rows = result["observations"]
        scores = pd.DataFrame(rows)
        if not scores.empty:
            st.plotly_chart(
                px.line(
                    scores,
                    x="window_end",
                    y=["score", "threshold"],
                    title="Reconstruction error and threshold",
                ),
                width="stretch",
            )
            st.write("Last window's error contributions")
            st.bar_chart(pd.Series(rows[-1]["feature_errors"]))
            st.caption("Error contributions are not causal explanations or diagnoses.")
        table(result["alerts"])
    with st.expander("Model card and synthetic evaluation"):
        card = call("GET", "/model/card")
        if card:
            st.json(card)

with tabs[2]:
    st.subheader("Evidence-backed decision support")
    active = [a for a in alerts if a["status"] != "closed"]
    if active:
        chosen = select_record(
            "Alert",
            active,
            key="decision_alert_id",
            format_func=lambda a: (
                f"{a['asset_id']} · {a['kind']} · {a['priority']} · v{a['version']}"
            ),
        )
        if chosen is None:
            st.info("Select an alert to review its evidence and draft an action plan.")
        else:
            workflow = "Flood readiness" if chosen["kind"] == "weather" else "Equipment condition"
            st.caption(f"{chosen['asset_id']} · {asset_names[chosen['asset_id']]} · {workflow}")
            st.json(chosen["details"], expanded=False)
            asset_type = next(a["asset_type"] for a in assets if a["id"] == chosen["asset_id"])
            if chosen["kind"] == "anomaly":
                default_question = "How should engineers review a persistent pump telemetry anomaly and decide whether inspection is needed?"
            elif chosen["details"].get("data_quality"):
                default_question = "What information should engineers confirm before flood readiness review when exposure is missing or asset records are stale?"
            elif asset_type == "pump":
                default_question = "Which flood readiness inspections and standby capacity reviews are supported for this pumping station?"
            else:
                default_question = (
                    "What checks should qualified personnel consider for a substation flood alert?"
                )
            question = st.text_area(
                "Review question", default_question, key="question:" + chosen["id"]
            )
            left, right = st.columns(2)
            with left:
                if st.button("Retrieve source evidence"):
                    hits = call(
                        "POST",
                        "/evidence",
                        json={"alert_id": chosen["id"], "question": question, "actor": actor},
                    )
                    if hits is not None:
                        st.session_state["retrieved"] = {"alert_id": chosen["id"], "hits": hits}
            with right:
                if st.button("Draft grounded action plan", type="primary"):
                    with st.spinner("Retrieving guidance and drafting a plan…"):
                        plan = call(
                            "POST",
                            "/plans",
                            json={"alert_id": chosen["id"], "question": question, "actor": actor},
                        )
                    if plan:
                        st.session_state["plan"] = plan
            if st.session_state.get("retrieved", {}).get("alert_id") == chosen["id"]:
                evidence_cards(st.session_state["retrieved"]["hits"])
            plan = st.session_state.get("plan")
            if plan and plan["alert_id"] == chosen["id"]:
                st.divider()
                st.write(f"**Draft plan · {chosen['asset_id']} · {workflow}**")
                st.caption(
                    f"{plan['id']} · alert v{plan['alert_version']} · {plan['generation_mode']}"
                )
                st.write(plan["answer"]["summary"])
                for missing in plan["answer"]["missing_information"]:
                    st.warning(missing)
                evidence_cards(plan["evidence"])
                actions = plan["answer"]["actions"]
                for action in actions:
                    st.write(f"**{action['action_code']}** — {action['rationale']}")
                    st.caption("Sources: " + ", ".join(action["source_ids"]))
                if actions and not plan["answer"]["insufficient_evidence"]:
                    with st.form("approval"):
                        codes = st.multiselect(
                            "Actions to approve", [a["action_code"] for a in actions]
                        )
                        assignee = st.text_input("Assigned team", "Field Team A")
                        hours = st.number_input("Due in hours", min_value=1, max_value=72, value=4)
                        confirmed = st.checkbox("I reviewed the facts, sources and existing work")
                        if st.form_submit_button("Approve selected actions"):
                            if not confirmed:
                                st.error("Human review confirmation is required.")
                            else:
                                outcome = call(
                                    "POST",
                                    f"/plans/{plan['id']}/approve",
                                    json={
                                        "action_codes": codes,
                                        "assignee": assignee,
                                        "actor": actor,
                                        "due_at": (
                                            datetime.now(timezone.utc) + timedelta(hours=hours)
                                        ).isoformat(),
                                    },
                                )
                                if outcome:
                                    st.success(
                                        "Approval recorded. Tasks created or existing work linked."
                                    )
                                    st.session_state.pop("plan", None)
                                    st.rerun()
    else:
        st.info("Load a weather warning or evaluate an anomaly to create an alert.")

with tabs[3]:
    st.subheader("Response work")
    table(tasks, ["id", "asset_id", "description", "assignee", "status", "due_at"])
    if tasks:
        selected = select_record(
            "Task",
            tasks,
            key="response_task_id",
            format_func=lambda t: f"{t['asset_id']} · {t['action_code']} · {t['status']}",
        )
        with st.form("task_update"):
            status = st.selectbox("New status", ["pending", "in_progress", "completed"])
            outcome = st.text_area("Inspection outcome / update")
            if st.form_submit_button("Save task update", disabled=selected is None) and selected:
                if call(
                    "PATCH",
                    f"/tasks/{selected['id']}",
                    json={"status": status, "outcome": outcome or None, "actor": actor},
                ):
                    st.rerun()
    if alerts:
        with st.expander("Update alert status"):
            selected = select_record(
                "Reviewed alert",
                alerts,
                key="disposition_alert_id",
                format_func=lambda a: f"{a['asset_id']} · {a['kind']} · {a['status']}",
            )
            with st.form("disposition"):
                status = st.selectbox("Disposition", ["acknowledged", "closed"])
                reason = st.text_area("Reason / engineer review")
                if (
                    st.form_submit_button("Record disposition", disabled=selected is None)
                    and selected
                ):
                    if call(
                        "PATCH",
                        f"/alerts/{selected['id']}",
                        json={"status": status, "reason": reason, "actor": actor},
                    ):
                        st.rerun()

with tabs[4]:
    st.subheader("Leadership situation overview")
    overview = call("GET", "/overview")
    if overview:
        st.caption("As of " + display_time(overview["as_of"]) + " · refresh for latest state")
        a, b, c = st.columns(3)
        a.metric("Registered assets", overview["assets"])
        b.metric("Active alerts", len(overview["active_alerts"]))
        c.metric("Outstanding tasks", sum(t["status"] != "completed" for t in overview["tasks"]))
        priority_rows = [
            {
                "asset": a["asset_id"],
                "signal": a["kind"],
                "priority": a["priority"],
                "updated_at": a["updated_at"],
                "reasons": "; ".join(a["details"].get("reasons", [])),
            }
            for a in overview["active_alerts"]
        ]
        table(priority_rows)
        if st.button("Generate grounded briefing"):
            briefing = call("POST", "/briefing")
            if briefing:
                st.session_state["briefing"] = briefing
        if "briefing" in st.session_state:
            briefing = st.session_state["briefing"]
            st.caption("Snapshot: " + display_time(briefing["snapshot"]["as_of"]))
            st.write(briefing["answer"]["summary"])
            evidence_cards(briefing["evidence"])
    with st.expander("Decision audit trail"):
        table(call("GET", "/audit") or [])
