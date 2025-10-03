"""Time MCP Server - Provides time and date context for AI conversations"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TimeMCPServer:
    """MCP server that provides current time and date information"""
    
    def __init__(self):
        """Initialize the time MCP server"""
        self.name = "time"
        self.version = "1.0.0"
        
    def get_current_datetime_context(self) -> Dict[str, Any]:
        """Get comprehensive current date/time context
        
        Returns:
            Dictionary with time context information
        """
        now = datetime.now()
        
        # Russian day and month names
        weekdays_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                     "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        
        # Determine time of day
        hour = now.hour
        if 5 <= hour < 12:
            time_of_day = "утро"
        elif 12 <= hour < 17:
            time_of_day = "день"
        elif 17 <= hour < 23:
            time_of_day = "вечер"
        else:
            time_of_day = "ночь"
        
        # Determine if weekend
        is_weekend = now.weekday() >= 5
        
        return {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "weekday": now.weekday(),
            "weekday_name": weekdays_ru[now.weekday()],
            "month_name": months_ru[now.month - 1],
            "time_of_day": time_of_day,
            "is_weekend": is_weekend,
            "formatted_date": f"{now.day} {months_ru[now.month - 1]} {now.year}",
            "formatted_time": f"{now.hour:02d}:{now.minute:02d}",
            "iso_datetime": now.isoformat(),
        }
    
    def get_time_context_string(self) -> str:
        """Get a formatted string with current time context for prompts
        
        Returns:
            Formatted string with date, time, and day of week
        """
        context = self.get_current_datetime_context()
        return (
            f"Сейчас {context['time_of_day']}, {context['weekday_name']}, "
            f"{context['formatted_date']}, {context['formatted_time']}"
        )
    
    def get_simple_context(self) -> Dict[str, Any]:
        """Get simplified context for enrich_prompt function
        
        Returns:
            Dictionary with 'hour' key for mood adjustment
        """
        context = self.get_current_datetime_context()
        return {
            "hour": context["hour"],
            "is_weekend": context["is_weekend"],
            "time_of_day": context["time_of_day"],
            "weekday_name": context["weekday_name"],
            "date": context["formatted_date"],
        }


# Global singleton instance
_time_server: TimeMCPServer = None


def get_time_server() -> TimeMCPServer:
    """Get or create global TimeMCPServer instance
    
    Returns:
        Global TimeMCPServer instance
    """
    global _time_server
    if _time_server is None:
        _time_server = TimeMCPServer()
        logger.info("Time MCP server initialized")
    return _time_server


# Convenience functions for direct use
def get_current_time_context() -> Dict[str, Any]:
    """Get current time context (convenience function)"""
    return get_time_server().get_current_datetime_context()


def get_time_string() -> str:
    """Get formatted time string (convenience function)"""
    return get_time_server().get_time_context_string()


def get_enrichment_context() -> Dict[str, Any]:
    """Get context for personality enrichment (convenience function)"""
    return get_time_server().get_simple_context()
