import TrafficAnalytics from "../modules/features/traffic/components/TrafficAnalytics";
import { useEffect, useMemo } from "react";
import { useTrafficStore } from "@/hooks/useTrafficStore";
import { Car, Bike, Gauge, AlertTriangle } from "lucide-react";

const AnalyticsPage = () => {
  const { trafficData, allowedRoads } = useTrafficStore();

  useEffect(() => {}, [allowedRoads]);

  const kpi = useMemo(() => {
    const roads = Object.values(trafficData);
    const totalCars = roads.reduce((s, d) => s + (d.count_car || 0), 0);
    const totalMotors = roads.reduce((s, d) => s + (d.count_motor || 0), 0);
    const avgSpeed = roads.length > 0
      ? roads.reduce((s, d) => s + ((d.speed_car + d.speed_motor) / 2), 0) / roads.length
      : 0;
    const busiestRoad = allowedRoads.reduce((best, road) => {
      const d = trafficData[road];
      const total = d ? d.count_car + d.count_motor : 0;
      const bestD = trafficData[best];
      const bestTotal = bestD ? bestD.count_car + bestD.count_motor : 0;
      return total > bestTotal ? road : best;
    }, allowedRoads[0] || "—");
    return { totalCars, totalMotors, avgSpeed, busiestRoad };
  }, [trafficData, allowedRoads]);

  return (
    <div className="space-y-5 py-2">
      {/* KPI Cards */}
      {allowedRoads.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/30">
              <Car className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Tổng ô tô</p>
              <p className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{kpi.totalCars}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-100 dark:bg-violet-900/30">
              <Bike className="h-4 w-4 text-violet-600 dark:text-violet-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Tổng xe máy</p>
              <p className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{kpi.totalMotors}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-100 dark:bg-amber-900/30">
              <Gauge className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Tốc độ TB</p>
              <p className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">{kpi.avgSpeed.toFixed(1)}<span className="text-sm font-normal text-slate-400"> km/h</span></p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-xl bg-white/80 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 px-4 py-3 shadow-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-rose-100 dark:bg-rose-900/30">
              <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-400" />
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Đông nhất</p>
              <p className="text-sm font-bold text-slate-900 dark:text-white truncate max-w-[100px]">{kpi.busiestRoad}</p>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-7xl mx-auto">
        <TrafficAnalytics trafficData={trafficData} allowedRoads={allowedRoads} />
      </div>
    </div>
  );
};

export default AnalyticsPage;
