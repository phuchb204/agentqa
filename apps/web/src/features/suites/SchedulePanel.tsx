import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiClientError } from "../../api/client";
import { useApi } from "../../api/context";
import type { ScheduleOccurrence } from "../../api/types";

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.message : "Thao tác thất bại";
}

const STATE_LABELS: Record<string, string> = {
  pending: "Chờ đến giờ",
  queued: "Xếp hàng (overlap)",
  claimed: "Đã tạo lượt chạy",
  skipped: "Bỏ qua",
  missed: "Lỡ lịch (không chạy bù)",
};

const REASON_LABELS: Record<string, string> = {
  dst_gap: "Giờ DST không tồn tại",
  downtime: "Downtime — không catch-up",
  overlap_skip: "Trùng lượt đang chạy — bỏ qua",
  overlap_queue: "Trùng lượt đang chạy — xếp hàng",
};

function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

function reasonLabel(reason: string | null): string {
  if (!reason) {
    return "—";
  }
  if (reason.startsWith("dispatch_failed:")) {
    return `Tạo lượt chạy thất bại (${reason.split(":")[1] ?? "error"})`;
  }
  return REASON_LABELS[reason] ?? reason;
}

function nextReadiness(occurrences: ScheduleOccurrence[]): string {
  const pending = occurrences
    .filter((item) => item.state === "pending" && item.scheduled_at !== null)
    .sort((a, b) => (a.scheduled_at ?? "").localeCompare(b.scheduled_at ?? ""));
  if (pending.length > 0) {
    return `Lượt kế tiếp: ${pending[0].scheduled_at} (local ${pending[0].local_wall_time})`;
  }
  return "Không có lượt chờ nào trong cửa sổ hiện tại";
}

export function SchedulePanel({
  workspaceId,
  suiteRevisionId,
  canManage,
  defaultLogicalKey,
}: {
  workspaceId: string;
  suiteRevisionId: string;
  canManage: boolean;
  defaultLogicalKey: string;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [logicalKey, setLogicalKey] = useState(`${defaultLogicalKey}-schedule`);
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");
  const [timeValue, setTimeValue] = useState("02:00");
  const [overlap, setOverlap] = useState<"skip" | "queue">("skip");
  const [message, setMessage] = useState<string | null>(null);

  const schedulesQuery = useQuery({
    queryKey: ["schedules", workspaceId],
    queryFn: () => api.listSchedules(workspaceId),
  });

  const suiteSchedules = (schedulesQuery.data ?? []).filter(
    (item) => item.latest_revision?.content.suite_revision_id === suiteRevisionId,
  );
  const primary = suiteSchedules[0] ?? null;

  const occurrencesQuery = useQuery({
    queryKey: ["schedule-occurrences", workspaceId, primary?.schedule_id ?? "none"],
    queryFn: () =>
      primary
        ? api.listScheduleOccurrences(workspaceId, primary.schedule_id)
        : Promise.resolve([] as ScheduleOccurrence[]),
    enabled: Boolean(primary),
    refetchInterval: 15000,
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const [hour, minute] = timeValue.split(":").map((part) => Number(part));
      const created = await api.createSchedule(workspaceId, logicalKey);
      await api.addScheduleRevision(workspaceId, created.schedule_id, {
        schema_version: "schedule/1",
        logical_key: logicalKey,
        suite_revision_id: suiteRevisionId,
        timezone,
        hour,
        minute,
        days_of_week: [],
        overlap,
      });
      return created;
    },
    onSuccess: async () => {
      setMessage("Đã tạo lịch chạy cho suite revision này");
      await queryClient.invalidateQueries({ queryKey: ["schedules", workspaceId] });
    },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const toggleMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      if (!primary) {
        return null;
      }
      return api.setScheduleEnabled(workspaceId, primary.schedule_id, enabled);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["schedules", workspaceId] });
    },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const occurrences = occurrencesQuery.data ?? [];

  return (
    <section className="panel">
      <h3 className="panel__title">Lịch chạy</h3>
      {schedulesQuery.isLoading ? (
        <p className="muted">Đang tải lịch chạy…</p>
      ) : suiteSchedules.length === 0 ? (
        <p className="muted">Suite revision này chưa có lịch chạy.</p>
      ) : (
        <div className="stack">
          {suiteSchedules.map((schedule) => (
            <div key={schedule.schedule_id} className="stack">
              <p>
                <strong>{schedule.logical_key}</strong> ·{" "}
                <span className={schedule.enabled ? "badge" : "badge badge--danger"}>
                  {schedule.enabled ? "Đang bật" : "Đã tắt"}
                </span>{" "}
                · timezone {String(schedule.latest_revision?.content.timezone ?? "—")} · giờ{" "}
                {String(schedule.latest_revision?.content.hour ?? "?")}:
                {String(schedule.latest_revision?.content.minute ?? "00").padStart(2, "0")} ·
                overlap {String(schedule.latest_revision?.content.overlap ?? "skip")} · revision v
                {schedule.latest_revision?.revision_no ?? "—"} (digest{" "}
                {String(schedule.latest_revision?.content.suite_revision_id ?? "").slice(0, 8)}…)
                {canManage ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => void toggleMutation.mutateAsync(!schedule.enabled)}
                      disabled={toggleMutation.isPending}
                    >
                      {schedule.enabled ? "Tắt lịch" : "Bật lịch"}
                    </button>
                  </>
                ) : null}
              </p>
              {schedule.schedule_id === primary?.schedule_id ? (
                <>
                  <p className="muted" role="status">
                    {nextReadiness(occurrences)}
                  </p>
                  {occurrencesQuery.isLoading ? (
                    <p className="muted">Đang tải lượt lịch…</p>
                  ) : occurrences.length === 0 ? (
                    <p className="muted">Chưa có lượt lịch nào được ghi nhận.</p>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Giờ địa phương</th>
                          <th>UTC</th>
                          <th>Trạng thái</th>
                          <th>Lý do</th>
                          <th>Lượt chạy</th>
                        </tr>
                      </thead>
                      <tbody>
                        {occurrences.slice(-10).map((occurrence) => (
                          <tr key={occurrence.occurrence_id}>
                            <td>
                              {occurrence.local_wall_time}
                              {occurrence.fold === 1 ? " (fold 1)" : ""}
                            </td>
                            <td>{occurrence.scheduled_at ?? "—"}</td>
                            <td data-state={occurrence.state}>{stateLabel(occurrence.state)}</td>
                            <td>{reasonLabel(occurrence.reason)}</td>
                            <td>
                              {occurrence.run_id ? (
                                <a
                                  href={`/w/${workspaceId}/runs/${occurrence.run_id}`}
                                  data-run-link
                                >
                                  {occurrence.run_id.slice(0, 8)}…
                                </a>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {canManage ? (
        <div className="stack">
          <div className="row">
            <label className="stack" style={{ flex: 1 }}>
              Logical key lịch mới
              <input value={logicalKey} onChange={(event) => setLogicalKey(event.target.value)} />
            </label>
            <label className="stack">
              Timezone (IANA)
              <input
                aria-label="Timezone"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
              />
            </label>
            <label className="stack">
              Giờ chạy
              <input
                aria-label="Giờ chạy"
                type="time"
                value={timeValue}
                onChange={(event) => setTimeValue(event.target.value)}
              />
            </label>
            <label className="stack">
              Overlap
              <select
                aria-label="Overlap"
                value={overlap}
                onChange={(event) => setOverlap(event.target.value === "queue" ? "queue" : "skip")}
              >
                <option value="skip">Bỏ qua lượt trùng</option>
                <option value="queue">Xếp hàng lượt trùng</option>
              </select>
            </label>
          </div>
          <button
            type="button"
            data-variant="primary"
            disabled={createMutation.isPending || logicalKey.trim() === ""}
            onClick={() => void createMutation.mutateAsync()}
          >
            Tạo lịch chạy cho revision này
          </button>
          {message ? <p role="status">{message}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
