import {
  asContent,
  listAssertions,
  listSecretRefs,
  listSources,
  withField,
  withNodeAssertion,
} from "./content-ops";

export function StructuredView({
  content,
  readOnly,
  onEdit,
}: {
  content: Record<string, unknown>;
  readOnly: boolean;
  onEdit: (next: Record<string, unknown>) => void;
}) {
  const nodes = Array.isArray(content.nodes) ? content.nodes : [];
  const assertions = listAssertions(content);
  const sources = listSources(content);
  const secrets = listSecretRefs(content);

  return (
    <div className="stack">
      <div className="row">
        <label className="stack" style={{ flex: 1 }}>
          Tiêu đề
          <input
            aria-label="Tiêu đề ca"
            value={String(content.title ?? "")}
            readOnly={readOnly}
            onChange={(event) => onEdit(withField(content, "title", event.target.value))}
          />
        </label>
        <label className="stack" style={{ flex: 2 }}>
          Mục tiêu
          <input
            aria-label="Mục tiêu ca"
            value={String(content.goal ?? "")}
            readOnly={readOnly}
            onChange={(event) => onEdit(withField(content, "goal", event.target.value))}
          />
        </label>
      </div>

      <section>
        <h3>Bước và checkpoint ({nodes.length})</h3>
        {nodes.map((node) => {
          const record = asContent(node);
          const nodeId = String(record.id ?? "");
          return (
            <article className="node-card" key={nodeId}>
              <div className="row">
                <strong>{nodeId}</strong>
                <span className="badge">{String(record.kind ?? "")}</span>
                {record.operation ? (
                  <span className="muted">{String(record.operation)}</span>
                ) : null}
              </div>
              {record.kind === "action" ? (
                <p className="muted">
                  {asContent(record.target).name
                    ? `Target: ${String(asContent(record.target).name)}`
                    : "Không có target"}
                </p>
              ) : null}
              {Array.isArray(record.assertions) && record.assertions.length > 0 ? (
                <table>
                  <thead>
                    <tr>
                      <th>Assertion</th>
                      <th>Comparator</th>
                      <th>Kỳ vọng</th>
                      <th>Bắt buộc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.assertions.map((assertion) => {
                      const item = asContent(assertion);
                      const assertionId = String(item.id ?? "");
                      const expected = asContent(item.expected);
                      return (
                        <tr key={assertionId}>
                          <td>{assertionId}</td>
                          <td>{String(item.comparator ?? "")}</td>
                          <td>
                            <input
                              aria-label={`Kỳ vọng ${assertionId}`}
                              value={
                                expected.value === undefined || expected.value === null
                                  ? ""
                                  : String(expected.value)
                              }
                              readOnly={readOnly}
                              onChange={(event) =>
                                onEdit(
                                  withNodeAssertion(content, nodeId, assertionId, {
                                    expected: { ...expected, value: event.target.value },
                                  }),
                                )
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Bắt buộc ${assertionId}`}
                              checked={Boolean(item.required)}
                              disabled={readOnly}
                              onChange={(event) =>
                                onEdit(
                                  withNodeAssertion(content, nodeId, assertionId, {
                                    required: event.target.checked,
                                  }),
                                )
                              }
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : null}
            </article>
          );
        })}
        {assertions.length === 0 ? <p className="muted">Chưa có assertion nào.</p> : null}
      </section>

      <section>
        <h3>Nguồn và provenance</h3>
        {sources.length === 0 ? (
          <p className="muted">Chưa có source_defs.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Nguồn</th>
                <th>Provenance</th>
                <th>Xác nhận</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.name}>
                  <td>{source.name}</td>
                  <td>
                    <span
                      className={`badge${source.provenance === "inferred" ? " badge--warning" : ""}`}
                    >
                      {source.provenance === "inferred"
                        ? "Suy luận từ quan sát"
                        : source.provenance}
                    </span>
                  </td>
                  <td>
                    {source.confirmationRef
                      ? "Đã xác nhận"
                      : source.provenance === "inferred"
                        ? "Chưa xác nhận"
                        : "Theo nguồn"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3>Tham chiếu bí mật</h3>
        {secrets.length === 0 ? (
          <p className="muted">Không có tham chiếu bí mật.</p>
        ) : (
          <ul>
            {secrets.map((secret) => (
              <li key={`${secret.nodeId}:${secret.credentialRef}`}>
                {secret.nodeId}: credential reference <code>{secret.credentialRef}</code> — giá trị
                chỉ được resolve ở executor khi target đã xác minh.
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
