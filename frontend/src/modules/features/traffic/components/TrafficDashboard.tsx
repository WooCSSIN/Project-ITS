import { useState, useEffect, useRef, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { Badge } from "@/ui/badge";
import { Skeleton } from "@/ui/skeleton";
import { toast } from "sonner";
import {
  MapPin,
  Car,
  Bike,
  AlertTriangle,
  CheckCircle,
  Clock,
  Gauge,
  Activity,
  Radio,
} from "lucide-react";
import VideoMonitor from "../../video/components/VideoMonitor";
import { motion, AnimatePresence } from "framer-motion";
import { useMultipleTrafficInfo, useMultipleFrameStreams } from "../../../../hooks/useWebSocket";
import { useMultipleWebRTCFrameStreams } from "../../../../hooks/useWebRTC";
import { endpoints } from "../../../../config";
import { getThresholdForRoad } from "../../../../config/trafficThresholds";

// Import types from the WebSocket hook
type VehicleData = {
  count_car: number;
  count_motor: number;
  speed_car: number;
  speed_motor: number;
};

type TrafficBackendData = VehicleData & {
  density_status?: string;
  speed_status?: string;
};

interface AlertItem {
  id: string;
  roadName: string;
  message: string;
  timestamp: string;
  type: "congested" | "busy" | "clear";
}

const TrafficDashboard = () => {
  const [selectedRoad, setSelectedRoad] = useState<string | null>(null);
  const [localFullscreen] = useState(false);
  const [allowedRoads, setAllowedRoads] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const prevStatusesRef = useRef<Record<string, string>>({});

  useEffect(() => {
    const fetchRoads = async () => {
      try {
        // roads_name endpoint không cần authentication
        const res = await fetch(endpoints.roadNames);
        if (!res.ok) {
          console.error("Failed to fetch road names");
          setAllowedRoads([
            "Nguyễn Văn Trỗi",
            "Nguyễn Trãi",
            "Ngã Tư Sở",
            "Đường Láng",
          ]);
          return;
        }
        const json = await res.json();
        const names: string[] = json?.road_names ?? [];
        setAllowedRoads(names);
      } catch (error) {
        console.error("Error fetching roads:", error);
        setAllowedRoads([
          "Nguyễn Văn Trỗi",
          "Nguyễn Trãi",
          "Ngã Tư Sở",
          "Đường Láng",
          "Văn Quán",
        ]);
      }
    };
    fetchRoads();
  }, []);

  // Use WebSocket for traffic data
  const { trafficData, isAnyConnected } = useMultipleTrafficInfo(allowedRoads);
  const { streamData, connections: streamConnections } =
    useMultipleWebRTCFrameStreams(allowedRoads);
  const { frameData, connections: frameConnections } =
    useMultipleFrameStreams(allowedRoads);

  // Combine WebRTC + WebSocket frame connections
  const combinedConnections: Record<string, boolean> = {};
  allowedRoads.forEach((road) => {
    combinedConnections[road] = !!(streamConnections[road] || frameConnections[road]);
  });

  const loading = !isAnyConnected;

  // Alert engine: phát hiện thay đổi trạng thái và thông báo
  useEffect(() => {
    if (allowedRoads.length === 0 || Object.keys(trafficData).length === 0) return;
    allowedRoads.forEach((road: string) => {
      if (!trafficData[road]) return;
      const { status } = getTrafficStatus(road);
      const prevStatus = prevStatusesRef.current[road];
      if (prevStatus !== undefined && prevStatus !== status) {
        const timeStr = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        const data = trafficData[road];
        if (status === "congested") {
          const msg = `Ô tô: ${data.count_car}, Xe máy: ${data.count_motor}. Tốc độ TB: ${((data.speed_car + data.speed_motor) / 2).toFixed(1)} km/h.`;
          toast.error(`🚨 ${road} đang tắc nghẽn!`, { description: msg, duration: 8000 });
          setAlerts((prev) => [{ id: `${road}-${Date.now()}`, roadName: road, message: msg, timestamp: timeStr, type: "congested" }, ...prev.slice(0, 9)]);
        } else if (status === "busy" && prevStatus === "clear") {
          const msg = `Mật độ giao thông đang tăng cao.`;
          toast.warning(`⚠️ ${road} bắt đầu đông đúc`, { description: msg, duration: 5000 });
          setAlerts((prev) => [{ id: `${road}-${Date.now()}`, roadName: road, message: msg, timestamp: timeStr, type: "busy" }, ...prev.slice(0, 9)]);
        } else if (status === "clear" && prevStatus === "congested") {
          const msg = `Giao thông đã thông thoáng trở lại.`;
          toast.success(`✅ ${road} đã thông thoáng`, { description: msg, duration: 5000 });
          setAlerts((prev) => [{ id: `${road}-${Date.now()}`, roadName: road, message: msg, timestamp: timeStr, type: "clear" }, ...prev.slice(0, 9)]);
        }
      }
      prevStatusesRef.current[road] = status;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trafficData, allowedRoads]);

  const getTrafficStatus = (roadName: string) => {
    const data = trafficData[roadName] as VehicleData | undefined;
    if (!data) return { status: "unknown", color: "gray", icon: Clock };
    // Prefer backend-provided classification when available
    const densityFromBackend = (data as TrafficBackendData).density_status;
    if (densityFromBackend) {
      if (densityFromBackend === "Tắc nghẽn")
        return { status: "congested", color: "red", icon: AlertTriangle };
      if (densityFromBackend === "Đông đúc")
        return { status: "busy", color: "yellow", icon: Clock };
      if (densityFromBackend === "Thông thoáng")
        return { status: "clear", color: "green", icon: CheckCircle };
    }
    // Fallback: compute from local thresholds when backend doesn't provide classification
    const threshold = getThresholdForRoad(roadName);
    const totalVehicles = (data.count_car ?? 0) + (data.count_motor ?? 0);
    if (totalVehicles > threshold.c2)
      return { status: "congested", color: "red", icon: AlertTriangle };
    if (totalVehicles > threshold.c1)
      return { status: "busy", color: "yellow", icon: Clock };
    return { status: "clear", color: "green", icon: CheckCircle };
  };

  const getSpeedStatus = (roadName: string) => {
    const data = trafficData[roadName] as VehicleData | undefined;
    if (!data) return { speedText: "Không rõ", speedColor: "gray" };
    const speedFromBackend = (data as TrafficBackendData).speed_status;
    if (speedFromBackend) {
      if (speedFromBackend === "Nhanh chóng")
        return { speedText: "Nhanh chóng", speedColor: "green" };
      if (speedFromBackend === "Chậm chạp")
        return { speedText: "Chậm chạp", speedColor: "orange" };
    }
    // Fallback: compute from local thresholds
    const threshold = getThresholdForRoad(roadName);
    const avgSpeed = ((data.speed_car ?? 0) + (data.speed_motor ?? 0)) / 2;
    if (avgSpeed >= threshold.v)
      return { speedText: "Nhanh chóng", speedColor: "green" };
    return { speedText: "Chậm chạp", speedColor: "orange" };
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case "congested": return "Tắc nghẽn";
      case "busy": return "Đông đúc";
      case "clear": return "Thông thoáng";
      default: return "Không rõ";
    }
  };

  // Summary stats
  const stats = useMemo(() => {
    const totalVehicles = allowedRoads.reduce((sum, road) => {
      const d = trafficData[road];
      return sum + (d ? (d.count_car + d.count_motor) : 0);
    }, 0);
    const activeRoads = allowedRoads.filter((r) => trafficData[r]).length;
    const congestedCount = allowedRoads.filter((r) => getTrafficStatus(r).status === "congested").length;
    return { totalVehicles, activeRoads, congestedCount };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trafficData, allowedRoads]);

  return (
    <div className="space-y-4 sm:space-y-5 pt-2">
      {/* ── Summary Stats Bar ── */}
      {!loading && allowedRoads.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/30">
              <Activity className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Tổng xe</p>
              <p className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{stats.totalVehicles}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
              <Radio className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Tuyến hoạt động</p>
              <p className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{stats.activeRoads}<span className="text-sm font-normal text-slate-400">/{allowedRoads.length}</span></p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${stats.congestedCount > 0 ? "bg-red-100 dark:bg-red-900/30" : "bg-slate-100 dark:bg-slate-800"}`}>
              <AlertTriangle className={`h-4 w-4 ${stats.congestedCount > 0 ? "text-red-600 dark:text-red-400" : "text-slate-400"}`} />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Cảnh báo</p>
              <p className={`text-xl font-bold tabular-nums ${stats.congestedCount > 0 ? "text-red-600 dark:text-red-400" : "text-slate-900 dark:text-white"}`}>{stats.congestedCount}</p>
            </div>
          </div>
        </div>
      )}
      {/* Main grid */}
      <div className={`grid gap-4 sm:gap-5 ${localFullscreen ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-4"}`}>
          {/* Video Monitoring */}
          <div className={localFullscreen ? "col-span-1" : "col-span-3"}>
            <VideoMonitor
              streamData={streamData}
              frameData={frameData}
              streamConnections={combinedConnections}
              trafficData={trafficData}
              allowedRoads={allowedRoads}
              selectedRoad={selectedRoad}
              setSelectedRoad={setSelectedRoad}
              loading={loading}
              isFullscreen={localFullscreen}
            />
          </div>

          {/* Traffic Status Cards */}
          {!localFullscreen && (
            <div className="space-y-4 w-full lg:max-w-xs lg:justify-self-end">
              <Card className="shadow-lg border border-stone-300 dark:border-zinc-700 bg-white/95 dark:bg-zinc-900/95">
                <CardHeader className="py-2 bg-transparent border-b border-stone-200 dark:border-zinc-700">
                  <CardTitle className="flex items-center space-x-2 text-base text-zinc-900 dark:text-zinc-100">
                    <MapPin className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                    <span>Tình Trạng Giao Thông</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 px-4 max-h-60 overflow-y-auto overscroll-contain">
                  {loading ? (
                    // Loading skeleton
                    <>
                      {[1, 2, 3, 4, 5].map((i) => (
                        <div
                          key={i}
                          className="flex items-center justify-between p-3 rounded-lg bg-gray-50 dark:bg-gray-800"
                        >
                          <Skeleton className="h-5 w-32" />
                          <Skeleton className="h-6 w-20" />
                        </div>
                      ))}
                    </>
                  ) : allowedRoads.length === 0 ? (
                    // Empty state
                    <div className="text-center py-8">
                      <Clock className="h-12 w-12 text-gray-400 mx-auto mb-3" />
                      <p className="text-gray-500 dark:text-gray-400 text-sm">
                        Không có tuyến đường nào
                      </p>
                    </div>
                  ) : (
                    <AnimatePresence>
                      {allowedRoads.map((road) => {
                        const { status, color } = getTrafficStatus(road);
                        const { speedText, speedColor } = getSpeedStatus(road);
                        const data = trafficData[road];

                        return (
                          <motion.div
                            key={road}
                            initial={{ opacity: 0, x: 20 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: -20 }}
                            transition={{ duration: 0.3 }}
                            className="flex flex-col p-3 rounded-lg bg-white dark:bg-zinc-800 border border-stone-300 dark:border-zinc-700 hover:bg-purple-50/50 dark:hover:bg-zinc-700 hover:border-purple-300 dark:hover:border-zinc-600 transition-all cursor-pointer hover:shadow-lg space-y-2"
                            onClick={() => setSelectedRoad(road)}
                          >
                            {/* Tên đường và nhãn mật độ */}
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                                {road}
                              </span>
                              <Badge
                                variant={
                                  color === "red"
                                    ? "destructive"
                                    : color === "yellow"
                                      ? "secondary"
                                      : "default"
                                }
                                className="text-xs h-5 leading-none px-2 py-0"
                              >
                                {getStatusText(status)}
                              </Badge>
                            </div>

                            {/* Thông tin số lượng và tốc độ */}
                            <div className="flex items-center justify-between gap-2">
                              {data && (
                                <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300 flex items-center space-x-1">
                                  <Car className="h-3 w-3 text-purple-600 dark:text-purple-400" />
                                  <span>{String(data.count_car)}</span>
                                  <Bike className="h-3 w-3 ml-2 text-violet-600 dark:text-violet-400" />
                                  <span>{String(data.count_motor)}</span>
                                </div>
                              )}
                              <Badge
                                variant="outline"
                                className={`flex items-center space-x-1 text-xs px-2 py-0 h-5 leading-none ${speedColor === "green"
                                    ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800"
                                    : "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800"
                                  }`}
                              >
                                <Gauge className="h-3 w-3" />
                                <span className="font-medium">{speedText}</span>
                              </Badge>
                            </div>
                          </motion.div>
                        );
                      })}
                    </AnimatePresence>
                  )}
                </CardContent>
              </Card>

              {/* Panel Cảnh Báo Ùn Tắc */}
              <Card className="shadow-lg border border-stone-300 dark:border-zinc-700 bg-white/95 dark:bg-zinc-900/95">
                <CardHeader className="py-2 bg-transparent border-b border-stone-200 dark:border-zinc-700 flex flex-row items-center justify-between">
                  <CardTitle className="flex items-center space-x-2 text-base text-zinc-900 dark:text-zinc-100">
                    <AlertTriangle className="h-5 w-5 text-amber-500" />
                    <span>Cảnh Báo Ùn Tắc</span>
                  </CardTitle>
                  {alerts.length > 0 && (
                    <Badge variant="destructive" className="text-[10px] px-1.5 py-0 h-4">
                      {alerts.length}
                    </Badge>
                  )}
                </CardHeader>
                <CardContent className="px-4 py-3 max-h-60 overflow-y-auto overscroll-contain">
                  {alerts.length === 0 ? (
                    <div className="text-center py-6">
                      <CheckCircle className="h-8 w-8 text-emerald-500 mx-auto mb-2 opacity-75" />
                      <p className="text-gray-500 dark:text-gray-400 text-xs font-medium">
                        Hệ thống vận hành bình thường.
                        <br />Chưa ghi nhận sự cố ùn tắc.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {alerts.map((item) => (
                        <div
                          key={item.id}
                          className={`p-2.5 rounded-lg border text-xs ${
                            item.type === "congested"
                              ? "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/50 text-red-700 dark:text-red-400"
                              : item.type === "busy"
                              ? "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800/50 text-amber-700 dark:text-amber-400"
                              : "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800/50 text-emerald-700 dark:text-emerald-400"
                          }`}
                        >
                          <div className="flex justify-between items-center mb-1 font-semibold">
                            <span>{item.roadName}</span>
                            <span className="text-[10px] opacity-70 font-normal">{item.timestamp}</span>
                          </div>
                          <p className="opacity-90 leading-relaxed">{item.message}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
    </div>
  );
};

export default TrafficDashboard;