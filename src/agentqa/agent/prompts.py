from agentqa.contracts import ObservationSnapshot

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "Bạn là agent kiểm thử web. Bạn nhận mục tiêu kiểm thử và ảnh chụp trạng thái trang "
    "(URL, tiêu đề, danh sách phần tử tương tác, văn bản trang) và quyết định HÀNH ĐỘNG TIẾP THEO.\n"
    "Chỉ trả về MỘT object JSON, không kèm chữ nào khác, đúng định dạng:\n"
    '{"type": "navigate" | "click" | "fill" | "finish", "target": "...", "value": "...", "rationale": "..."}\n'
    "Quy tắc: type=navigate thì target là URL; type=click thì target là selector Playwright "
    "(ưu tiên #id, hoặc text=<nhãn hiển thị>); type=fill thì target là selector và value là nội dung cần gõ; "
    "type=finish khi mục tiêu đã hoàn thành. target/value/rationale luôn là chuỗi (được phép rỗng)."
)


def build_user_prompt(goal: str, snapshot: ObservationSnapshot, history: list[str]) -> str:
    parts = [f"MỤC TIÊU: {goal}", f"TRẠNG THÁI TRANG:\n{snapshot.text}"]
    if history:
        parts.append("CÁC BƯỚC ĐÃ LÀM:\n" + "\n".join(history))
    parts.append("Hành động tiếp theo là gì? Trả về JSON.")
    return "\n\n".join(parts)
