# advanced_llm.py - Продвинутый LLM клиент с функциями и MCP
"""
Использует продвинутые возможности OpenAI API:
- Function calling для структурированных действий
- Streaming для естественного взаимодействия
- Structured outputs через JSON schemas
- Интеграция с MCP серверами
"""

import asyncio
import json
import random
from typing import List, Dict, Optional, AsyncGenerator, Any
from datetime import datetime
import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PYDANTIC МОДЕЛИ ДЛЯ STRUCTURED OUTPUTS
# ============================================================================

class EmotionalState(BaseModel):
    """Эмоциональное состояние пользователя."""
    primary_emotion: str = Field(description="Основная эмоция: joy, sadness, anger, fear, surprise, neutral")
    intensity: float = Field(description="Интенсивность эмоции от 0 до 1")
    triggers: List[str] = Field(description="Что вызвало эмоцию")
    suggested_response: str = Field(description="Рекомендуемый тон ответа")


class UserIntent(BaseModel):
    """Намерение пользователя."""
    primary_intent: str = Field(description="Основное намерение: question, statement, request, emotional_support, small_talk")
    topics: List[str] = Field(description="Темы в сообщении")
    urgency: float = Field(description="Срочность от 0 до 1")
    requires_action: bool = Field(description="Требуется ли действие")


class MemoryUpdate(BaseModel):
    """Обновление памяти о пользователе."""
    key: str = Field(description="Ключ памяти (например: 'любимый_цвет', 'имя_питомца')")
    value: str = Field(description="Значение для запоминания")
    importance: float = Field(description="Важность от 0 до 1")
    context: str = Field(description="Контекст, в котором это было упомянуто")


# ============================================================================
# ФУНКЦИИ ДЛЯ FUNCTION CALLING
# ============================================================================

class AlenaFunctions:
    """Функции, которые Алина может вызывать через function calling."""
    
    @staticmethod
    def get_function_schemas() -> List[Dict]:
        """Возвращает схемы функций для OpenAI API."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "remember_user_info",
                    "description": "Запомнить информацию о пользователе",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Что запоминаем (имя, работа, хобби и т.д.)"
                            },
                            "value": {
                                "type": "string",
                                "description": "Информация для запоминания"
                            },
                            "importance": {
                                "type": "number",
                                "description": "Важность от 0 до 1"
                            }
                        },
                        "required": ["key", "value", "importance"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_current_time",
                    "description": "Узнать текущее время и день недели",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_mood",
                    "description": "Проанализировать настроение пользователя",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Сообщение для анализа"
                            }
                        },
                        "required": ["message"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_random_cat_fact",
                    "description": "Получить случайный факт о котах (когда нужно поднять настроение)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
        ]
    
    @staticmethod
    async def execute_function(name: str, arguments: Dict) -> str:
        """Выполняет функцию и возвращает результат."""
        
        if name == "remember_user_info":
            # В реальности здесь было бы сохранение в БД
            return f"Запомнила: {arguments['key']} = {arguments['value']}"
        
        elif name == "check_current_time":
            now = datetime.now()
            weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
            return f"Сейчас {now.strftime('%H:%M')}, {weekdays[now.weekday()]}"
        
        elif name == "analyze_mood":
            # Простой анализ настроения
            message = arguments["message"].lower()
            if any(word in message for word in ["грустно", "плохо", "устал", "одиноко"]):
                return "Настроение: грустное, нужна поддержка"
            elif any(word in message for word in ["радость", "круто", "супер", "ура"]):
                return "Настроение: радостное, можно разделить радость"
            else:
                return "Настроение: нейтральное"
        
        elif name == "get_random_cat_fact":
            facts = [
                "Коты спят 70% своей жизни",
                "У котов 32 мышцы в каждом ухе",
                "Коты не чувствуют сладкий вкус",
                "Нос кота уникален, как отпечаток пальца человека"
            ]
            return random.choice(facts)
        
        return "Функция выполнена"


# ============================================================================
# MCP ИНТЕГРАЦИЯ
# ============================================================================

class MCPConnector:
    """Коннектор для MCP серверов."""
    
    def __init__(self):
        self.servers = {}
        self.active_connections = {}
    
    async def connect_server(self, server_name: str, server_url: str):
        """Подключается к MCP серверу."""
        try:
            # Здесь была бы реальная логика подключения к MCP
            # Для примера - эмулируем подключение
            self.servers[server_name] = {
                "url": server_url,
                "status": "connected",
                "capabilities": self._get_server_capabilities(server_name)
            }
            logger.info(f"Connected to MCP server: {server_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {server_name}: {e}")
            return False
    
    def _get_server_capabilities(self, server_name: str) -> List[str]:
        """Возвращает возможности сервера."""
        capabilities = {
            "filesystem": ["read_file", "write_file", "list_directory"],
            "memory": ["store_memory", "retrieve_memory", "search_memories"],
            "weather": ["get_current_weather", "get_forecast"],
            "time": ["get_current_time", "get_timezone", "convert_timezone"],
            "sentiment": ["analyze_sentiment", "detect_emotions"]
        }
        return capabilities.get(server_name, [])
    
    async def call_mcp_tool(self, server: str, tool: str, params: Dict) -> Any:
        """Вызывает инструмент на MCP сервере."""
        
        # Эмуляция вызовов MCP инструментов
        if server == "memory" and tool == "store_memory":
            return {"status": "stored", "key": params.get("key")}
        
        elif server == "memory" and tool == "retrieve_memory":
            # Эмуляция получения памяти
            memories = {
                "user_name": "Давид",
                "favorite_movie": "Интерстеллар",
                "pet": "кот по имени Васька"
            }
            return memories.get(params.get("key"), "не помню такого")
        
        elif server == "weather" and tool == "get_current_weather":
            # Эмуляция погоды
            weather_options = [
                "Солнечно, +22°C",
                "Облачно, +18°C", 
                "Дождь, +15°C",
                "Снег, -5°C"
            ]
            return random.choice(weather_options)
        
        elif server == "sentiment" and tool == "analyze_sentiment":
            # Простой анализ настроения
            text = params.get("text", "").lower()
            if any(word in text for word in ["грустно", "плохо", "печально"]):
                return {"sentiment": "negative", "confidence": 0.8}
            elif any(word in text for word in ["радость", "счастье", "круто"]):
                return {"sentiment": "positive", "confidence": 0.9}
            else:
                return {"sentiment": "neutral", "confidence": 0.7}
        
        return None


# ============================================================================
# ПРОДВИНУТЫЙ LLM КЛИЕНТ
# ============================================================================

class AdvancedAlinaLLM:
    """Продвинутый клиент с поддержкой streaming, functions и MCP."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        mcp_config: Optional[Dict] = None,
        sentiment_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.mcp = MCPConnector()
        self.functions = AlenaFunctions()

        # MCP конфиг и процессы stdio-серверов
        self.mcp_config = mcp_config or {"servers": {}}
        self.sentiment_url = sentiment_url
        self._mcp_procs: Dict[str, asyncio.subprocess.Process] = {}

        # Параметры режимов (как было)
        self.modes = {
            "chat": {"temperature": 0.8, "top_p": 1.0, "frequency_penalty": 0.4, "presence_penalty": 0.4},
            "creative": {"temperature": 0.95, "top_p": 0.95, "frequency_penalty": 0.5, "presence_penalty": 0.5},
            "analytical": {"temperature": 0.6, "top_p": 0.9, "frequency_penalty": 0.2, "presence_penalty": 0.2},
            "empathetic": {"temperature": 0.85, "top_p": 1.0, "frequency_penalty": 0.3, "presence_penalty": 0.5},
        }
    
    async def initialize_mcp_servers(self):
        """
        Запускает STDIO MCP-сервера из mcp_config (command + args).
        HTTP-серверы (sentiment) не спауним — просто используем их URL.
        """
        servers = self.mcp_config.get("servers", {})
        tasks = []

        for name, cfg in servers.items():
            if not cfg.get("enabled", False):
                continue

            # HTTP endpoint (например, sentiment)
            if cfg.get("url"):
                if name == "sentiment" and not self.sentiment_url:
                    self.sentiment_url = cfg["url"]
                # HTTP-сервера не спауним
                continue

            # STDIO сервер (command + args)
            cmd = cfg.get("command")
            args = cfg.get("args", [])
            if not cmd:
                logger.warning(f"[MCP] Server '{name}' enabled but no command provided")
                continue

            # Уже запущен?
            proc = self._mcp_procs.get(name)
            if proc and (proc.returncode is None):
                continue

            tasks.append(self._spawn_stdio(name, cmd, args))

        if tasks:
            await asyncio.gather(*tasks)

        # (Опционально) пометим в абстракции, что «подключены»
        for name in servers.keys():
            self.mcp.servers[name] = {"status": "connected"}

    async def _spawn_stdio(self, name: str, cmd: str, args: List[str]):
        try:
            proc = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._mcp_procs[name] = proc
            logger.info(f"[MCP] Spawned stdio server '{name}': {cmd} {' '.join(args)} (pid={proc.pid})")
        except Exception as e:
            logger.error(f"[MCP] Failed to spawn '{name}': {e}")
            
    async def _analyze_sentiment_http(self, text: str) -> Optional[Dict[str, Any]]:
        if not self.sentiment_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(f"{self.sentiment_url}/analyze", json={"text": text})
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning(f"[MCP] Sentiment HTTP failed: {e}")
            return None

    
    async def _create_client(self) -> AsyncOpenAI:
        """Создаёт клиент OpenAI."""
        return AsyncOpenAI(api_key=self.api_key)
    
    async def analyze_intent(self, message: str) -> UserIntent:
        """Анализирует намерение пользователя через structured output."""
        client = await self._create_client()
        
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Проанализируй намерение пользователя."
                    },
                    {
                        "role": "user",
                        "content": message
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "user_intent",
                        "schema": UserIntent.model_json_schema()
                    }
                },
                temperature=0.3
            )
            
            content = response.choices[0].message.content
            return UserIntent.model_validate_json(content)
            
        except Exception as e:
            logger.error(f"Error analyzing intent: {e}")
            return UserIntent(
                primary_intent="unknown",
                topics=[],
                urgency=0.5,
                requires_action=False
            )
        finally:
            await client.close()
    
    async def generate_with_functions(
        self,
        messages: List[Dict],
        mode: str = "chat",
        use_functions: bool = True
    ) -> Dict[str, Any]:
        """Генерирует ответ с возможностью вызова функций."""
        
        client = await self._create_client()
        params = self.modes.get(mode, self.modes["chat"])
        
        try:
            # Добавляем функции если нужно
            tools = self.functions.get_function_schemas() if use_functions else None
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                **params
            )
            
            message = response.choices[0].message
            
            # Проверяем, были ли вызваны функции
            if message.tool_calls:
                function_results = []
                
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    # Выполняем функцию
                    result = await self.functions.execute_function(function_name, arguments)
                    
                    function_results.append({
                        "tool_call_id": tool_call.id,
                        "function_name": function_name,
                        "result": result
                    })
                    
                    # Добавляем результат в контекст
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call.model_dump()]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                
                # Получаем финальный ответ с учётом результатов функций
                final_response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **params
                )
                
                return {
                    "content": final_response.choices[0].message.content,
                    "function_calls": function_results
                }
            else:
                return {
                    "content": message.content,
                    "function_calls": []
                }
                
        except Exception as e:
            logger.error(f"Error generating with functions: {e}")
            return {
                "content": "что-то пошло не так... давай попробуем ещё раз?",
                "function_calls": []
            }
        finally:
            await client.close()
    
    async def stream_response(
        self,
        messages: List[Dict],
        mode: str = "chat"
    ) -> AsyncGenerator[str, None]:
        """Стриминг ответа для более естественного взаимодействия."""
        
        client = await self._create_client()
        params = self.modes.get(mode, self.modes["chat"])
        
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **params
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            yield "ой, что-то пошло не так..."
        finally:
            await client.close()
    
    async def get_response_with_mcp(
        self,
        messages: List[Dict],
        context: Dict
    ) -> str:
        """Генерирует ответ с использованием MCP серверов."""
        
        # Проверяем, нужна ли информация из MCP
        last_message = messages[-1]["content"]
        
        mcp_context = []
        
        # Проверяем память
        if "помнишь" in last_message.lower() or "говорил" in last_message.lower():
            memory_key = self._extract_memory_key(last_message)
            if memory_key:
                memory = await self.mcp.call_mcp_tool("memory", "retrieve_memory", {"key": memory_key})
                if memory and memory != "не помню такого":
                    mcp_context.append(f"[Из памяти: {memory_key} = {memory}]")
        
        # Проверяем погоду
        if "погод" in last_message.lower():
            weather = await self.mcp.call_mcp_tool("weather", "get_current_weather", {})
            if weather:
                mcp_context.append(f"[Погода сейчас: {weather}]")
        
        # Анализируем настроение
        sentiment = await self._analyze_sentiment_http(last_message)
        if sentiment and sentiment.get("sentiment") and sentiment["sentiment"] != "neutral":
            mcp_context.append(f"[Настроение пользователя: {sentiment['sentiment']}]")
        
        # Добавляем MCP контекст в системное сообщение
        if mcp_context:
            mcp_message = {
                "role": "system",
                "content": "Дополнительный контекст:\n" + "\n".join(mcp_context)
            }
            messages.insert(-1, mcp_message)
        
        # Генерируем ответ
        result = await self.generate_with_functions(messages, mode="chat")
        
        # Если были важные данные для запоминания, сохраняем через MCP
        if result["function_calls"]:
            for call in result["function_calls"]:
                if call["function_name"] == "remember_user_info":
                    # Сохраняем в MCP memory сервер
                    await self.mcp.call_mcp_tool(
                        "memory", 
                        "store_memory",
                        {"key": call["result"]}
                    )
        
        return result["content"]
    
    def _extract_memory_key(self, message: str) -> Optional[str]:
        """Извлекает ключ памяти из сообщения."""
        # Простая эвристика для примера
        memory_keywords = {
            "имя": "user_name",
            "зовут": "user_name",
            "работ": "user_work",
            "любим": "user_favorite",
            "питом": "user_pet",
            "кот": "user_pet",
            "собак": "user_pet"
        }
        
        message_lower = message.lower()
        for keyword, key in memory_keywords.items():
            if keyword in message_lower:
                return key
        
        return None
    
    async def analyze_response_quality(
        self,
        response: str,
        context: Dict
    ) -> Dict[str, float]:
        """Анализирует качество сгенерированного ответа."""
        
        client = await self._create_client()
        
        try:
            # Используем logprobs для анализа уверенности модели
            analysis = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Оцени качество ответа Алины по шкале от 0 до 1."
                    },
                    {
                        "role": "user",
                        "content": f"Ответ: {response}\nКонтекст: {json.dumps(context, ensure_ascii=False)}"
                    }
                ],
                logprobs=True,
                top_logprobs=3,
                max_tokens=100,
                temperature=0.1
            )
            
            # Анализируем logprobs для определения уверенности
            logprobs = analysis.choices[0].logprobs
            confidence_scores = []
            
            if logprobs and logprobs.content:
                for token_data in logprobs.content[:10]:  # Первые 10 токенов
                    if token_data.top_logprobs:
                        # Берём вероятность самого вероятного токена
                        top_prob = token_data.top_logprobs[0].logprob
                        confidence_scores.append(top_prob)
            
            avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
            
            return {
                "confidence": avg_confidence,
                "coherence": 0.8,  # Можно добавить более сложный анализ
                "personality_match": 0.9,  # Соответствие личности Алины
                "emotional_appropriateness": 0.85  # Эмоциональная уместность
            }
            
        except Exception as e:
            logger.error(f"Error analyzing response quality: {e}")
            return {
                "confidence": 0.5,
                "coherence": 0.5,
                "personality_match": 0.5,
                "emotional_appropriateness": 0.5
            }
        finally:
            await client.close()