import pytest
from unittest.mock import patch
from orchestration.message_window import truncate_history, truncation_notice, SOFT_LIMIT, HARD_LIMIT, MIN_TAIL
from core.schemas import Message

@pytest.fixture
def mock_count_tokens():
    with patch("orchestration.message_window.count_tokens", side_effect=lambda t: len(t.split())) as m:
        yield m

def test_no_truncation(mock_count_tokens):
    messages = [Message(role="system", content="A " * 10)]
    for i in range(5):
        messages.append(Message(role="user", content="B " * 10))
    
    result, truncated = truncate_history(messages)
    assert not truncated
    assert len(result) == 6

def test_truncation_drops_middle(mock_count_tokens):
    # System: 100 tokens
    messages = [Message(role="system", content="S " * 100)]
    
    # Middle messages (total 10): each 300 tokens -> 3000 tokens
    for i in range(10):
        messages.append(Message(role="user", content=f"M{i} " * 300))
        
    # Tail messages (MIN_TAIL=6): each 10 tokens -> 60 tokens
    for i in range(MIN_TAIL):
        messages.append(Message(role="user", content=f"T{i} " * 10))

    # Total tokens = 100 + 3000 + 60 = 3160. Limit is 3200, so it shouldn't truncate yet.
    # Let's make middle 350 tokens each -> 3500 tokens -> Total 3660 > 3200 SOFT_LIMIT
    messages = [Message(role="system", content="S " * 10)]
    for i in range(10):
        messages.append(Message(role="user", content=f"M{i} " * 350))
    for i in range(MIN_TAIL):
        messages.append(Message(role="user", content=f"T{i} " * 10))
    
    result, truncated = truncate_history(messages)
    assert truncated
    
def test_hard_limit_fallback():
    # If messages are huge and exceed HARD_LIMIT even after middle drops
    messages = [
        Message(role="system", content="S" * 40),  # 10 tokens 
    ]
    # We put the big message in the tail so it doesn't get dropped by the soft limit
    for i in range(MIN_TAIL - 1):
        messages.append(Message(role="user", content="T " * 10))
    messages.append(Message(role="user", content="H " * 6000)) # 6000 tokens
    
    with patch("orchestration.message_window.count_tokens", side_effect=lambda t: len(t.split())):
        result, truncated = truncate_history(messages)
    assert truncated
    assert "[truncated]" in result[1].content
    
def test_truncation_notice():
    msg = truncation_notice(5)
    assert msg.role == "user"
    assert "5 earlier messages" in msg.content
