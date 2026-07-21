# Code Navi - Agent Skill Web Demo MVP

Code Navi is a lightweight, AI-native web demonstration MVP designed to showcase how an AI Agent can dynamically route user prompts to specialized capabilities (Skills) and safely execute them.

This project is decoupled into:
1. **Frontend Web UI**: A clean, premium dashboard built with Vanilla HTML, CSS, and JS (incorporating glassmorphism and real-time execution tracing).
2. **FastAPI API Layer**: RESTful endpoints for checking health, listing skills, and triggering agent requests.
3. **Agent Orchestration Layer**: The intelligent router that parses user intent (supporting both rule-based heuristics and LLM-based JSON function selection with fallback).
4. **Skill System Layer**: A modular, extensible framework for running sandboxed tasks.

---

## 🚀 Quick Start

### 1. Prerequisites
Ensure you have **Python 3.11 or higher** installed.

### 2. Installation
Install the required packages:
```bash
pip install -r requirements.txt
```

*(Optional)* If you want to run the unit test suite, also install `pytest-asyncio`:
```bash
pip install pytest-asyncio
```

### 3. Model Configuration (Optional)
By default, the Agent operates in **Rule-based Auto-Routing mode** (no API Key required). It detects math formulas, summary keywords, and falls back to echo routing automatically.

To enable **Model-based Routing** (where the LLM reads skill descriptions and outputs a JSON decision) and **AI Text Summarization**:
1. Create a `.env` file in the root directory:
   ```bash
   LLM_API_KEY=your_openai_compatible_api_key
   LLM_BASE_URL=https://api.openai.com/v1  # Or Spark API / local Qwen base url
   LLM_MODEL=gpt-3.5-turbo
   ```

### 4. Running the Web Server
Launch the server using:
```bash
python run.py
```
Or start Uvicorn directly:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 🌐 Web URLs

*   **Frontend Dashboard (Home)**: [http://localhost:8000/](http://localhost:8000/)
*   **Swagger API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
*   **Health Check Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🛠️ API Reference

### 1. Chat Router Endpoint
*   **Path**: `POST /api/chat`
*   **Payload**:
    ```json
    {
      "message": "Calculate (3.5 * 4) + 12",
      "preferred_skill": null  // Optional: "echo_skill", "calculator_skill", "summary_skill"
    }
    ```
*   **Response**:
    ```json
    {
      "request_id": "893d5a42-7cf1-4560-bf65-f12b23ea890e",
      "success": true,
      "reply": "Calculation Result: (3.5 * 4) + 12 = 26.0",
      "route_mode": "Auto (Rule-based)",
      "skill_name": "calculator_skill",
      "reason": "Rule-based: Detected purely mathematical expression characters.",
      "inputs": {
        "expression": "(3.5 * 4) + 12"
      },
      "outputs": {
        "result": 26.0,
        "formatted": "(3.5 * 4) + 12 = 26.0"
      },
      "duration_ms": 0.45,
      "error": null
    }
    ```

### 2. List Active Skills
*   **Path**: `GET /api/skills`
*   **Response**: Returns metadata and parameter schemas of all enabled skills.

---

## 🧩 How to Add a New Skill

Adding a new skill is extremely simple and requires **zero changes** to the FastAPI routes or the frontend code.

### Step 1: Create the Skill File
Create a new file in `app/services/skills/` (e.g., `my_skill.py`) inheriting from `BaseSkill`:
```python
from pydantic import BaseModel, Field
from app.services.skills.base import BaseSkill, SkillResult
from typing import Dict, Any
import time

class MyInputSchema(BaseModel):
    user_name: str = Field(..., description="The user's name to greet.")

class MyNewSkill(BaseSkill):
    name = "my_new_skill"
    display_name = "Personalized Greeter"
    description = "Greets a user by name."
    input_schema = MyInputSchema

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.perf_counter()
        try:
            validated = self.input_schema(**params)
            duration = (time.perf_counter() - start_time) * 1000.0
            return SkillResult(
                success=True,
                skill_name=self.name,
                data={"reply": f"Hello, {validated.user_name}!"},
                duration_ms=duration
            )
        except Exception as e:
            return SkillResult(success=False, skill_name=self.name, data=None, error=str(e))
```

### Step 2: Register it in Registry
Open `app/services/skills/__init__.py` and register it:
```python
from app.services.skills.my_skill import MyNewSkill
from app.services.registry import registry

my_new_skill = MyNewSkill()
registry.register(my_new_skill)
```
The Frontend Skill Library Panel and the Agent Router will automatically discover it on startup.

---

## 🔒 Security & Sandboxing Features
1.  **No `eval()` execution**: The mathematical calculator uses a custom token parser (Shunting-yard algorithm) to evaluate equations securely. Arbitrary code strings are rejected before parsing.
2.  **Mock Fallback**: If LLM API Keys are missing or the provider throws errors, the Agent instantly downgrades to local keyword-based rule routing to avoid crashing the server.
3.  **Strict Parameter Constraints**: Input parameters are strictly validated via Pydantic model schemas prior to execution.
