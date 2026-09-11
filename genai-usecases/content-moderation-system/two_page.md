# Content Moderation Platform Architecture

## Executive Summary
This project is an AI-powered content moderation and community safety platform designed to automatically review user-generated stories and comments, detect harmful content, enforce policy rules, and escalate uncertain or high-risk cases to human moderators. The solution combines a React frontend, a FastAPI backend, Python-based AI agents, SQLite/Firebase storage, ChromaDB memory, and Google Gemini-powered reasoning to support both real-time automated moderation and human-in-the-loop review.

The architecture is built for two environments:
1. Production architecture: scalable deployment model for real users, cloud hosting, managed databases, and external AI services.
2. Local development architecture: developer-friendly setup used in VS Code for coding, debugging, and testing with local SQLite and local frontend/backend processes.

### Technology Stack Used
- Frontend: React, Vite, JavaScript/JSX, Material UI
- Backend: Python, FastAPI, LangGraph, Pydantic
- AI/ML: Google Gemini LLM, multi-agent reasoning, ReAct loop, toxicity detection, policy enforcement
- Data and Memory: SQLite, Firebase Auth/User Data, ChromaDB vector memory
- Security and Auth: Firebase authentication, role-based access, moderator/admin workflows
- Monitoring and Observability: logging, tracing, metrics, operational monitoring
- Testing and Local Development: Python scripts, local SQLite setup, demo user initialization, VS Code + local terminals

### Core System Components Included in the Architecture
- User Interface Layer: regular users, moderator dashboard, admin/analyst views
- API Gateway Layer: FastAPI endpoints for authentication, content moderation, moderation review, appeals, and analytics
- Auth Database (DB1): Firebase-backed user auth and profile management
- Content Processing Layer: LangGraph workflow orchestration for submission, review, enforcement, and learning
- Multi-Agent Processing Layer: Agent 1 Content Analysis, Agent 2 Toxicity Detection, Agent 3 Policy Violation Detection, Agent 4 ReAct synthesis, Agent 5 HITL checkpoint, Agent 6 User Reputation, and Action Enforcement
- Data Storage Layer: SQLite moderation database for content submissions, stories, comments, actions, and review records
- Vector Memory Layer: ChromaDB for decision memory, pattern learning, and similar-content retrieval
- External Service Layer: Google Gemini API, optional ML models, OpenTelemetry observability, and logging services

### End-to-End Data Flow
User action -> React frontend -> FastAPI REST API -> LangGraph workflow -> AI agents -> ReAct decision synthesis -> moderation action -> SQLite/Firebase persistence + ChromaDB memory update -> HITL review queue if escalation is needed -> analytics and reports

---

## Page 1: Production Architecture

### Visual Architecture
```mermaid
flowchart LR
    U[Regular Users] --> UI[User Interface Layer
    React + Vite + MUI]
    M[Moderator / Analyst / Admin] --> UI

    UI --> API[API Gateway Layer
    FastAPI endpoints]
    API --> AUTH[(Auth Database DB1)
    Firebase Auth / User Profiles]
    API --> WF[LangGraph Workflow
    Content Processing]

    WF --> A1[Agent 1
    Content Analysis]
    WF --> A2[Agent 2
    Toxicity Detection]
    WF --> A3[Agent 3
    Policy Violation Detection]
    WF --> A4[Agent 4
    ReAct Decision Synthesis]
    WF --> HITL{HITL Required?}
    HITL --> A5[Agent 5a
    HITL Checkpoint]
    HITL --> A6[Agent 5b
    User Reputation]
    A4 --> A7[Agent 6
    Action Enforcement]

    A1 --> LLM[Google Gemini API]
    A2 --> LLM
    A3 --> LLM
    A7 --> DB2[(Moderation DB DB2)
    SQLite tables for content, stories, comments, actions, appeals]
    A7 --> MEM[(Vector Memory DB3)
    ChromaDB patterns + learned decisions]
    A5 --> MOD[Human Moderator Review]
    MOD --> API
    API --> ANALYTICS[Analytics + Reports]

    subgraph EXT[External Service Layer]
      GAI[Google Gemini API]
      ML[ML Models]
      OTel[Observability / Logging]
    end

    A1 --> GAI
    A2 --> ML
    A3 --> GAI
    A7 --> OTel
```

### What is actually happening in production
The production flow begins when a user creates a story, submits a comment, or files an appeal through the React application. The frontend sends requests to the FastAPI backend through REST APIs. Each request is processed by a LangGraph-based multi-agent workflow. The system does not rely on a single AI model call; instead, multiple specialized agents evaluate the content from different angles:

- Content Analysis Agent identifies context, sentiment, topic, and risk profile
- Toxicity Detection Agent scans for abusive, hateful, or explicit language
- Policy Violation Agent checks against community guidelines
- User Reputation Agent evaluates the user’s history and risk level
- HITL Checkpoint Agent decides whether a case should be escalated to a human moderator
- Action Enforcement Agent decides the final moderation action

The final decision is assembled through a ReAct reasoning loop, which combines evidence from all agents, checks confidence, and determines whether to allow, warn, remove, suspend, or escalate. If the content is ambiguous, high severity, or low-confidence, the workflow pauses for a human review instead of making a risky decision automatically.

### Production components and responsibilities
- User Interface Layer: React frontend for regular users, moderators, analysts, and admins
- API Gateway Layer: FastAPI service exposes endpoints for authentication, moderation, user management, analytics, and appeals
- Auth Database (DB1): Firebase handles user authentication, role assignment, and profile data
- Processing Layer: LangGraph orchestrates content flow through AI agents and decision logic
- AI/ML Layer: Google Gemini and optional ML models perform analysis, toxicity scoring, and policy checks
- Moderation Database (DB2): SQLite stores content submissions, moderation decisions, user actions, and related audit records
- Vector Memory (DB3): ChromaDB stores historical decisions, pattern memories, and similar-content lookup data
- Human loop: Moderators review the HITL queue and approve or override automated decisions
- Analytics and governance: dashboards provide trust, safety, and policy metrics for leadership and operations

### Production architecture summary
This is a true enterprise-style AI moderation pipeline: user actions trigger agentic decision-making, policy enforcement, and human escalation when needed. It balances speed, transparency, and accountability, which is critical for community-facing platforms that need to reduce harm while preserving user trust.

### Data flow in production
1. A user submits a story, comment, or appeal via the web frontend.
2. The frontend sends structured requests to the FastAPI backend.
3. The backend triggers the LangGraph moderation workflow.
4. Specialized AI agents analyze the content, score risk, and compare against policy rules.
5. The ReAct decision engine combines all evidence and decides the appropriate action.
6. If confidence is low or risk is high, the workflow routes the decision to the HITL queue for moderator review.
7. The final moderation result is stored in SQLite/Firebase, logged for auditing, and reused in memory for future similarity checks.
8. Dashboard analytics and reports are generated from the saved moderation data.

---

## Page 2: Local Development Architecture

### Visual Architecture
```mermaid
flowchart LR
    DEV[Developer in VS Code] --> FE[Frontend Layer
    React + Vite
    localhost:5173]
    DEV --> BE[Backend Layer
    FastAPI app
    localhost:8000]
    FE --> API[Local REST API calls]
    API --> APP[main.py
    route handlers + workflow trigger]
    APP --> AG[Python Agent Modules
    agents.py / workflow.py / reasoning.py]
    AG --> LLM[Google Gemini API
    configured through .env]
    AG --> MEM[(ChromaDB
    local vector memory)]
    AG --> DB[(SQLite Local DBs)
    moderation_data.db + auth_db.db]
    APP --> FB[(Firebase Local Auth / User Data)]
    FE --> MOD[Local UI dashboards
    stories, moderation queue, analytics]
    DEV --> TEST[Python tests + scripts
    initialize_users.py / test files]
    TEST --> DB
    TEST --> AG
```

### What is actually happening in local development
In local development, the system runs as a full-stack app on the developer machine. The frontend is served by a Vite dev server on localhost:5173, while the backend runs as a FastAPI app on localhost:8000. Developers work inside VS Code, editing Python and React files, then run the application in parallel using two terminals.

The local workflow mirrors production but is simplified for debugging. When a user submits content in the frontend, the browser invokes backend endpoints such as story creation, comment moderation, authentication, or analytics. The FastAPI application receives the request, loads the moderation workflow, and triggers the relevant AI agents. The backend uses a local SQLite database to store user, moderation, and content records, while ChromaDB persists learned moderation patterns and memory. If a Google Gemini API key is configured in the local .env file, the LLM is called for structured reasoning and decision generation.

This environment also includes local initialization scripts that set up demo users, JWT/session-like user structure, and test data. The developer can manually review moderation decisions, inspect logs, test the moderation queue, and validate the full flow without needing a production-style infrastructure stack.

### Local development stack and setup
- Frontend: React, Vite, JavaScript/JSX, MUI, custom dashboards
- Backend: Python 3.12+, FastAPI, LangGraph, Pydantic, Google Gemini integration
- Databases: SQLite for local persistence, ChromaDB for semantic memory, Firebase integration for auth and user data
- Local run model: developer starts backend and frontend separately in VS Code terminals
- Testing: scripts such as initialize_users.py and test files exercise registration, moderation, and submission flows
- Observability: logging and workflow traces for debugging AI decisions in local execution

### Key design difference: production vs local
The major difference is operational scale and deployment responsibility. Local development prioritizes fast iteration, debugging, and validation with simple local services. Production architecture is designed for reliability, security, scalability, and operational monitoring with external services, cloud hosting, and human review workflows. Both versions follow the same core logic: user input -> AI moderation workflow -> decision -> action -> memory + audit trail.

### Data flow in local development
1. The developer runs the frontend and backend separately in local terminals.
2. The React app sends API requests to the local FastAPI service on localhost:8000.
3. The backend loads the moderation workflow and relevant AI agent modules.
4. Gemini API is called for reasoning and decision generation when configured with an API key.
5. The application writes moderation and user activity records to SQLite and stores learned patterns in ChromaDB.
6. Test scripts and local database setup stream user and content data into the same workflow for validation.
7. Moderators can review the local moderation queue and verify that decisions match expected business rules.

---

## Final Architecture Statement
This project demonstrates a modern AI-driven moderation platform built around agentic intelligence, human oversight, and modular software design. The system is not just a model wrapper; it is an end-to-end platform that combines frontend interaction, backend orchestration, AI reasoning, memory, policy checks, user management, and moderation operations. The architecture is practical for production deployment and adaptable for local development, making it a strong candidate for enterprise and MNC-level evaluation.

## Suggested one-line pitch for presentation
An AI-powered community safety platform that combines multi-agent reasoning, human-in-the-loop review, and scalable full-stack architecture to automate moderation while preserving trust, transparency, and accountability.
