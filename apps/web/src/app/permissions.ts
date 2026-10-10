export type Role = "owner" | "editor" | "runner" | "viewer";

export function canEditCases(role: Role | undefined): boolean {
  return role === "owner" || role === "editor";
}

export function canPromoteCases(role: Role | undefined): boolean {
  return role === "owner" || role === "editor";
}

export function canRunCases(role: Role | undefined): boolean {
  return role === "owner" || role === "editor" || role === "runner";
}

export function canReadWorkspace(role: Role | undefined): boolean {
  return role !== undefined;
}

export function canManageSettings(role: Role | undefined): boolean {
  return role === "owner";
}

export function roleLabel(role: Role | undefined): string {
  switch (role) {
    case "owner":
      return "Chủ sở hữu";
    case "editor":
      return "Biên tập";
    case "runner":
      return "Người chạy";
    case "viewer":
      return "Người xem";
    default:
      return "Chưa có quyền";
  }
}
