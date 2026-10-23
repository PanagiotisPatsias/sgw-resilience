from datetime import datetime, timezone

import pydeck as pdk

PRIORITY_COLORS = {
    "critical": ("#fee2e2", "#991b1b", [220, 38, 38]),
    "high": ("#ffedd5", "#9a3412", [234, 88, 12]),
    "medium": ("#fef3c7", "#92400e", [234, 179, 8]),
    "low": ("#dbeafe", "#1e40af", [37, 99, 235]),
}
STATUS_COLORS = {
    "open": ("#dbeafe", "#1e40af"),
    "acknowledged": ("#fef3c7", "#92400e"),
    "closed": ("#dcfce7", "#166534"),
    "pending": ("#e2e8f0", "#334155"),
    "in_progress": ("#e0e7ff", "#3730a3"),
    "completed": ("#dcfce7", "#166534"),
}


def cell_color(value):
    colors = PRIORITY_COLORS.get(value) or STATUS_COLORS.get(value)
    if colors:
        return f"background-color: {colors[0]}; color: {colors[1]}; font-weight: bold"
    return ""


def weather_map(assets, events, alerts, now=None):
    now = now or datetime.now(timezone.utc)
    current_events = [
        event
        for event in events
        if datetime.fromisoformat(event["issued_at"].replace("Z", "+00:00")) <= now
        and datetime.fromisoformat(event["valid_from"].replace("Z", "+00:00"))
        <= now
        < datetime.fromisoformat(event["valid_until"].replace("Z", "+00:00"))
    ]
    event_ids = {event["id"] for event in current_events}
    areas = []
    for event in current_events:
        west, south, east, north = event["bbox"]
        areas.append({"polygon": [[west, south], [east, south], [east, north], [west, north]]})

    points = []
    priority_order = list(PRIORITY_COLORS)
    for asset in assets:
        applicable = [
            alert
            for alert in alerts
            if alert["kind"] == "weather"
            and alert["asset_id"] == asset["id"]
            and alert["event_id"] in event_ids
            and not alert["details"].get("outside_current_area")
        ]
        primary = (
            min(applicable, key=lambda a: priority_order.index(a["priority"]))
            if applicable
            else None
        )
        scope = "Inside current warning" if primary else "Outside current warning"
        points.append(
            {
                "position": [asset["longitude"], asset["latitude"]],
                "asset_id": asset["id"],
                "name": asset["name"],
                "asset_type": "Pump station" if asset["asset_type"] == "pump" else "Substation",
                "warning": scope if current_events else "No current warning",
                "priority": primary["priority"].title() if primary else "Not assessed",
                "status": primary["status"].title() if primary else "No current weather alert",
                "color": PRIORITY_COLORS[primary["priority"]][2] if primary else [148, 163, 184],
            }
        )

    return pdk.Deck(
        map_style="light",
        # keep the demo viewport fixed so both warning extents fit and growth stays visible
        initial_view_state=pdk.ViewState(latitude=30.2, longitude=-81.65, zoom=9.5),
        layers=[
            pdk.Layer(
                "PolygonLayer",
                areas,
                id="warning-area",
                get_polygon="polygon",
                get_fill_color=[59, 130, 246, 45],
                get_line_color=[59, 130, 246, 220],
                line_width_min_pixels=2,
                stroked=True,
                filled=True,
            ),
            pdk.Layer(
                "ScatterplotLayer",
                points,
                id="assets",
                get_position="position",
                get_fill_color="color",
                get_line_color=[255, 255, 255],
                radius_min_pixels=8,
                line_width_min_pixels=2,
                stroked=True,
                pickable=True,
                auto_highlight=True,
            ),
            pdk.Layer(
                "TextLayer",
                points,
                id="asset-labels",
                get_position="position",
                get_text="asset_id",
                get_color=[30, 41, 59],
                get_size=14,
                get_pixel_offset=[0, -20],
            ),
        ],
        tooltip={
            "text": "{name}\n{asset_id} · {asset_type}\n{warning}\nPriority: {priority}\nStatus: {status}"
        },
    )
