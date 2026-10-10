# Runbook — backup và restore

Backup gồm: snapshot dữ liệu logic từ database (admin DSN có quyền vượt RLS), blob manifest/checksums trong
artifact root, và file keyring mã hoá riêng. Restore bắt buộc vào database **cô lập** (tên khác) rồi kiểm
chứng trước khi cắt sang.

## 1. Tạo backup

```text
AGENTQA_ADMIN_DSN="postgresql+psycopg://agentqa_bootstrap:<password>@<host>:<port>/<database>" \
uv run --locked python -m agentqa.platform.backup create \
  --artifacts /var/lib/agentqa/artifacts \
  --out /var/backups/agentqa/2026-10-10
```

Kết quả: `manifest.json` (schema version + counts + checksums của từng data file và blob), `data/*.jsonl`,
`blobs/`.

Kiểm tra integrity (không cần DB):

```text
uv run --locked python -m agentqa.platform.backup verify --backup /var/backups/agentqa/2026-10-10
```

Keyring (master key material) backup riêng, có passphrase:

```text
AGENTQA_KEYRING_PASSPHRASE="<passphrase>" \
uv run --locked python -m agentqa.platform.backup keyring-backup \
  --out /var/backups/agentqa/2026-10-10/keyring.enc
```

Keyring không nằm trong workspace export; file `keyring.enc` phải được cất ở kênh riêng.

## 2. Restore vào môi trường cô lập

```text
AGENTQA_ADMIN_DSN="postgresql+psycopg://agentqa_bootstrap:<password>@<host>:<port>/postgres" \
uv run --locked python -m agentqa.platform.backup restore \
  --artifacts /var/lib/agentqa/artifacts \
  --backup /var/backups/agentqa/2026-10-10 \
  --database agentqa_restore_check
```

Trình tự thực thi (đã kiểm bằng test):

1. `verify` checksum + schema version head khớp trước khi ghi; backup hỏng → dừng, không tạo database.
2. Tạo database mới (isolated target) và chạy migration tới head.
3. Nạp dữ liệu theo thứ tự FK; sau đó theo policy: **revoke toàn bộ sessions/api_tokens** còn hiệu lực và
   **quarantine run active** (`status=error`, reason `quarantined:restore`; executions/jobs chuyển error/
   quarantined). Không hồi sinh browser/side effect.
4. Kiểm chứng: counts từng bảng khớp manifest, `links_ok` (artifact object_key/digest khớp blob manifest).
5. Kiểm keyring: `keyring-restore` với đúng passphrase trả version; thiếu file/sai passphrase → lỗi rõ
   (`KeyringRestoreError`), restore bị chặn.

```text
AGENTQA_KEYRING_PASSPHRASE="<passphrase>" \
uv run --locked python -m agentqa.platform.backup keyring-restore --file /var/backups/agentqa/2026-10-10/keyring.enc
```

## 3. Sau restore

- Đổi cấu hình API/worker sang database mới, chạy `/health/ready` (schema version/roles/storage).
- Người dùng phải đăng nhập lại (session bị revoke theo policy).
- Run từng active trước backup ở trạng thái quarantined; cần rerun tường minh nếu muốn chạy lại.
- Blob store khôi phục bằng cách đồng bộ thư mục `blobs/` vào artifact root đích; không sửa blob đang
  được finalize.

## 4. Giới hạn hiện tại

- Snapshot là export logic theo bảng (không dùng pg_basebackup); với dung lượng lớn cần thay bằng snapshot
  vật lý của PostgreSQL. Checksums/counts/links trong manifest là hợp đồng kiểm chứng giữa hai phương án.
- Artifact tombstones/retention chạy độc lập (`RetentionService`); backup giữ provenance metadata kể cả khi
  blob đã hết hạn.
