import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle, XCircle, RefreshCcw } from "lucide-react";
import { Button } from "@/ui/button";
import { endpoints } from "@/config";

interface Violation {
  id: number;
  camera_id: number;
  timestamp: string;
  violation_type: string;
  license_plate: string | null;
  status: string;
  evidence_image_url?: string | null;
}

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const getTypeLabel = (type: string) => {
  const map: Record<string, string> = {
    red_light: "Vượt đèn đỏ",
    wrong_lane: "Đi sai làn",
    no_parking: "Đỗ sai quy định",
  };
  return map[type] ?? type;
};

const StatusBadge = ({ status }: { status: string }) => {
  if (status === "pending")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-yellow-500/20 text-yellow-500">
        <AlertTriangle size={12} /> Chờ duyệt
      </span>
    );
  if (status === "confirmed")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-500/20 text-green-500">
        <CheckCircle size={12} /> Đã duyệt
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-500/20 text-red-500">
      <XCircle size={12} /> Đã huỷ
    </span>
  );
};

export default function ViolationsList() {
  const [violations, setViolations] = useState<Violation[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const navigate = useNavigate();

  const fetchViolations = async () => {
    setLoading(true);
    try {
      const url = statusFilter
        ? `${endpoints.violations}?status=${statusFilter}&limit=200`
        : `${endpoints.violations}?limit=200`;
      const res = await fetch(url, { headers: getAuthHeaders() });
      if (res.ok) {
        setViolations(await res.json());
      }
    } catch (err) {
      console.error("Lỗi khi tải danh sách vi phạm:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchViolations();
  }, [statusFilter]);

  return (
    <div className="p-6 h-full flex flex-col gap-6 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Xử Phạt Nguội</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Quản lý các phương tiện vi phạm giao thông được hệ thống AI phát hiện.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="pending">Chờ duyệt</option>
            <option value="confirmed">Đã duyệt</option>
            <option value="rejected">Đã huỷ</option>
          </select>
          <Button variant="outline" size="sm" onClick={fetchViolations} className="gap-2">
            <RefreshCcw size={14} /> Làm mới
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="border rounded-xl bg-card overflow-hidden shadow-sm flex-1">
        <table className="w-full text-sm text-left">
          <thead className="bg-muted/60 text-muted-foreground uppercase text-xs border-b">
            <tr>
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">Thời gian</th>
              <th className="px-4 py-3 font-medium">Biển số</th>
              <th className="px-4 py-3 font-medium">Lỗi vi phạm</th>
              <th className="px-4 py-3 font-medium">Camera</th>
              <th className="px-4 py-3 font-medium">Trạng thái</th>
              <th className="px-4 py-3 font-medium text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr>
                <td colSpan={7} className="text-center py-16 text-muted-foreground">
                  Đang tải dữ liệu...
                </td>
              </tr>
            ) : violations.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-16 text-muted-foreground">
                  Không có vi phạm nào.
                </td>
              </tr>
            ) : (
              violations.map((v) => (
                <tr key={v.id} className="hover:bg-muted/40 transition-colors cursor-pointer" onClick={() => navigate(`/violations/${v.id}`)}>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">#{v.id}</td>
                  <td className="px-4 py-3 text-xs">{new Date(v.timestamp).toLocaleString("vi-VN")}</td>
                  <td className="px-4 py-3 font-mono font-bold tracking-wider text-primary">
                    {v.license_plate ?? <span className="text-muted-foreground font-normal">Chưa đọc được</span>}
                  </td>
                  <td className="px-4 py-3 font-medium">{getTypeLabel(v.violation_type)}</td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">Cam #{v.camera_id}</td>
                  <td className="px-4 py-3"><StatusBadge status={v.status} /></td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="secondary" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/violations/${v.id}`); }}>
                      Chi tiết →
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
