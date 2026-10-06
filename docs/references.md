# Nguồn tham khảo

Nguồn được giữ từ tài liệu đồ án đã đọc và tài liệu chính thức đã đối chiếu trong brainstorming. Đây là đầu mối nghiên cứu; cần đọc nguồn gốc và kiểm tra phiên bản hiện hành khi viết spec. Không mang giá, giới hạn API, phiên bản model hoặc số liệu benchmark cũ vào thiết kế như dữ kiện hiện tại.

## Agent và quan sát

- ReAct — Yao và cộng sự: https://arxiv.org/abs/2210.03629
- Agent-E — Abuelsaad và cộng sự: https://arxiv.org/abs/2407.13032
- Mind2Web — Deng và cộng sự: https://arxiv.org/abs/2306.06070
- WebArena — Zhou và cộng sự: https://arxiv.org/abs/2307.13854
- WebVoyager — He và cộng sự: https://arxiv.org/abs/2401.13919
- SeeAct — Zheng và cộng sự: https://arxiv.org/abs/2401.01614
- Online-Mind2Web — Xue và cộng sự: https://arxiv.org/abs/2504.01382

## Jev và trình duyệt

- OpenCode Zen, route System One cho Jev: https://opencode.ai/docs/zen/
- OpenCode Go, route Chat Completions cho DeepSeek: https://opencode.ai/docs/go/
- DeepSeek V4.1 Flash, model card: https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash
- TypeSafe, primitive câu hỏi: https://docs.typesafe.ai/primitives
- TypeSafe, confidence: https://docs.typesafe.ai/confidence
- OpenRouter, hướng dẫn Jev: https://openrouter.ai/docs/guides/community/jev
- TypeSafe, tài liệu Jev: https://docs.typesafe.ai
- Playwright, locator: https://playwright.dev/docs/locators
- Playwright, assertion: https://playwright.dev/docs/test-assertions
- Playwright, thực hành kiểm thử: https://playwright.dev/docs/best-practices
- Stagehand, quan sát và hành động có cấu trúc: https://docs.stagehand.dev/v3/basics/observe
- Stagehand, caching hành động: https://docs.stagehand.dev/v3/best-practices/caching

Các công cụ tham khảo không phải dependency đã được chọn cho AgentQA. Thiết kế Python hoặc ngôn ngữ khác phải kiểm tra API tương ứng, không áp nguyên ví dụ TypeScript.

Provider được chọn ban đầu là OpenCode Zen và OpenCode Go. OpenRouter chỉ là nguồn tham khảo về Jev, không phải adapter phải triển khai. Dữ kiện đã kiểm tra, quyết định suy ra và khả năng cần xác minh được phân biệt trong [cơ sở nghiên cứu](research/design-evidence.md).

## Phục hồi và đánh giá

- Robula+ — Leotta và cộng sự (2016), "Robula+: An algorithm for generating robust XPath locators for web testing", Journal of Software: Evolution and Process, 28(3), 177–204.
- Similo — Nass và cộng sự (2023), "Similarity-based web element localization for robust test automation", ACM TOSEM, 32(3), article 75.
- Similo-LLM — Nass, Alégroth và Feldt (2024), "Improving web element localization by using a large language model": https://doi.org/10.1002/stvr.1893
- Locator bền vững — Nguyen, To và Diep (2021), "Generating and selecting resilient and maintainable locators for web automated testing", STVR, 31(3), e1760.
- MaewU — Yandrapally và Mesbah (2021), "Mutation analysis for assessing end-to-end web tests": https://doi.org/10.1109/ICSME52107.2021.00023
- Flaky test — Parry và cộng sự (2021), "A survey of flaky tests", ACM TOSEM, 31(1), article 17.
- Prompt injection — Greshake và cộng sự (2023), "Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection", AISec 2023.

## Tài liệu gốc

Báo cáo Word, nguồn Markdown, sơ đồ, code và lịch sử phiên bản cũ được lưu trong bản sao lưu ngoài workspace khi dọn repo. Chúng là nguồn lịch sử của đồ án; bộ yêu cầu trong workspace mới là cơ sở cho lần thiết kế lại.
