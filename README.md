# 🧭 TripQuorum AI

A multi-agent group trip planning and search-grounded highway micro-itinerary engine. 

TripQuorum AI allows friend groups to collaboratively plan trips by synthesizing diverse dietary, budget, and travel constraints. It features an automated voting system and generates real-time, hour-by-hour highway itineraries.

## 🚀 Core Features
* **Multi-Agent Constraint Synthesis:** Merges different squad preferences (budget caps, dietary restrictions, preferred vibes) into 4 distinct, optimized route packages.
* **Instant-Runoff Ranked-Choice Voting:** Uses IRV and Borda Count to automatically resolve group voting and determine the winning consensus itinerary.
* **Highway Micro-Itinerary Engine:** Generates search-grounded, hour-by-hour timelines including verified pure-veg highway stops and Google Maps waypoint cues.
* **ModelGateway Telemetry:** Built-in failover logic handling model timeouts with fallback orchestration between Google Gemini Flash and Flash-Lite models.

## 🛠️ Tech Stack
* **Frontend:** Streamlit (deployed on Streamlit Community Cloud)
* **Backend:** FastAPI, Python (deployed on Render)
* **Database:** SQLite
* **AI Orchestration:** Google Gemini API 

## 🌐 Live Demo
* Frontend App: [Add your Streamlit URL here]
* Backend API: [Add your Render URL here]

## 💻 Local Quick Start
1. Clone the repository: `git clone https://github.com/Bhat1801Pranav/tripquorum-ai.git`
2. Install dependencies: `pip install -r requirements.txt`
3. Add your `.env` file with `GEMINI_API_KEY=your_key`
4. Start the backend: `uvicorn main:app --reload`
5. Start the frontend: `streamlit run app.py`
