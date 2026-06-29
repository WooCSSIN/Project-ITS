/**
 * useAdminGuard – shared hook dùng chung cho các trang admin.
 *
 * Thay vì mỗi trang admin tự gọi /auth/me để kiểm tra role,
 * hook này tập trung logic đó vào một nơi duy nhất, tránh:
 *   - Gọi API trùng lặp khi nhiều trang admin cùng mount
 *   - Xử lý lỗi token hết hạn rải rác ở nhiều component
 */
import { useEffect, useMemo, useState } from "react";
import { authConfig } from "@/config";

export type AdminGuardState = {
  /** null = đang kiểm tra, true = admin, false = không phải admin */
  isAdmin: boolean | null;
  loading: boolean;
  error: string | null;
  /** JWT token lấy từ localStorage */
  token: string | null;
};

export function useAdminGuard(): AdminGuardState {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const token = useMemo(
    () =>
      typeof window !== "undefined"
        ? localStorage.getItem(authConfig.TOKEN_KEY)
        : null,
    [],
  );

  useEffect(() => {
    let cancelled = false;

    const checkRole = async () => {
      if (!token) {
        setIsAdmin(false);
        setError("Chưa đăng nhập");
        setLoading(false);
        return;
      }

      try {
        const res = await fetch(authConfig.ME_URL, {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "include",
        });

        if (!res.ok) {
          if (!cancelled) {
            setIsAdmin(false);
            setError(
              res.status === 401
                ? "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại"
                : "Không thể xác thực người dùng",
            );
            setLoading(false);
          }
          return;
        }

        const me = await res.json();
        if (!cancelled) {
          const admin = me?.role_id === 0;
          setIsAdmin(admin);
          if (!admin) {
            setError("Bạn không có quyền truy cập trang này");
          }
        }
      } catch {
        if (!cancelled) {
          setIsAdmin(false);
          setError("Lỗi kết nối tới server");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    checkRole();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { isAdmin, loading, error, token };
}
