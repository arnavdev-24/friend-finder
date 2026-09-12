MAX_ACTIVE_CHATS = 5


def can_accept_chat(active_count):
    return active_count < MAX_ACTIVE_CHATS


def active_chat_limit_message():
    return "Archive one chat to continue"