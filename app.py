import os
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "https://tripquorum-backend.onrender.com")

st.set_page_config(
    page_title="TripQuorum AI | Group Trip & Highway Micro-Planner",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# SESSION STATE & QUERY PARAMS SYNC
# ==========================================
query_params = st.query_params
default_room = query_params.get("room", "SIRSI26").upper()

if "room_code" not in st.session_state:
    st.session_state["room_code"] = default_room

def fetch_room_state(room_code: str):
    try:
        r = requests.get(f"{BACKEND_URL}/trips/{room_code.strip().upper()}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# ==========================================
# SIDEBAR: ROOM SYNC & SQUAD STATUS
# ==========================================
with st.sidebar:
    st.markdown("## 🧭 TripQuorum AI")
    st.caption("Search-Grounded Group Trip & Highway Micro-Itinerary Engine")
    st.divider()

    room_input = st.text_input(
        "🔑 Active Room Code",
        value=st.session_state["room_code"],
        help="Share this room code with your friends so everyone can add constraints and vote."
    ).strip().upper()

    if room_input and room_input != st.session_state["room_code"]:
        st.session_state["room_code"] = room_input
        st.query_params["room"] = room_input
        st.rerun()

    room_state = fetch_room_state(st.session_state["room_code"])

    if room_state:
        trip_info = room_state["trip"]
        prefs_list = room_state.get("preferences", [])
        votes_list = room_state.get("votes", [])
        voted_users = {v["user_name"] for v in votes_list}

        st.success(f"📍 **{trip_info.get('trip_name', 'Active Trip')}**")
        mode_label = "Fixed Destination" if trip_info.get("planning_mode") == "fixed_destination" else "Destination Discovery"
        st.markdown(f"**Mode:** `{mode_label}`")
        st.markdown(f"**Origin:** {trip_info.get('origin_city', 'N/A')}")
        st.markdown(f"**Target:** {trip_info.get('target_destination') or 'Open Discovery'}")
        st.markdown(f"**Duration:** {trip_info.get('trip_duration', 'N/A')}")

        if prefs_list:
            lowest_budget = min(p["max_budget_inr"] for p in prefs_list)
            st.metric("Strictest Group Budget Cap", f"₹{lowest_budget:,} / person")

            st.markdown(f"### 👥 Joined Squad ({len(prefs_list)})")
            for p in prefs_list:
                u = p["user_name"]
                status_badge = "🗳️ Voted" if u in voted_users else "✅ Ready"
                st.caption(f"• **{u}** ({p['dietary_pref']}) — {status_badge}")
        else:
            st.info("No squad preferences added yet. Add members in Tab 1!")
    else:
        st.warning(f"Room `{st.session_state['room_code']}` not initialized yet. Create it in Tab 1!")

    st.divider()
    with st.expander("⚙️ Advanced / BYOK API Key"):
        api_key_override = st.text_input(
            "Optional Gemini API Key Override",
            type="password",
            help="Leave blank to use the backend .env GEMINI_API_KEY."
        )

# ==========================================
# MAIN HEADER & 5-TAB NAVIGATION
# ==========================================
st.title("🧭 TripQuorum AI: Group Trip & Highway Micro-Planner")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1️⃣ Setup & Squad Preferences",
    "2️⃣ AI Route Proposals (A/B)",
    "3️⃣ Ranked-Choice Voting",
    "4️⃣ 1-Day / Highway Micro-Itinerary",
    "5️⃣ Engineering Telemetry"
])

# ==========================================
# TAB 1: SETUP & SQUAD PREFERENCES
# ==========================================
with tab1:
    col_setup, col_pref = st.columns([1, 1])

    with col_setup:
        st.subheader("🛠️ Step 1: Initialize or Update Trip Room")
        existing_trip = room_state["trip"] if room_state else {}

        with st.form("create_trip_form"):
            trip_name = st.text_input(
                "Trip Title",
                value=existing_trip.get("trip_name", "Hometown & Western Ghats Getaway")
            )
            planning_mode = st.selectbox(
                "Planning Mode",
                options=["fixed_destination", "discover_destination"],
                format_func=lambda x: "Fixed Destination (Propose 4 Route/Vibe Packages)" if x == "fixed_destination" else "Discover Destination (Propose 4 New Destinations)",
                index=0 if existing_trip.get("planning_mode", "fixed_destination") == "fixed_destination" else 1
            )
            origin_city = st.text_input(
                "Origin City / Starting Point",
                value=existing_trip.get("origin_city", "Bengaluru")
            )
            target_destination = st.text_input(
                "Target Destination / Region",
                value=existing_trip.get("target_destination", "Sirsi, Uttara Kannada (Karnataka)")
            )
            duration_options = [
                "1-Day Micro-Trip (Hour-by-Hour)",
                "Weekend Getaway (2-3 Days)",
                "Extended Trip (4-7 Days)"
            ]
            curr_dur = existing_trip.get("trip_duration", "Extended Trip (4-7 Days)")
            dur_idx = duration_options.index(curr_dur) if curr_dur in duration_options else 2
            trip_duration = st.selectbox("Trip Duration", options=duration_options, index=dur_idx)

            must_visit_spots = st.text_area(
                "Host's Must-Visit Local Spots (Optional)",
                value=existing_trip.get("must_visit_spots", "Marikamba Temple, Sahasralinga, Yana Caves, Banavasi, Unchalli Falls"),
                help="Specific temples, waterfalls, or viewpoints you want included."
            )

            submit_trip = st.form_submit_button("💾 Save / Initialize Trip Room", type="primary", use_container_width=True)
            if submit_trip:
                try:
                    r = requests.post(
                        f"{BACKEND_URL}/trips/create",
                        json={
                            "room_code": st.session_state["room_code"],
                            "trip_name": trip_name,
                            "planning_mode": planning_mode,
                            "origin_city": origin_city,
                            "target_destination": target_destination,
                            "trip_duration": trip_duration,
                            "must_visit_spots": must_visit_spots
                        },
                        timeout=15
                    )
                    if r.status_code == 200:
                        st.success(f"Room `{st.session_state['room_code']}` saved!")
                        st.rerun()
                    else:
                        st.error(f"Error: {r.text}")
                except Exception as e:
                    st.error(f"Could not connect to backend: {e}")

    with col_pref:
        st.subheader("🙋‍♂️ Step 2: Add Each Friend's Constraints")
        with st.form("add_pref_form"):
            user_name = st.text_input("Your Name", placeholder="e.g., Pranav, Shashi, Rahul")
            max_budget_inr = st.number_input("Max Per-Person Budget (₹ INR)", min_value=500, max_value=100000, value=4500, step=250)
            preferred_dates = st.text_input("Preferred Dates / Window", value="End of November 2026")
            dietary_pref = st.selectbox(
                "Dietary Requirement",
                options=[
                    "Strict Pure Veg (Pure Veg Restaurants Only)",
                    "Vegetarian Friendly (Veg Options Required)",
                    "Jain Vegetarian",
                    "No Restrictions (Non-Veg / Veg OK)"
                ]
            )
            vibe = st.text_input(
                "Travel Vibe & Interests",
                value="Western Ghats nature, waterfalls, heritage temples, relaxed highway drive"
            )
            transport_pref = st.selectbox(
                "Preferred Transport Mode",
                options=[
                    "Overnight Sleeper Bus (KSRTC / Vijayanand / Sugama)",
                    "Personal / Rental Car Road-Trip",
                    "Train + Local Cab",
                    "Flexible / Any"
                ]
            )
            dealbreakers = st.text_input(
                "Dealbreakers",
                value="Unhygienic highway stops or late-night risky ghat driving"
            )

            submit_pref = st.form_submit_button("➕ Add / Update Member Constraints", type="primary", use_container_width=True)
            if submit_pref:
                if not user_name.strip():
                    st.warning("Please enter your name first.")
                else:
                    try:
                        r = requests.post(
                            f"{BACKEND_URL}/trips/preferences",
                            json={
                                "room_code": st.session_state["room_code"],
                                "user_name": user_name.strip(),
                                "max_budget_inr": int(max_budget_inr),
                                "preferred_dates": preferred_dates,
                                "dietary_pref": dietary_pref,
                                "vibe": vibe,
                                "transport_pref": transport_pref,
                                "dealbreakers": dealbreakers
                            },
                            timeout=15
                        )
                        if r.status_code == 200:
                            st.success(f"Saved constraints for **{user_name}**!")
                            st.rerun()
                        else:
                            st.error(f"Error: {r.text}")
                    except Exception as e:
                        st.error(f"Backend error: {e}")

    if room_state and room_state.get("preferences"):
        st.divider()
        st.markdown("### 📋 Current Squad Constraints Matrix")
        st.dataframe(room_state["preferences"], use_container_width=True)

# ==========================================
# TAB 2: AI ROUTE PROPOSALS (A/B PROMPT TESTING)
# ==========================================
with tab2:
    st.subheader("🧠 AI Group Constraint Synthesis & Prompt A/B Testing")

    col_ab, col_btn = st.columns([2, 1])
    with col_ab:
        prompt_version = st.radio(
            "Select Prompt Engineering Variant (For A/B Evaluation):",
            options=["v1_vibe_balanced", "v2_budget_highway_strict"],
            format_func=lambda x: "v1_vibe_balanced (Balances Group Vibes + Must-Visit Spots)" if x == "v1_vibe_balanced" else "v2_budget_highway_strict (Strict Lowest-Budget Cap + Highway Pure-Veg Focus)",
            horizontal=False
        )
    with col_btn:
        st.write("")
        st.write("")
        gen_clicked = st.button("⚡ Generate 4 Grounded Options", type="primary", use_container_width=True)

    if gen_clicked:
        with st.spinner("Synthesizing squad constraints and generating 4 distinct route packages..."):
            try:
                r = requests.post(
                    f"{BACKEND_URL}/trips/generate",
                    json={
                        "room_code": st.session_state["room_code"],
                        "prompt_version": prompt_version,
                        "api_key_override": api_key_override or None
                    },
                    timeout=180
                )
                if r.status_code == 200:
                    st.success("Generated 4 tailored route options!")
                    st.rerun()
                else:
                    st.error(f"Generation failed: {r.text}")
            except Exception as e:
                st.error(f"Request failed or timed out: {e}")

    prop_data = room_state.get("proposals_data") if room_state else None
    if prop_data and prop_data.get("proposals"):
        st.caption(
            f"**Active Prompt Variant:** `{prop_data.get('prompt_version')}` | "
            f"**Model Used:** `{prop_data.get('model_used')}` | "
            f"**Latency:** `{prop_data.get('latency_ms')} ms`"
        )
        proposals = prop_data["proposals"]
        cols = st.columns(2)
        for idx, item in enumerate(proposals):
            with cols[idx % 2]:
                with st.container(border=True):
                    st.markdown(f"### {idx + 1}. {item.get('option_title', f'Option {idx + 1}')}")
                    m1, m2 = st.columns(2)
                    m1.metric("Est. Cost / Person", f"₹{item.get('estimated_cost_per_person_inr', 0):,}")
                    m2.metric("Travel Mode", item.get("travel_mode", "Bus / Car"))

                    st.markdown(f"**🗓️ Best Window:** {item.get('best_dates', 'N/A')}")
                    st.markdown(f"**🛣️ Highway & Route:** {item.get('route_highway_summary', 'N/A')}")
                    st.markdown(f"**🥗 Pure-Veg / Dietary Feasibility:** {item.get('veg_food_feasibility', 'N/A')}")
                    st.markdown(f"**🤝 Why It Fits the Squad:** {item.get('why_it_fits_group', 'N/A')}")
                    highlights = item.get("key_highlights", [])
                    if isinstance(highlights, list) and highlights:
                        st.markdown("**🌟 Key Highlights:** " + " • ".join(highlights))
                    st.caption(f"⚖️ *Trade-off Note:* {item.get('compromise_note', 'None')}")
    else:
        st.info("Click **⚡ Generate 4 Grounded Options** above to synthesize route proposals for your group.")

# ==========================================
# TAB 3: INSTANT-RUNOFF RANKED-CHOICE VOTING
# ==========================================
with tab3:
    st.subheader("🗳️ Instant-Runoff Ranked-Choice Voting (IRV + Borda Count)")
    prop_data = room_state.get("proposals_data") if room_state else None

    if not prop_data or not prop_data.get("proposals"):
        st.info("Generate the 4 route/destination options in **Tab 2** first to open the voting ballot!")
    else:
        option_titles = [p.get("option_title", f"Option {i+1}") for i, p in enumerate(prop_data["proposals"])]
        v_col1, v_col2 = st.columns([1, 1])

        with v_col1:
            st.markdown("#### Cast Your Ranked Ballot")
            squad_names = [p["user_name"] for p in room_state.get("preferences", [])]
            voter_name = st.selectbox("Select Your Name", options=squad_names if squad_names else ["Guest"])

            ranked_selection = st.multiselect(
                "Rank Options from 1st Choice (Top) to Last Choice (Select all 4 in order):",
                options=option_titles,
                default=option_titles
            )

            if st.button("🗳️ Submit My Ranked Ballot", type="primary", use_container_width=True):
                if len(ranked_selection) < 1:
                    st.warning("Please rank at least 1 option.")
                else:
                    try:
                        r = requests.post(
                            f"{BACKEND_URL}/trips/vote",
                            json={
                                "room_code": st.session_state["room_code"],
                                "user_name": voter_name,
                                "ranked_choices": ranked_selection
                            },
                            timeout=15
                        )
                        if r.status_code == 200:
                            st.success(f"Recorded ranked ballot for **{voter_name}**!")
                            st.rerun()
                        else:
                            st.error(f"Error: {r.text}")
                    except Exception as e:
                        st.error(f"Vote error: {e}")

        with v_col2:
            st.markdown("#### 🏆 Live Consensus Leaderboard")
            consensus = room_state.get("consensus")
            if consensus:
                st.success(f"🎉 **Winning Consensus Choice:** {consensus.get('winner')}")
                st.caption(
                    f"**Resolution Method:** `{consensus.get('method')}` | "
                    f"**Total Voters:** `{consensus.get('total_voters')}`"
                )
                borda = consensus.get("borda_scores", {})
                if borda:
                    st.markdown("**Borda Consensus Points Breakdown:**")
                    max_pts = max(borda.values()) if borda.values() else 1
                    for cand, pts in sorted(borda.items(), key=lambda x: x[1], reverse=True):
                        st.write(f"{cand} — **{pts} pts**")
                        st.progress(min(pts / max_pts, 1.0))
            else:
                st.info("No ballots cast yet. Submit a ranked ballot on the left to compute the winner!")

# ==========================================
# TAB 4: 1-DAY / HIGHWAY MICRO-ITINERARY
# ==========================================
with tab4:
    st.subheader("🛣️ Chronological Highway & Pure-Veg Micro-Itinerary")

    prop_data = room_state.get("proposals_data") if room_state else None
    consensus = room_state.get("consensus") if room_state else None

    available_routes = []
    if consensus and consensus.get("winner"):
        available_routes.append(consensus["winner"])
    if prop_data and prop_data.get("proposals"):
        for p in prop_data["proposals"]:
            t = p.get("option_title")
            if t and t not in available_routes:
                available_routes.append(t)
    if room_state and room_state.get("trip", {}).get("target_destination"):
        td = room_state["trip"]["target_destination"]
        if td not in available_routes:
            available_routes.append(td)

    selected_route = st.selectbox(
        "Target Route / Winning Package for Hour-by-Hour Plan:",
        options=available_routes if available_routes else ["Sirsi & Western Ghats Circuit"]
    )

    if st.button("🧭 Generate Live Search-Grounded Micro-Itinerary (Breakfast/Lunch/Dinner + Highway Cues)", type="primary", use_container_width=True):
        with st.spinner("Grounding highway stops, verifying Pure Veg dhabas, and computing hour-by-hour timeline..."):
            try:
                r = requests.post(
                    f"{BACKEND_URL}/trips/micro-itinerary",
                    json={
                        "room_code": st.session_state["room_code"],
                        "selected_option": selected_route,
                        "api_key_override": api_key_override or None
                    },
                    timeout=240
                )
                if r.status_code == 200:
                    st.success("Hour-by-Hour Highway Micro-Itinerary Ready!")
                    st.rerun()
                else:
                    st.error(f"Error: {r.text}")
            except requests.exceptions.RequestException as e:
                st.error(f"Request timed out or backend busy. Please click Generate again! ({e})")

    micro_data = room_state.get("micro_itinerary_data") if room_state else None
    if micro_data and micro_data.get("itinerary"):
        itin = micro_data["itinerary"]
        st.divider()
        st.markdown(f"## 📋 {itin.get('itinerary_title', selected_route)}")
        st.caption(
            f"**Engine:** `{micro_data.get('model_used')}` | "
            f"**Latency:** `{micro_data.get('latency_ms')} ms` | "
            f"**Dietary Rule:** `{itin.get('dietary_compliance_badge', 'Strict Pure Veg')}`"
        )

        if itin.get("remote_logistics_alert"):
            st.warning(f"⚠️ **Highway & Remote Corridor Alert:** {itin['remote_logistics_alert']}")

        budget_box = itin.get("split_budget_per_person_inr", {})
        if budget_box:
            b1, b2, b3, b4, b5 = st.columns(5)
            b1.metric("🚌 Transport", f"₹{budget_box.get('transport', 0):,}")
            b2.metric("🥗 Pure-Veg Dining", f"₹{budget_box.get('food_and_dining', 0):,}")
            b3.metric("🎟️ Stays / Tickets", f"₹{budget_box.get('stays_or_entry_tickets', 0):,}")
            b4.metric("🛡️ Buffer", f"₹{budget_box.get('emergency_buffer', 0):,}")
            b5.metric("💰 Total / Person", f"₹{budget_box.get('total', 0):,}")

        st.markdown("### ⏱️ Hour-by-Hour Timeline & Highway Restaurant Guide")
        for step in itin.get("timeline", []):
            with st.container(border=True):
                c_left, c_right = st.columns([4, 1])
                with c_left:
                    st.markdown(
                        f"#### 🕒 `{step.get('day_label', 'Day 1')} | {step.get('time_slot', '')}` — "
                        f"{step.get('stop_type', 'Stop')}: **{step.get('place_name', '')}**"
                    )
                    st.markdown(f"📍 **Highway Position & Landmark Cue:** {step.get('location_and_highway_cue', 'N/A')}")
                    st.markdown(f"🍽️ **What to Order / Do:** {step.get('what_to_order_or_do', 'N/A')}")
                    if step.get("backup_veg_option"):
                        st.caption(f"🔄 **Backup Pure-Veg Option Nearby:** {step.get('backup_veg_option')}")
                with c_right:
                    st.metric("Est. Cost", f"₹{step.get('estimated_cost_per_person_inr', 0):,}")
                    maps_url = step.get("google_maps_url")
                    if maps_url:
                        st.link_button("🗺️ Open in Maps", maps_url, use_container_width=True)

# ==========================================
# TAB 5: ENGINEERING TELEMETRY
# ==========================================
with tab5:
    st.subheader("📈 Model Gateway, Search Grounding & Prompt A/B Telemetry")
    try:
        r = requests.get(f"{BACKEND_URL}/telemetry", timeout=10)
        if r.status_code == 200:
            logs = r.json().get("logs", [])
            if not logs:
                st.info("No gateway calls logged yet. Generate a trip or micro-itinerary to populate telemetry.")
            else:
                avg_lat = round(sum(l["latency_ms"] for l in logs) / len(logs), 1)
                total_tok = sum(l["estimated_tokens"] for l in logs)
                m_c1, m_c2, m_c3 = st.columns(3)
                m_c1.metric("Total Gateway Calls", len(logs))
                m_c2.metric("Avg Gateway Latency", f"{avg_lat} ms")
                m_c3.metric("Total Estimated Tokens", f"{total_tok:,}")
                st.dataframe(logs, use_container_width=True)
    except Exception as e:
        st.error(f"Could not load telemetry: {e}")