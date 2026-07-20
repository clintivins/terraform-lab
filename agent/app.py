import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
import requests

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
GITHUB_REPO = "clintivins/terraform-lab"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)

@tool
def read_repo_file(filename: str) -> str:
    """Read a file from the terraform-lab repo. Provide a relative path,
    e.g. 'main.tf' or '.github/workflows/terraform-ci.yml'."""
    target = (REPO_ROOT / filename).resolve()
    if not str(target).startswith(str(REPO_ROOT.resolve())):
        return "Error: access outside repo is not allowed."
    if not target.exists():
        return f"Error: {filename} not found."
    return target.read_text()

@tool
def list_repo_files() -> str:
    """List all files in the terraform-lab repo (excluding .git, venv, node_modules)."""
    ignore = {".git", "venv", "node_modules", ".terraform", "__pycache__"}
    files = []
    for path in REPO_ROOT.rglob("*"):
        if path.is_file() and not any(part in ignore for part in path.parts):
            files.append(str(path.relative_to(REPO_ROOT)))
    return "\n".join(sorted(files))

@tool
def kubectl_get_pods() -> str:
    """Get the status of all pods across all namespaces in the local kind cluster (read-only)."""
    result = subprocess.run(["kubectl", "get", "pods", "-A"], capture_output=True, text=True, timeout=15)
    return result.stdout or result.stderr

@tool
def kubectl_get_nodes() -> str:
    """Get the status of all nodes in the local kind cluster (read-only)."""
    result = subprocess.run(["kubectl", "get", "nodes"], capture_output=True, text=True, timeout=15)
    return result.stdout or result.stderr

@tool
def kubectl_get_namespaces() -> str:
    """Get all namespaces in the local kind cluster (read-only)."""
    result = subprocess.run(["kubectl", "get", "namespaces"], capture_output=True, text=True, timeout=15)
    return result.stdout or result.stderr

@tool
def github_latest_workflow_run() -> str:
    """Get the status of the most recent GitHub Actions workflow run for the repo."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?per_page=1"
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return f"Error fetching workflow runs: {resp.status_code} {resp.text}"
    data = resp.json()
    runs = data.get("workflow_runs", [])
    if not runs:
        return "No workflow runs found."
    run = runs[0]
    return (
        f"Workflow: {run['name']}\n"
        f"Status: {run['status']}\n"
        f"Conclusion: {run['conclusion']}\n"
        f"Branch: {run['head_branch']}\n"
        f"Commit message: {run['head_commit']['message']}\n"
        f"URL: {run['html_url']}"
    )

def run_subagent(system_prompt: str, agent_tools: list, query: str, max_steps: int = 4) -> str:
    llm_with_tools = llm.bind_tools(agent_tools)
    tool_map = {t.name: t for t in agent_tools}
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=query)]
    for _ in range(max_steps):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            return response.content
        for call in response.tool_calls:
            result = tool_map[call["name"]].invoke(call["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return "Agent did not reach a final answer within the step limit."

@tool
def repo_agent(query: str) -> str:
    """Ask the Repo Agent about the contents of the terraform-lab codebase
    (Terraform config, GitHub Actions workflows, README, etc.)."""
    return run_subagent(
        "You are the Repo Agent. Answer questions about the terraform-lab "
        "codebase by reading actual files with your tools. Be concise and accurate.",
        [read_repo_file, list_repo_files], query)

@tool
def cluster_agent(query: str) -> str:
    """Ask the Cluster Agent about the live health of the local kind Kubernetes
    cluster (pods, nodes, namespaces)."""
    return run_subagent(
        "You are the Cluster Agent. Check the live state of the local kind "
        "Kubernetes cluster using your read-only kubectl tools. Report clearly "
        "on health, any pods not Running, and node status.",
        [kubectl_get_pods, kubectl_get_nodes, kubectl_get_namespaces], query)

@tool
def cicd_agent(query: str) -> str:
    """Ask the CI/CD Agent about the status of the latest GitHub Actions
    workflow run for this repo."""
    return run_subagent(
        "You are the CI/CD Agent. Report on the status of GitHub Actions "
        "workflow runs using your tool. Be clear about pass/fail and why.",
        [github_latest_workflow_run], query)

@tool
def terraform_advisor_agent(query: str) -> str:
    """Ask the Terraform Advisor Agent to review .tf files for best-practice
    issues (hardcoded values, missing variables, security concerns, etc.)."""
    return run_subagent(
        "You are the Terraform Advisor. Review Terraform files for best "
        "practice issues: hardcoded values that should be variables, missing "
        "descriptions, security concerns, lack of remote state, etc. Read the "
        "actual files first using your tools before giving an opinion.",
        [read_repo_file, list_repo_files], query)

SUPERVISOR_PROMPT = """You are the Supervisor of an infra-ops assistant made up
of four specialist agents:
- repo_agent: understands the codebase (Terraform files, CI workflows)
- cluster_agent: checks live Kubernetes cluster health
- cicd_agent: checks GitHub Actions workflow run status
- terraform_advisor_agent: reviews Terraform code for best-practice issues

Given the user's request, call ONLY the specialist agents actually needed to
answer it. You may call more than one if the request needs it. Once you have
enough information, give one clear, well-organized final answer to the user
that synthesizes what each agent found. Do not call an agent that isn't
relevant to the question."""

SPECIALISTS = [repo_agent, cluster_agent, cicd_agent, terraform_advisor_agent]

def run_supervisor(query: str, max_steps: int = 6):
    llm_with_tools = llm.bind_tools(SPECIALISTS)
    tool_map = {t.name: t for t in SPECIALISTS}
    messages = [SystemMessage(content=SUPERVISOR_PROMPT), HumanMessage(content=query)]
    yield {"type": "status", "text": "Supervisor: analyzing request..."}
    for _ in range(max_steps):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            yield {"type": "final", "text": response.content}
            return
        for call in response.tool_calls:
            yield {"type": "status", "text": f"Calling {call['name']}..."}
            result = tool_map[call["name"]].invoke(call["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
            yield {"type": "status", "text": f"{call['name']} responded."}
    yield {"type": "final", "text": "Reached step limit without a final answer."}

app = FastAPI(title="Infra Ops Assistant")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Question(BaseModel):
    question: str

@app.post("/ask")
def ask(q: Question):
    events = list(run_supervisor(q.question))
    final = next(e for e in events if e["type"] == "final")
    return {"answer": final["text"], "steps": [e["text"] for e in events if e["type"] == "status"]}

@app.get("/health")
def health():
    return {"status": "ok"}

from fastapi.responses import StreamingResponse
import json

@app.post("/ask-stream")
def ask_stream(q: Question):
    def event_generator():
        for event in run_supervisor(q.question):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
