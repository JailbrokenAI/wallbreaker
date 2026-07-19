from __future__ import annotations

import base64
import binascii
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from ..agent.messages import Message, StopEvent, StreamEvent, TextDelta
from ..config import Endpoint
from .base import Provider, ProviderError
from .request_gate import gated_request
from .openai_provider import _messages_to_wire

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


@dataclass
class ImageResult:
    """One image-generation turn: decoded images plus any accompanying text."""

    images: list[tuple[str, bytes]] = field(default_factory=list)  # (mime, raw bytes)
    data_urls: list[str] = field(default_factory=list)  # original data: URLs (for the vision judge)
    text: str = ""  # any prose / refusal the model returned alongside (or instead of) images
    reasoning: str = ""  # the model's reasoning/CoT, if exposed

    @property
    def refused(self) -> bool:
        return not self.images

    def ext_for(self, index: int) -> str:
        mime = self.images[index][0] if index < len(self.images) else "image/png"
        return _MIME_EXT.get(mime, "png")


def ext_for_mime(mime: str) -> str:
    return _MIME_EXT.get(mime, "png")


def _decode_data_url(url: str) -> tuple[str, bytes] | None:
    """Decode a data: URL or a bare base64 blob into (mime, bytes)."""
    mime = "image/png"
    payload = url
    if url.startswith("data:"):
        head, _, payload = url.partition(",")
        if ";" in head:
            mime = head[5:].split(";", 1)[0] or mime
    try:
        return mime, base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


def _extract_images(data: dict) -> tuple[list[tuple[str, bytes]], list[str], str]:
    """Pull generated images out of an OpenRouter response, whichever shape it uses.

    Two shapes seen in the wild:
      - chat-completions: choices[].message.images[].image_url.url  (data: URLs)
      - images endpoint:  data[].b64_json                           (bare base64)
    """
    images: list[tuple[str, bytes]] = []
    data_urls: list[str] = []
    texts: list[str] = []

    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content:
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    texts.append(str(part["text"]))
        for img in message.get("images") or []:
            url = ""
            if isinstance(img, dict):
                url = (img.get("image_url") or {}).get("url", "") if isinstance(img.get("image_url"), dict) else img.get("url", "")
            elif isinstance(img, str):
                url = img
            if not url:
                continue
            decoded = _decode_data_url(url)
            if decoded:
                images.append(decoded)
                data_urls.append(url if url.startswith("data:") else f"data:{decoded[0]};base64,{url}")

    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json") or item.get("image")
        if b64:
            decoded = _decode_data_url(b64)
            if decoded:
                images.append(decoded)
                data_urls.append(f"data:{decoded[0]};base64,{b64}")
        elif item.get("url"):
            data_urls.append(str(item["url"]))

    return images, data_urls, "\n".join(t for t in texts if t).strip()


def _extract_reasoning(data: dict) -> str:
    parts: list[str] = []
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            parts.append(reasoning)
        for det in message.get("reasoning_details") or []:
            if isinstance(det, dict) and det.get("text"):
                parts.append(str(det["text"]))
    return "\n".join(parts).strip()


class OpenRouterImageProvider(Provider):
    """Targets an OpenRouter image-generation model through the chat-completions API.

    Image models answer the same /chat/completions endpoint but need
    `modalities: ["image", "text"]`; the picture comes back base64-encoded in
    `choices[0].message.images[].image_url.url`. We run non-streaming because the
    payload is one big blob, then hand the bytes to query_image_target to save + grade.
    """

    supports_native_prefill = False

    def _payload(self, wire_messages: list[dict], max_tokens: int) -> dict:
        payload: dict = {
            "model": self.endpoint.model,
            "messages": wire_messages,
            "modalities": ["image", "text"],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if getattr(self.endpoint, "reasoning", False):
            payload["reasoning"] = {"enabled": True}
        if getattr(self.endpoint, "provider", ()):
            payload["provider"] = {
                "order": list(self.endpoint.provider),
                "allow_fallbacks": False,
            }
        return payload

    async def _post_chat(self, payload: dict) -> dict:
        from ..session import trace_inference_request, trace_inference_response

        path = getattr(self.endpoint, "inference_path", "") or "/chat/completions"
        url = f"{self.endpoint.base_url}{path if path.startswith('/') else '/' + path}"
        headers = {
            "Authorization": f"Bearer {self.endpoint.require_key()}",
            "Content-Type": "application/json",
        }
        inference_id = trace_inference_request(
            self.endpoint,
            payload.get("messages") or [],
            operation="image_generation",
            **{key: value for key, value in payload.items() if key != "messages"},
        )
        started = time.monotonic()
        try:
            async def send():
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=True
                ) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        raise ProviderError(
                            f"HTTP {resp.status_code} from {url}: {resp.text[:400]}"
                        )
                    return resp.json(), resp.status_code

            data, http_status = await gated_request(self.endpoint, send)
            from ..model_catalog import record_model_success

            record_model_success(self.endpoint)
            trace_inference_response(
                inference_id,
                status="ok",
                raw_response=data,
                http_status=http_status,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
            )
            return data
        except Exception as exc:
            trace_inference_response(
                inference_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.monotonic() - started) * 1000, 3),
            )
            if isinstance(exc, httpx.HTTPError):
                raise ProviderError(f"network error from {url}: {exc!r}") from exc
            raise

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ImageResult:
        if not system:
            system = str(getattr(self.endpoint, "system_prompt", "") or "") or None
        data = await self._post_chat(
            self._payload(_messages_to_wire(messages, system), max_tokens)
        )
        images, data_urls, text = _extract_images(data)
        return ImageResult(
            images=images, data_urls=data_urls, text=text,
            reasoning=_extract_reasoning(data),
        )

    async def generate_edit(
        self,
        turns: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ImageResult:
        """Image-EDIT / conditioning path: send multimodal turns (text + input images).

        The core Message/Block types are text-only, so a text->image *edit* (supply an
        input image, ask the model to modify it) can't ride `_messages_to_wire`. Each
        `turns` item is `{"role": "user"|"assistant", "text": str, "images": [data_url,...]}`;
        user turns carry the working/reference image(s) as `image_url` content parts, exactly
        like the vision judge does. This is the black-box surface for Chain-of-Jailbreak /
        Semantic-Chaining edit ladders where the harm accumulates across benign edit turns.
        """
        if not system:
            system = str(getattr(self.endpoint, "system_prompt", "") or "") or None
        wire = _edit_wire(turns, system)
        data = await self._post_chat(self._payload(wire, max_tokens))
        images, data_urls, text = _extract_images(data)
        return ImageResult(
            images=images, data_urls=data_urls, text=text,
            reasoning=_extract_reasoning(data),
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        result = await self.generate(messages, system=system, max_tokens=max_tokens)
        summary = result.text or ""
        if result.images:
            note = f"[{len(result.images)} image(s) generated]"
            summary = f"{note}\n{summary}".strip()
        elif not summary:
            summary = "[no image and no text returned]"
        yield TextDelta(summary)
        yield StopEvent("end_turn")


def _edit_wire(turns: list[dict], system: str | None = None) -> list[dict]:
    """Build a multimodal chat body from edit turns (text + optional input images).

    User turns render as `content:[{type:text},{type:image_url}...]`; assistant turns
    stay text-only (a placeholder like '[image produced]') so the running edit chain keeps
    genuine multi-turn structure while the current canvas rides the latest user turn.
    """
    wire: list[dict] = []
    if system:
        wire.append({"role": "system", "content": system})
    for turn in turns:
        role = turn.get("role", "user")
        text = str(turn.get("text", ""))
        images = turn.get("images") or []
        if role == "user" and images:
            content: list[dict] = [{"type": "text", "text": text}]
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})
            wire.append({"role": role, "content": content})
        else:
            wire.append({"role": role, "content": text})
    return wire


def _vision_wire(text: str, image_urls: list[str]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


async def vision_complete(
    endpoint: Endpoint,
    text: str,
    image_urls: list[str],
    system: str | None = None,
    max_tokens: int = 512,
    timeout: float = 120.0,
) -> str:
    """Send text + image(s) to a vision-capable OpenAI-protocol model, return its text.

    The core message types are text-only, so the multimodal body is built here instead
    of widening Message/Block. Used by the image judge to look at a generated picture.
    """
    path = getattr(endpoint, "inference_path", "") or "/chat/completions"
    url = f"{endpoint.base_url}{path if path.startswith('/') else '/' + path}"
    headers = {
        "Authorization": f"Bearer {endpoint.require_key()}",
        "Content-Type": "application/json",
    }
    messages = _vision_wire(text, image_urls)
    if system:
        messages.insert(0, {"role": "system", "content": system})
    payload = {
        "model": endpoint.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    from ..session import trace_inference_request, trace_inference_response

    inference_id = trace_inference_request(
        endpoint,
        messages,
        operation="vision_completion",
        max_tokens=max_tokens,
        stream=False,
    )
    started = time.monotonic()
    try:
        async def send():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    raise ProviderError(
                        f"HTTP {resp.status_code} from {url}: {resp.text[:400]}"
                    )
                # Return the status alongside the parsed body: `resp` is local to this
                # nested coroutine, so the outer scope cannot reference it (was a NameError
                # on every successful call). Mirrors `_post_chat`'s (json, status) shape.
                return resp.json(), resp.status_code

        data, http_status = await gated_request(endpoint, send)
    except Exception as exc:
        trace_inference_response(
            inference_id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=round((time.monotonic() - started) * 1000, 3),
        )
        if isinstance(exc, httpx.HTTPError):
            raise ProviderError(f"network error from {url}: {exc!r}") from exc
        raise
    choices = data.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content", "")
        if isinstance(content, list):
            answer = "".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict)
            ).strip()
        else:
            answer = str(content or "").strip()
    else:
        answer = ""
    if answer:
        from ..model_catalog import record_model_success

        record_model_success(endpoint)
    trace_inference_response(
        inference_id,
        status="ok",
        text=answer,
        raw_response=data,
        http_status=http_status,
        duration_ms=round((time.monotonic() - started) * 1000, 3),
    )
    return answer
