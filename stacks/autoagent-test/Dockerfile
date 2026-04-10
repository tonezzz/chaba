FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    gnupg \
    unzip \
    build-essential \
    ffmpeg \
    tk \
    libnss3-dev \
    libatk-bridge2.0-dev \
    libdrm2 \
    libgl1 \
    libxkbcommon-dev \
    libxcomposite-dev \
    libxdamage-dev \
    libxrandr-dev \
    libgbm-dev \
    libxss-dev \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies first (for better layer caching)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PostgreSQL support
RUN pip install --no-cache-dir psycopg2-binary

# Clone and install AutoAgent
RUN pip install --no-cache-dir git+https://github.com/HKUDS/AutoAgent.git

RUN python - <<'PY'
import site
from pathlib import Path

p = Path(site.getsitepackages()[0]) / 'constant.py'
p.write_text(
    """import os

DEBUG = os.getenv(\"DEBUG\", \"0\").lower() in (\"1\", \"true\", \"yes\", \"y\", \"on\")

DEFAULT_LOG = os.getenv(\"DEFAULT_LOG\", \"INFO\")
LOG_PATH = os.getenv(\"LOG_PATH\", None)

MC_MODE = os.getenv(\"MC_MODE\", \"default\")
FN_CALL = os.getenv(\"FN_CALL\", \"fn_call\")
NON_FN_CALL = os.getenv(\"NON_FN_CALL\", \"non_fn_call\")

API_BASE_URL = os.getenv("API_BASE_URL", "")
# Use model without prefix (AutoAgent format) - LiteLLM will infer provider from API key
COMPLETION_MODEL = os.getenv("COMPLETION_MODEL", os.getenv("AUTOAGENT_COMPLETION_MODEL", "claude-3-5-sonnet-20241022"))
EMBEDDING_MODEL = os.getenv(\"EMBEDDING_MODEL\", os.getenv(\"AUTOAGENT_EMBEDDING_MODEL\", \"\"))

# API keys for provider inference
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

NOT_SUPPORT_SENDER = os.getenv(\"NOT_SUPPORT_SENDER\", \"not_support_sender\")
ADD_USER = os.getenv(\"ADD_USER\", \"add_user\")

DOCKER_WORKPLACE_NAME = os.getenv(\"DOCKER_WORKPLACE_NAME\", \"/workspace\")
LOCAL_ROOT = os.getenv(\"LOCAL_ROOT\", \"/workspace\")

GITHUB_AI_TOKEN = os.getenv(\"GITHUB_AI_TOKEN\", os.getenv(\"GITHUB_TOKEN\", \"\"))
AI_USER = os.getenv(\"AI_USER\", \"ai\")
BASE_IMAGES = os.getenv(\"BASE_IMAGES\", \"\")
""",
    encoding='utf-8',
)
PY

RUN python - <<'PY'
import site
from pathlib import Path

sp = Path(site.getsitepackages()[0])

# AutoAgent's CLI expects a top-level `loop_utils` module which isn't packaged
loop_utils = sp / 'loop_utils'
loop_utils.mkdir(parents=True, exist_ok=True)
(loop_utils / '__init__.py').write_text('', encoding='utf-8')
(loop_utils / 'font_page.py').write_text(
    """MC_LOGO = \"\"\"AutoAgent\\n\"\"\"\n\nGOODBYE_LOGO = \"\"\"Goodbye!\\n\"\"\"\n\nNOTES = \"\"\"\\
- This is a minimal compatibility shim.\\
\"\"\"\n\ndef version_table():\n    return \"AutoAgent (shim)\"\n""",
    encoding='utf-8',
)

# AutoAgent's CLI imports `evaluation.utils`, which also isn't packaged
evaluation = sp / 'evaluation'
evaluation.mkdir(parents=True, exist_ok=True)
(evaluation / '__init__.py').write_text('', encoding='utf-8')
(evaluation / 'utils.py').write_text(
    """def update_progress(*args, **kwargs):
    return None


def check_port_available(*args, **kwargs):
    return True


def run_evaluation(*args, **kwargs):
    return None


def clean_msg(msg, *args, **kwargs):
    return msg
""",
    encoding='utf-8',
)
PY

# Patch autoagent/cli.py: when --local_env True, skip get_config() which
# invokes `docker` (not present inside the container) and build DockerConfig directly.
# Also ensure the model retains its provider prefix (e.g., "anthropic/claude-3-5-sonnet-20241022")
RUN python - <<'PY'
import site, re
from pathlib import Path

cli = Path(site.getsitepackages()[0]) / 'autoagent' / 'cli.py'
src = cli.read_text(encoding='utf-8')

# Patch 1: Skip get_config when local_env
old1 = (
    "        progress.update(task, description=\"[cyan]Initializing config...[/cyan]\\n\")\n"
    "        docker_config = get_config(container_name, port)\n"
)
new1 = (
    "        progress.update(task, description=\"[cyan]Initializing config...[/cyan]\\n\")\n"
    "        if local_env:\n"
    "            import os as _os\n"
    "            from autoagent.environment.docker_env import DockerConfig as _DC\n"
    "            _local_root = _os.path.join(_os.getcwd(), \"workspace_meta_showcase\", f\"showcase_{container_name}\")\n"
    "            _os.makedirs(_local_root, exist_ok=True)\n"
    "            docker_config = _DC(\n"
    "                workplace_name=DOCKER_WORKPLACE_NAME,\n"
    "                container_name=container_name,\n"
    "                communication_port=port,\n"
    "                conda_path='/root/miniconda3',\n"
    "                local_root=_local_root,\n"
    "            )\n"
    "        else:\n"
    "            docker_config = get_config(container_name, port)\n"
)

if old1 in src:
    src = src.replace(old1, new1)
    print('cli.py patch 1 OK (skip get_config)')
else:
    print('WARNING: cli.py patch 1 target not found')

# Patch 2: Ensure model retains provider prefix
old2 = '    model = COMPLETION_MODEL'
new2 = '''    # Ensure model retains provider prefix for LiteLLM
    model = COMPLETION_MODEL
    # If model doesn't have a prefix but API_BASE_URL points to Anthropic, add it
    try:
        from constant import API_BASE_URL
        if "/" not in model and API_BASE_URL and "anthropic.com" in API_BASE_URL:
            model = f"anthropic/{model}"
    except:
        pass'''

if old2 in src:
    src = src.replace(old2, new2)
    print('cli.py patch 2 OK (preserve provider prefix)')
else:
    print('WARNING: cli.py patch 2 target not found')

cli.write_text(src, encoding='utf-8')
PY

# Patch autoagent/core.py: infer provider from API_BASE_URL and add prefix to model for LiteLLM
RUN python - <<'PY'
import site
from pathlib import Path

core = Path(site.getsitepackages()[0]) / 'autoagent' / 'core.py'
src = core.read_text(encoding='utf-8')

# Helper function to add provider logic
def add_provider_logic(code):
    return '''            # Infer provider from API_BASE_URL and add prefix to model for LiteLLM
            custom_llm_provider = None
            print(f"[DEBUG] API_BASE_URL: {API_BASE_URL}")
            if API_BASE_URL:
                if "anthropic.com" in API_BASE_URL:
                    custom_llm_provider = "anthropic"
                elif "openai.com" in API_BASE_URL:
                    custom_llm_provider = "openai"
                # For Gemini (Google AI Studio), don't set custom_llm_provider
                # LiteLLM will auto-detect from the "gemini/" model prefix
                elif "openrouter.ai" in API_BASE_URL:
                    custom_llm_provider = "openrouter"
            print(f"[DEBUG] custom_llm_provider: {custom_llm_provider}")
            print(f"[DEBUG] create_model before: {create_model}")
            
            # For Anthropic native API, strip the provider prefix - they expect just the model name
            if custom_llm_provider == "anthropic" and "/" in create_model:
                create_model = create_model.split("/")[-1]
            # For OpenRouter, keep the full model path (e.g., anthropic/claude-3.5-sonnet)
            # but ensure it has the provider prefix format
            print(f"[DEBUG] create_model after: {create_model}")
            
''' + code

# Patch 1: FN_CALL path (around line 151)
old1 = '''            create_params = {
                "model": create_model,
                "messages": messages,
                "tools": tools or None,
                "tool_choice": agent.tool_choice,
                "stream": stream,
            }'''
new1 = add_provider_logic('''            create_params = {
                "model": create_model,
                "messages": messages,
                "tools": tools or None,
                "tool_choice": agent.tool_choice,
                "stream": stream,
            }
            if custom_llm_provider:
                create_params["custom_llm_provider"] = custom_llm_provider
                # Add API key for OpenRouter
                if custom_llm_provider == "openrouter":
                    from constant import OPENROUTER_API_KEY
                    if OPENROUTER_API_KEY:
                        create_params["api_key"] = OPENROUTER_API_KEY
                # Add API key for Gemini
                if custom_llm_provider == "gemini":
                    from constant import GEMINI_API_KEY
                    if GEMINI_API_KEY:
                        create_params["api_key"] = GEMINI_API_KEY''')

# Patch 2: NON_FN_CALL path (around line 209)
old2 = '''            create_params = {
                "model": create_model,
                "messages": messages,
                "stream": stream,
                "base_url": API_BASE_URL,
            }'''
new2 = add_provider_logic('''            create_params = {
                "model": create_model,
                "messages": messages,
                "stream": stream,
                "base_url": API_BASE_URL,
            }
            if custom_llm_provider:
                create_params["custom_llm_provider"] = custom_llm_provider
                # Add API key for OpenRouter
                if custom_llm_provider == "openrouter":
                    from constant import OPENROUTER_API_KEY
                    if OPENROUTER_API_KEY:
                        create_params["api_key"] = OPENROUTER_API_KEY
                # Add API key for Gemini
                if custom_llm_provider == "gemini":
                    from constant import GEMINI_API_KEY
                    if GEMINI_API_KEY:
                        create_params["api_key"] = GEMINI_API_KEY''')

patched = 0
if old1 in src:
    src = src.replace(old1, new1)
    patched += 1
    print('core.py FN_CALL path patched OK')
else:
    print('WARNING: FN_CALL patch target not found')

if old2 in src:
    src = src.replace(old2, new2)
    patched += 1
    print('core.py NON_FN_CALL path patched OK')
else:
    print('WARNING: NON_FN_CALL patch target not found')

if patched > 0:
    core.write_text(src, encoding='utf-8')
else:
    print('ERROR: No patches applied')
PY

# Install Playwright Chromium browser (without extra deps first - system deps already installed above)
RUN playwright install chromium

# Install GhostRoute discovery tools
COPY discovery/ghostroute/*.py /app/
COPY discovery/ghostroute/*.sh /app/
RUN chmod +x /app/*.sh

# Create workspace directory
RUN mkdir -p /workspace && \
    chmod 777 /workspace

# Create entrypoint script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Function to check if container is running interactively\n\
if [ -t 0 ]; then\n\
    echo "AutoAgent Interactive Mode"\n\
    echo "Available commands:"\n\
    echo "  auto main              - Start full AutoAgent (user mode, agent editor, workflow editor)"\n\
    echo "  auto deep-research     - Start deep research mode only"\n\
    echo "  auto agent --help      - Show agent command options"\n\
    echo "  auto workflow --help   - Show workflow command options"\n\
    echo ""\n\
    # Start bash shell for interactive use\n\
    exec /bin/bash\n\
else\n\
    echo "AutoAgent running in non-interactive mode"\n\
    echo "Use docker exec -it autoagent-test bash to enter container"\n\
    # Keep container running\n\
    tail -f /dev/null\n\
fi' > /entrypoint.sh && \
chmod +x /entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Expose port (for potential web interface)
EXPOSE 8080

# Default command
CMD ["/bin/bash"]
