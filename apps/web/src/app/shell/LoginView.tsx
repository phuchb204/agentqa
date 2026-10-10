import { useState, type FormEvent } from "react";

import { ApiClientError, type ApiClient } from "../../api/client";
import type { SessionInfo } from "../../api/types";

export function LoginView({
  api,
  onSuccess,
}: {
  api: ApiClient;
  onSuccess: (result: { csrfToken: string; user: SessionInfo }) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username, password);
      onSuccess(result);
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : "Đăng nhập thất bại");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="panel" style={{ maxWidth: 420, margin: "10vh auto" }}>
      <h1 className="panel__title">Đăng nhập AgentQA</h1>
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <label className="stack">
          Tài khoản
          <input
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="stack">
          Mật khẩu
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error ? (
          <p role="alert" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        ) : null}
        <button type="submit" data-variant="primary" disabled={busy}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </button>
      </form>
    </main>
  );
}
