import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ChevronLeft, Check, X, Printer, Camera } from "lucide-react";
import { Button } from "@/ui/button";
import { toast } from "sonner";
import { endpoints } from "@/config";

interface Violation {
  id: number;
  camera_id: number;
  timestamp: string;
  violation_type: string;
  license_plate: string | null;
  status: string;
  evidence_image_url?: string | null;
  fine_number?: string | null;
  confirmed_at?: string | null;
}

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const VIOLATION_LABELS: Record<string, string> = {
  red_light: "Vượt đèn đỏ",
  wrong_lane: "Đi sai làn",
  no_parking: "Dừng đỗ sai quy định",
};

export default function ViolationDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [violation, setViolation] = useState<Violation | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    const fetchDetail = async () => {
      try {
        const res = await fetch(endpoints.violation(id!), { headers: getAuthHeaders() });
        if (res.ok) {
          setViolation(await res.json());
        } else {
          toast.error("Không tìm thấy vi phạm hoặc lỗi kết nối backend.");
        }
      } catch {
        toast.error("Không thể kết nối tới backend.");
      } finally {
        setLoading(false);
      }
    };
    fetchDetail();
  }, [id]);

  const updateStatus = async (newStatus: "confirmed" | "rejected") => {
    setUpdating(true);
    try {
      const res = await fetch(endpoints.violation(id!), {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        const updated = await res.json();
        setViolation(updated);
        toast.success(
          newStatus === "confirmed"
            ? "✅ Đã xác nhận vi phạm! Có thể in biên bản."
            : "❌ Đã huỷ vi phạm (nhầm lẫn)."
        );
      } else {
        toast.error("Cập nhật thất bại.");
      }
    } catch {
      toast.error("Lỗi kết nối backend.");
    } finally {
      setUpdating(false);
    }
  };

  const handleExportPdf = async () => {
    try {
      const res = await fetch(endpoints.violationExportPdf(id!), { headers: getAuthHeaders() });
      if (!res.ok) {
        const err = await res.json();
        toast.error(err.detail ?? "Không thể tạo PDF.");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bien-ban-${id}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Đã tải biên bản PDF!");
    } catch {
      toast.error("Lỗi khi tải PDF.");
    }
  };

  if (loading) return <div className="p-10 text-center text-muted-foreground">Đang tải...</div>;
  if (!violation) return <div className="p-10 text-center text-muted-foreground">Không tìm thấy vi phạm.</div>;

  const vLabel = VIOLATION_LABELS[violation.violation_type] ?? violation.violation_type;

  return (
    <div className="p-6 flex flex-col gap-6 animate-in fade-in duration-300 max-w-5xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/violations")}>
          <ChevronLeft className="w-5 h-5" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Chi tiết vi phạm #{violation.id}</h1>
          <p className="text-sm text-muted-foreground">{new Date(violation.timestamp).toLocaleString("vi-VN")}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Ảnh bằng chứng */}
        <div className="border rounded-xl overflow-hidden shadow-sm bg-muted aspect-video flex items-center justify-center relative">
          {violation.evidence_image_url ? (
            <img src={violation.evidence_image_url} alt="Evidence" className="w-full h-full object-cover" />
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <Camera size={48} strokeWidth={1} />
              <span className="text-sm">Chưa có ảnh bằng chứng</span>
            </div>
          )}
          <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded font-mono backdrop-blur-sm">
            CAM_{violation.camera_id} · {new Date(violation.timestamp).toLocaleString("vi-VN")}
          </div>
        </div>

        {/* Thông tin & Thao tác */}
        <div className="flex flex-col gap-4">
          {/* Thông tin phương tiện */}
          <div className="border rounded-xl bg-card p-5 shadow-sm space-y-3">
            <h3 className="font-semibold border-b pb-2">Thông tin phương tiện</h3>
            <div className="grid grid-cols-2 gap-y-3 text-sm">
              <span className="text-muted-foreground">Biển kiểm soát</span>
              <span className="font-mono font-bold text-lg text-primary">{violation.license_plate ?? "Chưa rõ"}</span>
              <span className="text-muted-foreground">Lỗi vi phạm</span>
              <span className="font-semibold text-destructive">{vLabel}</span>
              <span className="text-muted-foreground">Camera</span>
              <span>Cam #{violation.camera_id}</span>
              <span className="text-muted-foreground">Trạng thái</span>
              <span>
                {violation.status === "pending" && <span className="text-yellow-500 font-medium">⏳ Chờ duyệt</span>}
                {violation.status === "confirmed" && <span className="text-green-500 font-medium">✅ Đã xác nhận</span>}
                {violation.status === "rejected" && <span className="text-red-500 font-medium">❌ Đã huỷ</span>}
              </span>
            </div>
          </div>

          {/* Nghiệp vụ CSGT */}
          <div className="border rounded-xl bg-card p-5 shadow-sm space-y-3">
            <h3 className="font-semibold border-b pb-2">Nghiệp vụ CSGT</h3>
            {violation.status === "pending" && (
              <div className="flex flex-col sm:flex-row gap-3">
                <Button
                  className="flex-1 gap-2 bg-green-600 hover:bg-green-700 text-white"
                  disabled={updating}
                  onClick={() => updateStatus("confirmed")}
                >
                  <Check size={16} /> Xác nhận vi phạm
                </Button>
                <Button
                  variant="outline"
                  className="flex-1 gap-2 text-destructive border-destructive hover:bg-destructive/10"
                  disabled={updating}
                  onClick={() => updateStatus("rejected")}
                >
                  <X size={16} /> Huỷ (Nhầm lẫn)
                </Button>
              </div>
            )}
            {violation.status === "confirmed" && (
              <Button className="w-full gap-2" variant="secondary" onClick={handleExportPdf}>
                <Printer size={16} /> Tải biên bản PDF
              </Button>
            )}
            {violation.status === "rejected" && (
              <p className="text-sm text-muted-foreground text-center">Vi phạm này đã bị huỷ, không thể thực hiện thêm thao tác.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
