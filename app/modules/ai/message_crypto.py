from app.core.encryption import decrypt_data, encrypt_data
from app.models.ai import AIMessage, AIMessageFeedback, new_id


def message_aad(user_id: str, conversation_id: str, message_id: str) -> bytes:
    return f"medi:ai-message:v1:{user_id}:{conversation_id}:{message_id}".encode("utf-8")


def encrypt_conversation_title(user_id: str, conversation_id: str, title: str) -> str:
    return encrypt_data(title, associated_data=f"medi:ai-conversation-title:v1:{user_id}:{conversation_id}".encode())


def decrypt_conversation_title(user_id: str, conversation_id: str, ciphertext: str) -> str:
    return decrypt_data(ciphertext, associated_data=f"medi:ai-conversation-title:v1:{user_id}:{conversation_id}".encode())


def new_encrypted_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    *,
    citations: list[dict] | None = None,
) -> AIMessage:
    if role not in {"system", "user", "assistant"}:
        raise ValueError("Unsupported AI message role.")
    message_id = new_id()
    return AIMessage(
        id=message_id,
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        encrypted_content=encrypt_message_content(user_id, conversation_id, message_id, content),
        citations=citations,
    )


def encrypt_message_content(user_id: str, conversation_id: str, message_id: str, content: str) -> str:
    if not content:
        raise ValueError("Message content cannot be empty.")
    return encrypt_data(content, associated_data=message_aad(user_id, conversation_id, message_id))


def decrypt_message_content(message: AIMessage) -> str:
    return decrypt_data(
        message.encrypted_content,
        associated_data=message_aad(message.user_id, message.conversation_id, message.id),
    )


def encrypt_feedback_comment(user_id: str, message_id: str, feedback_id: str, comment: str) -> str:
    return encrypt_data(comment, associated_data=f"medi:ai-feedback:v1:{user_id}:{message_id}:{feedback_id}".encode())


def decrypt_feedback_comment(feedback: AIMessageFeedback) -> str | None:
    if feedback.encrypted_comment is None:
        return None
    aad = f"medi:ai-feedback:v1:{feedback.user_id}:{feedback.message_id}:{feedback.id}".encode()
    return decrypt_data(feedback.encrypted_comment, associated_data=aad)

