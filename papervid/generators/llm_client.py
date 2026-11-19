"""llama.cpp / OpenAI-compatible API client for text and vision models."""

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Compact system prompt to reduce token count
SCRIPT_SYSTEM_PROMPT = (
    "You are an expert science communicator creating 3Blue1Brown-style animated video scripts. "
    "Convert paper sections into structured animation scenes with narration and visuals.\n\n"
    "Rules:\n"
    "- Narration: clear, natural pace, ~150 words/min\n"
    "- Visuals: geometric shapes, diagrams, formulas, smooth transitions\n"
    "- Scenes: 8-20 seconds each\n"
    "- Math: proper LaTeX via MathTex\n"
    "- Tone: educational, insightful\n\n"
    "Return ONLY valid JSON array matching this schema:\n"
    "[\n"
    '  {"scene_id": 1, "title": "Visual description", "narration": "Spoken words here",\n'
    '   "visual_type": "formula_animation|diagram_zoom|chart_build|slide_transition|concept_visual|intro_title",\n'
    '   "manim_elements": ["Circle()", "MathTex(r\'E=mc^2\')", "Line()"],\n'
    '   "transition_from": "fade_in|slide_up|transform|grow_from_center",\n'
    '   "transition_to": "fade_out|slide_down|transform|shrink_to_center",\n'
    '   "duration_seconds": 10.5}\n'
    "]"
)

VISION_SYSTEM_PROMPT = (
    "You are an expert analyzing scientific paper figures.\n\n"
    "Describe:\n"
    "1. Visualization type\n"
    "2. Key elements\n"
    "3. How to animate in Manim (shapes, lines, labels)\n"
    "4. Main takeaway\n"
)


class LlamaCppClient:
    """Client for llama.cpp and OpenAI-compatible APIs.

    Auto-detects API type and uses optimal request format.
    Supports streaming for long responses.
    """

    DEFAULT_PORT = 8080
    DEFAULT_TIMEOUT = 600  # seconds

    def __init__(self, base_url: str = None, model: str = None, timeout: int = None):
        """Initialize client.

        Args:
            base_url: API URL (e.g., http://localhost:8080, https://chat.genx32.com/completion)
            model: Model name (e.g., "llama3.2", "gpt-4o")
            timeout: Request timeout in seconds (default: 600)
        """
        if base_url is None:
            import os
            base_url = os.environ.get("LLAMA_CPP_URL", f"http://localhost:{self.DEFAULT_PORT}")

        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._api_type = None  # cached: "openai" or "llamacpp"

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        logger.info(f"LlamaCppClient: url={self.base_url}, model={model}, timeout={self.timeout}s")

    # ------------------------------------------------------------------ #
    #  API Detection                                                      #
    # ------------------------------------------------------------------ #

    def _detect_api_type(self) -> str:
        """Detect whether the endpoint is OpenAI-compatible or raw llama.cpp."""
        if self._api_type:
            return self._api_type

        # 1. URL already has explicit patterns
        if "/v1" in self.base_url:
            self._api_type = "openai"
        elif self.base_url.endswith(("/completion", "/chat")):
            self._api_type = "openai"
        # 2. Remote URL defaults to OpenAI
        elif "http" in self.base_url and str(self.DEFAULT_PORT) not in self.base_url:
            self._api_type = "openai"
        else:
            self._api_type = "llamacpp"

        logger.info(f"Detected API type: {self._api_type}")
        return self._api_type

    def _get_chat_endpoint(self) -> str:
        """Get the correct chat endpoint."""
        if self._detect_api_type() == "openai":
            if self.base_url.endswith(("/completion", "/chat")):
                return self.base_url
            if "/v1" in self.base_url:
                return f"{self.base_url}/chat/completions"
            return f"{self.base_url}/v1/chat/completions"
        return f"{self.base_url}/completion"

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def check_available(self) -> bool:
        """Check if the API server is reachable."""
        try:
            if self._detect_api_type() == "openai":
                try:
                    resp = self.session.get(
                        f"{self.base_url}/v1/models", timeout=10
                    )
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass
                # Try a minimal chat request
                payload = {
                    "model": self.get_model_name() or "test",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                }
                resp = self.session.post(
                    self._get_chat_endpoint(), json=payload, timeout=self.timeout
                )
                return resp.status_code == 200
            else:
                resp = self.session.post(
                    f"{self.base_url}/completion",
                    json={"prompt": "test", "n_predict": 1, "stream": False},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.debug(f"Availability check failed: {e}")
            return False

    def get_model_name(self) -> str:
        return self.model_name or "llama3.2"

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        stream: bool = True,  # default to streaming for reliability
        n_predict: int = 4096,
    ) -> str:
        """Send a chat request with auto-retry.

        Args:
            messages: Message list with 'role' and 'content'.
            model: Override default model.
            stream: Use streaming mode (recommended for long responses).
            n_predict: Max tokens (llama.cpp only).

        Returns:
            Response text.
        """
        api_type = self._detect_api_type()
        model = model or self.get_model_name()

        logger.info(f"Chat: type={api_type}, model={model}, stream={stream}")

        for attempt in range(3):
            try:
                if api_type == "openai":
                    result = self._chat_openai(messages, model, stream)
                else:
                    result = self._chat_llamacpp(messages, model, stream, n_predict)

                if result:
                    return result

            except Exception as e:
                logger.warning(
                    f"Request attempt {attempt + 1}/3 failed: {e}"
                )
                if attempt < 2:
                    time.sleep(2 ** attempt)  # exponential backoff

        logger.error("All 3 attempts failed for chat request")
        return ""

    def analyze_page(
        self, image_path: Path, prompt: str, model: Optional[str] = None
    ) -> str:
        """Analyze a PDF page image."""
        model = model or self.get_model_name()
        image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        messages = [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_data}"},
                    },
                ],
            },
        ]

        return self.chat(messages, model=model)

    def generate_script_for_section(
        self, section: dict, paper_info: dict, model: Optional[str] = None,
        max_tokens: int = 8192,
    ) -> str:
        """Generate animation script for one paper section.

        Uses compact prompt with truncated content to avoid timeouts.
        """
        # Safely extract fields
        title = str(paper_info.get("title") or "Unknown Paper")
        authors = paper_info.get("authors") or []
        authors_str = ", ".join(str(a) for a in authors[:3]) or "Unknown"
        abstract = str(paper_info.get("abstract") or "")[:500]
        section_name = str(section.get("name") or "Unknown Section")
        section_text = str(section.get("text") or "")
        page_numbers = section.get("page_numbers") or []

        # Very aggressive truncation — just the first paragraph of each section
        # This keeps prompt under ~300 words so the model has room to output JSON
        sentences = section_text.split(". ")
        text = ". ".join(sentences[:8]) + "."  # first ~8 sentences (~150 words)

        user_content = (
            f"Paper: {title}\n"
            f"Authors: {authors_str}\n"
            f"Abstract: {abstract[:200]}\n\n"
            f"Section: **{section_name}**\n"
            f"Content ({len(section_text.split())} words total, showing first 8 sentences):\n"
            f"{text}\n\n"
            f"Reference pages: {page_numbers}\n\n"
            f"Return ONLY a JSON array of scenes."
        )

        messages = [
            {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # Override max_tokens for this request — script JSON needs lots of room
        api_type = self._detect_api_type()
        if api_type == "openai":
            # Patch the chat method temporarily
            return self._chat_openai_with_tokens(messages, model, max_tokens=max_tokens)
        else:
            return self._chat_llamacpp_with_tokens(messages, model, n_predict=max_tokens)

    def _chat_openai_with_tokens(
        self, messages: list[dict], model: Optional[str], max_tokens: int = 8192
    ) -> str:
        """Send OpenAI chat request with custom max_tokens."""
        url = self._get_chat_endpoint()
        model = model or self.get_model_name()
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        return self._stream_openai(url, payload)

    def _chat_llamacpp_with_tokens(
        self, messages: list[dict], model: Optional[str], n_predict: int = 8192
    ) -> str:
        """Send llama.cpp chat request with custom n_predict."""
        url = f"{self.base_url}/completion"
        prompt = self._format_messages_to_prompt(messages)
        model = model or self.get_model_name()
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "n_predict": n_predict,
            "temperature": 0.3,
            "stop": ["</s>", "<|eot_id|>", "<|end_of_text|>"],
        }
        return self._stream_llamacpp(url, payload)

    # ------------------------------------------------------------------ #
    #  OpenAI-Compatible Requests                                         #
    # ------------------------------------------------------------------ #

    def _chat_openai(
        self, messages: list[dict], model: str, stream: bool
    ) -> str:
        url = self._get_chat_endpoint()
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": 0.5,
            "max_tokens": 4096,
        }

        if stream:
            return self._stream_openai(url, payload)
        else:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message") or {}
            return (content.get("content") or "").strip()

    def _stream_openai(self, url: str, payload: dict) -> str:
        full_response = ""
        resp = self.session.post(url, json=payload, stream=True, timeout=self.timeout * 5)

        for line in resp.iter_lines():
            if line:
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices")
                        if not choices:
                            continue
                        delta = choices[0].get("delta")
                        if not delta:
                            continue
                        token = delta.get("content") or ""
                        if not isinstance(token, str):
                            token = ""
                        full_response += token
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue

        return full_response.strip()

    # ------------------------------------------------------------------ #
    #  Raw llama.cpp Requests                                             #
    # ------------------------------------------------------------------ #

    def _chat_llamacpp(
        self, messages: list[dict], model: str, stream: bool, n_predict: int
    ) -> str:
        url = f"{self.base_url}/completion"
        prompt = self._format_messages_to_prompt(messages)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "n_predict": n_predict,
            "temperature": 0.5,
            "stop": ["</s>", "<|eot_id|>", "<|end_of_text|>"],
        }

        if stream:
            return self._stream_llamacpp(url, payload)
        else:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return (resp.json().get("content") or "").strip()

    def _stream_llamacpp(self, url: str, payload: dict) -> str:
        full_response = ""
        resp = self.session.post(url, json=payload, stream=True, timeout=self.timeout * 5)

        for line in resp.iter_lines():
            if line:
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        content = chunk.get("content") or ""
                        if not isinstance(content, str):
                            content = ""
                        full_response += content
                    except (json.JSONDecodeError, TypeError):
                        continue

        return full_response

    def _format_messages_to_prompt(self, messages: list[dict]) -> str:
        """Convert messages to llama.cpp prompt format."""
        parts = []
        for msg in messages:
            role = msg.get("role") or "user"
            content = msg.get("content") or ""
            if not isinstance(content, str):
                content = ""
            header = f"<|start_header_id|>{role}<|end_header_id|>\n\n"
            parts.append(header + content + "<|eot_id|>")
        parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "".join(parts)

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
