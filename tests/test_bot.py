"""Unit tests for Alina Bot"""

import pytest
import tempfile
from unittest.mock import Mock, patch

from database import DialogueDB
from llm import AlinaLLM
from payments import SubscriptionManager


class TestDatabase:
    """Test database operations"""
    
    def setup_method(self):
        """Create temporary database for testing"""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db = DialogueDB(self.temp_db.name)
    
    def test_user_creation(self):
        """Test user creation and retrieval"""
        user_id = 12345
        user = self.db.get_or_create_user(user_id)
        
        assert user['user_id'] == user_id
        assert user['total_messages'] == 0
        assert user['total_tokens'] == 0
    
    def test_message_storage(self):
        """Test message storage and retrieval"""
        user_id = 12345
        self.db.get_or_create_user(user_id)
        
        # Add messages
        self.db.add_message(user_id, 'user', 'Hello')
        self.db.add_message(user_id, 'assistant', 'Hi there', tokens_used=10)
        
        # Get history
        history = self.db.get_dialogue_history(user_id)
        
        assert len(history) == 2
        assert history[0]['role'] == 'user'
        assert history[0]['content'] == 'Hello'
        assert history[1]['role'] == 'assistant'
    
    def test_usage_tracking(self):
        """Test usage statistics"""
        user_id = 12345
        self.db.get_or_create_user(user_id)
        
        # Add messages with tokens
        self.db.add_message(user_id, 'user', 'Test')
        self.db.add_message(user_id, 'assistant', 'Response', tokens_used=50)
        
        usage = self.db.get_user_usage(user_id)
        
        assert usage['messages'] == 1  # Only user messages count
        assert usage['tokens'] == 50
    
    def test_limit_reset(self):
        """Test resetting user limits"""
        user_id = 12345
        self.db.get_or_create_user(user_id)
        
        # Add some usage
        self.db.add_message(user_id, 'user', 'Test')
        self.db.add_message(user_id, 'assistant', 'Response', tokens_used=100)
        
        # Reset limits
        self.db.reset_user_limits(user_id)
        
        usage = self.db.get_user_usage(user_id)
        assert usage['messages'] == 0
        assert usage['tokens'] == 0


class TestLLM:
    """Test LLM functionality"""
    
    def test_token_counting_text(self):
        """Test token counting for plain text"""
        llm = AlinaLLM(api_key='test_key', use_proxy=False)
        
        # Approximate counts
        text = "Hello world"
        tokens = llm.count_tokens_text(text)
        assert tokens > 0
    
    def test_token_counting_messages(self):
        """Test token counting for messages"""
        llm = AlinaLLM(api_key='test_key', use_proxy=False)
        
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        
        tokens = llm.count_tokens_messages(messages)
        assert tokens > 0
    
    @patch('llm.AsyncOpenAI')
    async def test_generate_response(self, mock_openai):
        """Test response generation"""
        llm = AlinaLLM(api_key='test_key', use_proxy=False)
        
        # Mock OpenAI response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Test response"))]
        mock_response.usage = Mock(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=Mock(cached_tokens=0)
        )
        
        mock_client = Mock()
        mock_client.chat.completions.create = Mock(return_value=mock_response)
        mock_client.close = Mock(return_value=None)
        mock_openai.return_value = mock_client
        
        messages = [{"role": "user", "content": "Hello"}]
        response, tokens = await llm.generate_response(messages)
        
        assert response == "Test response"
        assert tokens > 0


class TestSubscriptionManager:
    """Test subscription management"""
    
    def setup_method(self):
        """Create test environment"""
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db = DialogueDB(self.temp_db.name)
        self.manager = SubscriptionManager(self.db)
    
    def test_no_subscription(self):
        """Test user without subscription"""
        user_id = 12345
        assert not self.manager.has_active_subscription(user_id)
    
    def test_add_subscription(self):
        """Test adding subscription"""
        user_id = 12345
        
        # Add subscription
        result = self.manager.add_subscription(user_id, 'day')
        assert result is True
        
        # Check if active
        assert self.manager.has_active_subscription(user_id)
    
    def test_subscription_extension(self):
        """Test extending existing subscription"""
        user_id = 12345
        
        # Add initial subscription
        self.manager.add_subscription(user_id, 'day')
        
        # Add another subscription (should extend)
        self.manager.add_subscription(user_id, 'week')
        
        # Should still have only one active subscription
        assert self.manager.has_active_subscription(user_id)
    
    def test_subscription_info(self):
        """Test subscription info formatting"""
        user_id = 12345
        
        # No subscription
        info = self.manager.format_subscription_info(user_id)
        assert "нет активной подписки" in info.lower()
        
        # With subscription
        self.manager.add_subscription(user_id, 'month')
        info = self.manager.format_subscription_info(user_id)
        assert "активна" in info.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
