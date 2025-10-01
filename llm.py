"""LLM Client Module - OpenAI API Integration with Token Counting"""

import base64
import hashlib
import logging
import os
import random
from typing import Dict, List, Optional, Tuple

import httpx
import tiktoken
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# OpenAI Pricing Constants (per 1M tokens) for gpt-5-chat-latest
PRICE_INPUT = 0.00125  # $0.00125 per 1M input tokens
PRICE_CACHED = 0.00013  # $0.00013 per 1M cached tokens
PRICE_OUTPUT = 0.01  # $0.01 per 1M output tokens

# Image token calculation constants
IMAGE_BASE_TOKENS = 70  # Base tokens per image
IMAGE_TILE_TOKENS = 140  # Tokens per tile in high detail


class AlinaLLM:
    """OpenAI API client with automatic token counting and cost tracking"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-chat-latest",
        use_proxy: bool = True,
        proxy_url: Optional[str] = None
    ):
        """Initialize OpenAI client with optional proxy support
        
        Args:
            api_key: OpenAI API key
            model: Model name to use
            use_proxy: Whether to use HTTP proxy
            proxy_url: Proxy URL (required if use_proxy=True)
        """
        if not api_key:
            raise ValueError("API key is required")
        if use_proxy and not proxy_url:
            raise ValueError("Proxy URL is required when use_proxy=True")
        
        self.api_key = api_key
        self.model = model
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        self._encoder = None  # Cached tokenizer
    
    async def _create_client(self) -> AsyncOpenAI:
        """Create async OpenAI client with optional proxy configuration"""
        http_client = None
        
        if self.use_proxy:
            http_client = httpx.AsyncClient(
                proxy=self.proxy_url,
                timeout=httpx.Timeout(60.0, connect=20.0)
            )
        
        # Build client kwargs
        kwargs = {"api_key": self.api_key, "http_client": http_client}
        if self.base_url:
            kwargs["base_url"] = self.base_url.rstrip("/")
        
        return AsyncOpenAI(**kwargs)
    
    def _get_encoder(self):
        """Get or create tokenizer for the model"""
        if self._encoder is None:
            try:
                self._encoder = tiktoken.encoding_for_model(self.model)
            except Exception:
                # Fallback to cl100k_base encoding
                self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder
    
    def count_tokens_text(self, text: str) -> int:
        """Count tokens in plain text string
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens
        """
        return len(self._get_encoder().encode(text or ""))
    
    def count_tokens_messages(self, messages: List[Dict]) -> int:
        """Count tokens in chat messages including images using ChatML format
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Total number of tokens
        """
        enc = self._get_encoder()
        total = 0
        
        # ChatML format adds 3 tokens per message
        tokens_per_message = 3
        
        for message in messages:
            total += tokens_per_message
            
            content = message.get("content")
            
            # Handle string content (simple text message)
            if isinstance(content, str):
                total += len(enc.encode(content or ""))
            
            # Handle array content (text + images)
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        total += len(enc.encode(item.get("text") or ""))
                    elif item.get("type") == "image_url":
                        # Count tokens for image
                        image_url_obj = item.get("image_url", {})
                        if isinstance(image_url_obj, dict):
                            total += self._calculate_image_tokens(image_url_obj.get("url", ""))
                        else:
                            total += self._calculate_image_tokens(image_url_obj)
        
        # Assistant reply overhead
        total += 3
        return total
    
    def _calculate_image_tokens(self, image_url: str) -> int:
        """Calculate approximate token count for an image
        
        For gpt-5-chat-latest: base=70 tokens + tiles*140 tokens
        Returns average estimate (~490 tokens) as exact calculation requires image dimensions
        
        Args:
            image_url: Image URL or data URI
            
        Returns:
            Approximate token count for the image
        """
        # Simplified estimation: base + a few tiles
        # Most images will be 300-800 tokens
        return IMAGE_BASE_TOKENS + (IMAGE_TILE_TOKENS * 3)  # ~490 tokens
    
    def _get_generation_params(self, context: Optional[Dict] = None) -> Dict:
        """Generate dynamic parameters for text generation with slight randomness
        
        Args:
            context: Optional context dictionary with hints
            
        Returns:
            Dictionary of generation parameters
        """
        # Base temperature with small random variation
        base_temp = 0.85 + random.uniform(-0.05, 0.1)
        
        # Adjust based on context hints
        if context:
            if context.get("is_emotional"):
                base_temp = min(0.95, base_temp + 0.05)
            elif context.get("conversation_length", 0) > 20:
                base_temp = min(0.9, base_temp + 0.03)
        
        return {
            "temperature": base_temp,
            "top_p": 0.95,
            "frequency_penalty": 0.3 + random.uniform(0, 0.2),
            "presence_penalty": 0.3 + random.uniform(0, 0.2),
        }
    
    async def generate_response(
        self,
        messages: List[Dict],
        context: Optional[Dict] = None
    ) -> Tuple[str, int]:
        """Generate AI response from OpenAI API with prompt caching
        
        Args:
            messages: List of message dictionaries (ChatML format)
            context: Optional context for parameter adjustment
            
        Returns:
            Tuple of (response_text, total_tokens_used)
        """
        params = self._get_generation_params(context)
        client = None
        
        try:
            client = await self._create_client()
            
            # Count input tokens for estimation
            input_tokens = self.count_tokens_messages(messages)
            
            # Make API call
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **params
            )
            
            # Extract response text
            response_text = (response.choices[0].message.content or "").strip()
            output_tokens = self.count_tokens_text(response_text)
            total_tokens = input_tokens + output_tokens
            
            # Log detailed usage statistics with cached tokens
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                
                # Get cached tokens info (available in prompt_tokens_details)
                cached = 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0)
                
                # Calculate costs
                net_input = input_tokens - cached
                cost_input = net_input * PRICE_INPUT / 1_000_000
                cost_cached = cached * PRICE_CACHED / 1_000_000
                cost_output = output_tokens * PRICE_OUTPUT / 1_000_000
                cost_total = cost_input + cost_cached + cost_output
                
                logger.info(
                    f"Tokens: in={input_tokens} (cached={cached}), out={output_tokens}, "
                    f"total={total_tokens} | Cost: ${cost_total:.6f}"
                )
            
            return response_text, total_tokens
            
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            return "ой, кажется, я зависла. повторишь ещё раз?", 0
        finally:
            if client:
                await client.close()


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string
    
    Args:
        image_bytes: Raw image data
        
    Returns:
        Base64-encoded string
    """
    return base64.b64encode(image_bytes).decode('utf-8')


def get_image_hash(image_bytes: bytes) -> str:
    """Calculate SHA256 hash of image for duplicate detection
    
    Args:
        image_bytes: Raw image data
        
    Returns:
        Hex string of SHA256 hash
    """
    return hashlib.sha256(image_bytes).hexdigest()


def create_image_message(
    image_bytes: bytes,
    text: str = "",
    is_duplicate: bool = False,
    mime_type: str = "image/jpeg",
    detail: str = "auto"
) -> Dict:
    """Create a message with image content in OpenAI Chat Completions format
    
    Args:
        image_bytes: Raw image data
        text: Optional text prompt/caption from user
        is_duplicate: Whether this image was recently sent before
        mime_type: Image MIME type (e.g., "image/jpeg", "image/png")
        detail: OpenAI detail level ("low", "high", "auto")
        
    Returns:
        Message dictionary in OpenAI format
    """
    base64_image = encode_image_to_base64(image_bytes)
    
    # Adjust text based on duplicate status
    if is_duplicate:
        if text:
            final_text = f"{text}\n\n(кстати, ты уже отправлял эту картинку недавно)"
        else:
            final_text = "(эту картинку ты уже отправлял недавно)"
    else:
        if text:
            final_text = text
        else:
            # Gentle instruction that doesn't override system prompt
            final_text = "(отреагируй живо и естественно, 2-3 предложениями. можешь поделиться мыслями, спросить что-то или высказать мнение)"
    
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": final_text
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_image}",
                    "detail": detail
                }
            }
        ]
    }
