import { useState, useEffect, useRef, type MouseEvent } from "react";
import { Save, RefreshCcw, Navigation, Trash2, CheckCircle, WifiOff, Wifi } from "lucide-react";
import { Button } from "@/ui/button";
import { toast } from "sonner";
import { endpoints } from "@/config";

interface Point { x: number; y: number; }

interface SavedZone {
  id: number;
  camera_id: number;
  zone_type: string;
  points: number[][];
  zone_name: string | null;
  is_active: boolean;
}

const ZONE_COLORS: Record<string, string> = {
  red_light: "rgba(239, 68, 68, 0.25)",
  wrong_lane: "rgba(234, 179, 8, 0.25)",
  no_parking: "rgba(59, 130, 246, 0.25)",
};
const ZONE_STROKE: Record<string, string> = {
  red_light: "#ef4444",
  wrong_lane: "#eab308",
  no_parking: "#3b82f6",
};

const ZONE_LABEL: Record<string, string> = {
  red_light: "Vượt Đèn Đỏ",
  wrong_lane: "Đi Sai Làn",
  no_parking: "Dừng Đỗ Sai",
};

const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export default function ZoneConfig() {
  const [points, setPoints] = useState<Point[]>([]);
  const [zoneType, setZoneType] = useState("red_light");
  const [savedZones, setSavedZones] = useState<SavedZone[]>([]);
  const [saving, setSaving] = useState(false);

  // Road / camera selection
  const [roadNames, setRoadNames] = useState<string[]>([]);
  const [selectedRoad, setSelectedRoad] = useState<string>("");
  const [cameraId, setCameraId] = useState<number>(1);

  // Live frame via WebSocket
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── Fetch danh sách đường ─────────────────────────────────────────
  useEffect(() => {
    fetch(endpoints.roadNames, { headers: getAuthHeaders() })
      .then(r => r.json())
      .then((data: string[] | { road_names: string[] }) => {
        // API trả về { road_names: [...] } hoặc array trực tiếp
        const names = Array.isArray(data) ? data : (data as { road_names: string[] }).road_names ?? [];
        setRoadNames(names);
        if (names.length > 0) setSelectedRoad(names[0]);
      })
      .catch(() => console.error("Không tải được danh sách đường."));
  }, []);

  // Gán cameraId theo index của đường (tạm thời 1-based, đủ để phân biệt zone)
  useEffect(() => {
    const idx = roadNames.indexOf(selectedRoad);
    setCameraId(idx >= 0 ? idx + 1 : 1);
  }, [selectedRoad, roadNames]);

  // ── WebSocket lấy frame camera ────────────────────────────────────
  useEffect(() => {
    if (!selectedRoad) return;

    // Đóng socket cũ
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setWsConnected(false);

    const token = localStorage.getItem("access_token");
    const wsUrl = endpoints.framesWs(selectedRoad);
    const fullUrl = token ? `${wsUrl}?token=${encodeURIComponent(token)}` : wsUrl;

    const ws = new WebSocket(fullUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);

    ws.onmessage = (event) => {
      // Giải phóng blob URL cũ
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
      const blob = new Blob([event.data as ArrayBuffer], { type: "image/jpeg" });
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      setFrameUrl(url);
    };

    ws.onclose = () => setWsConnected(false);
    ws.onerror = () => setWsConnected(false);

    return () => {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [selectedRoad]);

  // ── Load zone đã lưu ─────────────────────────────────────────────
  const fetchZones = async () => {
    if (!cameraId) return;
    try {
      const res = await fetch(endpoints.zonesForCamera(cameraId), { headers: getAuthHeaders() });
      if (res.ok) setSavedZones(await res.json());
    } catch {
      console.error("Không thể tải zone configs.");
    }
  };

  useEffect(() => { fetchZones(); }, [cameraId]);

  // ── Click vẽ điểm ────────────────────────────────────────────────
  const handleImageClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const xRatio = (e.clientX - rect.left) / rect.width;
    const yRatio = (e.clientY - rect.top) / rect.height;
    setPoints(prev => [...prev, { x: xRatio, y: yRatio }]);
  };

  // ── Lưu zone ─────────────────────────────────────────────────────
  const handleSave = async () => {
    if (points.length < 3) {
      toast.error("Vui lòng vẽ ít nhất 3 điểm để tạo vùng khép kín!");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(endpoints.zones, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({
          camera_id: cameraId,
          zone_type: zoneType,
          points: points.map(p => [p.x, p.y]),
          zone_name: `${zoneType}_cam${cameraId}`,
        }),
      });
      if (res.ok) {
        toast.success("✅ Đã lưu cấu hình vùng vào hệ thống!");
        setPoints([]);
        await fetchZones();
      } else {
        toast.error("Lưu thất bại.");
      }
    } catch {
      toast.error("Lỗi kết nối backend.");
    } finally {
      setSaving(false);
    }
  };

  // ── Xoá zone ─────────────────────────────────────────────────────
  const handleDeleteZone = async (id: number) => {
    try {
      const res = await fetch(endpoints.deleteZone(id), {
        method: "DELETE",
        headers: getAuthHeaders(),
      });
      if (res.status === 204) {
        setSavedZones(prev => prev.filter(z => z.id !== id));
        toast.success("Đã xoá vùng cảnh báo.");
      }
    } catch {
      toast.error("Lỗi khi xoá zone.");
    }
  };

  return (
    <div className="p-6 flex flex-col gap-6 animate-in fade-in duration-300 max-w-6xl mx-auto w-full">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cấu hình Vùng Cảnh Báo</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Chọn camera, click lên hình để vẽ vùng phát hiện vi phạm. Toạ độ sẽ được lưu vào hệ thống.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* ── Thanh công cụ ── */}
        <div className="md:col-span-1 flex flex-col gap-4">
          <div className="border rounded-xl bg-card p-5 shadow-sm space-y-4">

            {/* Chọn camera */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Chọn Camera</label>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={selectedRoad}
                onChange={(e) => { setSelectedRoad(e.target.value); setPoints([]); }}
              >
                {roadNames.length === 0 && (
                  <option value="">Đang tải...</option>
                )}
                {roadNames.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            {/* Loại vi phạm */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Loại Vi Phạm</label>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                value={zoneType}
                onChange={(e) => { setZoneType(e.target.value); setPoints([]); }}
              >
                <option value="red_light">🔴 Vượt Đèn Đỏ</option>
                <option value="wrong_lane">🟡 Đi Sai Làn</option>
                <option value="no_parking">🔵 Dừng Đỗ Sai</option>
              </select>
            </div>

            <div className="space-y-1 text-xs text-muted-foreground bg-muted/40 rounded-lg p-3">
              <p className="font-medium text-foreground mb-1">Hướng dẫn:</p>
              <p>• Click lên hình để thêm điểm.</p>
              <p>• Cần ít nhất <strong>3 điểm</strong>.</p>
              <p>• Zone mới sẽ thay thế zone cũ cùng loại.</p>
            </div>

            <div className="text-xs text-muted-foreground">
              Điểm đã vẽ: <strong>{points.length}</strong>
            </div>

            <div className="flex flex-col gap-2 pt-2 border-t">
              <Button variant="outline" size="sm" className="gap-2" onClick={() => setPoints([])}>
                <RefreshCcw size={14} /> Xoá điểm
              </Button>
              <Button
                size="sm"
                className="gap-2"
                onClick={handleSave}
                disabled={saving || points.length < 3}
              >
                <Save size={14} /> {saving ? "Đang lưu..." : "Lưu cấu hình"}
              </Button>
            </div>
          </div>

          {/* Zones đã lưu */}
          {savedZones.length > 0 && (
            <div className="border rounded-xl bg-card p-4 shadow-sm space-y-2">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <CheckCircle size={14} className="text-green-500" />
                Zones đã lưu ({savedZones.length})
              </h3>
              {savedZones.map(z => (
                <div key={z.id} className="flex items-center justify-between text-xs py-1.5 border-b last:border-0">
                  <span className="flex items-center gap-1.5">
                    <span
                      style={{ backgroundColor: ZONE_STROKE[z.zone_type] }}
                      className="w-2.5 h-2.5 rounded-full inline-block"
                    />
                    {ZONE_LABEL[z.zone_type] ?? z.zone_type}
                  </span>
                  <button
                    onClick={() => handleDeleteZone(z.id)}
                    className="text-muted-foreground hover:text-destructive transition-colors"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Canvas vẽ zone ── */}
        <div
          className="md:col-span-3 border rounded-xl overflow-hidden shadow-sm bg-black aspect-video relative cursor-crosshair"
          ref={containerRef}
          onClick={handleImageClick}
        >
          {/* Frame camera live */}
          {frameUrl ? (
            <img
              src={frameUrl}
              alt="Camera Feed"
              className="w-full h-full object-cover select-none pointer-events-none"
            />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center text-white/50 gap-2 select-none">
              <WifiOff size={32} />
              <span className="text-sm">
                {selectedRoad ? `Đang kết nối tới ${selectedRoad}...` : "Chưa chọn camera"}
              </span>
            </div>
          )}

          {/* SVG overlay vẽ zone */}
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
          >
            {/* Zones đã lưu */}
            {savedZones.map(z => {
              const pts = z.points.map(([rx, ry]) => `${rx},${ry}`).join(" ");
              return (
                <polygon
                  key={z.id}
                  points={pts}
                  fill={ZONE_COLORS[z.zone_type] || "rgba(100,100,255,0.2)"}
                  stroke={ZONE_STROKE[z.zone_type] || "#6666ff"}
                  strokeWidth="0.003"
                />
              );
            })}

            {/* Zone đang vẽ */}
            {points.length >= 3 && (
              <polygon
                points={points.map(p => `${p.x},${p.y}`).join(" ")}
                fill={ZONE_COLORS[zoneType]}
                stroke={ZONE_STROKE[zoneType]}
                strokeWidth="0.003"
                strokeDasharray="0.01"
              />
            )}
            {points.length === 2 && (
              <polyline
                points={points.map(p => `${p.x},${p.y}`).join(" ")}
                fill="none"
                stroke={ZONE_STROKE[zoneType]}
                strokeWidth="0.003"
              />
            )}

            {/* Các điểm đã chấm */}
            {points.map((p, i) => (
              <g key={i}>
                <circle
                  cx={p.x} cy={p.y} r="0.008"
                  fill="white"
                  stroke={ZONE_STROKE[zoneType]}
                  strokeWidth="0.003"
                />
              </g>
            ))}
          </svg>

          {/* Badge camera + trạng thái kết nối */}
          <div className="absolute top-3 right-3 bg-black/60 text-white text-xs px-3 py-1.5 rounded-full flex items-center gap-1.5 backdrop-blur-sm">
            {wsConnected
              ? <Wifi size={12} className="text-green-400" />
              : <WifiOff size={12} className="text-red-400" />
            }
            <Navigation size={12} />
            {selectedRoad || "Chưa chọn camera"}
          </div>
        </div>
      </div>
    </div>
  );
}
