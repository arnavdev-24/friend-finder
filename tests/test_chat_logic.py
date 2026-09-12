from chat_logic import MAX_ACTIVE_CHATS, active_chat_limit_message, can_accept_chat


def test_accept_allowed_below_limit():
    assert can_accept_chat(MAX_ACTIVE_CHATS - 1) is True


def test_accept_blocked_at_limit():
    assert can_accept_chat(MAX_ACTIVE_CHATS) is False


def test_limit_message_matches_requirement():
    assert active_chat_limit_message() == "Archive one chat to continue"